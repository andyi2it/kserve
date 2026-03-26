"""Tools for scaling InferenceServices."""

import json
from typing import Any

from ..guardrails import PolicyError, check_namespace, check_write, require_confirmation
from ..k8s_client import custom_objects_api, KSERVE_GROUP, KSERVE_VERSION, ISVC_PLURAL


def register(mcp: Any) -> None:
    @mcp.tool()
    def scale_inference_service(
        name: str,
        min_replicas: int,
        max_replicas: int,
        namespace: str = "kserve",
        confirm: bool = False,
    ) -> str:
        """Scale an InferenceService by setting its min and max replica counts.

        Args:
            name: Name of the InferenceService.
            min_replicas: Minimum number of replicas (set to 0 for scale-to-zero in Serverless mode).
            max_replicas: Maximum number of replicas.
            namespace: Kubernetes namespace (default: kserve).
            confirm: Set to True to apply. False shows a dry-run preview.
        """
        try:
            check_namespace(namespace)
            check_write("scale_inference_service")
        except PolicyError as e:
            return str(e)

        if min_replicas < 0 or max_replicas < min_replicas:
            return (
                f"Invalid replica range: min={min_replicas}, max={max_replicas}. "
                "Ensure min >= 0 and max >= min."
            )

        preview = (
            f"Scale InferenceService '{name}' in namespace '{namespace}'\n"
            f"  minReplicas: {min_replicas}\n"
            f"  maxReplicas: {max_replicas}"
        )
        dry_run = require_confirmation(confirm, preview)
        if dry_run:
            return dry_run

        patch = {
            "spec": {
                "predictor": {
                    "minReplicas": min_replicas,
                    "maxReplicas": max_replicas,
                }
            }
        }
        api = custom_objects_api()
        updated = api.patch_namespaced_custom_object(
            group=KSERVE_GROUP,
            version=KSERVE_VERSION,
            namespace=namespace,
            plural=ISVC_PLURAL,
            name=name,
            body=patch,
        )
        predictor = updated.get("spec", {}).get("predictor", {})
        return (
            f"InferenceService '{name}' scaled.\n"
            f"  minReplicas: {predictor.get('minReplicas')}\n"
            f"  maxReplicas: {predictor.get('maxReplicas')}"
        )
