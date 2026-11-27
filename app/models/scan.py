from ipaddress import IPv4Address
from pydantic import BaseModel, Field, field_validator


class ScanRequest(BaseModel):
    network: str = Field(
        ...,
        description="IPv4 network in CIDR format",
        examples=["127.0.0.1/32"]
    )

    interface_ip: str | None = Field(
        default=None,
        examples=[None]
    )

    resolve_dns: bool = False

    workers: int = Field(
        default=8,
        ge=1,
        le=16
    )

    allow_large_scan: bool = False

    @field_validator("interface_ip")
    @classmethod
    def validate_interface_ip(cls, value):
        if value is None:
            return None

        return str(IPv4Address(value))
