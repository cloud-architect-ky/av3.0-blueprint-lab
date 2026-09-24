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
    AWS_REGION,
    INSTANCE_RATES,
    MODULE_CONFIG,
    SAGEMAKER_DOMAIN_ID,
    SESSIONS_TABLE_NAME,
    create_app_when_ready,
    jupyterlab_resource_spec,
    safe_delete_app,
    studio_quota_for,
    wait_for_app_deleted,
    wait_for_space_in_service,
)
from errors import ApiError, api_handler, require_own_user

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
sagemaker = boto3.client("sagemaker")
dynamodb = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")  # for the async self-invoke

# Valid instance types = what THIS REGION sells for Studio-JupyterLab. INSTANCE_RATES is
# generated per region (scripts/refresh_instance_rates.py), so this set now shrinks to what
# the deploy region actually offers. It used to be a us-west-2 snapshot applied everywhere,
# which let a participant pick a type their region does not sell — accepted here, then the
# app silently failed to start. Measured: eu-west-1 sells no ml.g6.* for Studio at all, and
# ap-northeast-2 sells no ml.g7e.* / ml.p5.*.
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

    # The TokenAuthorizer grants a stage-wide resource, so a valid token reaches this
    # route for ANY userId. Without this, a participant could act on someone else's
    # workspace by editing the path. See require_own_user for the full reasoning.
    require_own_user(event, user_id)

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

    # Validate the type is sold in THIS region. Naming the region matters: the participant
    # dashboard's recommendations are static (web/user/src/data/pipeline-config.ts) and
    # recommend ml.g6.24xlarge for four modules, so in a region that does not sell g6 the
    # rejection would otherwise look like a bug in the lab rather than a regional fact.
    if new_instance_type not in VALID_INSTANCE_TYPES:
        raise ApiError(
            400,
            f"{new_instance_type} is not available for Studio JupyterLab in {AWS_REGION}",
            details=(
                f"This is a REGIONAL limitation, not a quota. Types available in "
                f"{AWS_REGION}: {sorted(VALID_INSTANCE_TYPES)}."
            ),
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

    # Validate against module config if user has an active module.
    #
    # NOTE this is dormant in the real workshop: update_progress writes
    # currentModule as "m0".."m11", and MODULE_CONFIG is keyed
    # "module-1".."module-5", so the membership test is False and the guard is
    # skipped. It only fires for the legacy module-N ids.
    #
    # It also uses PRICE as a proxy for CAPABILITY, which is no longer sound now
    # that ml.g7e.* exists: ml.g7e.2xlarge is 96 GB on one card ($4.20/hr) yet
    # CHEAPER than ml.g6.24xlarge (4× 24 GB, $8.34/hr) while clearing every
    # per-GPU tier the g6 box fails. If MODULE_CONFIG is ever populated with the
    # real m0..m11 modules and their GPU defaults, this comparison must become a
    # capability check (per-GPU VRAM / total VRAM), or it will reject the
    # strictly better instance as "below minimum requirement".
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

    # Being SOLD in this region is not the same as being LAUNCHABLE by this account. A priced
    # type whose Studio quota is 0 is accepted by CreateApp and then fails to start —
    # measured: every ml.g6.* size is priced in ap-northeast-2 with quota 0, and
    # pipeline-config.ts still offers some of them as alternatives for M2/M3/M7.
    #
    # This MUST stay ahead of safe_delete_app below. The request path deletes the running app
    # before handing off to the async tail, so accepting a quota-0 type would destroy a
    # working workspace and leave the participant with nothing running to fall back to.
    #
    # Compared against 0 explicitly: studio_quota_for returns None for "unknown" (missing
    # IAM grant, throttle, no such quota in this region) and unknown must NOT block, so
    # `if not quota` would be wrong in both directions.
    quota = studio_quota_for(new_instance_type)
    if quota == 0:
        raise ApiError(
            400,
            f"{new_instance_type} is available in {AWS_REGION} but this account's quota "
            f"for it is 0, so the app would be accepted and then fail to start",
            details=(
                f"Your current instance ({previous_type}) is still running and has not been "
                f"touched. Pick a different type, or ask the workshop admin to request an "
                f"increase for 'Studio JupyterLab Apps running on {new_instance_type} "
                f"instances' in {AWS_REGION}."
            ),
        )

    logger.info(
        f"Changing instance for {user_id}: {previous_type} -> {new_instance_type} "
        f"(quota={'unknown' if quota is None else quota})"
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


def _record_change_error(user_id, previous_type, new_instance_type, message, recovered):
    """Persist why the change failed so GET /app-status can explain it.

    Best-effort: a failure to write the explanation must not mask the real error.
    """
    try:
        table = dynamodb.Table(SESSIONS_TABLE_NAME)
        table.update_item(
            Key={"userId": user_id},
            UpdateExpression="SET lastInstanceChangeError = :err",
            ExpressionAttributeValues={
                ":err": {
                    "requestedType": new_instance_type,
                    "previousType": previous_type,
                    "message": message[:900],  # DDB item-size hygiene
                    "recovered": recovered,
                    "failedAt": datetime.now(timezone.utc).isoformat(),
                }
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception(f"[async] Could not record change error for {user_id}")


def _restore_previous(space_name, previous_type):
    """Put the space back on `previous_type` and relaunch, so the user is not left empty.

    The request path already deleted the old app before dispatching here, so a failure in
    the middle of the change leaves the participant with NO workspace at all. Rolling the
    space's DefaultResourceSpec back and relaunching returns them to what they had.

    Never raises: the caller is already handling a failure and must not lose it.
    Returns True only if the app is actually back up.
    """
    if not previous_type:
        logger.error(f"[async] No previousType recorded for {space_name}; cannot restore")
        return False
    try:
        sagemaker.update_space(
            DomainId=SAGEMAKER_DOMAIN_ID,
            SpaceName=space_name,
            SpaceSettings={
                "JupyterLabAppSettings": {
                    "DefaultResourceSpec": jupyterlab_resource_spec(
                        previous_type, include_lcc=False
                    ),
                }
            },
        )
        wait_for_space_in_service(sagemaker, SAGEMAKER_DOMAIN_ID, space_name)
        # The failed attempt may have left an app behind (e.g. Failed state); clear it
        # first or create_app will collide with the existing name.
        safe_delete_app(sagemaker, SAGEMAKER_DOMAIN_ID, space_name, APP_TYPE)
        wait_for_app_deleted(sagemaker, SAGEMAKER_DOMAIN_ID, space_name, APP_TYPE)
        create_app_when_ready(
            sagemaker,
            SAGEMAKER_DOMAIN_ID,
            space_name,
            jupyterlab_resource_spec(previous_type),
            APP_TYPE,
        )
        logger.info(f"[async] Restored {space_name} to {previous_type}")
        return True
    except Exception:  # noqa: BLE001
        logger.exception(
            f"[async] RESTORE FAILED for {space_name} -> {previous_type}; "
            f"the participant has no running app and needs admin help"
        )
        return False


def _apply_async(event):
    """Slow continuation: wait for delete, resize the space, recreate the app.

    Not @api_handler-decorated: there is no HTTP caller to answer.

    DELIBERATELY DOES NOT RAISE on a handled failure. Lambda retries a failed async
    invocation twice by default, and a retry here is actively destructive: it would run
    wait_for_app_deleted against the app the recovery just brought back, then resize the
    space to the failing type a second time. Instead the failure is recovered, recorded in
    lastInstanceChangeError for GET /app-status, logged at ERROR (greppable, and the only
    signal CloudWatch metrics would otherwise have given us), and reported in the return
    value.

    The most likely failure left is ResourceLimitExceeded — quota exists but every slot is
    in use by other participants. In a region where the heavy types have a quota of 2, that
    is an ordinary Tuesday, not an exception, so "leave them with nothing" is not acceptable
    behaviour. (A quota of literally 0 is now rejected on the request path before anything
    is deleted; see studio_quota_for in _http_handler.)
    """
    user_id = event["userId"]
    space_name = event["spaceName"]
    new_instance_type = event["newInstanceType"]
    previous_type = event.get("previousType")

    logger.info(f"[async] Applying {new_instance_type} for {user_id}")

    try:
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
    except Exception as exc:  # noqa: BLE001 — every failure path must recover, then report
        logger.exception(
            f"[async] Failed applying {new_instance_type} for {user_id}; "
            f"restoring {previous_type}"
        )
        recovered = _restore_previous(space_name, previous_type)
        _record_change_error(
            user_id, previous_type, new_instance_type, str(exc), recovered
        )
        # DynamoDB instanceType is deliberately left on previous_type: it was only ever
        # written after a successful recreate, so it already reflects what is running.
        return {
            "applied": False,
            "userId": user_id,
            "requestedType": new_instance_type,
            "restoredType": previous_type if recovered else None,
            "recovered": recovered,
            "error": str(exc),
        }

    # Persist ONLY after the recreate succeeds — keeps the 409 "already set"
    # guard meaningful and never records a type that isn't actually running.
    now_iso = datetime.now(timezone.utc).isoformat()
    table = dynamodb.Table(SESSIONS_TABLE_NAME)
    table.update_item(
        Key={"userId": user_id},
        # REMOVE in the SAME expression as the SET: a stale lastInstanceChangeError from an
        # earlier failed attempt would otherwise keep being surfaced by /app-status after
        # this attempt succeeded. Doing it in one call also means there is no window where
        # the new type is recorded while the old error is still attached. REMOVE on an
        # absent attribute is a no-op, so this is safe on the common first-try path.
        UpdateExpression=(
            "SET instanceType = :new_type, "
            "instanceHistory = list_append(if_not_exists(instanceHistory, :empty_list), :history) "
            "REMOVE lastInstanceChangeError"
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
