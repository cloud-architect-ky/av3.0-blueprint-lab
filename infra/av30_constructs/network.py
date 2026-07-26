"""AV 3.0 Blueprint Lab - Network Construct.

Private-only VPC with VPC endpoints for AWS service access without NAT.
"""

from constructs import Construct

import aws_cdk as cdk
from aws_cdk import (
    aws_ec2 as ec2,
)


class NetworkConstruct(Construct):
    """VPC with private subnets and interface/gateway endpoints.

    Attributes:
        vpc: The VPC resource.
        endpoints_security_group: Security group attached to VPC interface endpoints.
    """

    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)

        # Private-only VPC across 2 AZs — no public subnets, no NAT
        self._vpc = ec2.Vpc(
            self,
            "Vpc",
            vpc_name="av30lab-vpc",
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                ),
            ],
        )

        # Security group for VPC interface endpoints — allows HTTPS from within VPC
        self._endpoints_sg = ec2.SecurityGroup(
            self,
            "EndpointsSg",
            vpc=self._vpc,
            description="Allow HTTPS inbound for VPC interface endpoints",
            allow_all_outbound=False,
        )
        self._endpoints_sg.add_ingress_rule(
            peer=ec2.Peer.ipv4(self._vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(443),
            description="HTTPS from VPC CIDR",
        )

        # Gateway endpoint: S3 (no security group needed for gateway endpoints)
        self._vpc.add_gateway_endpoint(
            "S3Endpoint",
            service=ec2.GatewayVpcEndpointAwsService.S3,
        )

        # Interface endpoints for AWS services accessed from private subnets
        interface_services = {
            "SageMakerApi": ec2.InterfaceVpcEndpointAwsService.SAGEMAKER_API,
            "SageMakerRuntime": ec2.InterfaceVpcEndpointAwsService.SAGEMAKER_RUNTIME,
            "EcrApi": ec2.InterfaceVpcEndpointAwsService.ECR,
            "EcrDkr": ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER,
            "CloudWatchLogs": ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
            "Sts": ec2.InterfaceVpcEndpointAwsService.STS,
        }

        for endpoint_id, service in interface_services.items():
            self._vpc.add_interface_endpoint(
                endpoint_id,
                service=service,
                private_dns_enabled=True,
                security_groups=[self._endpoints_sg],
            )

    @property
    def vpc(self) -> ec2.Vpc:
        """The VPC resource."""
        return self._vpc

    @property
    def endpoints_security_group(self) -> ec2.SecurityGroup:
        """Security group attached to VPC interface endpoints."""
        return self._endpoints_sg
