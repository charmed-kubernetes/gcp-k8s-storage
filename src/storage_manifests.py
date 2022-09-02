# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""Implementation of gcp specific details of the kubernetes manifests."""
import base64
import logging
import pickle
from hashlib import md5
from typing import Dict, Optional

from lightkube.codecs import AnyResource, from_dict
from ops.manifests import Addition, CreateNamespace, ConfigRegistry, ManifestLabel, Manifests

log = logging.getLogger(__file__)
NAMESPACE = "gce-pd-csi-driver"
SECRET_NAME = "cloud-sa"
STORAGE_CLASS_NAME = "csi-gce-pd-{type}"


class CreateSecret(Addition):
    """Create secret for the deployment."""

    CONFIG_TO_SECRET = {
        "cloud_sa": "cloud-sa.json",
    }

    def __call__(self) -> Optional[AnyResource]:
        """Craft the secrets object for the deployment."""
        secret_config = {
            new_k: self.manifests.config.get(k) for k, new_k in self.CONFIG_TO_SECRET.items()
        }
        if any(s is None for s in secret_config.values()):
            log.error("secret data item is None")
            return None

        log.info("Encode secret data for storage.")
        return from_dict(
            dict(
                apiVersion="v1",
                kind="Secret",
                type="Opaque",
                metadata=dict(name=SECRET_NAME, namespace=NAMESPACE),
                data=secret_config,
            )
        )


class CreateStorageClass(Addition):
    """Create vmware storage class."""

    def __init__(self, manifests: "Manifests", sc_type: str):
        super().__init__(manifests)
        self.type = sc_type

    def __call__(self) -> Optional[AnyResource]:
        """Craft the storage class object."""
        storage_name = STORAGE_CLASS_NAME.format(type=self.type)
        log.info(f"Creating storage class {storage_name}")
        return from_dict(
            dict(
                apiVersion="storage.k8s.io/v1",
                kind="StorageClass",
                metadata=dict(
                    name=storage_name,
                ),
                provisioner="pd.csi.storage.gke.io",
                volumeBindingMode="WaitForFirstConsumer",
            )
        )


class GCPStorageManifests(Manifests):
    """Deployment Specific details for the gce-pd-csi-driver."""

    def __init__(self, charm, charm_config, kube_control):
        super().__init__(
            "gce-pd-csi-driver",
            charm.model,
            "upstream/cloud_storage",
            [
                CreateNamespace(self, NAMESPACE),
                CreateSecret(self),
                ManifestLabel(self),
                ConfigRegistry(self),
                CreateStorageClass(self, "default"),  # creates gce-pd-csi-driver
            ],
        )
        self.charm_config = charm_config
        self.kube_control = kube_control

    @property
    def config(self) -> Dict:
        """Returns current config available from charm config and joined relations."""
        config: Dict = {}

        if self.kube_control.is_ready:
            config["image-registry"] = self.kube_control.get_registry_location()

        config.update(**self.charm_config.available_data)
        config.update(**{k: v.get_secret_value() for k, v in self.charm_config.credentials})

        for key, value in dict(**config).items():
            if value == "" or value is None:
                del config[key]

        config["release"] = config.pop("storage-release", None)
        return config

    def hash(self) -> int:
        """Calculate a hash of the current configuration."""
        return int(md5(pickle.dumps(self.config)).hexdigest(), 16)

    def evaluate(self) -> Optional[str]:
        """Determine if manifest_config can be applied to manifests."""
        props = CreateSecret.CONFIG_TO_SECRET.keys()
        for prop in props:
            value = self.config.get(prop)
            if not value:
                return f"Storage manifests waiting for definition of {prop}"
        return None
