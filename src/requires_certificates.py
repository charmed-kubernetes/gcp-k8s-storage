# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""Implementation of tls-certificates interface.

This only implements the requires side, currently, since the providers
is still using the Reactive Charm framework self.
"""
import json
import logging
from typing import List, Mapping, Optional

from backports.cached_property import cached_property
from ops.charm import RelationBrokenEvent
from ops.framework import Object
from pydantic import BaseModel, Field, ValidationError

log = logging.getLogger(__name__)


class Certificate(BaseModel):
    """Represent a Certificate."""

    cert_type: str
    common_name: str
    cert: str
    key: str


class Data(BaseModel):
    """Databag from the relation."""

    ca: str = Field(alias="ca")
    client_cert: str = Field(alias="client.cert")
    client_key: str = Field(alias="client.key")


class CertificatesRequires(Object):
    """Requires side of certificates relation."""

    def __init__(self, charm, endpoint="certificates"):
        super().__init__(charm, f"relation-{endpoint}")
        self.endpoint = endpoint
        events = charm.on[endpoint]
        self._unit_name = self.model.unit.name.replace("/", "_")
        self.framework.observe(events.relation_joined, self._joined)

    def _joined(self, event=None):
        event.relation.data[self.model.unit]["unit-name"] = self._unit_name

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
        return True

    @property
    def ca(self):
        """The ca value."""
        if not self.is_ready:
            return None

        return self._data.ca

    @property
    def client_certs(self) -> List[Certificate]:
        """Certificate instances for all available client certs."""
        if not self.is_ready:
            return []

        field = "{}.processed_client_requests".format(self._unit_name)
        certs_data = self._raw_data.get(field, {})
        return [
            Certificate(cert_type="client", common_name=common_name, **cert)
            for common_name, cert in certs_data.items()
        ]

    @property
    def client_certs_map(self) -> Mapping[str, Certificate]:
        """Certificate instances by their `common_name`."""
        return {cert.common_name: cert for cert in self.client_certs}

    def request_client_cert(self, cn, sans):
        """Request Client certificate for charm.

        Request a client certificate and key be generated for the given
        common name (`cn`) and list of alternative names (`sans`).
        This can be called multiple times to request more than one client
        certificate, although the common names must be unique.  If called
        again with the same common name, it will be ignored.
        """
        if not self.relation:
            return
        # assume we'll only be connected to one provider
        data = self.relation.data[self.charm.unit]
        requests = data.get("client_cert_requests", {})
        requests[cn] = {"sans": sans}
        data["client_cert_requests"] = json.dumps(requests)
