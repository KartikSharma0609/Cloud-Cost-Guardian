from dataclasses import dataclass, field


@dataclass(frozen=True)
class Finding:
    """One piece of wasted (or suspicious) infrastructure."""

    resource_type: str
    resource_id: str
    region: str
    reason: str
    estimated_monthly_cost_usd: float
    details: dict = field(default_factory=dict)
