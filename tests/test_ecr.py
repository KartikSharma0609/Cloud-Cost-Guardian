import json

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from guardian.pricing import PriceProvider
from guardian.scanners.ecr import KEEP_LATEST, scan_repositories_without_lifecycle
from tests.helpers import GB, FakeEcr, make_images

REGION = "ap-south-1"


def test_no_repositories_returns_empty_list():
    assert (
        scan_repositories_without_lifecycle(FakeEcr({}), REGION, PriceProvider()) == []
    )


def test_repository_with_lifecycle_policy_is_ignored():
    ecr = FakeEcr({"app": make_images([GB] * 30)}, policies=["app"])

    assert scan_repositories_without_lifecycle(ecr, REGION, PriceProvider()) == []


def test_repository_with_few_images_is_ignored():
    ecr = FakeEcr({"app": make_images([GB] * KEEP_LATEST)})

    assert scan_repositories_without_lifecycle(ecr, REGION, PriceProvider()) == []


def test_only_images_older_than_the_newest_are_counted():
    # 3 old 1 GB images, then the 10 newest at 5 GB each. Only the old ones count.
    sizes = [GB] * 3 + [5 * GB] * KEEP_LATEST
    ecr = FakeEcr({"app": make_images(sizes)})

    findings = scan_repositories_without_lifecycle(ecr, REGION, PriceProvider())

    assert len(findings) == 1
    finding = findings[0]
    assert finding.resource_type == "ecr_repository"
    assert finding.resource_id == "app"
    assert finding.kind == "review"  # which old images matter is a human call
    assert finding.details["image_count"] == 13
    assert finding.details["reclaimable_gb"] == 3.0
    assert finding.estimated_monthly_cost_usd == 0.3
    assert finding.price_source == "estimated"
    assert finding.details["estimate_is_upper_bound"] is True


def test_unexpected_aws_error_is_not_mistaken_for_missing_policy():
    denied = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "no"}},
        "GetLifecyclePolicy",
    )
    ecr = FakeEcr({"app": make_images([GB] * 30)}, lifecycle_error=denied)

    with pytest.raises(ClientError):
        scan_repositories_without_lifecycle(ecr, REGION, PriceProvider())


def _push(ecr, repository, count):
    for i in range(count):
        manifest = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
            "config": {
                "mediaType": "application/vnd.docker.container.image.v1+json",
                "size": 100,
                "digest": f"sha256:{i:064d}",
            },
            "layers": [
                {
                    "mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip",
                    "size": 1000,
                    "digest": f"sha256:{i + 1000:064d}",
                }
            ],
        }
        ecr.put_image(
            repositoryName=repository,
            imageManifest=json.dumps(manifest),
            imageTag=f"tag{i}",
        )


@mock_aws
def test_against_a_real_client_missing_policy_then_policy_added():
    ecr = boto3.client("ecr", region_name=REGION)
    ecr.create_repository(repositoryName="app")
    _push(ecr, "app", KEEP_LATEST + 2)

    findings = scan_repositories_without_lifecycle(ecr, REGION, PriceProvider())
    assert [f.resource_id for f in findings] == ["app"]
    assert findings[0].details["image_count"] == KEEP_LATEST + 2

    policy = {
        "rules": [
            {
                "rulePriority": 1,
                "description": "keep last 10",
                "selection": {
                    "tagStatus": "any",
                    "countType": "imageCountMoreThan",
                    "countNumber": KEEP_LATEST,
                },
                "action": {"type": "expire"},
            }
        ]
    }
    ecr.put_lifecycle_policy(
        repositoryName="app", lifecyclePolicyText=json.dumps(policy)
    )

    assert scan_repositories_without_lifecycle(ecr, REGION, PriceProvider()) == []
