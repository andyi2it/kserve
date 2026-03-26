"""Tools for listing, inspecting, creating, and deleting InferenceServices."""

import json
from typing import Any

from ..guardrails import (
    PolicyError,
    check_namespace,
    check_write,
    require_confirmation,
    scrub_k8s_object,
)
from ..k8s_client import (
    custom_objects_api,
    KSERVE_GROUP,
    KSERVE_VERSION,
    ISVC_PLURAL,
)


def _summarise(isvc: dict) -> dict:
    """Return a concise summary of an ISVC dict (no raw k8s boilerplate)."""
    meta = isvc.get("metadata", {})
    status = isvc.get("status", {})
    spec = isvc.get("spec", {})
    predictor = spec.get("predictor", {})
    model = predictor.get("model", {})
    conditions = {c["type"]: c["status"] for c in status.get("conditions", [])}
    return {
        "name": meta.get("name"),
        "namespace": meta.get("namespace"),
        "ready": conditions.get("Ready", "Unknown"),
        "url": status.get("url"),
        "deploymentMode": meta.get("annotations", {}).get(
            "serving.kserve.io/deploymentMode", "default"
        ),
        "modelFormat": model.get("modelFormat", {}).get("name"),
        "storageUri": model.get("storageUri"),
        "runtime": model.get("runtime"),
        "minReplicas": predictor.get("minReplicas"),
        "maxReplicas": predictor.get("maxReplicas"),
        "canaryTrafficPercent": predictor.get("canaryTrafficPercent"),
        "failureInfo": status.get("modelStatus", {}).get("lastFailureInfo"),
    }


def register(mcp: Any) -> None:
    @mcp.tool()
    def list_inference_services(namespace: str = "kserve") -> str:
        """List all InferenceServices in a namespace with their ready status and URL.

        Args:
            namespace: Kubernetes namespace to query (default: kserve).
        """
        try:
            check_namespace(namespace)
        except PolicyError as e:
            return str(e)

        api = custom_objects_api()
        result = api.list_namespaced_custom_object(
            group=KSERVE_GROUP,
            version=KSERVE_VERSION,
            namespace=namespace,
            plural=ISVC_PLURAL,
        )
        items = result.get("items", [])
        if not items:
            return f"No InferenceServices found in namespace '{namespace}'."
        summaries = [_summarise(i) for i in items]
        return json.dumps(summaries, indent=2)

    @mcp.tool()
    def get_inference_service(name: str, namespace: str = "kserve") -> str:
        """Get detailed information about a single InferenceService.

        Args:
            name: Name of the InferenceService.
            namespace: Kubernetes namespace (default: kserve).
        """
        try:
            check_namespace(namespace)
        except PolicyError as e:
            return str(e)

        api = custom_objects_api()
        isvc = api.get_namespaced_custom_object(
            group=KSERVE_GROUP,
            version=KSERVE_VERSION,
            namespace=namespace,
            plural=ISVC_PLURAL,
            name=name,
        )
        # Return scrubbed full spec + status for diagnostics
        cleaned = scrub_k8s_object(isvc)
        return json.dumps(cleaned, indent=2)

    @mcp.tool()
    def create_inference_service(
        name: str,
        model_format: str,
        storage_uri: str,
        namespace: str = "kserve",
        runtime: str | None = None,
        min_replicas: int = 1,
        max_replicas: int = 1,
        confirm: bool = False,
    ) -> str:
        """Create a new InferenceService.

        Args:
            name: Name for the InferenceService.
            model_format: Model format name, e.g. 'sklearn', 'xgboost', 'tensorflow'.
            storage_uri: URI to model artifacts, e.g. 'gs://bucket/path' or 's3://bucket/path'.
            namespace: Kubernetes namespace (default: kserve).
            runtime: Optional explicit serving runtime name (auto-selected if omitted).
            min_replicas: Minimum replica count (default: 1).
            max_replicas: Maximum replica count (default: 1).
            confirm: Set to True to actually create. False returns a dry-run preview.
        """
        try:
            check_namespace(namespace)
            check_write("create_inference_service")
        except PolicyError as e:
            return str(e)

        model_spec: dict = {
            "modelFormat": {"name": model_format},
            "storageUri": storage_uri,
        }
        if runtime:
            model_spec["runtime"] = runtime

        body: dict = {
            "apiVersion": f"{KSERVE_GROUP}/{KSERVE_VERSION}",
            "kind": "InferenceService",
            "metadata": {"name": name, "namespace": namespace},
            "spec": {
                "predictor": {
                    "minReplicas": min_replicas,
                    "maxReplicas": max_replicas,
                    "model": model_spec,
                }
            },
        }

        preview = (
            f"Create InferenceService '{name}' in namespace '{namespace}'\n"
            f"  modelFormat: {model_format}\n"
            f"  storageUri:  {storage_uri}\n"
            f"  runtime:     {runtime or '(auto-select)'}\n"
            f"  replicas:    {min_replicas}–{max_replicas}"
        )
        dry_run = require_confirmation(confirm, preview)
        if dry_run:
            return dry_run

        api = custom_objects_api()
        created = api.create_namespaced_custom_object(
            group=KSERVE_GROUP,
            version=KSERVE_VERSION,
            namespace=namespace,
            plural=ISVC_PLURAL,
            body=body,
        )
        return f"InferenceService '{name}' created.\n" + json.dumps(
            _summarise(created), indent=2
        )

    @mcp.tool()
    def delete_inference_service(
        name: str,
        namespace: str = "kserve",
        confirm: bool = False,
    ) -> str:
        """Delete an InferenceService.

        Args:
            name: Name of the InferenceService to delete.
            namespace: Kubernetes namespace (default: kserve).
            confirm: Set to True to actually delete. False shows a dry-run preview.
        """
        try:
            check_namespace(namespace)
            check_write("delete_inference_service")
        except PolicyError as e:
            return str(e)

        dry_run = require_confirmation(
            confirm, f"DELETE InferenceService '{name}' from namespace '{namespace}'"
        )
        if dry_run:
            return dry_run

        api = custom_objects_api()
        api.delete_namespaced_custom_object(
            group=KSERVE_GROUP,
            version=KSERVE_VERSION,
            namespace=namespace,
            plural=ISVC_PLURAL,
            name=name,
        )
        return f"InferenceService '{name}' deleted from namespace '{namespace}'."
