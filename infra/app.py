#!/usr/bin/env python3
"""CDK app entry point for AV 3.0 Blueprint Lab."""

import os

import aws_cdk as cdk

from stacks.av30_stack import Av30BlueprintLabStack

app = cdk.App()

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=app.node.try_get_context("region") or os.environ.get("CDK_DEFAULT_REGION", "us-west-2"),
)

Av30BlueprintLabStack(
    app,
    "Av30BlueprintLabStack",
    env=env,
    description="AV 3.0 Blueprint Lab - Multi-user NVIDIA + AWS Physical AI Platform",
)

app.synth()
