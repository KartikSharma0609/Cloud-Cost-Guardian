from dataclasses import dataclass, field

import guardian.scanners  # noqa: F401  (importing registers every scanner)
from guardian.models import Finding
from guardian.pricing import PriceProvider
from guardian.registry import SCANNERS


@dataclass
class ScanResult:
    findings: list[Finding] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


def scan_all(session, region: str, prices=None) -> ScanResult:
    """Run every registered scanner. One failing scanner never hides the others."""
    if prices is None:
        # The Pricing API is only served from a few regions; any can quote any region.
        prices = PriceProvider(session.client("pricing", region_name="us-east-1"))

    result = ScanResult()

    for name, spec in list(SCANNERS.items()):
        try:
            client = session.client(spec.service, region_name=region)
            result.findings.extend(spec.func(client, region, prices))
        except Exception as exc:  # report it, keep scanning
            result.errors[name] = f"{type(exc).__name__}: {exc}"

    return result
