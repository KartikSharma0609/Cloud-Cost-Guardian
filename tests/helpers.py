import json


def make_product(usd, unit="GB-Mo"):
    """Build a fake Price List API product with a single price dimension."""
    return json.dumps(
        {
            "terms": {
                "OnDemand": {
                    "t1": {
                        "priceDimensions": {
                            "d1": {"unit": unit, "pricePerUnit": {"USD": usd}}
                        }
                    }
                }
            }
        }
    )


class FakePricing:
    """Stands in for the boto3 pricing client. Never touches the network."""

    def __init__(self, price_list=None, error=None):
        self.price_list = price_list or []
        self.error = error
        self.calls = 0

    def get_products(self, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return {"PriceList": self.price_list}
