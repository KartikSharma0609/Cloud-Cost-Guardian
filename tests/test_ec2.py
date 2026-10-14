from datetime import UTC, datetime, timedelta

import boto3
import pytest
from moto import mock_aws

from guardian.pricing import PriceProvider
from guardian.scanners.ec2 import _hourly_price, scan_idle_instances
from tests.helpers import FakeCloudWatch, FakePricing, make_cpu_points, make_product

REGION = "ap-south-1"
NOW = datetime(2026, 10, 12, tzinfo=UTC)


def _launch(ec2, tags=None, instance_type="t3.micro"):
    image_id = ec2.describe_images()["Images"][0]["ImageId"]
    extra = {}
    if tags:
        extra["TagSpecifications"] = [
            {
                "ResourceType": "instance",
                "Tags": [{"Key": k, "Value": v} for k, v in tags.items()],
            }
        ]
    response = ec2.run_instances(
        ImageId=image_id, InstanceType=instance_type, MinCount=1, MaxCount=1, **extra
    )
    return response["Instances"][0]["InstanceId"]


def _prices():
    return PriceProvider(FakePricing([make_product("0.0112000000", unit="Hrs")]))


def _scan(ec2, cloudwatch, prices=None):
    return scan_idle_instances(
        ec2, REGION, prices or _prices(), cloudwatch=cloudwatch, now=NOW
    )


@mock_aws
def test_no_instances_returns_empty_list():
    ec2 = boto3.client("ec2", region_name=REGION)

    assert _scan(ec2, FakeCloudWatch()) == []


@mock_aws
def test_flags_an_idle_instance_for_review_not_as_waste():
    ec2 = boto3.client("ec2", region_name=REGION)
    instance_id = _launch(ec2)
    cloudwatch = FakeCloudWatch(make_cpu_points([2.0] * 14))

    findings = _scan(ec2, cloudwatch)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.resource_id == instance_id
    assert finding.resource_type == "ec2_instance"
    assert finding.kind == "review"
    assert finding.estimated_monthly_cost_usd == 8.18  # 0.0112 * 730
    assert finding.price_source == "live"
    assert "14 of 14 days" in finding.reason
    assert finding.details["instance_type"] == "t3.micro"
    assert finding.details["silence_with_tag"] == "guardian:ignore=true"
    assert "cpu_only" in finding.details["checked"]


@mock_aws
def test_the_real_task_manager_instance_data_is_flagged_for_review():
    # Exact 14 days from the probe on the real instance: one busy day (11.5%).
    maxima = [11.5, 2.4, 2.3, 2.8, 2.3, 2.3, 2.3, 2.2, 3.3, 2.3, 2.8, 2.4, 2.6, 2.2]
    averages = [1.1] + [1.0] * 13
    ec2 = boto3.client("ec2", region_name=REGION)
    _launch(ec2)

    findings = _scan(ec2, FakeCloudWatch(make_cpu_points(maxima, averages)))

    assert len(findings) == 1
    assert "13 of 14 days (peak 11.5%, average 1.0%)" in findings[0].reason


@mock_aws
def test_busy_instance_is_not_flagged():
    ec2 = boto3.client("ec2", region_name=REGION)
    _launch(ec2)

    assert _scan(ec2, FakeCloudWatch(make_cpu_points([60.0] * 14))) == []


@pytest.mark.parametrize(
    ("idle_days", "flagged"),
    [(11, False), (12, True)],  # 11/14 = 0.79 is below 0.8; 12/14 = 0.86 is above
)
@mock_aws
def test_idle_day_ratio_boundary(idle_days, flagged):
    ec2 = boto3.client("ec2", region_name=REGION)
    _launch(ec2)
    maxima = [2.0] * idle_days + [50.0] * (14 - idle_days)

    findings = _scan(ec2, FakeCloudWatch(make_cpu_points(maxima)))

    assert bool(findings) is flagged


@mock_aws
def test_too_little_data_is_not_judged():
    ec2 = boto3.client("ec2", region_name=REGION)
    _launch(ec2)

    assert _scan(ec2, FakeCloudWatch(make_cpu_points([1.0] * 6))) == []


@mock_aws
def test_ignore_tag_silences_an_instance_without_even_querying_it():
    ec2 = boto3.client("ec2", region_name=REGION)
    _launch(ec2, tags={"guardian:ignore": "true"})
    cloudwatch = FakeCloudWatch(make_cpu_points([2.0] * 14))

    assert _scan(ec2, cloudwatch) == []
    assert cloudwatch.requests == []


@mock_aws
def test_ignore_tag_must_actually_say_true():
    ec2 = boto3.client("ec2", region_name=REGION)
    _launch(ec2, tags={"guardian:ignore": "false"})

    assert len(_scan(ec2, FakeCloudWatch(make_cpu_points([2.0] * 14)))) == 1


@mock_aws
def test_stopped_instances_are_not_checked():
    ec2 = boto3.client("ec2", region_name=REGION)
    instance_id = _launch(ec2)
    ec2.stop_instances(InstanceIds=[instance_id])
    cloudwatch = FakeCloudWatch(make_cpu_points([2.0] * 14))

    assert _scan(ec2, cloudwatch) == []
    assert cloudwatch.requests == []


@mock_aws
def test_unknown_price_is_reported_honestly_not_guessed():
    ec2 = boto3.client("ec2", region_name=REGION)
    _launch(ec2)

    findings = _scan(
        ec2, FakeCloudWatch(make_cpu_points([2.0] * 14)), prices=PriceProvider()
    )

    assert findings[0].price_source == "unknown"
    assert findings[0].estimated_monthly_cost_usd == 0.0


@mock_aws
def test_asks_cloudwatch_for_14_days_of_daily_cpu():
    ec2 = boto3.client("ec2", region_name=REGION)
    instance_id = _launch(ec2)
    cloudwatch = FakeCloudWatch(make_cpu_points([2.0] * 14))

    _scan(ec2, cloudwatch)

    [request] = cloudwatch.requests
    assert request["Namespace"] == "AWS/EC2"
    assert request["MetricName"] == "CPUUtilization"
    assert request["Dimensions"] == [{"Name": "InstanceId", "Value": instance_id}]
    assert request["Period"] == 86400
    assert request["StartTime"] == NOW - timedelta(days=14)
    assert request["EndTime"] == NOW


def test_only_shared_tenancy_linux_gets_a_price():
    prices = _prices()
    linux = {"InstanceType": "t3.micro", "PlatformDetails": "Linux/UNIX"}
    windows = {"InstanceType": "t3.micro", "PlatformDetails": "Windows"}
    dedicated = {
        "InstanceType": "t3.micro",
        "PlatformDetails": "Linux/UNIX",
        "Placement": {"Tenancy": "dedicated"},
    }

    assert _hourly_price(linux, prices, REGION).usd == 0.0112
    assert _hourly_price(windows, prices, REGION) is None
    assert _hourly_price(dedicated, prices, REGION) is None
