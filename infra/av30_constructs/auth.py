"""AV 3.0 Blueprint Lab - Auth Construct.

Cognito User Pool (admin-only), User Pool Client, WAF WebACL with IP allowlist.
"""

from constructs import Construct

import aws_cdk as cdk
from aws_cdk import (
    aws_cognito as cognito,
    aws_wafv2 as wafv2,
)


class AuthConstruct(Construct):
    """Authentication and WAF protection for admin dashboard.

    Attributes:
        user_pool: Cognito User Pool with strict password policy (admin-only).
        user_pool_client: App client for admin dashboard SPA.
        web_acl_arn: ARN of the WAF WebACL (CLOUDFRONT scope) with IP allowlist.
    """

    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)

        # Cognito User Pool — admin-only with strict password policy
        self._user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name="av30lab-admin-pool",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
                require_lowercase=True,
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # User Pool Client for admin dashboard SPA (no secret for public client)
        self._user_pool_client = cognito.UserPoolClient(
            self,
            "UserPoolClient",
            user_pool=self._user_pool,
            user_pool_client_name="av30lab-admin-dashboard",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(
                user_srp=True,
                user_password=False,
            ),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(
                    authorization_code_grant=True,
                    implicit_code_grant=False,
                ),
                scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL],
            ),
            prevent_user_existence_errors=True,
        )

        # WAF IP allowlist from context parameter (comma-separated CIDRs)
        # Scope is REGIONAL — attached to API Gateway (not CloudFront).
        # If "0.0.0.0/0" (allow all) → skip WAF entirely (WAF IP Set rejects /0 notation)
        admin_ip_allowlist = self.node.try_get_context("admin_ip_allowlist") or "0.0.0.0/0"
        self._waf_enabled = admin_ip_allowlist.strip() != "0.0.0.0/0"

        if self._waf_enabled:
            ip_addresses = [cidr.strip() for cidr in admin_ip_allowlist.split(",")]

            self._ip_set = wafv2.CfnIPSet(
                self,
                "AdminIpSet",
                name="av30lab-admin-ip-allowlist",
                scope="REGIONAL",
                ip_address_version="IPV4",
                addresses=ip_addresses,
            )

            self._web_acl = wafv2.CfnWebACL(
                self,
                "WebAcl",
                name="av30lab-admin-waf",
                scope="REGIONAL",
                default_action=wafv2.CfnWebACL.DefaultActionProperty(block={}),
                visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                    cloud_watch_metrics_enabled=True,
                    metric_name="av30lab-admin-waf",
                    sampled_requests_enabled=True,
                ),
                rules=[
                    wafv2.CfnWebACL.RuleProperty(
                        name="AllowAdminIPs",
                        priority=0,
                        action=wafv2.CfnWebACL.RuleActionProperty(allow={}),
                        visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                            cloud_watch_metrics_enabled=True,
                            metric_name="av30lab-allow-admin-ips",
                            sampled_requests_enabled=True,
                        ),
                        statement=wafv2.CfnWebACL.StatementProperty(
                            ip_set_reference_statement=wafv2.CfnWebACL.IPSetReferenceStatementProperty(
                                arn=self._ip_set.attr_arn,
                            ),
                        ),
                    ),
                ],
            )

    @property
    def user_pool(self) -> cognito.UserPool:
        """Cognito User Pool for admin authentication."""
        return self._user_pool

    @property
    def user_pool_client(self) -> cognito.UserPoolClient:
        """App client for admin dashboard SPA."""
        return self._user_pool_client

    @property
    def waf_enabled(self) -> bool:
        """Whether WAF IP allowlist is active."""
        return self._waf_enabled

    @property
    def web_acl_arn(self) -> str | None:
        """ARN of the WAF WebACL (REGIONAL scope), or None if WAF disabled."""
        return self._web_acl.attr_arn if self._waf_enabled else None
