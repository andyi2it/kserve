# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

KServe is a Kubernetes-native ML model serving platform. The codebase has two main parts:
- **Control plane** (Go): Kubernetes controllers, webhooks, and CRDs in `/pkg` and `/cmd`
- **Data plane** (Python): Model servers and SDK in `/python`

## Build Commands

```bash
# Build Go binaries
make manager          # Build controller manager
make agent            # Build agent binary
make router           # Build router binary

# Code generation (run after modifying API types)
make manifests        # Regenerate CRDs, RBAC, webhook configs
make generate         # Full codegen: controller-gen, openapi, Python SDK
```

## Testing

```bash
# Go unit + integration tests (requires setup-envtest)
make test

# Run a single Go test package
KUBEBUILDER_ASSETS="$(setup-envtest use 1.29 -p path)" go test ./pkg/controller/v1beta1/inferenceservice/... -v

# Queue proxy extension tests
make test-qpext

# Python SDK tests
cd python/kserve && make test          # pytest
cd python/kserve && make type_check    # mypy
```

## Linting

```bash
make fmt       # go fmt
make vet       # go vet
make go-lint   # golangci-lint (config: .golangci.yml)
make py-fmt    # black formatting for Python
```

## Architecture

### Control Plane (`/pkg`, `/cmd`)

**API types** (`pkg/apis/serving/`):
- `v1beta1/`: Primary production APIs — `InferenceService`, `ServingRuntime`, `ClusterServingRuntime`, `TrainedModel`
- `v1alpha1/`: Newer/experimental APIs — `InferenceGraph`, `LocalModel`, `ClusterLocalModel`

**Controllers** (`pkg/controller/`):
- `v1beta1/inferenceservice/`: Core controller — reconciles InferenceService CRs, creates/updates Knative Services or raw K8s Deployments depending on deploy mode
- `v1alpha1/inferencegraph/`: Routes requests across multiple inference services
- `v1alpha1/trainedmodel/`: Multi-model serving (multiple models on one server)
- `v1alpha1/localmodel/`: Node-local model caching via LocalModel CRs

**Webhooks** (`pkg/webhook/`): Defaulting and validation webhooks for all CRDs. Resource defaulting behavior can be toggled via config (see recent branch `enable-disable-resource-defaulting`).

**Entry points** (`cmd/`):
- `manager/`: Starts controller manager (registers all controllers + webhooks)
- `agent/`: Sidecar agent for model watching/downloading
- `router/`: Request router for InferenceGraph

### Data Plane (`/python`)

**`python/kserve/`**: Core Python SDK
- `kserve/model.py`, `kserve/model_server.py`: Base model class and FastAPI/uvicorn server
- `kserve/protocol/`: V1 and V2 (Open Inference Protocol) REST + gRPC
- `kserve/storage/`: Model download backends (GCS, S3, Azure, HTTP, local)
- `kserve/ray/`: Ray Serve integration for distributed inference

**Framework-specific servers** (each is an independent Python package):
- `python/sklearnserver`, `python/xgbserver`, `python/lgbserver`, `python/pmmlserver`, `python/paddleserver`, `python/huggingfaceserver`

**`python/storage-initializer/`**: Init container that downloads models before serving starts.

### Deployment Modes

InferenceService supports three deployment modes (set in `InferenceServiceSpec`):
1. **Serverless** (default): Uses Knative Serving for scale-to-zero
2. **RawDeployment**: Standard K8s Deployment + Service (no Knative)
3. **ModelMesh**: Delegates to ModelMesh controller (separate installation)

### Key Configuration

- `config/configmap/`: Runtime ConfigMaps (`inferenceservice.yaml`) — controls defaults, feature flags, resource limits
- `config/rbac/`: RBAC for controller service accounts
- `config/manager/`: Controller manager Deployment manifests

## Common Workflows

**Modifying API types:**
1. Edit types in `pkg/apis/serving/v1beta1/` or `v1alpha1/`
2. Run `make manifests generate` to regenerate CRDs and clients
3. Update webhooks in `pkg/webhook/` if validation logic changes
4. Update controller reconcile logic in `pkg/controller/`

**Adding a new framework server:**
1. Create new package under `python/`
2. Implement `kserve.Model` interface from `python/kserve`
3. Add Dockerfile and entry to `Makefile` docker-build targets

**Deploying to a cluster:**
```bash
make deploy          # Uses kubectl apply with kustomize
make deploy-helm     # Helm-based deployment
```

## Go Module

Module path: `github.com/kserve/kserve`, Go 1.22.7

Key dependencies: `sigs.k8s.io/controller-runtime` v0.18.5, `knative.dev/serving` v0.42.2, `istio.io/client-go` v1.23.0, `k8s.io/api` v0.30.4
