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
    NOTEBOOK_TEMPLATES_PREFIX,
    PRESIGNED_URL_EXPIRY,
    SAGEMAKER_DOMAIN_ID,
    SESSIONS_TABLE_NAME,
    SHARED_BUCKET_NAME,
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

    # UserProfile creation is asynchronous — wait until it is InService
    # before creating the space (CreateSpace fails otherwise).
    deadline = time.time() + 120
    while time.time() < deadline:
        profile = sagemaker.describe_user_profile(
            DomainId=SAGEMAKER_DOMAIN_ID, UserProfileName=user_id
        )
        status = profile.get("Status")
        if status == "InService":
            break
        if status in ("Failed", "Delete_Failed", "Update_Failed"):
            raise ApiError(502, f"UserProfile creation failed with status: {status}")
        time.sleep(3)
    else:
        raise ApiError(504, "Timed out waiting for UserProfile to become InService")
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
    api_url = os.environ.get("API_URL", "").rstrip("/")
    if api_url:
        progress_env = (
            f'export AV30_API_URL="{api_url}"\n'
            f'export AV30_PROGRESS_TOKEN="{participant_token}"\n'
        )
        try:
            s3.put_object(
                Bucket=USER_BUCKET_NAME,
                Key=f"users/{user_id}/.av30-progress.env",
                Body=progress_env.encode("utf-8"),
                ContentType="text/plain",
            )
            logger.info(f"Wrote progress env for {user_id}")
        except Exception as e:  # noqa: BLE001 — non-fatal; progress ping is best-effort
            logger.warning(f"Could not write progress env for {user_id}: {e}")

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
    }
