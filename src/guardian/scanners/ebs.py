from guardian.models import Finding

# Approximate gp3 price in ap-south-1. We'll make this configurable later.
USD_PER_GB_MONTH = 0.0912


def scan_unattached_volumes(ec2_client, region: str) -> list[Finding]:
    """Return EBS volumes that are not attached to any instance."""
    findings = []
    paginator = ec2_client.get_paginator("describe_volumes")

    for page in paginator.paginate(
        Filters=[{"Name": "status", "Values": ["available"]}]
    ):
        for volume in page["Volumes"]:
            size_gb = volume["Size"]
            findings.append(
                Finding(
                    resource_type="ebs_volume",
                    resource_id=volume["VolumeId"],
                    region=region,
                    reason="Volume is not attached to any instance",
                    estimated_monthly_cost_usd=round(size_gb * USD_PER_GB_MONTH, 2),
                    details={
                        "size_gb": size_gb,
                        "created": volume["CreateTime"].isoformat(),
                    },
                )
            )
    return findings
