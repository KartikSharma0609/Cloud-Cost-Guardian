from datetime import UTC, datetime, timedelta
from statistics import fmean

from guardian.models import KIND_REVIEW, Finding
from guardian.registry import register

LOOKBACK_DAYS = 14
IDLE_MAX_CPU_PERCENT = 10.0  # a day is "idle" if CPU never exceeded this
MIN_DATA_DAYS = 7  # don't judge a new instance (or one with no data) on thin evidence
IDLE_DAY_RATIO = 0.8  # share of days that must be idle to raise a flag
IGNORE_TAG = "guardian:ignore"  # set to "true" to silence an instance you've reviewed
HOURS_PER_MONTH = 730


def _is_ignored(instance) -> bool:
    tags = {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}
    return tags.get(IGNORE_TAG, "").strip().lower() == "true"


def _hourly_price(instance, prices, region):
    """Our price lookup only covers shared-tenancy Linux. Anything else: unknown."""
    platform = instance.get("PlatformDetails", "Linux/UNIX")
    tenancy = instance.get("Placement", {}).get("Tenancy", "default")
    if platform != "Linux/UNIX" or tenancy != "default":
        return None
    return prices.ec2_instance_hour(instance["InstanceType"], region)


@register(
    "ec2_idle",
    service="ec2",
    billing_services=("Amazon Elastic Compute Cloud - Compute",),
    extra_services=("cloudwatch",),
)
def scan_idle_instances(
    ec2_client, region: str, prices, *, cloudwatch, now: datetime | None = None
) -> list[Finding]:
    """Flag running instances whose CPU stayed low. A hint for review, not proof."""
    now = now or datetime.now(UTC)
    findings = []

    paginator = ec2_client.get_paginator("describe_instances")
    for page in paginator.paginate(
        Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
    ):
        for reservation in page["Reservations"]:
            for instance in reservation["Instances"]:
                if _is_ignored(instance):
                    continue

                instance_id = instance["InstanceId"]
                points = cloudwatch.get_metric_statistics(
                    Namespace="AWS/EC2",
                    MetricName="CPUUtilization",
                    Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                    StartTime=now - timedelta(days=LOOKBACK_DAYS),
                    EndTime=now,
                    Period=86400,
                    Statistics=["Maximum", "Average"],
                )["Datapoints"]

                if len(points) < MIN_DATA_DAYS:
                    continue

                idle_days = sum(p["Maximum"] < IDLE_MAX_CPU_PERCENT for p in points)
                if idle_days / len(points) < IDLE_DAY_RATIO:
                    continue

                peak = max(p["Maximum"] for p in points)
                average = fmean(p["Average"] for p in points)
                price = _hourly_price(instance, prices, region)

                findings.append(
                    Finding(
                        resource_type="ec2_instance",
                        resource_id=instance_id,
                        region=region,
                        reason=(
                            f"CPU stayed below {IDLE_MAX_CPU_PERCENT:.0f}% on "
                            f"{idle_days} of {len(points)} days (peak {peak:.1f}%, "
                            f"average {average:.1f}%)"
                        ),
                        # Full instance cost: what you'd save if it isn't needed.
                        estimated_monthly_cost_usd=(
                            round(price.usd * HOURS_PER_MONTH, 2) if price else 0.0
                        ),
                        price_source=price.source if price else "unknown",
                        kind=KIND_REVIEW,
                        details={
                            "instance_type": instance["InstanceType"],
                            "checked": "cpu_only (network and memory not checked)",
                            "silence_with_tag": f"{IGNORE_TAG}=true",
                        },
                    )
                )
    return findings
