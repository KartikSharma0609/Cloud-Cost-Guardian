from guardian.models import Finding
from guardian.report import SUBJECT_LIMIT, format_report, summarize
from guardian.spend import ServiceSpend


def _finding(cost=0.16, kind="waste", price_source="estimated"):
    return Finding(
        resource_type="ecr_repository",
        resource_id="app",
        region="ap-south-1",
        reason="No lifecycle policy; 19 images are older than the newest 10",
        estimated_monthly_cost_usd=cost,
        price_source=price_source,
        kind=kind,
        details={"image_count": 29},
    )


def test_all_clear_report():
    subject, body = format_report([], {}, ["ap-south-1"])

    assert subject == "Cost Guardian: all clear"
    assert "No wasted resources found" in body
    assert "Guardian changed nothing" in body


def test_report_lists_findings_and_total():
    subject, body = format_report([_finding(0.16), _finding(3.65)], {}, ["ap-south-1"])

    assert subject == "Cost Guardian: 2 finding(s), ~$3.81/month"
    assert "[ecr_repository] app (ap-south-1)" in body
    assert "(estimated price)" in body
    assert "image_count=29" in body
    assert "Worth reviewing" not in body


def test_errors_say_the_area_was_not_checked():
    subject, body = format_report(
        [], {"ap-south-1/ecr_lifecycle": "AccessDenied"}, ["ap-south-1"]
    )

    assert subject == "Cost Guardian: scan finished with errors"
    assert "NOT checked" in body
    assert "ap-south-1/ecr_lifecycle: AccessDenied" in body


def test_spend_section_and_spend_error():
    rows = [ServiceSpend("Amazon Virtual Private Cloud", 3.59, ("elastic_ip",))]

    _, with_spend = format_report([], {}, ["ap-south-1"], spend_rows=rows)
    subject, with_error = format_report([], {}, ["ap-south-1"], spend_error="denied")

    assert "checks: elastic_ip" in with_spend
    assert "Could not read spend from Cost Explorer: denied" in with_error
    assert subject == "Cost Guardian: scan finished with errors"


def test_subject_never_exceeds_sns_limit():
    many = [_finding(1234567.89)] * 5

    subject, _ = format_report(many, {}, ["ap-south-1"])

    assert len(subject) <= SUBJECT_LIMIT


def test_review_items_are_kept_apart_from_certain_waste():
    findings = [_finding(0.91, kind="waste"), _finding(8.18, kind="review")]

    subject, body = format_report(findings, {}, ["ap-south-1"])

    assert subject == "Cost Guardian: 1 finding(s), ~$0.91/month; 1 to review"
    assert "Findings (1, ~$0.91/month):" in body
    assert "Worth reviewing (1, up to ~$8.18/month):" in body
    assert "not necessarily waste" in body


def test_only_review_items_does_not_claim_waste():
    subject, body = format_report([_finding(8.18, kind="review")], {}, ["r"])

    assert subject == "Cost Guardian: 1 item(s) to review"
    assert "No wasted resources found" in body
    assert "Worth reviewing" in body


def test_unknown_price_says_so_instead_of_showing_zero_dollars():
    finding = _finding(0.0, kind="review", price_source="unknown")

    _, body = format_report([finding], {}, ["ap-south-1"])

    assert "cost unknown (no live price available)" in body
    assert "Worth reviewing (1, cost unknown):" in body
    assert "$0.00" not in body
    assert summarize([finding]).endswith("1 to review (cost unknown)")


def test_mixed_known_and_unknown_review_costs_are_both_stated():
    findings = [
        _finding(8.18, kind="review"),
        _finding(0.0, kind="review", price_source="unknown"),
    ]

    _, body = format_report(findings, {}, ["ap-south-1"])

    assert "(2, up to ~$8.18/month, plus 1 of unknown cost):" in body


def test_summary_never_mixes_waste_and_review_totals():
    findings = [_finding(0.91), _finding(8.18, kind="review")]

    assert summarize(findings) == (
        "1 waste finding(s), ~$0.91/month; 1 to review (up to ~$8.18/month)"
    )
    assert summarize([]) == "0 waste finding(s), ~$0.00/month"
