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


def make_ce_page(spend, next_token=None):
    """Build a fake Cost Explorer response page: {service: "amount"}."""
    page = {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": "2026-09-11", "End": "2026-10-11"},
                "Groups": [
                    {
                        "Keys": [service],
                        "Metrics": {"UnblendedCost": {"Amount": amount, "Unit": "USD"}},
                    }
                    for service, amount in spend.items()
                ],
            }
        ]
    }
    if next_token:
        page["NextPageToken"] = next_token
    return page


class FakeCostExplorer:
    """Stands in for the boto3 ce client. Returns the given pages in order."""

    def __init__(self, pages):
        self.pages = pages
        self.requests = []  # every request we received, for assertions

    def get_cost_and_usage(self, **kwargs):
        self.requests.append(kwargs)
        return self.pages[len(self.requests) - 1]
