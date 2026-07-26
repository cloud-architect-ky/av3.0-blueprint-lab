"""AV 3.0 Blueprint Lab - SageMaker Construct.

SageMaker Studio Domain in PublicInternetOnly mode with execution role and lifecycle config.
"""

import base64

from constructs import Construct

import aws_cdk as cdk
from aws_cdk import (
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_s3 as s3,
    aws_sagemaker as sagemaker,
)


_IDLE_SHUTDOWN_SCRIPT = """\
#!/bin/bash
set -eu
IDLE_TIMEOUT_SECONDS=10800
echo "Configuring idle kernel shutdown after ${IDLE_TIMEOUT_SECONDS}s (3 hours)"
cat > /etc/jupyter/jupyter_notebook_config.py <<EOF
c.MappingKernelManager.cull_idle_timeout = ${IDLE_TIMEOUT_SECONDS}
c.MappingKernelManager.cull_connected = True
c.MappingKernelManager.cull_busy = False
EOF
echo "Restarting Jupyter server to apply idle shutdown configuration"
restart-jupyter-server
"""


# JupyterLab bootstrap script. Two jobs on app launch:
#   1. Sync the participant's notebooks from their S3 workspace prefix into the
#      JupyterLab EFS home so they appear in the file browser.
#   2. Inject config env vars (USER_PROFILE, SHARED_BUCKET, USER_BUCKET, plus
#      BLUEPRINT_* aliases) so the tutorial notebooks resolve the correct
#      per-user profile and the real deployed bucket names instead of the
#      hardcoded placeholders they ship with.
#
# The bucket names are injected via .replace with their CDK tokens, then the
# whole script is base64-encoded with cdk.Fn.base64 (a DEPLOY-time intrinsic) so
# the tokens resolve — Python's base64.b64encode would freeze the unresolved
# ${Token[...]} markers into the output. The per-user profile name is read at
# runtime from the app metadata file.
#
# Env injection targets an IPython startup file, NOT ~/.bashrc or
# /etc/profile.d: the Jupyter kernel is launched non-interactively, so login/
# profile shells never run and their exports would be invisible to os.environ
# in a notebook cell (this is exactly why USER_PROFILE previously fell back to
# "default"). The startup file runs inside every kernel process. bashrc +
# profile.d exports are also written for terminal convenience.
#
# Non-fatal throughout: neither a sync failure nor an env-write failure may
# block the app from starting.
_NOTEBOOK_SYNC_SCRIPT_TEMPLATE = """\
#!/bin/bash
set -eux
USER_BUCKET="__USER_BUCKET_NAME__"
SHARED_BUCKET="__SHARED_BUCKET_NAME__"
META=/opt/ml/metadata/resource-metadata.json
if [ ! -f "$META" ]; then
  echo "resource-metadata.json not found; skipping notebook bootstrap"
  exit 0
fi
USER_PROFILE=$(python3 -c "import json;print(json.load(open('$META')).get('UserProfileName',''))")
if [ -z "$USER_PROFILE" ]; then
  echo "UserProfileName empty; skipping notebook bootstrap"
  exit 0
fi

# --- 1. Sync notebooks S3 -> EFS home (non-fatal) ---
echo "Syncing s3://${USER_BUCKET}/users/${USER_PROFILE}/ -> /home/sagemaker-user/"
aws s3 sync "s3://${USER_BUCKET}/users/${USER_PROFILE}/" /home/sagemaker-user/ --exact-timestamps \\
  || echo "WARN: notebook sync failed (non-fatal)"

# --- 2. Inject config env vars for the tutorial notebooks (non-fatal) ---
# IPython startup file: sourced by every kernel process (login shells are not).
STARTUP_DIR=/home/sagemaker-user/.ipython/profile_default/startup
mkdir -p "$STARTUP_DIR" || true
cat > "$STARTUP_DIR/00-av30-env.py" <<PYEOF || true
import os
os.environ.setdefault("USER_PROFILE", "${USER_PROFILE}")
os.environ.setdefault("SHARED_BUCKET", "${SHARED_BUCKET}")
os.environ.setdefault("USER_BUCKET", "${USER_BUCKET}")
os.environ.setdefault("BLUEPRINT_PROFILE", "${USER_PROFILE}")
os.environ.setdefault("BLUEPRINT_S3_BUCKET", "${USER_BUCKET}")
PYEOF

# --- 3. B2 progress env: source the participant's own progress credentials ---
# create_user wrote users/<id>/.av30-progress.env (AV30_API_URL +
# AV30_PROGRESS_TOKEN); step 1's `aws s3 sync` above pulled it to the home dir.
# Parse those two exports into the SAME IPython startup file so the notebook
# mark-complete cells can POST progress. No DDB read / no new IAM — it is just a
# file already in the participant's own workspace. Best-effort (non-fatal).
PROGRESS_ENV=/home/sagemaker-user/.av30-progress.env
if [ -f "$PROGRESS_ENV" ]; then
  # shellcheck disable=SC1090
  . "$PROGRESS_ENV" || true
  if [ -n "${AV30_API_URL:-}" ] && [ -n "${AV30_PROGRESS_TOKEN:-}" ]; then
    cat >> "$STARTUP_DIR/00-av30-env.py" <<PROGEOF || true
os.environ.setdefault("AV30_API_URL", "${AV30_API_URL}")
os.environ.setdefault("AV30_PROGRESS_TOKEN", "${AV30_PROGRESS_TOKEN}")
PROGEOF
  fi
fi

# Terminal convenience: write the same vars to a home env file and source it
# from .bashrc for interactive shells (independent of the kernel path above).
cat > /home/sagemaker-user/.av30-env.sh <<SHEOF || true
export USER_PROFILE="${USER_PROFILE}"
export SHARED_BUCKET="${SHARED_BUCKET}"
export USER_BUCKET="${USER_BUCKET}"
export BLUEPRINT_PROFILE="${USER_PROFILE}"
export BLUEPRINT_S3_BUCKET="${USER_BUCKET}"
SHEOF
grep -q 'av30-env.sh' /home/sagemaker-user/.bashrc 2>/dev/null \\
  || echo '[ -f /home/sagemaker-user/.av30-env.sh ] && . /home/sagemaker-user/.av30-env.sh' >> /home/sagemaker-user/.bashrc \\
  || true

echo "Notebook bootstrap complete (sync + env injection)"
"""


class SageMakerConstruct(Construct):
    """SageMaker Studio Domain with execution role and lifecycle configuration.

    Attributes:
        domain_id: The SageMaker Studio Domain ID.
        execution_role: IAM role assumed by SageMaker Studio users.
        lifecycle_config_arn: ARN of the lifecycle configuration for idle shutdown.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.Vpc,
        shared_data_bucket: s3.Bucket,
        user_workspace_bucket: s3.Bucket,
        sagemaker_image_arn: str,
    ) -> None:
        super().__init__(scope, construct_id)

        # Execution role for SageMaker Studio users
        self._execution_role = iam.Role(
            self,
            "ExecutionRole",
            role_name="av30lab-sagemaker-execution-role",
            assumed_by=iam.ServicePrincipal("sagemaker.amazonaws.com"),
            description="Execution role for AV 3.0 Blueprint Lab SageMaker Studio users",
        )

        # S3 read access on shared-data bucket (all objects)
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="SharedDataBucketRead",
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:GetObject",
                    "s3:GetObjectVersion",
                    "s3:ListBucket",
                ],
                resources=[
                    shared_data_bucket.bucket_arn,
                    f"{shared_data_bucket.bucket_arn}/*",
                ],
            )
        )

        # S3 WRITE access on the shared-data bucket, scoped to the hf-cache/
        # prefix ONLY. The admin populates the M4/M5 offline HuggingFace cache
        # (hf-cache/hub/) by syncing the checkpoints cosmos actually downloaded
        # on a GPU app — but the SageMaker execution role is otherwise read-only
        # on this bucket. Scoping the write to hf-cache/* lets that one-time
        # upload run from a notebook terminal without granting write to the rest
        # of the shared bucket (model-cache, datasets, notebook-templates).
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="SharedDataHfCacheWrite",
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:PutObject",
                    "s3:DeleteObject",
                ],
                resources=[
                    f"{shared_data_bucket.bucket_arn}/hf-cache/*",
                ],
            )
        )

        # S3 object-level read/write on the user-workspace bucket, scoped to the
        # per-user prefix via the SageMakerUserProfile principal tag when it is
        # present. Object actions (Get/Put/Delete) carry no s3:prefix context
        # key, so no condition is attached here.
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="UserWorkspaceObjectReadWrite",
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                ],
                resources=[
                    f"{user_workspace_bucket.bucket_arn}/users/*",
                ],
            )
        )

        # Bucket-level ListBucket for the notebook-sync LCC (aws s3 sync issues
        # ListObjectsV2). The JupyterLab app session does NOT carry the
        # SageMakerUserProfile principal tag, so scoping the s3:prefix condition
        # to that tag would deny the list. Instead allow listing objects under
        # any users/ prefix within this one bucket — still isolated to the
        # workspace bucket, and object access above stays under users/.
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="UserWorkspaceListBucket",
                effect=iam.Effect.ALLOW,
                actions=["s3:ListBucket"],
                resources=[user_workspace_bucket.bucket_arn],
                conditions={
                    "StringLike": {
                        "s3:prefix": ["users/*"],
                    },
                },
            )
        )

        # Scoped SageMaker permissions (not full AmazonSageMakerFullAccess)
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="SageMakerStudioAccess",
                effect=iam.Effect.ALLOW,
                actions=[
                    "sagemaker:CreatePresignedDomainUrl",
                    "sagemaker:DescribeDomain",
                    "sagemaker:DescribeUserProfile",
                    "sagemaker:ListApps",
                    "sagemaker:CreateApp",
                    "sagemaker:DeleteApp",
                    "sagemaker:DescribeApp",
                    "sagemaker:ListDomains",
                    "sagemaker:ListUserProfiles",
                    "sagemaker:DescribeSpace",
                    "sagemaker:ListSpaces",
                    "sagemaker:CreateSpace",
                    "sagemaker:DeleteSpace",
                    "sagemaker:UpdateSpace",
                    # AddTags is required because SageMaker auto-tags the App
                    # resource when a user launches their JupyterLab space;
                    # without it CreateApp fails with AccessDenied on AddTags.
                    "sagemaker:AddTags",
                    "sagemaker:DeleteTags",
                    "sagemaker:ListTags",
                ],
                resources=["*"],
            )
        )

        # SageMaker Training Jobs — needed by M9, which submits a real 2-node
        # torch.distributed DDP job from the notebook via the PyTorch estimator.
        # Scoped to the av30-m9-* job-name prefix so this does not grant blanket
        # training control. Describe/Stop are needed for estimator.fit(wait=True)
        # polling and the metrics/cleanup cells.
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="SageMakerTrainingJobs",
                effect=iam.Effect.ALLOW,
                actions=[
                    "sagemaker:CreateTrainingJob",
                    "sagemaker:DescribeTrainingJob",
                    "sagemaker:StopTrainingJob",
                ],
                resources=[
                    f"arn:aws:sagemaker:{cdk.Stack.of(self).region}:"
                    f"{cdk.Stack.of(self).account}:training-job/av30-m9-*",
                ],
            )
        )

        # SageMaker Pipelines + Processing — needed by M11, which upserts and runs
        # a 3-step SageMaker Pipeline (each step is a ProcessingJob) from the
        # notebook. Pipelines are scoped to the av30-* name prefix. ProcessingJob
        # names are SDK-generated (not reliably prefixable), so those actions use
        # "*" — still limited to the processing-job resource type and this account.
        _region = cdk.Stack.of(self).region
        _account = cdk.Stack.of(self).account
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="SageMakerPipelines",
                effect=iam.Effect.ALLOW,
                actions=[
                    "sagemaker:CreatePipeline",
                    "sagemaker:UpdatePipeline",
                    "sagemaker:DescribePipeline",
                    "sagemaker:DeletePipeline",
                    "sagemaker:StartPipelineExecution",
                    "sagemaker:DescribePipelineExecution",
                    "sagemaker:ListPipelineExecutionSteps",
                    "sagemaker:ListPipelineParametersForExecution",
                ],
                resources=[
                    f"arn:aws:sagemaker:{_region}:{_account}:pipeline/av30-*",
                ],
            )
        )
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="SageMakerProcessingJobs",
                effect=iam.Effect.ALLOW,
                actions=[
                    "sagemaker:CreateProcessingJob",
                    "sagemaker:DescribeProcessingJob",
                    "sagemaker:StopProcessingJob",
                    "sagemaker:AddTags",
                ],
                resources=[
                    f"arn:aws:sagemaker:{_region}:{_account}:processing-job/*",
                ],
            )
        )

        # PassRole — CreateTrainingJob (M9) and the pipeline's ProcessingSteps
        # (M11) must hand the containers an execution role; the notebook passes
        # THIS role to itself. Scope the PassRole to this role's own ARN, and only
        # when SageMaker is the consuming service, so it cannot be used to pass any
        # other role. Reused by both M9 training and M11 processing.
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="PassSelfToSageMakerTraining",
                effect=iam.Effect.ALLOW,
                actions=["iam:PassRole"],
                resources=[
                    f"arn:aws:iam::{cdk.Stack.of(self).account}:role/"
                    "av30lab-sagemaker-execution-role",
                ],
                conditions={
                    "StringEquals": {"iam:PassedToService": "sagemaker.amazonaws.com"}
                },
            )
        )

        # CloudWatch Logs permissions for kernel and notebook logs
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudWatchLogsAccess",
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogStreams",
                    "logs:GetLogEvents",
                ],
                resources=[
                    cdk.Arn.format(
                        cdk.ArnComponents(
                            service="logs",
                            resource="log-group",
                            resource_name="/aws/sagemaker/*",
                            arn_format=cdk.ArnFormat.COLON_RESOURCE_NAME,
                        ),
                        cdk.Stack.of(self),
                    ),
                ],
            )
        )

        # KMS permissions for decrypting objects in encrypted buckets
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="KmsDecryptForBuckets",
                effect=iam.Effect.ALLOW,
                actions=[
                    "kms:Decrypt",
                    "kms:GenerateDataKey",
                ],
                resources=["*"],
                conditions={
                    "StringEquals": {
                        "kms:ViaService": [
                            f"s3.{cdk.Stack.of(self).region}.amazonaws.com",
                        ],
                    },
                },
            )
        )

        # OpenSearch Serverless (aoss) access for M8 (semantic search).
        # Two-layer model:
        #   control-plane: create/read the security + data-access policies and the
        #     VECTORSEARCH collection (policy-management actions do NOT support
        #     resource ARNs, so Resource must be "*").
        #   data-plane: aoss:APIAccessAll gates all HTTPS index/search calls
        #     (required since 2023-05); scoped to this account/region collections.
        # The collection stays protected even with a public network policy: the
        # data-access policy names ONLY this execution role as principal, and
        # APIAccessAll is required on top — no unauthenticated access is possible.
        _region = cdk.Stack.of(self).region
        _account = cdk.Stack.of(self).account
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="OpenSearchServerlessControlPlane",
                effect=iam.Effect.ALLOW,
                actions=[
                    "aoss:CreateSecurityPolicy",
                    "aoss:GetSecurityPolicy",
                    "aoss:ListSecurityPolicies",
                    "aoss:CreateAccessPolicy",
                    "aoss:GetAccessPolicy",
                    "aoss:ListAccessPolicies",
                    "aoss:CreateCollection",
                    "aoss:BatchGetCollection",
                    "aoss:ListCollections",
                ],
                resources=["*"],
            )
        )
        self._execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="OpenSearchServerlessDataPlane",
                effect=iam.Effect.ALLOW,
                actions=["aoss:APIAccessAll"],
                resources=[f"arn:aws:aoss:{_region}:{_account}:collection/*"],
            )
        )
        # NOTE: no iam:CreateServiceLinkedRole — the aoss service-linked role
        # (AWSServiceRoleForAmazonOpenSearchServerless) already exists in this
        # account, so the execution role does not need to create it.

        # Lifecycle configuration for 3-hour idle kernel shutdown
        encoded_script = base64.b64encode(
            _IDLE_SHUTDOWN_SCRIPT.encode("utf-8")
        ).decode("utf-8")

        self._lifecycle_config = sagemaker.CfnStudioLifecycleConfig(
            self,
            "IdleShutdownLifecycleConfig",
            studio_lifecycle_config_app_type="JupyterServer",
            studio_lifecycle_config_content=encoded_script,
            studio_lifecycle_config_name="av30lab-idle-shutdown-3h",
        )

        # JupyterLab lifecycle config: sync notebooks from S3 to the EFS home and
        # inject config env vars on app launch. Both bucket names are baked into
        # the script at synth time; the per-user profile name is resolved at
        # runtime from the app metadata file.
        notebook_sync_script = (
            _NOTEBOOK_SYNC_SCRIPT_TEMPLATE
            .replace("__USER_BUCKET_NAME__", user_workspace_bucket.bucket_name)
            .replace("__SHARED_BUCKET_NAME__", shared_data_bucket.bucket_name)
        )
        # cdk.Fn.base64 defers encoding to deploy time so the bucket-name tokens
        # inside the script resolve; Python base64 here would embed the raw
        # ${Token[...]} placeholders and break the shell script.
        encoded_notebook_sync = cdk.Fn.base64(notebook_sync_script)

        # Name is versioned (-v3): a custom-named StudioLifecycleConfig cannot be
        # updated in place when its content changes (CloudFormation requires
        # replacement, which collides on the fixed name). Bump the suffix to
        # force a clean create/replace when the script content changes.
        self._notebook_lcc = sagemaker.CfnStudioLifecycleConfig(
            self,
            "NotebookSyncLifecycleConfigV4",
            studio_lifecycle_config_app_type="JupyterLab",
            studio_lifecycle_config_content=encoded_notebook_sync,
            studio_lifecycle_config_name="av30lab-notebook-sync-v4",
        )

        # Security group for SageMaker Studio Domain
        studio_sg = ec2.SecurityGroup(
            self,
            "StudioSg",
            vpc=vpc,
            description="Security group for SageMaker Studio Domain",
            allow_all_outbound=True,
        )
        studio_sg.add_ingress_rule(
            peer=studio_sg,
            connection=ec2.Port.all_traffic(),
            description="Allow intra-domain traffic between Studio apps",
        )

        # SageMaker Studio Domain in VpcOnly mode
        private_subnet_ids = [
            subnet.subnet_id for subnet in vpc.isolated_subnets
        ]

        default_user_settings = sagemaker.CfnDomain.UserSettingsProperty(
            execution_role=self._execution_role.role_arn,
            security_groups=[studio_sg.security_group_id],
            jupyter_server_app_settings=sagemaker.CfnDomain.JupyterServerAppSettingsProperty(
                default_resource_spec=sagemaker.CfnDomain.ResourceSpecProperty(
                    sage_maker_image_arn=sagemaker_image_arn,
                    lifecycle_config_arn=self._lifecycle_config.attr_studio_lifecycle_config_arn,
                ),
                lifecycle_config_arns=[
                    self._lifecycle_config.attr_studio_lifecycle_config_arn,
                ],
            ),
            # JupyterLab is the app type participants actually launch. Attach the
            # notebook-sync LCC as the default (and allowlist it) so notebooks
            # appear automatically, and enable idle shutdown after 3h — the
            # JupyterServer LCC above never runs on these apps. Pin the CPU
            # SageMaker Distribution image as the default (initial spaces are
            # t3.medium); the Lambdas swap to the GPU image when a participant
            # picks a GPU instance. Distribution images live in account
            # 542918446943, published per-region.
            jupyter_lab_app_settings=sagemaker.CfnDomain.JupyterLabAppSettingsProperty(
                default_resource_spec=sagemaker.CfnDomain.ResourceSpecProperty(
                    sage_maker_image_arn=(
                        f"arn:aws:sagemaker:{cdk.Stack.of(self).region}"
                        ":542918446943:image/sagemaker-distribution-cpu"
                    ),
                    lifecycle_config_arn=self._notebook_lcc.attr_studio_lifecycle_config_arn,
                ),
                lifecycle_config_arns=[
                    self._notebook_lcc.attr_studio_lifecycle_config_arn,
                ],
                app_lifecycle_management=sagemaker.CfnDomain.AppLifecycleManagementProperty(
                    idle_settings=sagemaker.CfnDomain.IdleSettingsProperty(
                        lifecycle_management="ENABLED",
                        idle_timeout_in_minutes=180,
                        min_idle_timeout_in_minutes=60,
                        max_idle_timeout_in_minutes=180,
                    ),
                ),
            ),
        )

        # PublicInternetOnly: Studio traffic (including presigned-URL app access)
        # flows through a SageMaker-managed VPC with direct internet access, so
        # participants can open their workspace from any browser. A VPC + subnets
        # are still supplied for EFS/home-directory traffic. Switching this value
        # is an in-place update (no domain replacement, domain ID preserved).
        self._domain = sagemaker.CfnDomain(
            self,
            "Domain",
            auth_mode="IAM",
            domain_name="av30-blueprint-lab",
            vpc_id=vpc.vpc_id,
            subnet_ids=private_subnet_ids,
            app_network_access_type="PublicInternetOnly",
            default_user_settings=default_user_settings,
        )

    @property
    def domain_id(self) -> str:
        """The SageMaker Studio Domain ID."""
        return self._domain.attr_domain_id

    @property
    def execution_role(self) -> iam.Role:
        """IAM execution role for SageMaker Studio users."""
        return self._execution_role

    @property
    def lifecycle_config_arn(self) -> str:
        """ARN of the idle shutdown lifecycle configuration."""
        return self._lifecycle_config.attr_studio_lifecycle_config_arn

    @property
    def notebook_lifecycle_config_arn(self) -> str:
        """ARN of the JupyterLab notebook-sync lifecycle configuration."""
        return self._notebook_lcc.attr_studio_lifecycle_config_arn
