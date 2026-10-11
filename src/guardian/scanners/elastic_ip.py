from guardian.models import Finding
from guardian.registry import register

HOURS_PER_MONTH = 730


@register("elastic_ip", service="ec2")
def scan_unassociated_addresses(ec2_client, region: str, prices) -> list[Finding]:
    """Return Elastic IPs that are not associated with anything."""
    findings = []
    price = prices.public_ipv4_hour(region)

    for address in ec2_client.describe_addresses()["Addresses"]:
        if "AssociationId" in address:
            continue  # in use

        findings.append(
            Finding(
                resource_type="elastic_ip",
                resource_id=address.get("AllocationId", address["PublicIp"]),
                region=region,
                reason="Elastic IP is not associated with any resource",
                estimated_monthly_cost_usd=round(price.usd * HOURS_PER_MONTH, 2),
                price_source=price.source,
                details={"public_ip": address["PublicIp"]},
            )
        )
    return findings
