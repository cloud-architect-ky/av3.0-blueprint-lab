"""AV 3.0 Blueprint Lab - API Construct.

API Gateway REST API with Cognito and Token authorizers,
wiring all Lambda handlers to their routes.
"""

from pathlib import Path

from constructs import Construct

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    aws_apigateway as apigw,
    aws_cognito as cognito,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_s3 as s3,
)


# Path to Lambda source code (relative to the infra/ directory at synth time)
_LAMBDA_DIR = Path(__file__).resolve().parent.parent / "lambda"


class ApiConstruct(Construct):
    """API Gateway REST API with Lambda integrations.

    Attributes:
        api: The API Gateway REST API resource.
        api_url: The invoke URL of the deployed API stage.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        user_pool: cognito.UserPool,
        sessions_table: dynamodb.Table,
        shared_data_bucket: s3.Bucket,
        user_workspace_bucket: s3.Bucket,
        sagemaker_domain_id: str,
        sagemaker_execution_role: iam.IRole,
        notebook_lifecycle_config_arn: str,
    ) -> None:
        super().__init__(scope, construct_id)

        stack = cdk.Stack.of(self)

        # --- REST API ---
        self._api = apigw.RestApi(
            self,
            "Api",
            rest_api_name="av30-api",
            description="AV 3.0 Blueprint Lab API",
            deploy_options=apigw.StageOptions(
                stage_name="prod",
                throttling_rate_limit=50,
                throttling_burst_limit=100,
                logging_level=apigw.MethodLoggingLevel.INFO,
                metrics_enabled=True,
            ),
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=[
                    "Content-Type",
                    "X-Api-Key",
                    "Authorization",
                ],
            ),
        )

        # --- CORS on gateway-generated error responses ---------------------
        # default_cors_preflight_options only builds the OPTIONS preflight; it
        # does NOT add CORS headers to 4XX/5XX responses that API Gateway itself
        # generates (e.g. the 504 when a Lambda integration exceeds the 29s
        # limit, or a 403 from an authorizer). Without these headers the browser
        # turns such a response into a CORS "TypeError: Failed to fetch" instead
        # of a readable HTTP error, so the frontend's 502/504 tolerance never
        # fires. Mirror the preflight values. API Gateway static header values
        # must be wrapped in single quotes; CDK adds the gatewayresponse.header.
        # prefix automatically.
        _gateway_cors_headers = {
            "Access-Control-Allow-Origin": "'*'",
            "Access-Control-Allow-Headers": "'Content-Type,X-Api-Key,Authorization'",
            "Access-Control-Allow-Methods": "'OPTIONS,GET,PUT,POST,DELETE,PATCH,HEAD'",
        }
        self._api.add_gateway_response(
            "Default5xxCors",
            type=apigw.ResponseType.DEFAULT_5_XX,
            response_headers=_gateway_cors_headers,
        )
        self._api.add_gateway_response(
            "Default4xxCors",
            type=apigw.ResponseType.DEFAULT_4_XX,
            response_headers=_gateway_cors_headers,
        )

        # --- Authorizers ---
        cognito_authorizer = apigw.CognitoUserPoolsAuthorizer(
            self,
            "CognitoAuthorizer",
            cognito_user_pools=[user_pool],
            authorizer_name="av30-cognito-authorizer",
            results_cache_ttl=Duration.minutes(5),
        )

        # Token authorizer Lambda
        token_authorizer_fn = self._create_lambda(
            "TokenAuthorizerFn",
            handler_dir="token_authorizer",
            environment={
                "SESSIONS_TABLE_NAME": sessions_table.table_name,
            },
        )
        sessions_table.grant_read_data(token_authorizer_fn)

        token_authorizer = apigw.TokenAuthorizer(
            self,
            "TokenAuthorizer",
            handler=token_authorizer_fn,
            authorizer_name="av30-token-authorizer",
            identity_source="method.request.header.X-Api-Key",
            results_cache_ttl=Duration.minutes(5),
        )

        # --- Shared environment variables for business Lambdas ---
        # SageMaker Distribution images live in account 542918446943, published
        # per-region. Lambdas pick CPU vs GPU by instance family (see config.py).
        _smd_account = "542918446943"
        shared_env = {
            "SAGEMAKER_DOMAIN_ID": sagemaker_domain_id,
            "SESSIONS_TABLE_NAME": sessions_table.table_name,
            "SHARED_BUCKET_NAME": shared_data_bucket.bucket_name,
            "USER_BUCKET_NAME": user_workspace_bucket.bucket_name,
            "NOTEBOOK_TEMPLATES_PREFIX": "notebook-templates/",
            "SMD_CPU_IMAGE_ARN": f"arn:aws:sagemaker:{stack.region}:{_smd_account}:image/sagemaker-distribution-cpu",
            "SMD_GPU_IMAGE_ARN": f"arn:aws:sagemaker:{stack.region}:{_smd_account}:image/sagemaker-distribution-gpu",
            "SMD_IMAGE_VERSION_ALIAS": "4.2.1",
            "NOTEBOOK_LIFECYCLE_CONFIG_ARN": notebook_lifecycle_config_arn,
            # B2 progress tracking: create_user writes this + the participant
            # token into users/<id>/.av30-progress.env so the notebook-sync LCC
            # can source it and the notebooks can POST module completion.
            # Build the invoke URL from rest_api_id + the fixed "prod" stage
            # instead of self._api.url: .url depends on the Deployment/Stage,
            # which depends on every method -> every business Lambda, so feeding
            # it back into shared_env creates a circular dependency. rest_api_id
            # is a property of the RestApi resource alone (no Deployment dep).
            "API_URL": (
                f"https://{self._api.rest_api_id}.execute-api."
                f"{stack.region}.amazonaws.com/prod/"
            ),
        }

        # --- Lambda functions ---
        create_user_fn = self._create_lambda(
            "CreateUserFn",
            handler_dir="create_user",
            environment=shared_env,
            timeout=Duration.minutes(5),
        )
        list_users_fn = self._create_lambda(
            "ListUsersFn", handler_dir="list_users", environment=shared_env
        )
        reset_workspace_fn = self._create_lambda(
            "ResetWorkspaceFn", handler_dir="reset_workspace", environment=shared_env
        )
        delete_user_fn = self._create_lambda(
            "DeleteUserFn",
            handler_dir="delete_user",
            environment=shared_env,
            timeout=Duration.minutes(5),
        )
        bulk_provision_fn = self._create_lambda(
            "BulkProvisionFn",
            handler_dir="bulk_provision",
            environment=shared_env,
            timeout=Duration.minutes(5),
        )
        list_sessions_fn = self._create_lambda(
            "ListSessionsFn", handler_dir="list_sessions", environment=shared_env
        )
        terminate_session_fn = self._create_lambda(
            "TerminateSessionFn", handler_dir="terminate_session", environment=shared_env
        )
        # 15-min timeout: the fast sync path returns in seconds, but the async
        # self-invoke tail (delete -> wait -> update_space -> wait -> create_app)
        # can block up to ~660s worst-case (240+180+240) — well past the old
        # 5-min timeout, which would kill the recreate mid-flight.
        change_instance_fn = self._create_lambda(
            "ChangeInstanceFn",
            handler_dir="change_instance",
            environment=shared_env,
            timeout=Duration.minutes(15),
        )
        expand_storage_fn = self._create_lambda(
            "ExpandStorageFn",
            handler_dir="expand_storage",
            environment=shared_env,
            timeout=Duration.minutes(15),
        )
        instance_options_fn = self._create_lambda(
            "InstanceOptionsFn", handler_dir="instance_options", environment=shared_env
        )
        update_progress_fn = self._create_lambda(
            "UpdateProgressFn", handler_dir="update_progress", environment=shared_env
        )
        get_costs_fn = self._create_lambda(
            "GetCostsFn", handler_dir="get_costs", environment=shared_env
        )
        presigned_url_fn = self._create_lambda(
            "PresignedUrlFn", handler_dir="presigned_url", environment=shared_env
        )
        app_status_fn = self._create_lambda(
            "AppStatusFn", handler_dir="app_status", environment=shared_env
        )

        # --- IAM permissions ---
        # DynamoDB read/write for all functions that interact with sessions
        ddb_rw_functions = [
            create_user_fn,
            list_users_fn,
            reset_workspace_fn,
            delete_user_fn,
            bulk_provision_fn,
            list_sessions_fn,
            terminate_session_fn,
            change_instance_fn,
            expand_storage_fn,
            update_progress_fn,
            presigned_url_fn,
        ]
        for fn in ddb_rw_functions:
            sessions_table.grant_read_write_data(fn)

        # DynamoDB read-only for instance options (queries table for user context)
        sessions_table.grant_read_data(instance_options_fn)
        # DynamoDB read-only for app status (resolves spaceName for describe_app)
        sessions_table.grant_read_data(app_status_fn)

        # S3 read on shared bucket (for template copying)
        shared_data_bucket.grant_read(create_user_fn)
        shared_data_bucket.grant_read(bulk_provision_fn)
        shared_data_bucket.grant_read(reset_workspace_fn)

        # S3 read/write on user workspace bucket
        s3_rw_functions = [
            create_user_fn,
            bulk_provision_fn,
            reset_workspace_fn,
            delete_user_fn,
            presigned_url_fn,
            expand_storage_fn,
        ]
        for fn in s3_rw_functions:
            user_workspace_bucket.grant_read_write(fn)

        # SageMaker admin permissions for user/space management
        sagemaker_admin_functions = [
            create_user_fn,
            bulk_provision_fn,
            reset_workspace_fn,
            delete_user_fn,
            terminate_session_fn,
            change_instance_fn,
            expand_storage_fn,
            presigned_url_fn,
            list_sessions_fn,
            app_status_fn,
        ]
        sagemaker_policy = iam.PolicyStatement(
            sid="SageMakerAdminAccess",
            effect=iam.Effect.ALLOW,
            actions=[
                "sagemaker:CreateUserProfile",
                "sagemaker:DeleteUserProfile",
                "sagemaker:DescribeUserProfile",
                "sagemaker:ListUserProfiles",
                "sagemaker:CreateSpace",
                "sagemaker:DeleteSpace",
                "sagemaker:UpdateSpace",
                "sagemaker:DescribeSpace",
                "sagemaker:ListSpaces",
                "sagemaker:CreateApp",
                "sagemaker:DeleteApp",
                "sagemaker:DescribeApp",
                "sagemaker:ListApps",
                "sagemaker:CreatePresignedDomainUrl",
                "sagemaker:DescribeDomain",
                "sagemaker:AddTags",
                "sagemaker:ListTags",
            ],
            resources=["*"],
        )
        for fn in sagemaker_admin_functions:
            fn.add_to_role_policy(sagemaker_policy)

        # Self-invoke (async): change_instance / expand_storage return fast on
        # the request path and self-invoke with InvocationType='Event' to run
        # the slow delete->wait->update->wait->create tail (avoids the 29s API
        # Gateway 504). Grant each function permission to invoke ITSELF. Build
        # the ARN from the LITERAL function name (not fn.function_arn) to avoid a
        # Role<->Function circular reference: referencing fn.function_arn would
        # make the role's policy depend on the function while the function
        # already depends on the role.
        for fn, fn_name in (
            (change_instance_fn, "av30-change-instance"),
            (expand_storage_fn, "av30-expand-storage"),
        ):
            self_arn = stack.format_arn(
                service="lambda",
                resource="function",
                resource_name=fn_name,
                arn_format=cdk.ArnFormat.COLON_RESOURCE_NAME,
            )
            fn.add_to_role_policy(
                iam.PolicyStatement(
                    sid="SelfInvokeAsync",
                    effect=iam.Effect.ALLOW,
                    actions=["lambda:InvokeFunction"],
                    resources=[self_arn],
                )
            )

        # OpenSearch Serverless cleanup for delete_user — it tears down the
        # collection + policies that M8 creates for a user. Lookup+delete of the
        # collection and its encryption/network/data-access policies. Policy and
        # collection management actions do not support resource ARNs, so "*".
        delete_user_fn.add_to_role_policy(
            iam.PolicyStatement(
                sid="OpenSearchServerlessCleanup",
                effect=iam.Effect.ALLOW,
                actions=[
                    "aoss:BatchGetCollection",
                    "aoss:ListCollections",
                    "aoss:DeleteCollection",
                    "aoss:DeleteSecurityPolicy",
                    "aoss:DeleteAccessPolicy",
                ],
                resources=["*"],
            )
        )

        # iam:PassRole — create_user/bulk_provision create user profiles that
        # inherit the SageMaker domain default execution role; the caller must
        # be allowed to pass that role to SageMaker.
        pass_role_policy = iam.PolicyStatement(
            sid="PassSageMakerExecutionRole",
            effect=iam.Effect.ALLOW,
            actions=["iam:PassRole"],
            resources=[sagemaker_execution_role.role_arn],
            conditions={
                "StringEquals": {"iam:PassedToService": "sagemaker.amazonaws.com"}
            },
        )
        for fn in [create_user_fn, bulk_provision_fn]:
            fn.add_to_role_policy(pass_role_policy)

        # Cost Explorer read for get_costs
        get_costs_fn.add_to_role_policy(
            iam.PolicyStatement(
                sid="CostExplorerRead",
                effect=iam.Effect.ALLOW,
                actions=["ce:GetCostAndUsage"],
                resources=["*"],
            )
        )

        # --- API Gateway route wiring ---
        # /users
        users_resource = self._api.root.add_resource("users")
        users_resource.add_method(
            "POST",
            apigw.LambdaIntegration(create_user_fn),
            authorizer=cognito_authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )
        users_resource.add_method(
            "GET",
            apigw.LambdaIntegration(list_users_fn),
            authorizer=cognito_authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /users/{id}
        user_by_id = users_resource.add_resource("{id}")
        # DELETE /users/{id} — hard-delete the user + all SageMaker/S3/DDB state
        user_by_id.add_method(
            "DELETE",
            apigw.LambdaIntegration(delete_user_fn),
            authorizer=cognito_authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /users/{id}/reset
        user_reset = user_by_id.add_resource("reset")
        user_reset.add_method(
            "POST",
            apigw.LambdaIntegration(reset_workspace_fn),
            authorizer=cognito_authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /users/bulk
        users_bulk = users_resource.add_resource("bulk")
        users_bulk.add_method(
            "POST",
            apigw.LambdaIntegration(bulk_provision_fn),
            authorizer=cognito_authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /sessions
        sessions_resource = self._api.root.add_resource("sessions")
        sessions_resource.add_method(
            "GET",
            apigw.LambdaIntegration(list_sessions_fn),
            authorizer=cognito_authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /sessions/{id}
        session_by_id = sessions_resource.add_resource("{id}")

        # /sessions/{id}/terminate
        session_terminate = session_by_id.add_resource("terminate")
        session_terminate.add_method(
            "POST",
            apigw.LambdaIntegration(terminate_session_fn),
            authorizer=cognito_authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /sessions/{id}/instance-type (Token auth)
        session_instance_type = session_by_id.add_resource("instance-type")
        session_instance_type.add_method(
            "PATCH",
            apigw.LambdaIntegration(change_instance_fn),
            authorizer=token_authorizer,
            authorization_type=apigw.AuthorizationType.CUSTOM,
        )

        # /sessions/{id}/storage (Token auth)
        session_storage = session_by_id.add_resource("storage")
        session_storage.add_method(
            "PATCH",
            apigw.LambdaIntegration(expand_storage_fn),
            authorizer=token_authorizer,
            authorization_type=apigw.AuthorizationType.CUSTOM,
        )

        # /sessions/{id}/progress (Token auth)
        session_progress = session_by_id.add_resource("progress")
        session_progress.add_method(
            "POST",
            apigw.LambdaIntegration(update_progress_fn),
            authorizer=token_authorizer,
            authorization_type=apigw.AuthorizationType.CUSTOM,
        )

        # /sessions/{id}/app-status (Token auth) — live JupyterLab app health
        session_app_status = session_by_id.add_resource("app-status")
        session_app_status.add_method(
            "GET",
            apigw.LambdaIntegration(app_status_fn),
            authorizer=token_authorizer,
            authorization_type=apigw.AuthorizationType.CUSTOM,
        )

        # /modules/{id}/instance-options (Token auth)
        modules_resource = self._api.root.add_resource("modules")
        module_by_id = modules_resource.add_resource("{id}")
        module_instance_options = module_by_id.add_resource("instance-options")
        module_instance_options.add_method(
            "GET",
            apigw.LambdaIntegration(instance_options_fn),
            authorizer=token_authorizer,
            authorization_type=apigw.AuthorizationType.CUSTOM,
        )

        # /costs/daily (Cognito auth)
        costs_resource = self._api.root.add_resource("costs")
        costs_daily = costs_resource.add_resource("daily")
        costs_daily.add_method(
            "GET",
            apigw.LambdaIntegration(get_costs_fn),
            authorizer=cognito_authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # /presigned-url/{userId} (Token auth)
        presigned_url_resource = self._api.root.add_resource("presigned-url")
        presigned_url_by_user = presigned_url_resource.add_resource("{userId}")
        presigned_url_by_user.add_method(
            "POST",
            apigw.LambdaIntegration(presigned_url_fn),
            authorizer=token_authorizer,
            authorization_type=apigw.AuthorizationType.CUSTOM,
        )

    def _create_lambda(
        self,
        function_id: str,
        *,
        handler_dir: str,
        environment: dict[str, str],
        timeout: Duration = Duration.seconds(30),
    ) -> lambda_.Function:
        """Create a Lambda function with shared bundling configuration.

        Bundles from the lambda/ parent directory so the shared/ module is
        accessible. Handler path is set to <handler_dir>/handler.handler.
        """
        return lambda_.Function(
            self,
            function_id,
            function_name=f"av30-{handler_dir.replace('_', '-')}",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler=f"{handler_dir}/handler.handler",
            code=lambda_.Code.from_asset(
                str(_LAMBDA_DIR),
                exclude=["**/__pycache__", "*.pyc"],
            ),
            environment=environment,
            timeout=timeout,
            memory_size=256,
            tracing=lambda_.Tracing.ACTIVE,
        )

    @property
    def api(self) -> apigw.RestApi:
        """The API Gateway REST API resource."""
        return self._api

    @property
    def api_url(self) -> str:
        """The invoke URL of the deployed API stage."""
        return self._api.url
