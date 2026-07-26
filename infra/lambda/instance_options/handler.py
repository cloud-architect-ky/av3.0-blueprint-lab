"""Lambda handler for retrieving module instance options.

GET /modules/{id}/instance-options
Returns the configuration and available instance types for a given module.
"""

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from config import INSTANCE_RATES, MODULE_CONFIG
from errors import ApiError, api_handler

logger = logging.getLogger()
logger.setLevel(logging.INFO)


@api_handler
def handler(event, context):
    """Get instance options for a specific module."""
    # Extract moduleId from path
    path_params = event.get("pathParameters") or {}
    module_id = path_params.get("id")

    if not module_id:
        raise ApiError(400, "Missing moduleId in path")

    # Look up module configuration
    module = MODULE_CONFIG.get(module_id)
    if not module:
        raise ApiError(
            404,
            f"Module not found: {module_id}",
            details=f"Valid modules: {sorted(MODULE_CONFIG.keys())}",
        )

    # Build instance options with rates
    default_instance = module["instance_type"]
    default_rate = INSTANCE_RATES.get(default_instance, 0)

    # Return all instances at or above the module's minimum requirement
    available_instances = []
    for instance_type, rate in sorted(INSTANCE_RATES.items(), key=lambda x: x[1]):
        if rate >= default_rate:
            available_instances.append(
                {
                    "instanceType": instance_type,
                    "hourlyCost": rate,
                    "isDefault": instance_type == default_instance,
                }
            )

    return {
        "moduleId": module_id,
        "moduleName": module["name"],
        "defaultInstanceType": default_instance,
        "estimatedDurationMinutes": module["estimated_duration_minutes"],
        "availableInstances": available_instances,
    }
