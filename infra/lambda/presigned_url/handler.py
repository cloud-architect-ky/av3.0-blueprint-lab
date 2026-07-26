"""Lambda handler for generating a new presigned URL for an existing user.

POST /presigned-url/{userId}
Validates the user exists in DynamoDB, generates a fresh presigned URL,
and updates the expiry in DynamoDB.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from config import PRESIGNED_URL_EXPIRY, SAGEMAKER_DOMAIN_ID, SESSIONS_TABLE_NAME
from errors import ApiError, api_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
sagemaker = boto3.client("sagemaker")
dynamodb = boto3.resource("dynamodb")


@api_handler
def handler(event, context):
    """Generate a new presigned URL for an existing user."""
    # Extract userId from path parameters
    path_params = event.get("pathParameters") or {}
    user_id = path_params.get("userId") or path_params.get("id")

    if not user_id:
        raise ApiError(400, "userId path parameter is required")

    logger.info(f"Generating presigned URL for user: {user_id}")

    # Validate user exists in DynamoDB
    table = dynamodb.Table(SESSIONS_TABLE_NAME)
    response = table.get_item(Key={"userId": user_id})

    if "Item" not in response:
        raise ApiError(404, f"User not found: {user_id}")

    user_item = response["Item"]

    if user_item.get("status") == "deleted":
        raise ApiError(410, f"User has been deleted: {user_id}")

    # Generate new presigned URL
    presigned_url_response = sagemaker.create_presigned_domain_url(
        DomainId=SAGEMAKER_DOMAIN_ID,
        UserProfileName=user_id,
        SessionExpirationDurationInSeconds=PRESIGNED_URL_EXPIRY,
    )
    presigned_url = presigned_url_response["AuthorizedUrl"]

    # Calculate new expiry
    now = datetime.now(timezone.utc)
    expires_at = int(now.timestamp()) + PRESIGNED_URL_EXPIRY
    expires_at_iso = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()

    # Update DynamoDB with new presigned URL and expiry
    table.update_item(
        Key={"userId": user_id},
        UpdateExpression="SET presignedUrl = :url, expiresAt = :exp, expiresAtIso = :expIso, updatedAt = :now",
        ExpressionAttributeValues={
            ":url": presigned_url,
            ":exp": expires_at,
            ":expIso": expires_at_iso,
            ":now": now.isoformat(),
        },
    )
    logger.info(f"Updated presigned URL for user: {user_id}, expires: {expires_at_iso}")

    return {
        "userId": user_id,
        "presignedUrl": presigned_url,
        "expiresAt": expires_at_iso,
    }
