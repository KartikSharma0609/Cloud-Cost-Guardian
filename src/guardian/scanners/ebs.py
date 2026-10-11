from guardian.models import Finding
from guardian.registry import register


@register("ebs_volume", service="ec2", billing_services=("EC2 - Other",))
def scan_unattached_volumes(ec2_client, region: str, prices) -> list[Finding]:
    """Return EBS volumes that are not attached to any instance."""
    findings = []
    paginator = ec2_client.get_paginator("describe_volumes")

    for page in paginator.paginate(
        Filters=[{"Name": "status", "Values": ["available"]}]
    ):
        for volume in page["Volumes"]:
            size_gb = volume["Size"]
            volume_type = volume["VolumeType"]
            price = prices.ebs_gb_month(volume_type, region)
            findings.append(
                Finding(
                    resource_type="ebs_volume",
                    resource_id=volume["VolumeId"],
                    region=region,
                    reason="Volume is not attached to any instance",
                    estimated_monthly_cost_usd=round(size_gb * price.usd, 2),
                    price_source=price.source,
                    details={
                        "size_gb": size_gb,
                        "volume_type": volume_type,
                        "created": volume["CreateTime"].isoformat(),
                    },
                )
            )
    return findings
