"""Shared configuration for AV 3.0 Blueprint Lab Lambda functions."""

import logging
import os
import re
import time

from botocore.exceptions import ClientError

_logger = logging.getLogger()


def aoss_collection_name(user_id: str) -> str:
    """AOSS collection name for a user — MUST byte-match M8's _aoss_name().

    M8 (notebooks/M8_OpenSearch_Semantic_Search.ipynb, cell 1) creates the
    OpenSearch Serverless collection with exactly this algorithm. delete_user
    and the teardown script must reproduce it precisely, or they look up the
    WRONG collection name and silently orphan a continuously-billing collection
    (the root cause of the av30-semantic-ky-5-34x orphan seen in the field).

    Keep this identical to M8's _aoss_name: lowercase, non [a-z0-9-] -> '-',
    first 8 chars, strip stray leading/trailing hyphens, ensure a letter start.
    """
    slug = re.sub(r"[^a-z0-9-]", "-", user_id.lower())[:8].strip("-") or "user"
    if not slug[0].isalpha():
        slug = f"u{slug}"[:8]
    return f"av30-semantic-{slug}"

# Environment variables
SAGEMAKER_DOMAIN_ID = os.environ.get("SAGEMAKER_DOMAIN_ID", "")
SESSIONS_TABLE_NAME = os.environ.get("SESSIONS_TABLE_NAME", "")
SHARED_BUCKET_NAME = os.environ.get("SHARED_BUCKET_NAME", "")
USER_BUCKET_NAME = os.environ.get("USER_BUCKET_NAME", "")
NOTEBOOK_TEMPLATES_PREFIX = os.environ.get("NOTEBOOK_TEMPLATES_PREFIX", "notebook-templates/")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")

# --- SageMaker Distribution image selection ---------------------------------
# JupyterLab apps must pin a Distribution image; without it SageMaker uses the
# domain/account default (a CPU build), so torch.cuda.is_available() is False on
# GPU instances and the GPU pre-flight checks in M2..M10 fail. NOTE: this is NOT
# the jupyter-server-3 image used for the JupyterServer default in the CDK stack
# — the JupyterLab Distribution images are different and live in the SageMaker
# Distribution account (542918446943), published per-region.
_SMD_ACCOUNT = "542918446943"
SMD_CPU_IMAGE_ARN = os.environ.get(
    "SMD_CPU_IMAGE_ARN",
    f"arn:aws:sagemaker:{AWS_REGION}:{_SMD_ACCOUNT}:image/sagemaker-distribution-cpu",
)
SMD_GPU_IMAGE_ARN = os.environ.get(
    "SMD_GPU_IMAGE_ARN",
    f"arn:aws:sagemaker:{AWS_REGION}:{_SMD_ACCOUNT}:image/sagemaker-distribution-gpu",
)
# "4.2.1" is the version verified working. Overridable via env; avoid "latest"
# so the image can't silently drift across workshop runs.
SMD_IMAGE_VERSION_ALIAS = os.environ.get("SMD_IMAGE_VERSION_ALIAS", "4.2.1")

# Notebook-sync JupyterLab LCC ARN (the domain default), passed by the stack so
# apps recreated by change_instance / expand_storage re-run notebook sync + env
# injection. Empty string => omit the LifecycleConfigArn.
NOTEBOOK_LIFECYCLE_CONFIG_ARN = os.environ.get("NOTEBOOK_LIFECYCLE_CONFIG_ARN", "")

# GPU-accelerated SageMaker instance-family prefixes.
_GPU_INSTANCE_PREFIXES = (
    "ml.g4dn.",
    "ml.g5.",
    "ml.g6.",
    "ml.p3.",
    "ml.p4d.",
    "ml.p5.",
)


def is_gpu_instance(instance_type: str) -> bool:
    """True if instance_type belongs to a GPU-accelerated family."""
    return instance_type.startswith(_GPU_INSTANCE_PREFIXES)


def image_for_instance(instance_type: str) -> str:
    """Return the SageMaker Distribution image ARN matching the instance family."""
    return SMD_GPU_IMAGE_ARN if is_gpu_instance(instance_type) else SMD_CPU_IMAGE_ARN


def jupyterlab_resource_spec(instance_type: str, *, include_lcc: bool = True) -> dict:
    """Build a JupyterLab ResourceSpec/DefaultResourceSpec dict for an instance.

    Includes the correct CPU/GPU Distribution image + version alias, the instance
    type, and (optionally) the notebook-sync lifecycle config so a recreated app
    re-syncs notebooks and injects env vars. Never sets SageMakerImageVersionArn
    (it would override SageMakerImageArn and freeze the image).
    """
    spec = {
        "SageMakerImageArn": image_for_instance(instance_type),
        "SageMakerImageVersionAlias": SMD_IMAGE_VERSION_ALIAS,
        "InstanceType": instance_type,
    }
    if include_lcc and NOTEBOOK_LIFECYCLE_CONFIG_ARN:
        spec["LifecycleConfigArn"] = NOTEBOOK_LIFECYCLE_CONFIG_ARN
    return spec


def safe_delete_app(sagemaker_client, domain_id: str, space_name: str,
                    app_type: str = "JupyterLab", app_name: str = "default") -> bool:
    """Delete a space's app, tolerating the cases where there is nothing to delete.

    Returns True if a delete was issued, False if the app was already gone.

    Two "already gone" cases must both be swallowed, or an instance change /
    storage resize / user delete 502s when the previous app is not cleanly
    running:
      * ResourceNotFound     — no app was ever created for the space.
      * ValidationException  — the app *previously failed* (e.g.
        EC2InsufficientCapacityError) and SageMaker AUTO-DELETED it. delete_app
        then raises "App [default] previously failed and was automatically
        deleted. For tracking purposes, apps are available in the ListApps API
        results for only 24 hours after failure." That is not an error for us —
        the app is already gone, so proceed to update_space/create_app.
    """
    try:
        sagemaker_client.delete_app(
            DomainId=domain_id,
            SpaceName=space_name,
            AppType=app_type,
            AppName=app_name,
        )
        return True
    except sagemaker_client.exceptions.ResourceNotFound:
        return False
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", "")
        # A previously-failed, auto-deleted app surfaces as ValidationException.
        if code == "ValidationException" and (
            "previously failed" in msg or "automatically deleted" in msg
            or "does not exist" in msg
        ):
            return False
        raise


def wait_for_app_deleted(sagemaker_client, domain_id: str, space_name: str,
                         app_type: str = "JupyterLab", app_name: str = "default",
                         max_wait: int = 240) -> None:
    """Poll DescribeApp until the app is gone (Deleted/Failed or ResourceNotFound).

    Raises TimeoutError if the app is still shutting down after max_wait. Kept
    free of HTTP concerns (no ApiError) so it can be shared by both the async
    apply path (where a raise simply fails the invocation) and any HTTP caller.
    """
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            resp = sagemaker_client.describe_app(
                DomainId=domain_id,
                SpaceName=space_name,
                AppType=app_type,
                AppName=app_name,
            )
            if resp.get("Status") in ("Deleted", "Failed"):
                return
        except sagemaker_client.exceptions.ResourceNotFound:
            return
        time.sleep(5)
    raise TimeoutError(f"Timed out waiting for app to delete on space {space_name}")


def wait_for_space_in_service(sagemaker_client, domain_id: str, space_name: str,
                              max_wait: int = 180) -> None:
    """Poll DescribeSpace until the space returns to InService.

    update_space briefly transitions the space out of InService; create_app
    would 502 in that window. Raises TimeoutError if it never settles.
    """
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            resp = sagemaker_client.describe_space(
                DomainId=domain_id, SpaceName=space_name
            )
            if resp.get("Status") == "InService":
                return
        except sagemaker_client.exceptions.ResourceNotFound:
            # Space gone entirely — nothing to wait for.
            return
        time.sleep(5)
    raise TimeoutError(
        f"Timed out waiting for space {space_name} to return to InService"
    )


def create_app_when_ready(sagemaker_client, domain_id: str, space_name: str,
                          resource_spec: dict, app_type: str = "JupyterLab",
                          app_name: str = "default", max_wait: int = 240) -> None:
    """create_app, retrying while the space's EBS volume is still settling.

    After update_space changes the instance type, the space returns to
    InService BEFORE its EBS volume finishes re-attaching. Calling create_app in
    that window raises:
        ResourceInUse: Unable to create app [...] because storage is not in
        Available status.
    describe_space exposes no storage-status field to poll, so we retry
    create_app with backoff until the volume is Available (or a genuinely
    different error surfaces). This is common when switching between two GPU
    instances (e.g. g6 -> g5) where the volume must re-attach.
    """
    deadline = time.time() + max_wait
    attempt = 0
    while True:
        attempt += 1
        try:
            sagemaker_client.create_app(
                DomainId=domain_id,
                SpaceName=space_name,
                AppType=app_type,
                AppName=app_name,
                ResourceSpec=resource_spec,
            )
            return
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            msg = e.response.get("Error", {}).get("Message", "")
            storage_not_ready = code == "ResourceInUse" and (
                "storage is not in Available" in msg or "not in Available status" in msg
            )
            if storage_not_ready and time.time() < deadline:
                _logger.info(
                    f"create_app attempt {attempt}: storage not ready for "
                    f"{space_name}, retrying in 10s"
                )
                time.sleep(10)
                continue
            raise

# Presigned URL expiry in seconds (8 hours)
PRESIGNED_URL_EXPIRY = 28800

# SageMaker instance rates (USD per hour)
INSTANCE_RATES = {
    "ml.t3.medium": 0.05,
    "ml.t3.large": 0.10,
    "ml.t3.xlarge": 0.20,
    "ml.t3.2xlarge": 0.40,
    "ml.m5.large": 0.12,
    "ml.m5.xlarge": 0.23,
    "ml.m5.2xlarge": 0.46,
    "ml.m5.4xlarge": 0.92,
    "ml.c5.large": 0.10,
    "ml.c5.xlarge": 0.20,
    "ml.c5.2xlarge": 0.41,
    "ml.g4dn.xlarge": 0.74,
    "ml.g4dn.2xlarge": 1.12,
    "ml.g5.xlarge": 1.41,
    "ml.g5.2xlarge": 1.69,
    "ml.g5.4xlarge": 2.03,
    "ml.g5.8xlarge": 2.75,
    "ml.g5.12xlarge": 6.68,
    "ml.g5.24xlarge": 11.76,
    "ml.g5.48xlarge": 20.36,
    # g6 (L40S) — used as a capacity fallback when g5 is unavailable
    "ml.g6.xlarge": 1.15,
    "ml.g6.2xlarge": 1.41,
    "ml.g6.4xlarge": 1.93,
    "ml.g6.12xlarge": 5.53,
    "ml.g6.24xlarge": 9.84,
    "ml.g6.48xlarge": 19.69,
    "ml.p3.2xlarge": 3.83,
    "ml.p4d.24xlarge": 37.69,
    "ml.p5.48xlarge": 113.14,
}

# Module configuration for the workshop
MODULE_CONFIG = {
    "module-1": {
        "name": "Data Preparation",
        "notebook": "01-data-preparation.ipynb",
        "instance_type": "ml.t3.medium",
        "estimated_duration_minutes": 45,
    },
    "module-2": {
        "name": "Model Training",
        "notebook": "02-model-training.ipynb",
        "instance_type": "ml.m5.xlarge",
        "estimated_duration_minutes": 60,
    },
    "module-3": {
        "name": "Model Evaluation",
        "notebook": "03-model-evaluation.ipynb",
        "instance_type": "ml.m5.large",
        "estimated_duration_minutes": 30,
    },
    "module-4": {
        "name": "Model Deployment",
        "notebook": "04-model-deployment.ipynb",
        "instance_type": "ml.m5.large",
        "estimated_duration_minutes": 45,
    },
    "module-5": {
        "name": "Inference and Testing",
        "notebook": "05-inference-testing.ipynb",
        "instance_type": "ml.t3.medium",
        "estimated_duration_minutes": 30,
    },
}

# CORS headers
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,X-Api-Key,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
    "Content-Type": "application/json",
}
