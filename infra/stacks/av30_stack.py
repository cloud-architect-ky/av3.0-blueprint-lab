"""AV 3.0 Blueprint Lab - Main CDK Stack.

Orchestrates all constructs: Network, Storage, Database, SageMaker, Auth,
Monitoring, API, and Dashboards (admin + user).
"""

from constructs import Construct

import aws_cdk as cdk
from aws_cdk import aws_wafv2 as wafv2

from av30_constructs.network import NetworkConstruct
from av30_constructs.storage import StorageConstruct
from av30_constructs.database import DatabaseConstruct
from av30_constructs.sagemaker import SageMakerConstruct
from av30_constructs.auth import AuthConstruct
from av30_constructs.monitoring import MonitoringConstruct
from av30_constructs.api import ApiConstruct
from av30_constructs.dashboards import DashboardConstruct


class Av30BlueprintLabStack(cdk.Stack):
    """Core infrastructure stack for AV 3.0 Blueprint Lab."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Apply project-level tags
        cdk.Tags.of(self).add("Project", "av30-blueprint-lab")
        cdk.Tags.of(self).add("Owner", "av30-blueprint-lab")

        # Network layer: VPC with private subnets and VPC endpoints
        network = NetworkConstruct(self, "Network")

        # Storage layer: KMS key and S3 buckets
        storage = StorageConstruct(self, "Storage")

        # Database layer: DynamoDB sessions table
        database = DatabaseConstruct(self, "Database")

        # SageMaker layer: Studio Domain with execution role and lifecycle config
        sagemaker_domain = SageMakerConstruct(
            self,
            "SageMaker",
            vpc=network.vpc,
            shared_data_bucket=storage.shared_data_bucket,
            user_workspace_bucket=storage.user_workspace_bucket,
            sagemaker_image_arn=self.node.try_get_context("sagemaker_image_arn")
            or f"arn:aws:sagemaker:{self.region}:236514542706:image/jupyter-server-3",
        )

        # Auth layer: Cognito User Pool + WAF WebACL with IP allowlist
        auth = AuthConstruct(self, "Auth")

        # Monitoring layer: SNS notifications + daily budget alarm
        monitoring = MonitoringConstruct(self, "Monitoring")

        # API layer: API Gateway + Lambda functions + authorizers
        api = ApiConstruct(
            self,
            "Api",
            user_pool=auth.user_pool,
            sessions_table=database.sessions_table,
            shared_data_bucket=storage.shared_data_bucket,
            user_workspace_bucket=storage.user_workspace_bucket,
            sagemaker_domain_id=sagemaker_domain.domain_id,
            sagemaker_execution_role=sagemaker_domain.execution_role,
            notebook_lifecycle_config_arn=sagemaker_domain.notebook_lifecycle_config_arn,
        )

        # Attach WAF (REGIONAL) to API Gateway stage for IP allowlist enforcement
        # Only created when admin_ip_allowlist is set to specific IPs (not 0.0.0.0/0)
        if auth.waf_enabled:
            wafv2.CfnWebACLAssociation(
                self,
                "WafApiAssociation",
                resource_arn=f"arn:aws:apigateway:{cdk.Aws.REGION}::/restapis/{api.api.rest_api_id}/stages/{api.api.deployment_stage.stage_name}",
                web_acl_arn=auth.web_acl_arn,
            )

        # Dashboard layer: Admin and User dashboards (WAF is on API Gateway, not CloudFront)
        admin_dashboard = DashboardConstruct(
            self,
            "AdminDashboard",
            bucket_name=f"av30lab-admin-dashboard-{cdk.Aws.ACCOUNT_ID}",
        )

        user_dashboard = DashboardConstruct(
            self,
            "UserDashboard",
            bucket_name=f"av30lab-user-dashboard-{cdk.Aws.ACCOUNT_ID}",
        )

        # Stack outputs for cross-stack references and operational visibility
        cdk.CfnOutput(self, "VpcId", value=network.vpc.vpc_id)
        cdk.CfnOutput(self, "KmsKeyArn", value=storage.kms_key.key_arn)
        cdk.CfnOutput(
            self,
            "SharedDataBucketArn",
            value=storage.shared_data_bucket.bucket_arn,
        )
        cdk.CfnOutput(
            self,
            "UserWorkspaceBucketArn",
            value=storage.user_workspace_bucket.bucket_arn,
        )
        cdk.CfnOutput(
            self, "SessionsTableArn", value=database.sessions_table.table_arn
        )
        cdk.CfnOutput(
            self, "SageMakerDomainId", value=sagemaker_domain.domain_id
        )
        cdk.CfnOutput(
            self,
            "SageMakerExecutionRoleArn",
            value=sagemaker_domain.execution_role.role_arn,
        )
        cdk.CfnOutput(
            self,
            "SageMakerLifecycleConfigArn",
            value=sagemaker_domain.lifecycle_config_arn,
        )
        cdk.CfnOutput(
            self,
            "SageMakerNotebookLifecycleConfigArn",
            value=sagemaker_domain.notebook_lifecycle_config_arn,
        )
        cdk.CfnOutput(
            self, "UserPoolId", value=auth.user_pool.user_pool_id
        )
        cdk.CfnOutput(
            self,
            "UserPoolClientId",
            value=auth.user_pool_client.user_pool_client_id,
        )
        if auth.waf_enabled:
            cdk.CfnOutput(self, "WebAclArn", value=auth.web_acl_arn)
        cdk.CfnOutput(
            self, "AdminSnsTopicArn", value=monitoring.sns_topic.topic_arn
        )
        cdk.CfnOutput(self, "ApiUrl", value=api.api_url)
        cdk.CfnOutput(
            self,
            "AdminBucketName",
            value=admin_dashboard.bucket.bucket_name,
        )
        cdk.CfnOutput(
            self,
            "UserBucketName",
            value=user_dashboard.bucket.bucket_name,
        )
        cdk.CfnOutput(
            self,
            "AdminDistributionId",
            value=admin_dashboard.distribution.distribution_id,
        )
        cdk.CfnOutput(
            self,
            "UserDistributionId",
            value=user_dashboard.distribution.distribution_id,
        )
        cdk.CfnOutput(self, "AdminUrl", value=admin_dashboard.url)
        cdk.CfnOutput(self, "UserUrl", value=user_dashboard.url)
