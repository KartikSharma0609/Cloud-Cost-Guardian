from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ScannerSpec:
    name: str  # e.g. "ebs_volume"
    service: str  # boto3 client to create, e.g. "ec2"
    func: Callable  # func(client, region) -> list[Finding]


SCANNERS: dict[str, ScannerSpec] = {}


def register(name: str, service: str):
    """Decorator: add a scanner function to the registry."""

    def decorator(func):
        if name in SCANNERS:
            raise ValueError(f"Scanner '{name}' is already registered")
        SCANNERS[name] = ScannerSpec(name, service, func)
        return func  # unchanged, so tests can still call it directly

    return decorator
