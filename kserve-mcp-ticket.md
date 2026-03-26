# Feature: MCP Server for KServe — AI-Native Operational Interface

## Summary

Introduce an [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server for KServe that exposes core operational capabilities — listing, deploying, scaling, debugging, and running inference against InferenceServices — as structured tools consumable by AI agents and LLM-powered workflows.

## Motivation

Today, interacting with KServe requires familiarity with `kubectl`, KServe's CRD schema, the Open Inference Protocol payload format, and various CLI conventions. This creates friction for new users, increases cognitive load for experienced ones, and makes it difficult to integrate KServe operations into AI-driven workflows.

An MCP server addresses this by providing a goal-oriented interface that abstracts away the underlying mechanics.

## Justifications

### 1. Reduced Cognitive Overhead
Users should not need to know CRD group names (`inferenceservices.serving.kserve.io`), craft `jsonpath` expressions, or remember `kubectl` flags to answer basic operational questions like "is my model ready?" or "what URL is my service on?". The MCP server returns structured, relevant fields directly.

### 2. LLM-Native Operational Workflows
The primary motivation for MCP is enabling AI agents to drive KServe operations end-to-end within a conversational loop — deploy a model, poll readiness, fetch logs on failure, run a test inference, adjust traffic split — without requiring the user to context-switch to a terminal and act as the integration layer between steps.

### 3. Inference as a First-Class Operation
`run_inference` removes the need to manually construct V1/V2 protocol payloads, locate the endpoint URL, and manage auth headers via `curl`. This is especially valuable for quick model validation after deployment.

### 4. Built-in Safety and Guardrails
- Destructive operations (e.g. delete) require explicit confirmation before execution, reducing the risk of accidental data loss in conversational or agentic contexts.
- Sensitive data in logs and inference responses is automatically redacted, preventing accidental credential leakage in chat sessions or shared terminals.

### 5. Discoverability for New Users
Tool signatures self-document what operations are possible and what parameters they accept. A new team member or external contributor does not need to internalize KServe's object model to perform common tasks — they can discover capabilities through the tool interface.

### 6. Consistent Interface Across Deployment Environments
Whether running locally, in CI, or through an AI assistant, the MCP server provides the same interface regardless of the underlying Kubernetes setup, kubectl context management, or kubeconfig configuration.

## Proposed Capabilities

| Tool | Description |
|------|-------------|
| `list_inference_services` | List all InferenceServices in a namespace with ready status and URL |
| `get_inference_service` | Get detailed status of a specific InferenceService |
| `create_inference_service` | Deploy a new InferenceService |
| `delete_inference_service` | Delete an InferenceService (with confirmation) |
| `scale_inference_service` | Adjust min/max replicas |
| `update_traffic_split` | Manage canary/stable traffic weights |
| `run_inference` | Send a prediction request to a deployed model |
| `get_inference_service_logs` | Fetch logs for debugging (with redaction) |
| `get_inference_service_events` | Fetch Kubernetes events for a service |

## Relationship to Existing Tooling

This feature complements rather than replaces `kubectl` and the KServe Python SDK. Power users and automation pipelines will continue to use `kubectl` for full flexibility. The MCP server targets:

- AI agent workflows and LLM-powered assistants
- Developers who want quick operational access without deep KServe/Kubernetes expertise
- Demos and interactive exploration of deployed models

## References

- [Model Context Protocol](https://modelcontextprotocol.io)
- [KServe InferenceService API](https://kserve.github.io/website/latest/reference/api/)
- [Open Inference Protocol (V2)](https://kserve.github.io/website/latest/modelserving/data_plane/v2_protocol/)
