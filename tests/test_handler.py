import json

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from guardian.handler import lambda_handler
from guardian.pricing import PriceProvider
from guardian.registry import SCANNERS, ScannerSpec
from tests.helpers import FakeCostExplorer, make_ce_page

REGION = "ap-south-1"


def _topic_with_inbox():
    """A fake SNS topic wired to an SQS queue, so tests can read what was sent."""
    sns = boto3.client("sns", region_name=REGION)
    sqs = boto3.client("sqs", region_name=REGION)
    topic_arn = sns.create_topic(Name="guardian")["TopicArn"]
    queue_url = sqs.create_queue(QueueName="inbox")["QueueUrl"]
    queue_arn = sqs.get_queue_attributes(
        QueueUrl=queue_url, AttributeNames=["QueueArn"]
    )["Attributes"]["QueueArn"]
    sns.subscribe(TopicArn=topic_arn, Protocol="sqs", Endpoint=queue_arn)
    return topic_arn, queue_url, sqs


def _inbox(sqs, queue_url):
    messages = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10).get(
        "Messages", []
    )
    return [json.loads(m["Body"]) for m in messages]


def _run(**kwargs):
    return lambda_handler(
        {},
        None,
        session=boto3.Session(region_name=REGION),
        prices=PriceProvider(),
        **kwargs,
    )


@mock_aws
def test_publishes_a_report_when_there_are_findings(monkeypatch):
    topic_arn, queue_url, sqs = _topic_with_inbox()
    monkeypatch.setenv("SNS_TOPIC_ARN", topic_arn)
    ec2 = boto3.client("ec2", region_name=REGION)
    ec2.create_volume(AvailabilityZone="ap-south-1a", Size=10, VolumeType="gp3")

    summary = _run()

    assert summary == {"findings": 1, "errors": 0, "notified": True}
    [message] = _inbox(sqs, queue_url)
    assert message["Subject"] == "Cost Guardian: 1 finding(s), ~$0.91/month"
    assert "[ebs_volume]" in message["Message"]


@mock_aws
def test_sends_all_clear_by_default(monkeypatch):
    topic_arn, queue_url, sqs = _topic_with_inbox()
    monkeypatch.setenv("SNS_TOPIC_ARN", topic_arn)

    summary = _run()

    assert summary["notified"] is True
    [message] = _inbox(sqs, queue_url)
    assert message["Subject"] == "Cost Guardian: all clear"


@mock_aws
def test_stays_quiet_when_clean_and_notify_when_clean_is_off(monkeypatch):
    topic_arn, queue_url, sqs = _topic_with_inbox()
    monkeypatch.setenv("SNS_TOPIC_ARN", topic_arn)
    monkeypatch.setenv("NOTIFY_WHEN_CLEAN", "false")

    summary = _run()

    assert summary["notified"] is False
    assert _inbox(sqs, queue_url) == []


@mock_aws
def test_works_without_a_topic_and_only_logs(monkeypatch):
    monkeypatch.delenv("SNS_TOPIC_ARN", raising=False)

    assert _run() == {"findings": 0, "errors": 0, "notified": False}


@mock_aws
def test_scans_every_configured_region(monkeypatch):
    monkeypatch.setenv("REGIONS", "ap-south-1, us-east-1")
    for region in ("ap-south-1", "us-east-1"):
        boto3.client("ec2", region_name=region).allocate_address(Domain="vpc")

    summary = _run()

    assert summary["findings"] == 2


@mock_aws
def test_a_failing_scanner_is_reported_not_hidden(monkeypatch):
    def broken(client, region, prices):
        raise RuntimeError("boom")

    monkeypatch.setitem(SCANNERS, "broken", ScannerSpec("broken", "ec2", broken))
    topic_arn, queue_url, sqs = _topic_with_inbox()
    monkeypatch.setenv("SNS_TOPIC_ARN", topic_arn)

    summary = _run()

    assert summary["errors"] == 1
    [message] = _inbox(sqs, queue_url)
    assert message["Subject"] == "Cost Guardian: scan finished with errors"
    assert "ap-south-1/broken: RuntimeError: boom" in message["Message"]


class SessionWithCostExplorer:
    """Real (mock) AWS for everything except Cost Explorer."""

    def __init__(self, ce):
        self._real = boto3.Session(region_name=REGION)
        self._ce = ce

    def client(self, service, **kwargs):
        if service == "ce":
            return self._ce
        return self._real.client(service, **kwargs)


class BrokenCostExplorer:
    def get_cost_and_usage(self, **kwargs):
        raise ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "no ce"}},
            "GetCostAndUsage",
        )


@mock_aws
def test_spend_section_is_included_when_enabled(monkeypatch):
    topic_arn, queue_url, sqs = _topic_with_inbox()
    monkeypatch.setenv("SNS_TOPIC_ARN", topic_arn)
    monkeypatch.setenv("INCLUDE_SPEND", "true")
    ce = FakeCostExplorer([make_ce_page({"Amazon Virtual Private Cloud": "3.59"})])

    lambda_handler(
        {}, None, session=SessionWithCostExplorer(ce), prices=PriceProvider()
    )

    [message] = _inbox(sqs, queue_url)
    assert "checks: elastic_ip" in message["Message"]


@mock_aws
def test_cost_explorer_failure_does_not_stop_the_report(monkeypatch):
    topic_arn, queue_url, sqs = _topic_with_inbox()
    monkeypatch.setenv("SNS_TOPIC_ARN", topic_arn)
    monkeypatch.setenv("INCLUDE_SPEND", "true")

    lambda_handler(
        {},
        None,
        session=SessionWithCostExplorer(BrokenCostExplorer()),
        prices=PriceProvider(),
    )

    [message] = _inbox(sqs, queue_url)
    assert "Could not read spend from Cost Explorer" in message["Message"]


@mock_aws
def test_a_failed_publish_fails_the_invocation(monkeypatch):
    monkeypatch.setenv(
        "SNS_TOPIC_ARN", "arn:aws:sns:ap-south-1:123456789012:does-not-exist"
    )

    with pytest.raises(ClientError):
        _run()
