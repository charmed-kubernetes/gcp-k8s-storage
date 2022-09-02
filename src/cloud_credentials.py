import base64
import binascii
import json

from pydantic import BaseModel, Field, SecretStr, validator


class Credentials(BaseModel):
    """Represents an cloud-sa secret json."""

    cloud_sa: SecretStr = Field(min_length=1)

    @validator("cloud_sa")
    def must_be_base64(cls, s: SecretStr):
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
