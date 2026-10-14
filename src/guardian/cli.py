import argparse
import json
import sys
from dataclasses import asdict

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from guardian.report import format_spend_section, summarize
from guardian.runner import scan_all
from guardian.spend import build_spend_report, fetch_spend_by_service


def print_spend_report(session) -> None:
    try:
        # Cost Explorer is only served from us-east-1.
        ce = session.client("ce", region_name="us-east-1")
        rows = build_spend_report(fetch_spend_by_service(ce))
    except (BotoCoreError, ClientError) as exc:
        print(f"Could not read spend from Cost Explorer: {exc}", file=sys.stderr)
        return

    print("\n" + format_spend_section(rows), file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(prog="guardian")
    parser.add_argument("region", nargs="?", default="ap-south-1")
    parser.add_argument(
        "--spend",
        action="store_true",
        help="also show usage by service (Cost Explorer, about $0.01 per run)",
    )
    args = parser.parse_args()

    session = boto3.Session(region_name=args.region)
    result = scan_all(session, args.region)

    print(json.dumps([asdict(f) for f in result.findings], indent=2))

    print(f"\n{summarize(result.findings)}", file=sys.stderr)
    for name, error in result.errors.items():
        print(f"Scanner '{name}' failed: {error}", file=sys.stderr)

    if args.spend:
        print_spend_report(session)


if __name__ == "__main__":
    main()
