import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Price:
    usd: float
    source: (
        str  # "live" (from the AWS Price List API) or "estimated" (built-in default)
    )


# Fallbacks, used only when the Price List API is unavailable.
# EBS value: gp3 in ap-south-1, verified against the Price List API.
DEFAULTS = {
    "ebs_gb_month": 0.0912,
    "public_ipv4_hour": 0.005,
}


class PriceProvider:
    """Looks up AWS prices once per run and falls back to defaults on any problem."""

    def __init__(self, pricing_client=None):
        self._client = pricing_client  # None means "use defaults only"
        self._cache: dict[tuple, Price] = {}

    def ebs_gb_month(self, volume_type: str, region: str) -> Price:
        key = ("ebs", volume_type, region)
        if key not in self._cache:
            self._cache[key] = self._lookup_ebs(volume_type, region)
        return self._cache[key]

    def public_ipv4_hour(self, region: str) -> Price:
        # Live lookup comes once we've verified the right filters (see Step 8e).
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
            except Exception as exc:
                logger.warning("Live EBS price lookup failed (%s); using default", exc)
        return Price(DEFAULTS["ebs_gb_month"], "estimated")

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
