"""Tool for making test inference calls against a deployed InferenceService."""

import json
from typing import Any

import httpx

from ..guardrails import (
    PolicyError, check_namespace, scrub_dict, scrub_inference_enabled,
)
from ..k8s_client import core_api


def _predictor_url(name: str, namespace: str) -> str:
    """Construct the in-cluster URL for the predictor service."""
    return f"http://{name}-predictor.{namespace}.svc.cluster.local"


def _service_exists(name: str, namespace: str) -> bool:
    api = core_api()
    services = api.list_namespaced_service(
        namespace=namespace,
        label_selector=f"serving.kserve.io/inferenceservice={name}",
    )
    return bool(services.items)


def register(mcp: Any) -> None:

    @mcp.tool()
    def run_inference(
        name: str,
        payload: str,
        namespace: str = "kserve",
        protocol_version: str = "v1",
        timeout_seconds: int = 30,
    ) -> str:
        """Send a test inference request to a deployed InferenceService.

        The response is automatically scrubbed for sensitive content before
        being returned to the chat context.

        Args:
            name: Name of the InferenceService.
            payload: JSON string with the request body.
                     V1 example: '{"instances": [[6.8, 2.8, 4.8, 1.4]]}'
                     V2 example: '{"inputs": [{"name": "input-0", "shape": [1, 4],
                                               "datatype": "FP32",
                                               "data": [6.8, 2.8, 4.8, 1.4]}]}'
            namespace: Kubernetes namespace (default: kserve).
            protocol_version: 'v1' (default) or 'v2'.
            timeout_seconds: Request timeout in seconds (default: 30, max: 120).
        """
        try:
            check_namespace(namespace)
        except PolicyError as e:
            return str(e)

        # Validate payload is parseable JSON
        try:
            request_body = json.loads(payload)
        except json.JSONDecodeError as e:
            return f"Invalid JSON payload: {e}"

        if protocol_version == "v1":
            endpoint = f"/v1/models/{name}:predict"
        elif protocol_version == "v2":
            endpoint = f"/v2/models/{name}/infer"
        else:
            return f"Unknown protocol_version '{protocol_version}'. Use 'v1' or 'v2'."

        timeout_seconds = min(timeout_seconds, 120)
        base_url = _predictor_url(name, namespace)
        url = base_url + endpoint

        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(url, json=request_body)
                response.raise_for_status()
                result = response.json()
        except httpx.ConnectError:
            return (
                f"Connection refused to {url}.\n"
                "Possible causes:\n"
                "  • InferenceService is not Ready (check get_inference_service)\n"
                "  • Predictor pod is not running (check get_inference_service_logs)\n"
                "  • Running outside the cluster (in-cluster URLs only work from within k8s)"
            )
        except httpx.TimeoutException:
            return f"Request to {url} timed out after {timeout_seconds}s."
        except httpx.HTTPStatusError as e:
            body = e.response.text[:500]
            return f"HTTP {e.response.status_code} from {url}:\n{body}"
        except Exception as e:
            return f"Inference request failed: {e}"

        if scrub_inference_enabled():
            result = scrub_dict(result)

        return json.dumps(result, indent=2)
