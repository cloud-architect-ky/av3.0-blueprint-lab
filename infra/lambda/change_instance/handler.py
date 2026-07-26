"""Lambda handler for changing a session's instance type.

PATCH /sessions/{id}/instance-type

Split into a fast synchronous request path and an asynchronous continuation:

* Sync path (`_http_handler`): validate, issue the app delete (instant, async
  server-side), then self-invoke this same function with InvocationType='Event'
  and return 200 immediately. The whole cycle (delete -> wait -> update_space ->
  wait -> create_app) can take minutes, but API Gateway's REST integration is
  capped at 29s — a synchronous handler always 504s, and that 504 has no CORS
  headers so the browser sees "Failed to fetch". Returning fast avoids the 504
  entirely; the frontend polls GET /sessions/{id}/app-status for the outcome.

* Async path (`_apply_async`): the slow tail. Runs within the 15-min Lambda
  timeout. Persists the new instanceType to DynamoDB only AFTER create_app
  succeeds, so the 409 "already set" guard stays meaningful and we never record
  a type that isn't actually running.

Issuing delete_app on the SYNC path (before returning) flips the old app to
Deleting before the frontend's first poll, so the poller can't latch onto the
pre-change app as InService and stop early.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from config import (
    INSTANCE_RATES,
    MODULE_CONFIG,
    SAGEMAKER_DOMAIN_ID,
    SESSIONS_TABLE_NAME,
    create_app_when_ready,
    jupyterlab_resource_spec,
    safe_delete_app,
    wait_for_app_deleted,
    wait_for_space_in_service,
)
from errors import ApiError, api_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
sagemaker = boto3.client("sagemaker")
dynamodb = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")  # for the async self-invoke

# All valid instance types (keys of the rate table)
VALID_INSTANCE_TYPES = set(INSTANCE_RATES.keys())

# App type for user compute (JupyterLab spaces, matching create_user)
APP_TYPE = "JupyterLab"


def handler(event, context):
    """Dispatch: async continuation vs. synchronous HTTP request."""
    if isinstance(event, dict) and event.get("_async_apply"):
        return _apply_async(event)
    return _http_handler(event, context)


@api_handler
def _http_handler(event, context):
    """Sync request path: validate, issue delete, self-invoke, return fast."""
    # Extract userId from path
    path_params = event.get("pathParameters") or {}
    user_id = path_params.get("id")

    if not user_id:
        raise ApiError(400, "Missing userId in path")

    # Parse request body
    body = event.get("body")
    if not body:
        raise ApiError(400, "Request body is required")

    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise ApiError(400, "Invalid JSON in request body")

    new_instance_type = body.get("newInstanceType", "").strip()
    if not new_instance_type:
        raise ApiError(400, "Field 'newInstanceType' is required")

    # Validate instance type exists in our rate table
    if new_instance_type not in VALID_INSTANCE_TYPES:
        raise ApiError(
            400,
            f"Invalid instance type: {new_instance_type}",
            details=f"Valid types: {sorted(VALID_INSTANCE_TYPES)}",
        )

    # Retrieve current session
    table = dynamodb.Table(SESSIONS_TABLE_NAME)
    response = table.get_item(Key={"userId": user_id})
    item = response.get("Item")

    if not item:
        raise ApiError(404, f"User not found: {user_id}")

    current_module = item.get("currentModule")
    previous_type = item.get("instanceType", "ml.t3.medium")
    space_name = item.get("spaceName", f"{user_id}-space")

    # Validate against module config if user has an active module
    if current_module and current_module in MODULE_CONFIG:
        module_default = MODULE_CONFIG[current_module].get("instance_type")
        # Allow the module default and any instance that is equal or higher cost
        module_rate = INSTANCE_RATES.get(module_default, 0)
        requested_rate = INSTANCE_RATES.get(new_instance_type, 0)
        if requested_rate < module_rate:
            raise ApiError(
                400,
                f"Instance type {new_instance_type} is below minimum "
                f"requirement for {MODULE_CONFIG[current_module]['name']}",
                details=f"Minimum: {module_default}",
            )

    if new_instance_type == previous_type:
        raise ApiError(409, "Instance type is already set to the requested type")

    logger.info(
        f"Changing instance for {user_id}: {previous_type} -> {new_instance_type}"
    )

    # Issue the delete SYNCHRONOUSLY (instant, async server-side) so the OLD app
    # flips to Deleting before we return — this prevents the frontend poller
    # from reading the pre-change app as InService and stopping prematurely.
    # safe_delete_app tolerates "no app" and "previously failed + auto-deleted".
    deleting = safe_delete_app(sagemaker, SAGEMAKER_DOMAIN_ID, space_name, APP_TYPE)
    if deleting:
        logger.info(f"Issued delete for existing app on space: {space_name}")
    else:
        logger.warning(f"No live app for space: {space_name}, proceeding")

    # Hand off the slow tail (wait-deleted -> update_space -> wait-InService ->
    # create_app -> DDB write) to an async self-invocation so this request
    # returns well within the 29s API Gateway limit.
    lambda_client.invoke(
        FunctionName=context.invoked_function_arn,
        InvocationType="Event",
        Payload=json.dumps(
            {
                "_async_apply": True,
                "userId": user_id,
                "spaceName": space_name,
                "newInstanceType": new_instance_type,
                "previousType": previous_type,
            }
        ).encode("utf-8"),
    )
    logger.info(f"Dispatched async apply for {user_id} -> {new_instance_type}")

    return {
        "updated": True,
        "async": True,
        "previousType": previous_type,
        "newType": new_instance_type,
    }


def _apply_async(event):
    """Slow continuation: wait for delete, resize the space, recreate the app.

    Not @api_handler-decorated: there is no HTTP caller to answer. On failure it
    raises, which fails the async invocation (logged + retried by Lambda). The
    app is left in a Failed state that GET /app-status surfaces as capacityError.
    """
    user_id = event["userId"]
    space_name = event["spaceName"]
    new_instance_type = event["newInstanceType"]
    previous_type = event.get("previousType")

    logger.info(f"[async] Applying {new_instance_type} for {user_id}")

    # The delete was already issued on the request path; wait for it to finish.
    wait_for_app_deleted(sagemaker, SAGEMAKER_DOMAIN_ID, space_name, APP_TYPE)

    # Update space with new instance type + matching CPU/GPU image.
    sagemaker.update_space(
        DomainId=SAGEMAKER_DOMAIN_ID,
        SpaceName=space_name,
        SpaceSettings={
            "JupyterLabAppSettings": {
                "DefaultResourceSpec": jupyterlab_resource_spec(
                    new_instance_type, include_lcc=False
                ),
            }
        },
    )
    logger.info(f"[async] Updated space {space_name} -> {new_instance_type}")

    # update_space briefly takes the space out of InService; wait for it to
    # settle before creating the app (otherwise create_app 502s on first try).
    wait_for_space_in_service(sagemaker, SAGEMAKER_DOMAIN_ID, space_name)

    # Create new app with the correct image (GPU image for GPU instances) and the
    # notebook-sync LCC. create_app_when_ready retries while the EBS volume is
    # still re-attaching (ResourceInUse "storage is not in Available status").
    create_app_when_ready(
        sagemaker,
        SAGEMAKER_DOMAIN_ID,
        space_name,
        jupyterlab_resource_spec(new_instance_type),
        APP_TYPE,
    )
    logger.info(f"[async] Created new {APP_TYPE} app for space: {space_name}")

    # Persist ONLY after the recreate succeeds — keeps the 409 "already set"
    # guard meaningful and never records a type that isn't actually running.
    now_iso = datetime.now(timezone.utc).isoformat()
    table = dynamodb.Table(SESSIONS_TABLE_NAME)
    table.update_item(
        Key={"userId": user_id},
        UpdateExpression=(
            "SET instanceType = :new_type, "
            "instanceHistory = list_append(if_not_exists(instanceHistory, :empty_list), :history)"
        ),
        ExpressionAttributeValues={
            ":new_type": new_instance_type,
            ":history": [
                {"from": previous_type, "to": new_instance_type, "changedAt": now_iso}
            ],
            ":empty_list": [],
        },
    )
    logger.info(f"[async] Apply complete for {user_id} -> {new_instance_type}")
    return {"applied": True, "userId": user_id, "newType": new_instance_type}
