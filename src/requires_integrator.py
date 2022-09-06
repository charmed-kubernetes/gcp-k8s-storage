# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""Implementation of tls-certificates interface.

This only implements the requires side, currently, since the providers
is still using the Reactive Charm framework self.
"""
import base64
import json
import logging
import os
import random
import string
from typing import Mapping, Optional
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from backports.cached_property import cached_property
from ops.charm import RelationBrokenEvent
from ops.framework import Object, StoredState
from pydantic import BaseModel, Json, SecretStr, ValidationError, validator

log = logging.getLogger(__name__)


# block size to read data from GCP metadata service
# (realistically, just needs to be bigger than ~20 chars)
READ_BLOCK_SIZE = 2048


class Data(BaseModel):
    """Databag for information shared over the relation."""

    completed: Json[Mapping[str, str]]
    credentials: SecretStr

    @validator("credentials")
    def must_be_json(cls, s: SecretStr):
        """Validate cloud-sa is base64 encoded json."""
        secret_val = s.get_secret_value()
        try:
            json.loads(secret_val)
        except json.JSONDecodeError:
            raise ValueError("Couldn't find json data")
        return s


class GCPIntegratorRequires(Object):
    """Requires side of gcp-integration relation."""

    stored = StoredState()

    # https://cloud.google.com/compute/docs/storing-retrieving-metadata
    _metadata_url = "http://metadata.google.internal/computeMetadata/v1/"
    _instance_url = urljoin(_metadata_url, "instance/name")
    _zone_url = urljoin(_metadata_url, "instance/zone")
    _metadata_headers = {"Metadata-Flavor": "Google"}

    def __init__(self, charm, endpoint="gcp-integration"):
        super().__init__(charm, f"relation-{endpoint}")
        self.endpoint = endpoint
        events = charm.on[endpoint]
        self._unit_name = self.model.unit.name.replace("/", "_")
        self.framework.observe(events.relation_joined, self._joined)
        self.stored.set_default(
            instance=None,  # stores the instance name
            zone=None,  # stores the zone of this instance
        )

    def _joined(self, event):
        to_publish = self.relation.data[self.model.unit]
        to_publish["charm"] = self.model.app.name
        to_publish["instance"] = self.instance
        to_publish["zone"] = self.zone
        to_publish["model-uuid"] = os.environ["JUJU_MODEL_UUID"]

    @cached_property
    def relation(self):
        """The relation to the integrator, or None."""
        return self.model.get_relation(self.endpoint)

    @cached_property
    def _raw_data(self):
        if self.relation and self.relation.units:
            return self.relation.data[list(self.relation.units)[0]]
        return None

    @cached_property
    def _data(self) -> Optional[Data]:
        raw = self._raw_data
        return Data(**raw) if raw else None

    def evaluate_relation(self, event) -> Optional[str]:
        """Determine if relation is ready."""
        no_relation = not self.relation or (
            isinstance(event, RelationBrokenEvent) and event.relation is self.relation
        )
        if not self.is_ready:
            if no_relation:
                return f"Missing required {self.endpoint}"
            return f"Waiting for {self.endpoint}"
        return None

    @property
    def instance(self):
        """This unit's instance name."""
        if self.stored.instance is None:
            req = Request(self._instance_url, headers=self._metadata_headers)
            with urlopen(req) as fd:
                instance = fd.read(READ_BLOCK_SIZE).decode("utf8").strip()
            self.stored.instance = instance
        return self.stored.instance

    @property
    def zone(self):
        """The zone this unit is in."""
        if self.stored.zone is None:
            req = Request(self._zone_url, headers=self._metadata_headers)
            with urlopen(req) as fd:
                zone = fd.read(READ_BLOCK_SIZE).decode("utf8").strip()
                zone = zone.split("/")[-1]
            self.stored.zone = zone
        return self.stored.zone

    @property
    def is_ready(self):
        """Whether the request for this instance has been completed."""
        try:
            self._data
        except ValidationError as ve:
            log.error(f"{self.endpoint} relation data not yet valid. ({ve}")
            return False
        if self._data is None:
            log.error(f"{self.endpoint} relation data not yet available.")
            return False
        last_completed = self._data.completed.get(self.instance)
        last_requested = self.relation.data[self.model.unit].get("requested")
        log.info(f"{self.endpoint} completion {last_completed}?={last_requested}.")
        return last_requested and last_completed == last_requested

    def _request(self, keyvals):
        alphabet = string.ascii_letters + string.digits
        nonce = "".join(random.choice(alphabet) for _ in range(8))
        to_publish = self.relation.data[self.model.unit]
        to_publish.update({k: json.dumps(v) for k, v in keyvals.items()})
        to_publish["requested"] = nonce

    @property
    def credentials(self) -> Optional[bytes]:
        """Return credentials from integrator charm."""
        if not self.is_ready:
            return None
        return base64.b64encode(self._data.credentials.get_secret_value().encode())

    def enable_block_storage_management(self):
        """Request the ability to manage block storage."""
        self._request({"enable-block-storage-management": True})
