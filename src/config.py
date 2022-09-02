# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""Config Management for the gcp cloud provider charm."""

import base64
import binascii
import json
import logging
import subprocess
from typing import Optional

import yaml
from pydantic import BaseModel, Field, SecretStr, ValidationError, validator

log = logging.getLogger(__name__)


class Credentials(BaseModel):
    """Represents an cloud-sa secret json."""

    cloud_sa: SecretStr = Field(min_length=1)

    @validator("cloud_sa")
    def must_be_base64(self, s: SecretStr):
        """Validate cloud-sa is base64 encoded json."""
        secret_val = s.get_secret_value()
        try:
            d = base64.b64decode(secret_val.encode())
        except binascii.Error:
            raise ValueError("not valid base64")
        if base64.b64encode(d) != secret_val.encode():
            raise ValueError("base64 inconsistency")
        try:
            json.loads(d)
        except json.JSONDecodeError:
            raise ValueError("Couldn't find json data")

        return s


class CredentialsError(Exception):
    """Raised for any issue gathering credentials."""

    pass


class CharmConfig:
    """Representation of the charm configuration."""

    def __init__(self, charm):
        """Creates a CharmConfig object from the configuration data."""
        self.config = charm.config

    @property
    def credentials(self) -> Credentials:
        """Get the credentials from either the config or the hook tool.

        Prefers the config so that it can be overridden.
        """
        try:
            result = subprocess.run(
                ["credential-get"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            creds = yaml.safe_load(result.stdout.decode("utf8"))
            encode = base64.b64encode(creds["credential"]["attributes"]["file"].encode())
            return Credentials(cloud_sa=encode)
        except ValidationError as e:
            no_creds_msg = "trust credentials invalid."
            raise CredentialsError(no_creds_msg) from e
        except FileNotFoundError:
            # juju trust not available
            no_creds_msg = "missing credentials; set via config"
        except subprocess.CalledProcessError as e:
            if "permission denied" not in e.stderr.decode("utf8"):
                raise
            no_creds_msg = "missing credentials access; grant with: juju trust"

        # try cloud-sa base64 value
        try:
            return Credentials(cloud_sa=self.config["cloud-sa"])
        except ValidationError as e:
            raise CredentialsError(no_creds_msg) from e

    @property
    def available_data(self):
        """Parse valid charm config into a dict, drop keys if unset."""
        data = {}
        for key, value in self.config.items():
            if key in "cloud-sa":
                continue
            data[key] = value

        for key, value in dict(**data).items():
            if value == "" or value is None:
                del data[key]

        return data

    def evaluate(self) -> Optional[str]:
        """Determine if configuration is valid."""
        try:
            self.credentials
        except CredentialsError as e:
            return str(e)
        return None
