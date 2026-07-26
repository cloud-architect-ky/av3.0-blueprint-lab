"""Lambda handler for permanently deleting a workshop user.

DELETE /users/{id}
Tears down everything create_user provisioned, in dependency order:
  1. JupyterLab app  (must be gone before the space can be deleted)
  2. Space           (must be gone before the user profile can be deleted)
  3. User profile
  4. OpenSearch Serverless collection + policies created by M8 (if any)
  5. S3 workspace files under users/{userId}/
  6. DynamoDB session row

This is a HARD delete and cannot be undone. Every SageMaker step is idempotent
(ResourceNotFound is swallowed) so a retry after a partial failure resumes cleanly.
"""

import logging
import os
import sys
import time

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from config import (
    SAGEMAKER_DOMAIN_ID,
    SESSIONS_TABLE_NAME,
    USER_BUCKET_NAME,
    aoss_collection_name,
    safe_delete_app,
)
from errors import ApiError, api_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
sagemaker = boto3.client("sagemaker")
s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
aoss = boto3.client("opensearchserverless")

# App type for user compute (JupyterLab spaces, matching create_user).
APP_TYPE = "JupyterLab"


def cleanup_aoss(user_id: str) -> dict:
    """Best-effort teardown of the OpenSearch Serverless resources M8 creates.

    Deletes the collection (by id, after lookup) then its three policies
    (encryption `-enc`, network `-net`, data-access `-access`). Fully idempotent:
    a user who never ran M8 has none of these, and every "not found" is ignored.

    Best-effort — never raises, so an AOSS hiccup can't block the SageMaker/S3/DDB
    teardown. But it now RECORDS incompleteness in the response (`complete` +
    `reasons`) instead of silently swallowing it, so a caller/sweeper can tell a
    collection may still be billing. The collection name is derived with the
    SHARED sanitizer (aoss_collection_name) so it byte-matches whatever M8 named
    it — the old raw `user_id[:8]` diverged for uppercase/leading-digit/hyphen
    ids and left orphans.

    NOTE (async): delete_collection returns immediately; the collection enters
    DELETING and its 3 policies cannot be dropped until it is fully gone (they
    raise ConflictException here). That is EXPECTED on a fresh delete — the
    teardown.sh global AOSS sweep is the backstop that reaps the policies later.
    So `collectionDeleted: True` means "deletion queued", not "confirmed gone".
    """
    name = aoss_collection_name(user_id)
    result = {
        "collection": name,
        "collectionDeleted": False,
        "policiesDeleted": [],
        "complete": True,
        "reasons": [],
    }

    # 1) Delete the collection (needs the id from batch_get_collection).
    try:
        resp = aoss.batch_get_collection(names=[name])
        details = resp.get("collectionDetails", [])
        if details:
            coll_id = details[0]["id"]
            aoss.delete_collection(id=coll_id)  # async: enters DELETING
            result["collectionDeleted"] = True  # QUEUED, not confirmed gone
            logger.info(f"Queued delete of aoss collection {name} (id={coll_id})")
        else:
            logger.info(f"No aoss collection {name} (user never ran M8)")
    except Exception as e:  # noqa: BLE001 — best-effort, but now RECORDED
        result["complete"] = False
        result["reasons"].append(f"collection:{type(e).__name__}")
        logger.warning(f"aoss collection cleanup for {name}: {e}")

    # 2) Delete the security + access policies. Names/types match M8.
    for pname, ptype, api in (
        (f"{name}-enc", "encryption", aoss.delete_security_policy),
        (f"{name}-net", "network", aoss.delete_security_policy),
        (f"{name}-access", "data", aoss.delete_access_policy),
    ):
        try:
            api(name=pname, type=ptype)
            result["policiesDeleted"].append(pname)
            logger.info(f"Deleted aoss {ptype} policy {pname}")
        except Exception as e:  # noqa: BLE001 — best-effort
            # ConflictException is EXPECTED while the collection is still
            # DELETING (it still references the policy) — the teardown.sh sweep
            # reaps these once the collection is gone.
            result["complete"] = False
            result["reasons"].append(f"{pname}:{type(e).__name__}")
            logger.warning(f"aoss policy cleanup for {pname}: {e}")

    return result


def wait_for_app_deleted(space_name: str, max_wait: int = 240) -> None:
    """Poll DescribeApp until the app is gone (Deleted/Failed or ResourceNotFound)."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            resp = sagemaker.describe_app(
                DomainId=SAGEMAKER_DOMAIN_ID,
                SpaceName=space_name,
                AppType=APP_TYPE,
                AppName="default",
            )
            if resp.get("Status") in ("Deleted", "Failed"):
                return
        except sagemaker.exceptions.ResourceNotFound:
            return
        time.sleep(5)
    raise ApiError(504, "Timed out waiting for the app to shut down")


def wait_for_space_deleted(space_name: str, max_wait: int = 180) -> None:
    """Poll DescribeSpace until the space no longer exists."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            sagemaker.describe_space(
                DomainId=SAGEMAKER_DOMAIN_ID, SpaceName=space_name
            )
        except sagemaker.exceptions.ResourceNotFound:
            return
        time.sleep(5)
    raise ApiError(504, "Timed out waiting for the space to delete")


def wait_for_profile_deleted(user_id: str, max_wait: int = 180) -> None:
    """Poll DescribeUserProfile until the profile no longer exists."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            sagemaker.describe_user_profile(
                DomainId=SAGEMAKER_DOMAIN_ID, UserProfileName=user_id
            )
        except sagemaker.exceptions.ResourceNotFound:
            return
        time.sleep(5)
    raise ApiError(504, "Timed out waiting for the user profile to delete")


def delete_user_workspace(user_id: str) -> int:
    """Delete all S3 objects under the user's workspace prefix.

    Mirrors reset_workspace.delete_user_workspace. Returns objects deleted.
    """
    prefix = f"users/{user_id}/"
    deleted_count = 0

    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=USER_BUCKET_NAME, Prefix=prefix)

    for page in pages:
        objects = page.get("Contents", [])
        if not objects:
            continue
        delete_keys = [{"Key": obj["Key"]} for obj in objects]
        s3.delete_objects(
            Bucket=USER_BUCKET_NAME, Delete={"Objects": delete_keys, "Quiet": True}
        )
        deleted_count += len(delete_keys)

    return deleted_count


@api_handler
def handler(event, context):
    """Permanently delete a workshop user and all of their resources."""
    path_params = event.get("pathParameters") or {}
    user_id = path_params.get("id") or path_params.get("userId")

    if not user_id:
        raise ApiError(400, "Missing userId in path")

    logger.info(f"Deleting user: {user_id}")

    # Verify the user exists in DynamoDB and grab the space name.
    table = dynamodb.Table(SESSIONS_TABLE_NAME)
    response = table.get_item(Key={"userId": user_id})
    item = response.get("Item")

    if not item:
        raise ApiError(404, f"User not found: {user_id}")

    space_name = item.get("spaceName", f"{user_id}-space")

    # 1. Delete the JupyterLab app, then wait for it to fully shut down.
    #    safe_delete_app tolerates "no app" and "app previously failed +
    #    auto-deleted" (ValidationException).
    if safe_delete_app(sagemaker, SAGEMAKER_DOMAIN_ID, space_name, APP_TYPE):
        logger.info(f"Deleting app for space: {space_name}")
        wait_for_app_deleted(space_name)
    else:
        logger.warning(f"No live app for space: {space_name}, proceeding")

    # 2. Delete the space (only possible once the app is gone).
    try:
        sagemaker.delete_space(
            DomainId=SAGEMAKER_DOMAIN_ID, SpaceName=space_name
        )
        logger.info(f"Deleting space: {space_name}")
        wait_for_space_deleted(space_name)
    except sagemaker.exceptions.ResourceNotFound:
        logger.warning(f"No space: {space_name}, proceeding")

    # 3. Delete the user profile (only possible once the space is gone).
    try:
        sagemaker.delete_user_profile(
            DomainId=SAGEMAKER_DOMAIN_ID, UserProfileName=user_id
        )
        logger.info(f"Deleting user profile: {user_id}")
        wait_for_profile_deleted(user_id)
    except sagemaker.exceptions.ResourceNotFound:
        logger.warning(f"No user profile: {user_id}, proceeding")

    # 4. Delete the OpenSearch Serverless collection + policies that M8 may have
    #    created for this user (best-effort, idempotent — no-op if M8 never ran).
    aoss_result = cleanup_aoss(user_id)

    # 5. Delete the user's S3 workspace files.
    files_deleted = delete_user_workspace(user_id)
    logger.info(f"Deleted {files_deleted} S3 objects for user: {user_id}")

    # 6. Delete the DynamoDB session row (last, so a mid-teardown retry can
    #    still look the user up and resume).
    table.delete_item(Key={"userId": user_id})
    logger.info(f"Deleted DynamoDB row for user: {user_id}")

    return {
        "deleted": True,
        "userId": user_id,
        "filesDeleted": files_deleted,
        "aoss": aoss_result,
    }
