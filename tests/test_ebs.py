import boto3
from moto import mock_aws

from guardian.scanners.ebs import scan_unattached_volumes

REGION = "ap-south-1"


@mock_aws
def test_no_volumes_returns_empty_list():
    ec2 = boto3.client("ec2", region_name=REGION)

    assert scan_unattached_volumes(ec2, REGION) == []


@mock_aws
def test_finds_unattached_volume():
    ec2 = boto3.client("ec2", region_name=REGION)
    volume = ec2.create_volume(
        AvailabilityZone="ap-south-1a", Size=10, VolumeType="gp3"
    )

    findings = scan_unattached_volumes(ec2, REGION)

    assert len(findings) == 1
    assert findings[0].resource_id == volume["VolumeId"]
    assert findings[0].resource_type == "ebs_volume"
    assert findings[0].details["size_gb"] == 10
    assert findings[0].estimated_monthly_cost_usd == 0.91


@mock_aws
def test_ignores_attached_volume():
    ec2 = boto3.client("ec2", region_name=REGION)
    image_id = ec2.describe_images()["Images"][0]["ImageId"]
    instance = ec2.run_instances(ImageId=image_id, MinCount=1, MaxCount=1)["Instances"][
        0
    ]
    volume = ec2.create_volume(
        AvailabilityZone=instance["Placement"]["AvailabilityZone"], Size=5
    )
    ec2.attach_volume(
        VolumeId=volume["VolumeId"],
        InstanceId=instance["InstanceId"],
        Device="/dev/sdh",
    )

    assert scan_unattached_volumes(ec2, REGION) == []
