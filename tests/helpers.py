import json
from datetime import UTC, datetime, timedelta

from botocore.exceptions import ClientError


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


GB = 1024**3


def make_images(sizes_oldest_first):
    """Fake ECR imageDetails, pushed one hour apart, oldest first."""
    start = datetime(2026, 9, 1, tzinfo=UTC)
    return [
        {"imageSizeInBytes": size, "imagePushedAt": start + timedelta(hours=i)}
        for i, size in enumerate(sizes_oldest_first)
    ]


class FakePaginator:
    def __init__(self, fn):
        self._fn = fn

    def paginate(self, **kwargs):
        return iter(self._fn(**kwargs))


class FakeEcr:
    """Stands in for the boto3 ecr client, with exact image sizes and dates.

    repos: {repository_name: [imageDetails]}   policies: names that have a policy
    """

    def __init__(self, repos, policies=(), lifecycle_error=None):
        self.repos = repos
        self.policies = set(policies)
        self.lifecycle_error = lifecycle_error

    def get_paginator(self, operation):
        if operation == "describe_repositories":
            return FakePaginator(
                lambda: [{"repositories": [{"repositoryName": n} for n in self.repos]}]
            )
        if operation == "describe_images":
            return FakePaginator(
                lambda repositoryName: [{"imageDetails": self.repos[repositoryName]}]
            )
        raise NotImplementedError(operation)

    def get_lifecycle_policy(self, repositoryName):
        if self.lifecycle_error:
            raise self.lifecycle_error
        if repositoryName in self.policies:
            return {"lifecyclePolicyText": "{}"}
        raise ClientError(
            {"Error": {"Code": "LifecyclePolicyNotFoundException", "Message": "none"}},
            "GetLifecyclePolicy",
        )
