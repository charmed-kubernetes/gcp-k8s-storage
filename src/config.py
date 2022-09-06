# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""Config Management for the gcp k8s storage charm."""

import logging
from typing import Optional

log = logging.getLogger(__name__)


class CharmConfig:
    """Representation of the charm configuration."""

    def __init__(self, charm):
        """Creates a CharmConfig object from the configuration data."""
        self.config = charm.config

    @property
    def available_data(self):
        """Parse valid charm config into a dict, drop keys if unset."""
        data = {}
        for key, value in self.config.items():
            data[key] = value

        for key, value in dict(**data).items():
            if value == "" or value is None:
                del data[key]

        return data

    def evaluate(self) -> Optional[str]:
        """Determine if configuration is valid."""
        return None
