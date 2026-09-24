"""Shared configuration for AV 3.0 Blueprint Lab Lambda functions."""

import json
import logging
import os
import re
import time

import boto3
from botocore.exceptions import ClientError

_logger = logging.getLogger()


def aoss_collection_name(user_id: str) -> str:
    """AOSS collection name for a user — MUST byte-match M4's _aoss_name().

    M4 (notebooks/M4_OpenSearch_Semantic_Search.ipynb, cell 1) creates the
    OpenSearch Serverless collection with exactly this algorithm. delete_user
    and the teardown script must reproduce it precisely, or they look up the
    WRONG collection name and silently orphan a continuously-billing collection
    (the root cause of the av30-semantic-ky-5-34x orphan seen in the field).

    Keep this identical to M4's _aoss_name: lowercase, non [a-z0-9-] -> '-',
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
# GPU instances and the GPU pre-flight checks in the GPU modules (M2, M3, M5-M9) fail.
# NOTE: this is NOT the jupyter-server-3 image used for the JupyterServer default in
# the CDK stack — the JupyterLab Distribution images are different.
#
# The owning account is region-specific (it is NOT one account published per-region),
# so the ARN is built from the table in smd_images.py rather than a hardcoded literal.
# See that module for why getting this wrong fails silently and per-participant.
from smd_images import smd_image_arn  # noqa: E402  (shared layer, same directory)


def _smd_arn(env_key: str, variant: str) -> str:
    """Env var if the stack supplied one, else derive it from the region table.

    Written as a function rather than os.environ.get(key, smd_image_arn(...)) because
    that form evaluates the default EAGERLY: a region missing from the table would
    raise at import time even when the env var already held the correct ARN, turning a
    working deploy into a cold-start crash.
    """
    return os.environ.get(env_key) or smd_image_arn(AWS_REGION, variant)


SMD_CPU_IMAGE_ARN = _smd_arn("SMD_CPU_IMAGE_ARN", "cpu")
SMD_GPU_IMAGE_ARN = _smd_arn("SMD_GPU_IMAGE_ARN", "gpu")
# "4.2.1" is the version verified working. Overridable via env; avoid "latest"
# so the image can't silently drift across workshop runs.
SMD_IMAGE_VERSION_ALIAS = os.environ.get("SMD_IMAGE_VERSION_ALIAS", "4.2.1")

# Notebook-sync JupyterLab LCC ARN (the domain default), passed by the stack so
# apps recreated by change_instance / expand_storage re-run notebook sync + env
# injection. Empty string => omit the LifecycleConfigArn.
NOTEBOOK_LIFECYCLE_CONFIG_ARN = os.environ.get("NOTEBOOK_LIFECYCLE_CONFIG_ARN", "")

# --- Multi-region control plane ---------------------------------------------
# One control plane governs SageMaker Studio domains in up to 3 regions, because GPU
# capacity differs per region. A participant's region is written onto their DynamoDB
# row at provisioning time and is IMMUTABLE: a UserProfile belongs to exactly one
# Domain and a Domain is regional, so "move this participant" does not exist — only
# delete and re-provision.
#
# AWS_REGION above is a Lambda RESERVED variable and cannot be overridden
# (https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html). It
# therefore only ever means "where this function runs". The TARGET region travels as
# DATA: on the request for placement decisions, and on the row for everything else.
#
# EXPAND PHASE. The single-region scalars above still work and still describe the
# control region, so a handler that has not been converted yet behaves exactly as it
# did. REGION_CONFIG is synthesised from those scalars when the stack has not supplied
# it, which keeps a single-region deploy working unchanged. The scalars are removed
# only once nothing reads them.


def _load_region_config() -> dict:
    """region -> {domainId, sharedBucket, userBucket, lccArn, cpuImageArn, gpuImageArn}."""
    raw = os.environ.get("REGION_CONFIG")
    if raw:
        cfg = json.loads(raw)
        if not isinstance(cfg, dict) or not cfg:
            raise ValueError("REGION_CONFIG must be a non-empty JSON object keyed by region")
        return cfg
    # Single-region deploy: derive the one-entry map so both code paths agree.
    return {
        AWS_REGION: {
            "domainId": SAGEMAKER_DOMAIN_ID,
            "sharedBucket": SHARED_BUCKET_NAME,
            "userBucket": USER_BUCKET_NAME,
            "lccArn": NOTEBOOK_LIFECYCLE_CONFIG_ARN,
            "cpuImageArn": SMD_CPU_IMAGE_ARN,
            "gpuImageArn": SMD_GPU_IMAGE_ARN,
        }
    }


REGION_CONFIG = _load_region_config()
TARGET_REGIONS = sorted(REGION_CONFIG)
# Where the control plane itself runs. Not the same thing as a participant's region.
CONTROL_REGION = os.environ.get("CONTROL_REGION") or AWS_REGION


class UnknownRegionError(ValueError):
    """A region that this control plane does not manage.

    Raised rather than falling back to CONTROL_REGION. A fallback would act on the
    wrong region's domain and buckets and still report success — and for S3
    specifically that failure is invisible, because botocore silently redirects a
    mis-regioned request to the correct endpoint for whatever bucket name it was
    given. A wrong bucket NAME therefore succeeds against the wrong bucket.
    """


def region_config(region: str) -> dict:
    """Regional identifiers for `region`, or raise. Never defaults."""
    try:
        return REGION_CONFIG[region]
    except KeyError:
        raise UnknownRegionError(
            f"Region {region!r} is not managed by this control plane. "
            f"Managed regions: {', '.join(TARGET_REGIONS)}"
        ) from None


_CLIENT_CACHE: dict = {}


def client_for(service: str, region: str):
    """Memoized boto3 client for (service, region), from the ONE default session.

    Deliberately `boto3.client(...)` and NOT `boto3.session.Session().client(...)`.
    Clients from DIFFERENT Session objects do not share exception classes — verified
    on boto3/botocore 1.39.17:

        same default session, two regions -> a.exceptions.ResourceNotFound
                                             is b.exceptions.ResourceNotFound  True
        separate Session() objects        -> ... is ...                        False
        and issubclass(other, mine)                                           False

    So a per-region Session would silently stop every
    `except client.exceptions.ResourceNotFound` in this file and in delete_user /
    terminate_session / app_status from catching, turning "the app is already gone"
    into a 502. One session, explicit region_name.
    """
    region_config(region)  # validate before building anything
    key = (service, region)
    if key not in _CLIENT_CACHE:
        _CLIENT_CACHE[key] = boto3.client(service, region_name=region)
    return _CLIENT_CACHE[key]


def domain_id_for(region: str) -> str:
    """Studio domain id in `region`, or raise if the stack did not supply one."""
    did = region_config(region).get("domainId") or ""
    if not did:
        raise UnknownRegionError(
            f"No SageMaker domain id configured for region {region!r}. "
            f"The control plane cannot address a domain it was not told about."
        )
    return did


def buckets_for(region: str) -> tuple:
    """(sharedBucket, userBucket) in `region`, or raise.

    Raises rather than falling back for the botocore-redirect reason above: an empty
    or wrong bucket name does not fail loudly, it succeeds against the wrong bucket.
    """
    cfg = region_config(region)
    shared, user = cfg.get("sharedBucket") or "", cfg.get("userBucket") or ""
    if not shared or not user:
        raise UnknownRegionError(
            f"Bucket names missing for region {region!r} "
            f"(shared={shared!r}, user={user!r})."
        )
    return shared, user



# GPU-accelerated SageMaker instance-family prefixes.
# NOTE the trailing dots: they are load-bearing. "ml.g6e.24xlarge" does NOT start
# with "ml.g6." (the char after g6 is "e", not "."), so every family needs its own
# entry. Getting this wrong fails SILENTLY — is_gpu_instance() returns False, the
# space gets the CPU image, and the notebook dies on
# `assert torch.cuda.is_available()` on a box with 4 idle GPUs.
# Only families that also have INSTANCE_RATES entries belong here. A prefix
# without a rate is harmless (change_instance rejects on the rate table) but
# implies support that does not exist — so g6e and g7 are deliberately absent.
#
# Keyed by prefix so the family -> GPU-model mapping and the "is this a GPU box"
# test cannot drift apart: _GPU_INSTANCE_PREFIXES is DERIVED from this dict, so
# adding a family here automatically teaches both. Models match the reference
# table further down this file (g4dn=T4, g5=A10G, g6=L4, p4d=A100, p5=H100).
_GPU_MODEL_BY_PREFIX = {
    "ml.g4dn.": "T4",
    "ml.g5.": "A10G",
    "ml.g6.": "L4",
    "ml.g7e.": "RTX PRO 6000",
    "ml.p3.": "V100",
    "ml.p4d.": "A100",
    "ml.p5.": "H100",
}
_GPU_INSTANCE_PREFIXES = tuple(_GPU_MODEL_BY_PREFIX)


def is_gpu_instance(instance_type: str) -> bool:
    """True if instance_type belongs to a GPU-accelerated family."""
    return instance_type.startswith(_GPU_INSTANCE_PREFIXES)


def gpu_model(instance_type: str) -> str | None:
    """GPU model name for an instance type, or None for a CPU instance.

    Returns None rather than "" or "none" because the admin Sessions page counts
    GPU sessions with `gpuType !== null`. Any non-null placeholder would make every
    CPU session count as a GPU session — which is exactly what happened while this
    field was absent from the API response entirely (undefined !== null is true).
    """
    for prefix, model in _GPU_MODEL_BY_PREFIX.items():
        if instance_type.startswith(prefix):
            return model
    return None


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


def wait_for_user_profile_in_service(sagemaker_client, domain_id: str,
                                     user_profile_name: str,
                                     max_wait: int = 120) -> None:
    """Poll DescribeUserProfile until the profile is InService.

    CreateUserProfile is asynchronous and CreateSpace rejects a profile that has not
    settled ("Unable to create Space ... because UserProfile ... is not in
    InService"). create_user waited for this inline; bulk_provision did not, so every
    bulk row failed on CreateSpace once the request/response shapes were fixed.
    Shared so the two provisioning paths cannot drift apart again.

    Raises RuntimeError on a terminal profile status and TimeoutError if it never
    settles — both surface as that row's `error` in the bulk response rather than
    failing the whole batch.
    """
    deadline = time.time() + max_wait
    while time.time() < deadline:
        status = sagemaker_client.describe_user_profile(
            DomainId=domain_id, UserProfileName=user_profile_name
        ).get("Status")
        if status == "InService":
            return
        if status in ("Failed", "Delete_Failed", "Update_Failed"):
            raise RuntimeError(
                f"UserProfile {user_profile_name} creation failed with status: {status}"
            )
        time.sleep(3)
    raise TimeoutError(
        f"Timed out waiting for UserProfile {user_profile_name} to become InService"
    )


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

# SageMaker instance rates (USD per hour) — THE authoritative table for this repo.
#
# SOURCE OF TRUTH: AWS Price List API, service AmazonSageMaker, region us-west-2,
# platoinstancetype="Studio-JupyterLab", effective 2026-09-01. Re-verify with:
#   aws pricing get-products --service-code AmazonSageMaker --region us-east-1 \
#     --filters Type=TERM_MATCH,Field=instanceName,Value=ml.g6.24xlarge \
#               Type=TERM_MATCH,Field=platoinstancetype,Value=Studio-JupyterLab
# Do NOT hand-edit these from memory — a stale table silently mis-bills every
# cost readout (admin Sessions column, get_costs, the daily budget alarm).
#
# GPU GEOMETRY (the recurring source of confusion — size is NOT GPU count, and
# within a family a bigger size adds GPUs, never per-GPU VRAM):
#   g4dn  = T4    16 GB   | g5  = A10G 24 GB | g6 = L4 24 GB (NOT L40S — that is g6e)
#   p4d   = A100  40 GB   | p5  = H100 80 GB
#   4-GPU sizes: g5/g6 .12xlarge and .24xlarge ;  8-GPU: .48xlarge
# M5/M6 branch on PER-GPU VRAM (>=38 GB -> 720p + guardrails ON), and M9 on
# >=40 GB (single-GPU "verified path"). So no g5/g6 size can reach the top tier;
# only p4d (40 GB) / p5 (80 GB) can. 24 GB cards still COMPLETE the lab — see
# docs/en/ALPAMAYO_M9.md "Verified runs" (minADE 0.3779 m, Status: PASS).
INSTANCE_RATES = {
    # --- CPU ---
    "ml.t3.medium": 0.05,
    "ml.t3.large": 0.10,
    "ml.t3.xlarge": 0.20,
    "ml.t3.2xlarge": 0.399,
    "ml.m5.large": 0.115,
    "ml.m5.xlarge": 0.23,
    "ml.m5.2xlarge": 0.461,
    "ml.m5.4xlarge": 0.922,
    "ml.c5.large": 0.102,
    "ml.c5.xlarge": 0.204,
    "ml.c5.2xlarge": 0.408,
    # --- g4dn (1x T4 16 GB) ---
    "ml.g4dn.xlarge": 0.7364,
    "ml.g4dn.2xlarge": 0.94,
    # --- g5 (A10G 24 GB/card): 1 GPU up to 8xlarge, 4 on 12/24xlarge, 8 on 48xlarge ---
    "ml.g5.xlarge": 1.41,
    "ml.g5.2xlarge": 1.52,
    "ml.g5.4xlarge": 2.03,
    "ml.g5.8xlarge": 3.06,
    "ml.g5.12xlarge": 7.09,
    "ml.g5.24xlarge": 10.18,
    "ml.g5.48xlarge": 20.36,
    # --- g6 (L4 24 GB/card) — capacity fallback when g5 is short. Same per-GPU
    #     VRAM as g5, so it is a cost/availability choice, not a capability one.
    "ml.g6.xlarge": 1.127,
    "ml.g6.2xlarge": 1.222,
    "ml.g6.4xlarge": 1.654,
    "ml.g6.12xlarge": 5.752,
    "ml.g6.24xlarge": 8.344,
    "ml.g6.48xlarge": 16.688,
    # --- g7e (RTX PRO 6000 Blackwell, 96 GB/card) — the instance the AWS blog
    #     names for Stage 5, and the CHEAPEST route to M5/M6's top tier. 96 GB
    #     per card clears their ">= 70 GB per GPU" branch, so Cosmos Transfer /
    #     Predict load on ONE GPU at full 720p with guardrails ON, and M9 takes
    #     its verified single-GPU path. ml.g7e.2xlarge ($4.20) therefore beats
    #     ml.g6.24xlarge ($8.34) on BOTH price and output quality.
    #     GPU COUNT IS NOT THE SIZE (same trap as g6e) — verified against the
    #     karpenter instance-type reference:
    #       2xl / 4xl / 8xl = 1 GPU ;  12xl = 2 ;  24xl = 4 ;  48xl = 8
    #     Note g6e differs: its 12xlarge has 4 GPUs, g7e's has 2.
    #     AWS DLAMI release notes flag multi-node errors on g7e.8xlarge and
    #     suggest g7e.12xlarge instead; irrelevant for single-node notebooks.
    "ml.g7e.2xlarge": 4.2039,
    "ml.g7e.4xlarge": 4.9977,
    "ml.g7e.8xlarge": 6.5853,
    "ml.g7e.12xlarge": 10.3576,
    "ml.g7e.24xlarge": 20.7152,
    "ml.g7e.48xlarge": 41.4304,
    # --- p4d/p5 — clear M5/M6's 38 GB and M9's 40 GB tiers, but cost far more
    #     per unit of quality than g7e now does ---
    # NOTE: ml.p3.2xlarge is NOT in the us-west-2 SageMaker price list (V100 is
    # being retired), so this rate is unverifiable and the type is effectively
    # unorderable there. Kept only so is_gpu_instance()/validation stay stable.
    "ml.p3.2xlarge": 3.83,
    "ml.p4d.24xlarge": 25.251286,
    "ml.p5.48xlarge": 63.296,
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
