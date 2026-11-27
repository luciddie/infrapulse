from typing import Literal
from urllib.parse import urlsplit
from ipaddress import IPv4Address

from pydantic import BaseModel, Field, model_validator


class ServiceCreate(BaseModel):

    device_id: int = Field(gt=0)

    name: str = Field(
        min_length=1,
        max_length=100
    )

    protocol: Literal["tcp", "http"]

    port: int | None = Field(
        default=None,
        ge=1,
        le=65535
    )

    url: str | None = Field(
        default=None,
        max_length=2048
    )

    expected_status: int = Field(
        default=200,
        ge=100,
        le=599
    )

    timeout_seconds: float = Field(
        default=3.0,
        gt=0,
        le=10
    )

    @model_validator(mode="after")
    def validate_target(self):

        if self.protocol == "tcp":

            if self.port is None or self.url is not None:
                raise ValueError(
                    "TCP requires port and no URL"
                )

        elif self.protocol == "http":

            if self.url is None or self.port is not None:
                raise ValueError(
                    "HTTP requires URL and no port"
                )

            parsed = urlsplit(self.url)

            if parsed.scheme not in ("http", "https"):
                raise ValueError("Invalid URL scheme")

            if parsed.username or parsed.password:
                raise ValueError(
                    "URL credentials are not allowed"
                )

            if not parsed.hostname:
                raise ValueError("Invalid hostname")

            IPv4Address(parsed.hostname)

            if parsed.port is not None:
                if not 1 <= parsed.port <= 65535:
                    raise ValueError("Invalid URL port")

        return self
