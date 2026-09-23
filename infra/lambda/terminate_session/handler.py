"""Lambda handler for terminating a user session.

POST /sessions/{id}/terminate
Deletes the participant's SageMaker JupyterLab app and marks them offline.

WAS BROKEN: this handler deleted AppType="JupyterServer" while participants only ever
run JupyterLab apps (create_user/change_instance/expand_storage/delete_user and
config.safe_delete_app all use JupyterLab). So the delete always raised
ResourceNotFound, which was swallowed with a warning — and the handler then wrote
status="offline" and returned terminated=True anyway. list_sessions skips cost
calculation for offline rows, so the still-running GPU instance reported $0.00. The
admin's main cost-control lever did nothing, claimed success, and then hid the spend;
a retry was refused with 409 "already offline".

Now: delete the JupyterLab app via the shared helper, and only mark the user offline
if there was actually an app to stop. If there was not, say so instead of pretending.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from config import SAGEMAKER_DOMAIN_ID, SESSIONS_TABLE_NAME, safe_delete_app
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

    # Delete the JupyterLab app — the app type participants actually run.
    # safe_delete_app returns False for BOTH "no app existed" cases (ResourceNotFound,
    # and the ValidationException SageMaker raises for an app that previously failed
    # and was auto-deleted), so False here means there was nothing running.
    deleting = safe_delete_app(sagemaker, SAGEMAKER_DOMAIN_ID, space_name, "JupyterLab")

    if not deleting:
        # Do NOT write status="offline" here. That is what made this handler
        # dangerous: marking a user offline makes list_sessions report $0.00 for them,
        # so an instance that is still running becomes invisible in the cost view, and
        # a retry is refused with 409. Leave the row alone and report the truth.
        logger.warning(
            f"No JupyterLab app to terminate for space {space_name} "
            f"(user {user_id}); status left unchanged"
        )
        return {
            "terminated": False,
            "userId": user_id,
            "reason": "no-running-app",
            "detail": (
                "No running JupyterLab app was found for this user, so nothing was "
                "stopped and their status was left unchanged. If the dashboard shows "
                "them as active, check the app directly: "
                f"aws sagemaker describe-app --domain-id {SAGEMAKER_DOMAIN_ID} "
                f"--space-name {space_name} --app-type JupyterLab --app-name default"
            ),
        }

    # Only now is "offline" true.
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
    logger.info(f"Deleted JupyterLab app and marked {user_id} offline")

    return {"terminated": True, "userId": user_id}
