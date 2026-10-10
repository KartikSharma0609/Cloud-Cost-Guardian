import json
import sys
from dataclasses import asdict

import boto3

from guardian.scanners.ebs import scan_unattached_volumes


def main():
    region = sys.argv[1] if len(sys.argv) > 1 else "ap-south-1"
    ec2 = boto3.client("ec2", region_name=region)
    findings = scan_unattached_volumes(ec2, region)
    print(json.dumps([asdict(f) for f in findings], indent=2))
    total = sum(f.estimated_monthly_cost_usd for f in findings)
    print(f"\n{len(findings)} finding(s), ~${total:.2f}/month wasted", file=sys.stderr)


if __name__ == "__main__":
    main()
