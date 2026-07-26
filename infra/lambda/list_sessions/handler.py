"""Lambda handler for listing active sessions with estimated costs.

GET /sessions
Scans DynamoDB for all users, calculates running costs for active sessions,
and returns sessions sorted by status (active first) then cost descending.
"""

import logging
import os
import sys
from datetime import datetime, timezone

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from config import INSTANCE_RATES, SESSIONS_TABLE_NAME
from errors import api_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
dynamodb = boto3.resource("dynamodb")


def calculate_estimated_cost(item: dict, now: datetime) -> float:
    """Calculate estimated cost based on running time and instance rate."""
    start_time_str = item.get("createdAt")
    instance_type = item.get("instanceType", "ml.t3.medium")

    if not start_time_str:
        return 0.0

    try:
        start_time = datetime.fromisoformat(start_time_str)
    except (ValueError, TypeError):
        return 0.0

    elapsed_hours = (now - start_time).total_seconds() / 3600
    rate = INSTANCE_RATES.get(instance_type, 0.0)
    return round(elapsed_hours * rate, 4)


@api_handler
def handler(event, context):
    """List all sessions with estimated costs."""
    table = dynamodb.Table(SESSIONS_TABLE_NAME)

    # Scan all items (acceptable for workshop-scale data)
    items = []
    response = table.scan()
    items.extend(response.get("Items", []))

    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))

    logger.info(f"Found {len(items)} total users")

    now = datetime.now(timezone.utc)
    sessions = []

    for item in items:
        status = item.get("status", "offline")
        estimated_cost = 0.0

        if status != "offline":
            estimated_cost = calculate_estimated_cost(item, now)

        sessions.append(
            {
                "userId": item.get("userId"),
                "name": item.get("name"),
                "status": status,
                "instanceType": item.get("instanceType", "ml.t3.medium"),
                "currentModule": item.get("currentModule"),
                "estimatedCost": estimated_cost,
                "startTime": item.get("createdAt"),
                "storageGB": item.get("storageGB", 5),
            }
        )

    # Sort: active first, then by cost descending
    status_priority = {"active": 0, "provisioning": 1, "stopping": 2, "offline": 3}
    sessions.sort(
        key=lambda s: (
            status_priority.get(s["status"], 9),
            -s["estimatedCost"],
        )
    )

    return {
        "sessions": sessions,
        "total": len(sessions),
        "activeCount": sum(1 for s in sessions if s["status"] != "offline"),
    }
