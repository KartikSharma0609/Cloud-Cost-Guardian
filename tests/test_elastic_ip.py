import boto3
from moto import mock_aws

from guardian.pricing import PriceProvider
from guardian.scanners.elastic_ip import scan_unassociated_addresses

REGION = "ap-south-1"


@mock_aws
def test_no_addresses_returns_empty_list():
    ec2 = boto3.client("ec2", region_name=REGION)

    assert scan_unassociated_addresses(ec2, REGION, PriceProvider()) == []


@mock_aws
def test_finds_unassociated_address():
    ec2 = boto3.client("ec2", region_name=REGION)
    address = ec2.allocate_address(Domain="vpc")

    findings = scan_unassociated_addresses(ec2, REGION, PriceProvider())

    assert len(findings) == 1
    assert findings[0].resource_id == address["AllocationId"]
    assert findings[0].details["public_ip"] == address["PublicIp"]
    assert findings[0].estimated_monthly_cost_usd == 3.65
    assert findings[0].price_source == "estimated"
    assert findings[0].kind == "waste"


@mock_aws
def test_ignores_associated_address():
    ec2 = boto3.client("ec2", region_name=REGION)
    image_id = ec2.describe_images()["Images"][0]["ImageId"]
    instance = ec2.run_instances(ImageId=image_id, MinCount=1, MaxCount=1)["Instances"][
        0
    ]
    address = ec2.allocate_address(Domain="vpc")
    ec2.associate_address(
        AllocationId=address["AllocationId"], InstanceId=instance["InstanceId"]
    )

    assert scan_unassociated_addresses(ec2, REGION, PriceProvider()) == []
