from dataclasses import dataclass, field

# "waste":  provably unused by definition (an orphaned volume, an unattached IP).
# "review": looks suspicious but needs a human's judgment (an idle-looking server).
KIND_WASTE = "waste"
KIND_REVIEW = "review"


@dataclass(frozen=True)
class Finding:
    """One piece of wasted (or suspicious) infrastructure."""

    resource_type: str
    resource_id: str
    region: str
    reason: str
    estimated_monthly_cost_usd: float
    price_source: str = "estimated"  # "live", "estimated", or "unknown"
    kind: str = KIND_WASTE
    details: dict = field(default_factory=dict)
