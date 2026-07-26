"""Lambda handler for resetting a user's workspace.

POST /users/{id}/reset
Deletes the user's S3 workspace files, re-copies notebook templates,
and resets module progress in DynamoDB.
"""

import logging
import os
import sys

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from config import (
    NOTEBOOK_TEMPLATES_PREFIX,
    SESSIONS_TABLE_NAME,
    SHARED_BUCKET_NAME,
    USER_BUCKET_NAME,
)
from errors import ApiError, api_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")


def delete_user_workspace(user_id: str) -> int:
    """Delete all S3 objects under the user's workspace prefix.

    Returns the number of objects deleted.
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


def copy_notebook_templates(user_id: str) -> int:
    """Copy notebook templates from shared bucket to user workspace.

    Returns the number of files copied.
    """
    copied_count = 0
    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(
        Bucket=SHARED_BUCKET_NAME, Prefix=NOTEBOOK_TEMPLATES_PREFIX
    )

    for page in pages:
        for obj in page.get("Contents", []):
            source_key = obj["Key"]
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
            copied_count += 1

    return copied_count


@api_handler
def handler(event, context):
    """Reset a user's workspace to initial state."""
    # Extract userId from path parameters
    path_params = event.get("pathParameters") or {}
    user_id = path_params.get("id") or path_params.get("userId")

    if not user_id:
        raise ApiError(400, "userId path parameter is required")

    logger.info(f"Resetting workspace for user: {user_id}")

    # Validate user exists in DynamoDB
    table = dynamodb.Table(SESSIONS_TABLE_NAME)
    response = table.get_item(Key={"userId": user_id})

    if "Item" not in response:
        raise ApiError(404, f"User not found: {user_id}")

    # Delete existing workspace files
    deleted_count = delete_user_workspace(user_id)
    logger.info(f"Deleted {deleted_count} objects from workspace: {user_id}")

    # Re-copy notebook templates
    copied_count = copy_notebook_templates(user_id)
    logger.info(f"Copied {copied_count} template files for user: {user_id}")

    # Reset module progress in DynamoDB
    table.update_item(
        Key={"userId": user_id},
        UpdateExpression="SET moduleProgress = :empty, lastResetAt = :now",
        ExpressionAttributeValues={
            ":empty": {},
            ":now": __import__("datetime")
            .datetime.now(__import__("datetime").timezone.utc)
            .isoformat(),
        },
    )
    logger.info(f"Reset module progress for user: {user_id}")

    return {
        "userId": user_id,
        "message": "Workspace reset successfully",
        "filesDeleted": deleted_count,
        "filesCopied": copied_count,
    }
