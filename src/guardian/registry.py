from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ScannerSpec:
    name: str  # e.g. "ebs_volume"
    service: str  # boto3 client to create, e.g. "ec2"
    func: Callable  # func(client, region, prices) -> list[Finding]
    billing_services: tuple[str, ...] = ()  # Cost Explorer service names it checks


SCANNERS: dict[str, ScannerSpec] = {}


def register(name: str, service: str, billing_services: tuple[str, ...] = ()):
    """Decorator: add a scanner function to the registry."""

    def decorator(func):
        if name in SCANNERS:
            raise ValueError(f"Scanner '{name}' is already registered")
        SCANNERS[name] = ScannerSpec(name, service, func, billing_services)
        return func  # unchanged, so tests can still call it directly

    return decorator
