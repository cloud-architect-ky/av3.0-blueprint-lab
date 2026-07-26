"""AV 3.0 Blueprint Lab - Monitoring Construct.

SNS topic for admin notifications, email subscription, and daily AWS Budget alarm.
"""

from constructs import Construct

import aws_cdk as cdk
from aws_cdk import (
    aws_sns as sns,
    aws_sns_subscriptions as sns_subscriptions,
    aws_budgets as budgets,
)


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

        # Email subscription for admin
        self._sns_topic.add_subscription(
            sns_subscriptions.EmailSubscription(admin_email)
        )

        # AWS Budget — daily $200 threshold with notification to SNS
        # Note: DAILY budgets only support ACTUAL notification type (not FORECASTED)
        budgets.CfnBudget(
            self,
            "DailyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name="av30lab-daily-budget",
                budget_type="COST",
                time_unit="DAILY",
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

    @property
    def sns_topic(self) -> sns.Topic:
        """SNS topic for admin alert delivery."""
        return self._sns_topic
