import boto3
from moto import mock_aws

from guardian.pricing import PriceProvider
from guardian.registry import SCANNERS, ScannerSpec
from guardian.runner import scan_all

REGION = "ap-south-1"


@mock_aws
def test_scan_all_runs_every_registered_scanner():
    session = boto3.Session(region_name=REGION)
    ec2 = session.client("ec2")
    ec2.create_volume(AvailabilityZone="ap-south-1a", Size=1)
    ec2.allocate_address(Domain="vpc")

    result = scan_all(session, REGION, prices=PriceProvider())

    assert {f.resource_type for f in result.findings} == {"ebs_volume", "elastic_ip"}
    assert result.errors == {}


def test_one_failing_scanner_does_not_stop_the_others(monkeypatch):
    def broken(client, region, prices):
        raise RuntimeError("boom")

    monkeypatch.setitem(SCANNERS, "broken", ScannerSpec("broken", "ec2", broken))

    with mock_aws():
        session = boto3.Session(region_name=REGION)
        session.client("ec2").allocate_address(Domain="vpc")
        result = scan_all(session, REGION, prices=PriceProvider())

    assert "broken" in result.errors
    assert any(f.resource_type == "elastic_ip" for f in result.findings)


def test_extra_services_are_passed_as_keyword_clients(monkeypatch):
    seen = {}

    def needs_cloudwatch(client, region, prices, *, cloudwatch):
        seen["cloudwatch_client"] = hasattr(cloudwatch, "get_metric_statistics")
        return []

    spec = ScannerSpec(
        "needs_cw", "ec2", needs_cloudwatch, extra_services=("cloudwatch",)
    )
    monkeypatch.setitem(SCANNERS, "needs_cw", spec)

    with mock_aws():
        session = boto3.Session(region_name=REGION)
        result = scan_all(session, REGION, prices=PriceProvider())

    assert seen == {"cloudwatch_client": True}
    assert "needs_cw" not in result.errors


def test_the_ec2_scanner_is_registered_with_its_cloudwatch_dependency():
    import guardian.scanners  # noqa: F401

    spec = SCANNERS["ec2_idle"]

    assert spec.extra_services == ("cloudwatch",)
    assert spec.billing_services == ("Amazon Elastic Compute Cloud - Compute",)
