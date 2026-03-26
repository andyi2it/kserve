"""Tools for managing canary traffic splits on InferenceServices.

Note: canaryTrafficPercent is primarily supported in Serverless (Knative) mode.
In RawDeployment mode this field is accepted but has no effect without a
compatible ingress controller.
"""

from typing import Any

from ..guardrails import PolicyError, check_namespace, check_write, require_confirmation
from ..k8s_client import custom_objects_api, KSERVE_GROUP, KSERVE_VERSION, ISVC_PLURAL


def register(mcp: Any) -> None:

    @mcp.tool()
    def update_traffic_split(
        name: str,
        canary_traffic_percent: int,
        namespace: str = "kserve",
        confirm: bool = False,
    ) -> str:
        """Set the canary traffic percentage for an InferenceService.

        When canary_traffic_percent is set (1–99), that percentage of traffic is
        routed to the latest revision while the remainder goes to the previous
        stable revision. Set to 100 to promote the canary to stable (no split).

        Requires Serverless (Knative) deployment mode for full effect.

        Args:
            name: Name of the InferenceService.
            canary_traffic_percent: Percentage of traffic to the latest revision (0–100).
            namespace: Kubernetes namespace (default: kserve).
            confirm: Set to True to apply. False shows a dry-run preview.
        """
        try:
            check_namespace(namespace)
            check_write("update_traffic_split")
        except PolicyError as e:
            return str(e)

        if not 0 <= canary_traffic_percent <= 100:
            return "canary_traffic_percent must be between 0 and 100."

        preview = (
            f"Update traffic split for InferenceService '{name}' in namespace '{namespace}'\n"
            f"  canaryTrafficPercent: {canary_traffic_percent}%\n"
            f"  stable traffic:       {100 - canary_traffic_percent}%"
        )
        dry_run = require_confirmation(confirm, preview)
        if dry_run:
            return dry_run

        patch = {"spec": {"predictor": {"canaryTrafficPercent": canary_traffic_percent}}}
        api = custom_objects_api()
        api.patch_namespaced_custom_object(
            group=KSERVE_GROUP,
            version=KSERVE_VERSION,
            namespace=namespace,
            plural=ISVC_PLURAL,
            name=name,
            body=patch,
        )
        if canary_traffic_percent == 100:
            msg = f"Canary promoted to stable: '{name}' now receives 100% of traffic."
        elif canary_traffic_percent == 0:
            msg = f"Canary rolled back: '{name}' latest revision receives 0% of traffic."
        else:
            msg = (
                f"Traffic split updated for '{name}': "
                f"{canary_traffic_percent}% → latest, "
                f"{100 - canary_traffic_percent}% → stable."
            )
        return msg
