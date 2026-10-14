import json
import logging
from dataclasses import dataclass

from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Price:
    usd: float
    # "live" (from the AWS Price List API) or "estimated" (a built-in default)
    source: str


# Fallbacks, used only when the Price List API is unavailable.
# EBS value: gp3 in ap-south-1, verified against the Price List API.
DEFAULTS = {
    "ebs_gb_month": 0.0912,
    "public_ipv4_hour": 0.005,
    # Not yet verified against the Price List API, so it is always labelled "estimated".
    "ecr_gb_month": 0.10,
}

# What a pricing failure looks like: AWS/network errors, or a response shape we
# don't understand. Anything else is a bug and should surface, not be hidden.
PRICING_ERRORS = (BotoCoreError, ClientError, KeyError, TypeError, ValueError)


class PriceProvider:
    """Looks up AWS prices once per run and falls back to defaults on any problem."""

    def __init__(self, pricing_client=None):
        self._client = pricing_client  # None means "use defaults only"
        self._cache: dict[tuple, Price | None] = {}

    def ebs_gb_month(self, volume_type: str, region: str) -> Price:
        key = ("ebs", volume_type, region)
        if key not in self._cache:
            self._cache[key] = self._lookup_ebs(volume_type, region)
        return self._cache[key]

    def ec2_instance_hour(self, instance_type: str, region: str) -> Price | None:
        """Live on-demand price for shared-tenancy Linux, or None.

        There is no safe default for an arbitrary instance type, so we never guess:
        None means "unknown" and the finding says so.
        """
        key = ("ec2", instance_type, region)
        if key not in self._cache:
            self._cache[key] = self._lookup_ec2(instance_type, region)
        return self._cache[key]

    def ecr_gb_month(self, region: str) -> Price:
        # Live lookup comes once we have verified the right filters.
        return Price(DEFAULTS["ecr_gb_month"], "estimated")

    def public_ipv4_hour(self, region: str) -> Price:
        # Live lookup comes once we have verified the right filters.
        return Price(DEFAULTS["public_ipv4_hour"], "estimated")

    def _lookup_ebs(self, volume_type: str, region: str) -> Price:
        if self._client is not None:
            try:
                usd = self._single_price(
                    "AmazonEC2",
                    [
                        ("productFamily", "Storage"),
                        ("volumeApiName", volume_type),
                        ("regionCode", region),
                    ],
                    unit="GB-Mo",
                )
                return Price(usd, "live")
            except PRICING_ERRORS as exc:
                logger.warning("Live EBS price lookup failed (%s); using default", exc)
        return Price(DEFAULTS["ebs_gb_month"], "estimated")

    def _lookup_ec2(self, instance_type: str, region: str) -> Price | None:
        if self._client is None:
            return None
        try:
            usd = self._single_price(
                "AmazonEC2",
                [
                    ("regionCode", region),
                    ("instanceType", instance_type),
                    ("operatingSystem", "Linux"),
                    ("tenancy", "Shared"),
                    ("preInstalledSw", "NA"),
                    ("capacitystatus", "Used"),
                ],
                unit="Hrs",
            )
            return Price(usd, "live")
        except PRICING_ERRORS as exc:
            logger.warning("Live EC2 price lookup failed (%s); cost unknown", exc)
            return None

    def _single_price(self, service_code, filters, unit) -> float:
        response = self._client.get_products(
            ServiceCode=service_code,
            Filters=[
                {"Type": "TERM_MATCH", "Field": field, "Value": value}
                for field, value in filters
            ],
            MaxResults=100,
        )
        products = response["PriceList"]
        if len(products) != 1:
            raise ValueError(f"expected exactly 1 product, got {len(products)}")

        dimensions = [
            dimension
            for term in json.loads(products[0])["terms"]["OnDemand"].values()
            for dimension in term["priceDimensions"].values()
        ]
        if len(dimensions) != 1 or dimensions[0]["unit"] != unit:
            raise ValueError("price dimensions are ambiguous")

        return float(dimensions[0]["pricePerUnit"]["USD"])
