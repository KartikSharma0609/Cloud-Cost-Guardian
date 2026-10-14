import logging
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from guardian.report import format_report
from guardian.runner import scan_all
from guardian.spend import build_spend_report, fetch_spend_by_service

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _flag(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")


def _regions() -> list[str]:
    default = os.environ.get("AWS_REGION", "ap-south-1")
    raw = os.environ.get("REGIONS", default)
    return [region.strip() for region in raw.split(",") if region.strip()]


def lambda_handler(event, context, session=None, prices=None):
    """Scan, build a report, and publish it. Read-only: nothing is modified.

    Settings come from environment variables:
      REGIONS            comma-separated regions to scan (default: Lambda's own region)
      SNS_TOPIC_ARN      where to send the report (optional; without it, log only)
      INCLUDE_SPEND      "true" to add the Cost Explorer section (about $0.01 per run)
      NOTIFY_WHEN_CLEAN  "true" (default) sends an "all clear" email, so silence
                         never has to mean "maybe it's broken"
    """
    session = session or boto3.Session()
    regions = _regions()

    findings = []
    errors: dict[str, str] = {}
    for region in regions:
        result = scan_all(session, region, prices)
        findings.extend(result.findings)
        for name, error in result.errors.items():
            errors[f"{region}/{name}"] = error

    spend_rows = None
    spend_error = None
    if _flag("INCLUDE_SPEND", "false"):
        try:
            # Cost Explorer is only served from us-east-1.
            ce = session.client("ce", region_name="us-east-1")
            spend_rows = build_spend_report(fetch_spend_by_service(ce))
        except (BotoCoreError, ClientError) as exc:
            spend_error = str(exc)

    subject, body = format_report(findings, errors, regions, spend_rows, spend_error)
    logger.info("%s", subject)

    topic_arn = os.environ.get("SNS_TOPIC_ARN")
    has_news = bool(findings or errors or spend_error)
    notified = False
    if topic_arn and (has_news or _flag("NOTIFY_WHEN_CLEAN", "true")):
        # Not caught on purpose: if publishing fails, the invocation must fail
        # visibly (Lambda error metrics) instead of pretending the report was sent.
        session.client("sns").publish(TopicArn=topic_arn, Subject=subject, Message=body)
        notified = True

    return {"findings": len(findings), "errors": len(errors), "notified": notified}
