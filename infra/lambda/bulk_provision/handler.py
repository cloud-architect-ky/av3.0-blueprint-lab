"""Lambda handler for bulk user provisioning.

POST /users/bulk
Parses a base64-encoded CSV of users and provisions them in parallel
using ThreadPoolExecutor (max 20 concurrent).
"""

import base64
import csv
import io
import json
import logging
import os
import random
import re
import string
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
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
)
from errors import ApiError, api_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
sagemaker = boto3.client("sagemaker")
s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

MAX_CONCURRENT_PROVISIONS = 20


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


def copy_notebook_templates(user_id: str) -> None:
    """Copy notebook templates from shared bucket to user workspace."""
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


def provision_single_user(user_data: dict) -> dict:
    """Provision a single user. Returns result dict with success/failure info.

    `user_data["region"]` is already validated against TARGET_REGIONS by
    parse_csv_body. It is recorded on the DynamoDB row here; the SageMaker/S3 calls in
    this function still target the control region until the per-handler region
    resolution lands, so today it only ever holds CONTROL_REGION in practice.
    """
    name = user_data.get("name", "").strip()
    email = user_data.get("email", "").strip()
    region = (user_data.get("region") or CONTROL_REGION).strip()

    if not name:
        return {"name": name, "email": email, "success": False, "error": "Name is required"}

    user_id = generate_user_id(name)
    participant_token = str(uuid.uuid4())

    try:
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

        # Create SageMaker space
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

        # Copy notebook templates
        copy_notebook_templates(user_id)

        # Generate presigned URL
        presigned_url_response = sagemaker.create_presigned_domain_url(
            DomainId=SAGEMAKER_DOMAIN_ID,
            UserProfileName=user_id,
            SessionExpirationDurationInSeconds=PRESIGNED_URL_EXPIRY,
        )
        presigned_url = presigned_url_response["AuthorizedUrl"]

        # Calculate expiry
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
            # See create_user: this is the only record of which region's domain holds
            # the profile, so every later handler resolves its clients from it.
            "region": region,
        }
        table.put_item(Item=item)

        return {
            "name": name,
            "email": email,
            "userId": user_id,
            "participantToken": participant_token,
            "workspaceUrl": presigned_url,
            "presignedUrl": presigned_url,
            "expiresAt": expires_at_iso,
            "success": True,
        }

    except Exception as e:
        logger.error(f"Failed to provision user {name}: {str(e)}")
        return {
            "name": name,
            "email": email,
            "userId": user_id,
            "success": False,
            "error": str(e),
        }


def parse_csv_body(body: str, is_base64: bool, default_region: str = "") -> list[dict]:
    """Parse CSV content from request body.

    Expects columns: name, email (header row required). An optional `region` column
    overrides `default_region` per row.
    """
    default_region = default_region or CONTROL_REGION
    if is_base64:
        try:
            csv_content = base64.b64decode(body).decode("utf-8")
        except Exception:
            raise ApiError(400, "Invalid base64-encoded CSV data")
    else:
        csv_content = body

    reader = csv.DictReader(io.StringIO(csv_content))

    # Validate headers
    if not reader.fieldnames:
        raise ApiError(400, "CSV must have a header row")

    # Normalize field names to lowercase
    normalized_fields = [f.lower().strip() for f in reader.fieldnames]
    if "name" not in normalized_fields:
        raise ApiError(400, "CSV must contain a 'name' column")

    users = []
    for row in reader:
        # Normalize keys
        normalized_row = {k.lower().strip(): v for k, v in row.items()}
        name = normalized_row.get("name", "").strip()
        if name:
            # Optional per-row region column. Validated here so a typo fails the whole
            # upload up front, rather than provisioning half a room into the wrong
            # region — the choice is immutable per participant.
            row_region = (normalized_row.get("region") or default_region).strip()
            if row_region not in TARGET_REGIONS:
                raise ApiError(
                    400,
                    f"Unknown region '{row_region}' for '{name}'",
                    details=f"This control plane manages: {', '.join(TARGET_REGIONS)}",
                )
            users.append(
                {
                    "name": name,
                    "email": normalized_row.get("email", "").strip(),
                    "region": row_region,
                }
            )

    return users


@api_handler
def handler(event, context):
    """Bulk provision workshop users from CSV."""
    body = event.get("body")
    if not body:
        raise ApiError(400, "Request body is required (CSV data)")

    is_base64 = event.get("isBase64Encoded", False)

    # Batch-wide region default. Initialised HERE, not inside the branch below: a raw
    # CSV body never enters that branch, so assigning it only there would leave this
    # name unbound and raise NameError on the parse call. Empty means "let
    # parse_csv_body fall back to CONTROL_REGION".
    batch_region = ""

    # Try JSON wrapper first: {"csv": "<base64 data>", "region": "<optional>"}
    if not is_base64:
        try:
            json_body = json.loads(body)
            if isinstance(json_body, dict) and "csv" in json_body:
                body = json_body["csv"]
                is_base64 = True
                # Optional batch-wide default; a per-row `region` column still wins.
                batch_region = (json_body.get("region") or "").strip()
        except (json.JSONDecodeError, TypeError):
            pass

    # Parse CSV
    users = parse_csv_body(body, is_base64, default_region=batch_region)

    if not users:
        raise ApiError(400, "No valid users found in CSV")

    if len(users) > 100:
        raise ApiError(400, f"Maximum 100 users per batch, got {len(users)}")

    logger.info(f"Bulk provisioning {len(users)} users")

    # Provision users in parallel
    results = []
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_PROVISIONS) as executor:
        future_to_user = {
            executor.submit(provision_single_user, user): user for user in users
        }
        for future in as_completed(future_to_user):
            result = future.result()
            results.append(result)

    # Summarize results
    successful = [r for r in results if r.get("success")]
    failed = [r for r in results if not r.get("success")]

    logger.info(
        f"Bulk provision complete: {len(successful)} succeeded, {len(failed)} failed"
    )

    return {
        "total": len(users),
        "successful": len(successful),
        "failed": len(failed),
        "results": results,
    }
