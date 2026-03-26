"""Tools for debugging InferenceServices: pod logs and Kubernetes events."""

from typing import Any

from ..guardrails import (
    PolicyError, check_namespace, scrub, scrub_logs_enabled,
)
from ..k8s_client import core_api


# Containers present in a KServe predictor pod
_KNOWN_CONTAINERS = ["kserve-container", "storage-initializer", "queue-proxy"]


def register(mcp: Any) -> None:

    @mcp.tool()
    def get_inference_service_logs(
        name: str,
        namespace: str = "kserve",
        container: str = "kserve-container",
        tail_lines: int = 100,
        previous: bool = False,
    ) -> str:
        """Fetch logs from the predictor pod of an InferenceService.

        Sensitive values (tokens, secrets, IPs) are automatically redacted before
        the log content is returned.

        Args:
            name: Name of the InferenceService.
            namespace: Kubernetes namespace (default: kserve).
            container: Container to fetch logs from. Options: kserve-container
                       (default), storage-initializer, queue-proxy.
            tail_lines: Number of recent log lines to return (default: 100, max: 500).
            previous: If True, return logs from the previously terminated container
                      (useful for diagnosing CrashLoopBackOff).
        """
        try:
            check_namespace(namespace)
        except PolicyError as e:
            return str(e)

        tail_lines = min(tail_lines, 500)

        api = core_api()

        # Find predictor pods for this ISVC
        pods = api.list_namespaced_pod(
            namespace=namespace,
            label_selector=f"serving.kserve.io/inferenceservice={name}",
        )
        if not pods.items:
            return (
                f"No pods found for InferenceService '{name}' in namespace '{namespace}'. "
                "The ISVC may not be deployed yet or may have been scaled to zero."
            )

        # Prefer running pods; fall back to any pod
        running = [p for p in pods.items if p.status.phase == "Running"]
        pod = (running or pods.items)[0]
        pod_name = pod.metadata.name

        try:
            logs = api.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                container=container,
                tail_lines=tail_lines,
                previous=previous,
            )
        except Exception as exc:
            available = [
                cs.name
                for cs in (pod.status.container_statuses or [])
            ]
            return (
                f"Failed to read logs from container '{container}' in pod '{pod_name}': {exc}\n"
                f"Available containers: {available or _KNOWN_CONTAINERS}"
            )

        if scrub_logs_enabled():
            logs = scrub(logs)

        header = (
            f"=== Logs: {pod_name} / {container} "
            f"({'previous' if previous else 'current'}, last {tail_lines} lines) ===\n"
        )
        return header + (logs or "(no log output)")

    @mcp.tool()
    def get_inference_service_events(
        name: str,
        namespace: str = "kserve",
    ) -> str:
        """Fetch Kubernetes events related to an InferenceService and its pods.

        Events surface scheduling failures, image pull errors, OOM kills, and
        other cluster-level issues that don't appear in application logs.

        Args:
            name: Name of the InferenceService.
            namespace: Kubernetes namespace (default: kserve).
        """
        try:
            check_namespace(namespace)
        except PolicyError as e:
            return str(e)

        api = core_api()
        events = api.list_namespaced_event(
            namespace=namespace,
            field_selector=f"involvedObject.name={name}",
        )

        # Also grab events for predictor pods
        pods = api.list_namespaced_pod(
            namespace=namespace,
            label_selector=f"serving.kserve.io/inferenceservice={name}",
        )
        for pod in pods.items:
            pod_events = api.list_namespaced_event(
                namespace=namespace,
                field_selector=f"involvedObject.name={pod.metadata.name}",
            )
            events.items.extend(pod_events.items)

        if not events.items:
            return f"No events found for InferenceService '{name}' in namespace '{namespace}'."

        # Sort by last timestamp
        items = sorted(
            events.items,
            key=lambda e: e.last_timestamp or e.event_time or "",
        )

        lines = []
        for e in items:
            ts = e.last_timestamp or e.event_time or "unknown"
            reason = e.reason or ""
            msg = scrub(e.message or "") if scrub_logs_enabled() else (e.message or "")
            obj = f"{e.involved_object.kind}/{e.involved_object.name}"
            lines.append(f"[{ts}] {e.type:8s} {reason:30s} {obj}\n  {msg}")

        return "\n".join(lines)
