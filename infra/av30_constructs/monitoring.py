"""AV 3.0 Blueprint Lab - Monitoring Construct.

SNS topic for admin notifications, email subscription, and daily AWS Budget alarm.
"""

from constructs import Construct

import aws_cdk as cdk
from aws_cdk import (
    aws_iam as iam,
    aws_sns as sns,
    aws_sns_subscriptions as sns_subscriptions,
    aws_budgets as budgets,
)

# Cost Explorer identifies a region by its DISPLAY name, not its code, and the Budgets
# Region cost filter uses the same vocabulary — "us-west-2" is silently not a match.
# Only regions this lab can actually be deployed to need an entry; an unlisted region
# raises rather than producing a budget that measures the whole account by accident.
_CE_REGION_DISPLAY_NAME = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "eu-west-1": "EU (Ireland)",
    "eu-west-2": "EU (London)",
    "eu-central-1": "EU (Frankfurt)",
    "eu-north-1": "EU (Stockholm)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "ap-northeast-3": "Asia Pacific (Osaka)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-south-1": "Asia Pacific (Mumbai)",
    "ca-central-1": "Canada (Central)",
    "sa-east-1": "South America (Sao Paulo)",
}


class UnsupportedBudgetRegionError(ValueError):
    """No Cost Explorer display name known for this region.

    Raised instead of omitting the Region cost filter: a budget with no filter measures
    ENTIRE-ACCOUNT spend, so silently dropping it would give every region a budget that
    alarms on everyone else's usage and names no culprit.
    """


class MonitoringConstruct(Construct):
    """Budget monitoring and admin notifications.

    Attributes:
        sns_topic: SNS topic for admin alert delivery.
    """

    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)

        # Admin email from CDK context (optional during bootstrap; required for deploy)
        admin_email = self.node.try_get_context("admin_email") or "placeholder@example.com"

        # SNS Topic for admin notifications
        self._sns_topic = sns.Topic(
            self,
            "AdminTopic",
            topic_name="av30lab-admin-notifications",
            display_name="AV 3.0 Blueprint Lab Admin Notifications",
        )

        # Let AWS Budgets publish to this topic. Without it the budget fails validation
        # with "Unable to publish to SNS topic". This existed ONLY as hand-added drift
        # on the us-west-2 topic — the CDK declared no topic policy at all (verified:
        # 0 AWS::SNS::TopicPolicy in the synthesized template, while the live topic
        # carries Sid AllowAWSBudgetsPublish). So any fresh deployment, in any region,
        # would have produced a budget that could not alert. Scoped to this account so
        # another account's budget cannot publish here.
        self._sns_topic.add_to_resource_policy(
            iam.PolicyStatement(
                sid="AllowAWSBudgetsPublish",
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal("budgets.amazonaws.com")],
                actions=["SNS:Publish"],
                resources=[self._sns_topic.topic_arn],
                conditions={
                    "StringEquals": {"aws:SourceAccount": cdk.Stack.of(self).account}
                },
            )
        )

        # Email subscription for admin.
        #
        # WARNING — THIS RESOURCE REPORTS SUCCESS WITHOUT WORKING. An SNS email
        # subscription is not active until the recipient clicks the confirmation link,
        # and CloudFormation reports CREATE_COMPLETE as soon as the REQUEST is made. It
        # never waits for confirmation and never retries. SNS then deletes an
        # unconfirmed pending subscription after ~3 days.
        #
        # That is not hypothetical here: the subscription created 2026-07-02 showed
        # CREATE_COMPLETE in CloudFormation while sns:GetSubscriptionAttributes on the
        # very ARN CFN recorded returned "NotFound: Subscription does not exist", and
        # list-subscriptions-by-topic returned []. The daily budget alarm therefore had
        # nowhere to deliver for months — including three consecutive days of ~$269
        # spend against a $200/day budget, which is part of why four abandoned
        # notebook apps in other regions ran for ~85 days unnoticed.
        #
        # There is no way to confirm on the admin's behalf, so scripts/deploy.sh checks
        # for a CONFIRMED subscription after every deploy and warns loudly when there is
        # none. Do not treat a green CloudFormation resource here as a working alert.
        self._sns_topic.add_subscription(
            sns_subscriptions.EmailSubscription(admin_email)
        )

        # AWS Budget — daily $200 threshold with notification to SNS
        # Note: DAILY budgets only support ACTUAL notification type (not FORECASTED)
        budgets.CfnBudget(
            self,
            "DailyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                # Region-suffixed AND region-SCOPED. Both halves are required:
                #
                #  - The name: Budgets is an ACCOUNT-GLOBAL service and budget names are
                #    unique per account, so the old fixed "av30lab-daily-budget" made a
                #    second regional deployment hard-fail with DuplicateRecordException.
                #  - The filter: fixing only the name would give every region a budget
                #    with NO CostFilters, i.e. two budgets both measuring the entire
                #    account. Each would alarm at the combined total, neither could say
                #    which region overran, and a single region quietly using its whole
                #    allowance would trip the other region's alarm too.
                budget_name=f"av30lab-daily-budget-{cdk.Stack.of(self).region}",
                budget_type="COST",
                time_unit="DAILY",
                cost_filters={"Region": [self._ce_region_name()]},
                budget_limit=budgets.CfnBudget.SpendProperty(
                    amount=200,
                    unit="USD",
                ),
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        comparison_operator="GREATER_THAN",
                        notification_type="ACTUAL",
                        threshold=100,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[
                        budgets.CfnBudget.SubscriberProperty(
                            address=self._sns_topic.topic_arn,
                            subscription_type="SNS",
                        ),
                    ],
                ),
            ],
        )

    def _ce_region_name(self) -> str:
        """Cost Explorer display name for this stack's region."""
        region = cdk.Stack.of(self).region
        try:
            return _CE_REGION_DISPLAY_NAME[region]
        except KeyError:
            raise UnsupportedBudgetRegionError(
                f"No Cost Explorer region display name for {region!r}. Add it to "
                f"_CE_REGION_DISPLAY_NAME in monitoring.py — do NOT drop the Region "
                f"cost filter, which would silently make this an account-wide budget."
            ) from None

    @property
    def sns_topic(self) -> sns.Topic:
        """SNS topic for admin alert delivery."""
        return self._sns_topic
