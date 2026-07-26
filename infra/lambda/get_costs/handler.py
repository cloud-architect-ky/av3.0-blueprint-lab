"""Lambda handler for retrieving daily cost data.

GET /costs/daily
Queries AWS Cost Explorer for the last 14 days filtered by the project tag.
"""

import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from errors import api_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Boto3 clients — created at module level for connection reuse
ce = boto3.client("ce")

# Project tag used for cost filtering
PROJECT_TAG_KEY = "Project"
PROJECT_TAG_VALUE = os.environ.get("PROJECT_TAG_VALUE", "av30-blueprint-lab")

# Number of days to look back
LOOKBACK_DAYS = 14


@api_handler
def handler(event, context):
    """Get daily costs for the workshop project."""
    now = datetime.now(timezone.utc)
    end_date = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    logger.info(f"Querying costs from {start_date} to {end_date}")

    response = ce.get_cost_and_usage(
        TimePeriod={
            "Start": start_date,
            "End": end_date,
        },
        Granularity="DAILY",
        Metrics=["UnblendedCost"],
        Filter={
            "Tags": {
                "Key": PROJECT_TAG_KEY,
                "Values": [PROJECT_TAG_VALUE],
            }
        },
    )

    costs = []
    for result in response.get("ResultsByTime", []):
        date = result["TimePeriod"]["Start"]
        amount = float(result["Total"]["UnblendedCost"]["Amount"])
        costs.append(
            {
                "date": date,
                "amount": round(amount, 2),
            }
        )

    total = round(sum(c["amount"] for c in costs), 2)
    logger.info(f"Retrieved {len(costs)} days of cost data, total: ${total}")

    return {
        "costs": costs,
        "total": total,
        "currency": "USD",
        "periodStart": start_date,
        "periodEnd": end_date,
    }
