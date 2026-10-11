from datetime import date

from guardian.spend import build_spend_report, fetch_spend_by_service
from tests.helpers import FakeCostExplorer, make_ce_page

TODAY = date(2026, 10, 11)


def test_sums_a_service_across_periods():
    page = make_ce_page({"EC2 - Other": "1.0"})
    page["ResultsByTime"] += make_ce_page({"EC2 - Other": "2.0"})["ResultsByTime"]

    spend = fetch_spend_by_service(FakeCostExplorer([page]), today=TODAY)

    assert spend == {"EC2 - Other": 3.0}


def test_follows_pagination():
    fake = FakeCostExplorer(
        [
            make_ce_page({"A": "1.0"}, next_token="page-2"),
            make_ce_page({"B": "2.0"}),
        ]
    )

    spend = fetch_spend_by_service(fake, today=TODAY)

    assert spend == {"A": 1.0, "B": 2.0}
    assert "NextPageToken" not in fake.requests[0]
    assert fake.requests[1]["NextPageToken"] == "page-2"


def test_request_excludes_credits_and_covers_last_30_days():
    fake = FakeCostExplorer([make_ce_page({})])

    fetch_spend_by_service(fake, today=TODAY)

    request = fake.requests[0]
    assert request["Filter"] == {
        "Dimensions": {"Key": "RECORD_TYPE", "Values": ["Usage"]}
    }
    assert request["TimePeriod"] == {"Start": "2026-09-11", "End": "2026-10-11"}


def test_report_marks_services_with_and_without_scanners():
    spend = {
        "EC2 - Other": 0.73,
        "Amazon Elastic Compute Cloud - Compute": 6.4,
        "Amazon Virtual Private Cloud": 2.85,
        "AWS Secrets Manager": 0.00003,
    }

    report = build_spend_report(spend)

    assert [row.service for row in report] == [
        "Amazon Elastic Compute Cloud - Compute",
        "Amazon Virtual Private Cloud",
        "EC2 - Other",
    ]
    scanners = {row.service: row.scanners for row in report}
    assert scanners["Amazon Elastic Compute Cloud - Compute"] == ()
    assert scanners["Amazon Virtual Private Cloud"] == ("elastic_ip",)
    assert scanners["EC2 - Other"] == ("ebs_volume",)
