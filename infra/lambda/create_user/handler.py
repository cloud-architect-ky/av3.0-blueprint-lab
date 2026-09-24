"""Lambda handler for creating a new workshop user.

POST /users
Creates a SageMaker user profile, space, copies notebook templates,
generates a presigned URL, and saves the session to DynamoDB.
"""

import json
import logging
import os
import random
import re
import string
import sys
import time
import uuid
from datetime import datetime, timezone

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from config import (
    CONTROL_REGION,
    NOTEBOOK_TEMPLATES_PREFIX,
    PRESIGNED_URL_EXPIRY,
    SAGEMAKER_DOMAIN_ID,
    SESSIONS_TABLE_NAME,
    SHARED_BUCKET_NAME,
    TARGET_REGIONS,
    USER_BUCKET_NAME,
    jupyterlab_resource_spec,
    wait_for_user_profile_in_service,
    write_progress_env,
)
from errors import ApiError, api_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
sagemaker = boto3.client("sagemaker")
s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")


def slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text


def generate_user_id(name: str) -> str:
    """Generate a unique user ID from the name with 6 random characters."""
    slug = slugify(name)[:20]
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{slug}-{suffix}"


def copy_notebook_templates(user_id: str) -> int:
    """Copy notebook templates into the user's workspace. Returns the count copied.

    RAISES when nothing was copied. An empty/absent notebook-templates/ prefix used to
    be indistinguishable from success: the paginator yields a page with no "Contents"
    key, the loop body never runs, and this returned None to a caller that ignored it.
    The participant then received an EMPTY workspace and provisioning still answered
    HTTP 200. That is the expected state of a NEW REGION's shared-data bucket before it
    is seeded, so silently succeeding there would hand a whole cohort empty workspaces.
    """
    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(
        Bucket=SHARED_BUCKET_NAME, Prefix=NOTEBOOK_TEMPLATES_PREFIX
    )

    copied = 0
    for page in pages:
        for obj in page.get("Contents", []):
            source_key = obj["Key"]
            # Strip the templates prefix, keep the relative path
            relative_path = source_key[len(NOTEBOOK_TEMPLATES_PREFIX) :]
            if not relative_path:
                continue

            dest_key = f"users/{user_id}/{relative_path}"
            copy_source = {"Bucket": SHARED_BUCKET_NAME, "Key": source_key}

            s3.copy_object(
                CopySource=copy_source,
                Bucket=USER_BUCKET_NAME,
                Key=dest_key,
            )
            logger.info(f"Copied {source_key} -> {dest_key}")
            copied += 1

    if copied == 0:
        raise ApiError(
            500,
            "Notebook templates are not staged in this region",
            details=(
                f"s3://{SHARED_BUCKET_NAME}/{NOTEBOOK_TEMPLATES_PREFIX} is empty, so "
                f"this participant would get an empty workspace. Publish the templates "
                f"first (README deploy Step 8 / ADMIN_GUIDE §6.5)."
            ),
        )
    return copied


@api_handler
def handler(event, context):
    """Create a new workshop user."""
    # Parse and validate request body
    body = event.get("body")
    if not body:
        raise ApiError(400, "Request body is required")

    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise ApiError(400, "Invalid JSON in request body")

    name = body.get("name", "").strip()
    email = body.get("email", "").strip()

    if not name:
        raise ApiError(400, "Field 'name' is required")

    # Which region does this participant's Studio domain live in? Optional, defaults
    # to the control-plane region. Validated against the managed set rather than
    # accepted blindly: a typo'd region must 400 here, because a UserProfile belongs
    # to exactly one Domain and a Domain is regional — the choice is IMMUTABLE after
    # this call, and the only correction is delete + re-provision.
    region = (body.get("region") or CONTROL_REGION).strip()
    if region not in TARGET_REGIONS:
        raise ApiError(
            400,
            f"Unknown region '{region}'",
            details=f"This control plane manages: {', '.join(TARGET_REGIONS)}",
        )

    # Generate identifiers
    user_id = generate_user_id(name)
    participant_token = str(uuid.uuid4())

    logger.info(f"Creating user: {user_id} (name={name})")

    # Create SageMaker user profile
    sagemaker.create_user_profile(
        DomainId=SAGEMAKER_DOMAIN_ID,
        UserProfileName=user_id,
        Tags=[
            {"Key": "SageMakerUserProfile", "Value": user_id},
            {"Key": "Workshop", "Value": "av3-blueprint-lab"},
            {"Key": "ParticipantName", "Value": name},
        ],
    )
    logger.info(f"Created SageMaker user profile: {user_id}")

    # UserProfile creation is asynchronous — wait until it is InService before
    # creating the space (CreateSpace fails otherwise). Shared with bulk_provision,
    # which was missing this wait entirely.
    try:
        wait_for_user_profile_in_service(sagemaker, SAGEMAKER_DOMAIN_ID, user_id)
    except TimeoutError as e:
        raise ApiError(504, str(e))
    except RuntimeError as e:
        raise ApiError(502, str(e))
    logger.info(f"UserProfile {user_id} is InService")

    # Create SageMaker space for the user
    space_name = f"{user_id}-space"
    sagemaker.create_space(
        DomainId=SAGEMAKER_DOMAIN_ID,
        SpaceName=space_name,
        OwnershipSettings={"OwnerUserProfileName": user_id},
        SpaceSettings={
            "AppType": "JupyterLab",
            "JupyterLabAppSettings": {
                # CPU image on the initial t3.medium; instance + image are
                # switched together later via change_instance.
                "DefaultResourceSpec": jupyterlab_resource_spec("ml.t3.medium"),
            },
        },
        SpaceSharingSettings={"SharingType": "Private"},
        Tags=[
            {"Key": "Workshop", "Value": "av3-blueprint-lab"},
            {"Key": "UserId", "Value": user_id},
        ],
    )
    logger.info(f"Created SageMaker space: {space_name}")

    # Copy notebook templates to user workspace
    copy_notebook_templates(user_id)

    # B2 progress tracking: write the participant's own progress credentials into
    # their workspace prefix. The notebook-sync LCC already `aws s3 sync`s
    # users/<id>/ to the home dir at app launch, so it lands as
    # ~/.av30-progress.env with NO new IAM grant (the file holds only this
    # participant's own token — same trust boundary as their browser session).
    # The notebook mark-complete cells source AV30_API_URL + AV30_PROGRESS_TOKEN.
    if write_progress_env(
        s3, USER_BUCKET_NAME, user_id, participant_token,
        os.environ.get("API_URL", ""),
    ):
        logger.info(f"Wrote progress env for {user_id}")
    else:
        logger.warning(f"No progress env written for {user_id}")

    # Generate presigned URL (8 hours)
    presigned_url_response = sagemaker.create_presigned_domain_url(
        DomainId=SAGEMAKER_DOMAIN_ID,
        UserProfileName=user_id,
        SessionExpirationDurationInSeconds=PRESIGNED_URL_EXPIRY,
    )
    presigned_url = presigned_url_response["AuthorizedUrl"]

    # Calculate expiry timestamp
    now = datetime.now(timezone.utc)
    expires_at = int(now.timestamp()) + PRESIGNED_URL_EXPIRY
    expires_at_iso = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()

    # Save to DynamoDB
    table = dynamodb.Table(SESSIONS_TABLE_NAME)
    item = {
        "userId": user_id,
        "participantToken": participant_token,
        "name": name,
        "email": email,
        "spaceName": space_name,
        "presignedUrl": presigned_url,
        "expiresAt": expires_at,
        "expiresAtIso": expires_at_iso,
        "createdAt": now.isoformat(),
        "status": "active",
        "moduleProgress": {},
        # The ONLY record of which region's domain holds this user's profile. Every
        # later handler resolves its SageMaker/S3 clients from this, so the row is
        # read before teardown starts and deleted last.
        "region": region,
    }
    table.put_item(Item=item)
    logger.info(f"Saved session to DynamoDB: {user_id}")

    return {
        "userId": user_id,
        "workspaceUrl": presigned_url,
        "presignedUrl": presigned_url,
        "participantToken": participant_token,
        "expiresAt": expires_at_iso,
        "name": name,
        "email": email,
        "status": "active",
        "module": "-",
        "spaceName": space_name,
        "region": region,
    }
