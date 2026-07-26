"""Lambda handler for terminating a user session.

POST /sessions/{id}/terminate
Deletes the SageMaker JupyterServer app and sets the user status to offline.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from config import SAGEMAKER_DOMAIN_ID, SESSIONS_TABLE_NAME
from errors import ApiError, api_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
sagemaker = boto3.client("sagemaker")
dynamodb = boto3.resource("dynamodb")


@api_handler
def handler(event, context):
    """Terminate a user's SageMaker session."""
    # Extract userId from path
    path_params = event.get("pathParameters") or {}
    user_id = path_params.get("id")

    if not user_id:
        raise ApiError(400, "Missing userId in path")

    logger.info(f"Terminating session for user: {user_id}")

    # Retrieve current session data
    table = dynamodb.Table(SESSIONS_TABLE_NAME)
    response = table.get_item(Key={"userId": user_id})
    item = response.get("Item")

    if not item:
        raise ApiError(404, f"User not found: {user_id}")

    if item.get("status") == "offline":
        raise ApiError(409, "Session is already offline")

    space_name = item.get("spaceName", f"{user_id}-space")

    # Delete the JupyterServer app
    try:
        sagemaker.delete_app(
            DomainId=SAGEMAKER_DOMAIN_ID,
            SpaceName=space_name,
            AppType="JupyterServer",
            AppName="default",
        )
        logger.info(f"Deleted JupyterServer app for space: {space_name}")
    except sagemaker.exceptions.ResourceNotFound:
        logger.warning(f"App already deleted for space: {space_name}")

    # Update DynamoDB status
    now_iso = datetime.now(timezone.utc).isoformat()
    table.update_item(
        Key={"userId": user_id},
        UpdateExpression="SET #s = :status, terminatedAt = :terminated_at",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "offline",
            ":terminated_at": now_iso,
        },
    )
    logger.info(f"Updated status to offline for user: {user_id}")

    return {"terminated": True, "userId": user_id}
