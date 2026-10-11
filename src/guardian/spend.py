from dataclasses import dataclass
from datetime import date, timedelta

import guardian.scanners  # noqa: F401  (importing registers every scanner)
from guardian.registry import SCANNERS


@dataclass(frozen=True)
class ServiceSpend:
    service: str
    usd: float
    scanners: tuple[str, ...]  # empty tuple = no scanner covers this service yet


def fetch_spend_by_service(ce_client, today: date | None = None, days: int = 30):
    """Gross usage per billed service. Credits, refunds and tax are excluded.

    Many learner accounts run on credits, so net cost is ~0 and would hide all
    spending. Filtering to RECORD_TYPE=Usage shows what the resources really cost.
    """
    today = today or date.today()
    request = {
        "TimePeriod": {
            "Start": (today - timedelta(days=days)).isoformat(),
            "End": today.isoformat(),  # End is exclusive
        },
        "Granularity": "MONTHLY",
        "Metrics": ["UnblendedCost"],
        "Filter": {"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Usage"]}},
        "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
    }

    totals: dict[str, float] = {}
    while True:
        response = ce_client.get_cost_and_usage(**request)
        for period in response["ResultsByTime"]:
            for group in period["Groups"]:
                service = group["Keys"][0]
                amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
                totals[service] = totals.get(service, 0.0) + amount

        token = response.get("NextPageToken")
        if not token:
            return totals
        request["NextPageToken"] = token


def build_spend_report(spend: dict[str, float], min_usd: float = 0.01):
    """Biggest spend first, each row showing which scanners cover that service."""
    rows = []
    for service, usd in spend.items():
        if usd < min_usd:
            continue  # skip noise like $0.00003 of Secrets Manager
        scanners = tuple(
            sorted(
                name
                for name, spec in SCANNERS.items()
                if service in spec.billing_services
            )
        )
        rows.append(ServiceSpend(service, round(usd, 2), scanners))
    return sorted(rows, key=lambda row: row.usd, reverse=True)
