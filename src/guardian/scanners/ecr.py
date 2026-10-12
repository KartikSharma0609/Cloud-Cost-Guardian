from botocore.exceptions import ClientError

from guardian.models import Finding
from guardian.registry import register

# Newest images we assume are worth keeping (current deploy plus rollbacks).
KEEP_LATEST = 10
BYTES_PER_GB = 1024**3


def _has_lifecycle_policy(ecr_client, repository_name: str) -> bool:
    try:
        ecr_client.get_lifecycle_policy(repositoryName=repository_name)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "LifecyclePolicyNotFoundException":
            return False
        raise  # e.g. AccessDenied: we must not mistake "can't tell" for "no policy"


@register(
    "ecr_lifecycle",
    service="ecr",
    billing_services=("Amazon EC2 Container Registry (ECR)",),
)
def scan_repositories_without_lifecycle(
    ecr_client, region: str, prices
) -> list[Finding]:
    """Return ECR repositories with no lifecycle policy and old images piling up."""
    findings = []
    price = prices.ecr_gb_month(region)

    for page in ecr_client.get_paginator("describe_repositories").paginate():
        for repository in page["repositories"]:
            name = repository["repositoryName"]
            if _has_lifecycle_policy(ecr_client, name):
                continue

            images = []
            for image_page in ecr_client.get_paginator("describe_images").paginate(
                repositoryName=name
            ):
                images.extend(image_page["imageDetails"])

            images.sort(key=lambda image: image["imagePushedAt"], reverse=True)
            older = images[KEEP_LATEST:]
            if not older:
                continue  # nothing beyond what we'd keep anyway

            reclaimable_gb = sum(i["imageSizeInBytes"] for i in older) / BYTES_PER_GB
            findings.append(
                Finding(
                    resource_type="ecr_repository",
                    resource_id=name,
                    region=region,
                    reason=(
                        f"No lifecycle policy; {len(older)} images are older than "
                        f"the newest {KEEP_LATEST}"
                    ),
                    estimated_monthly_cost_usd=round(reclaimable_gb * price.usd, 2),
                    price_source=price.source,
                    details={
                        "image_count": len(images),
                        "keep_latest": KEEP_LATEST,
                        "reclaimable_gb": round(reclaimable_gb, 3),
                        # Images share layers, so real savings are lower than this.
                        "estimate_is_upper_bound": True,
                    },
                )
            )
    return findings
