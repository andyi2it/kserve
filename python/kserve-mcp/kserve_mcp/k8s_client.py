"""Initialises the Kubernetes client.  Prefers in-cluster config and falls
back to the local kubeconfig for development."""

import logging
import os
from functools import lru_cache

from kubernetes import client, config
from kubernetes.client import CoreV1Api, CustomObjectsApi, AppsV1Api

logger = logging.getLogger(__name__)

KSERVE_GROUP = "serving.kserve.io"
KSERVE_VERSION = "v1beta1"
ISVC_PLURAL = "inferenceservices"


@lru_cache(maxsize=1)
def _load_config() -> None:
    if os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/token"):
        logger.info("Loading in-cluster Kubernetes config")
        config.load_incluster_config()
    else:
        logger.info("Loading local kubeconfig (development mode)")
        config.load_kube_config()


def custom_objects_api() -> CustomObjectsApi:
    _load_config()
    return CustomObjectsApi()


def core_api() -> CoreV1Api:
    _load_config()
    return CoreV1Api()


def apps_api() -> AppsV1Api:
    _load_config()
    return AppsV1Api()
