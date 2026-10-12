import pytest
from botocore.exceptions import ClientError

from guardian.pricing import DEFAULTS, PriceProvider
from tests.helpers import FakePricing, make_product


def test_uses_live_price_when_exactly_one_match():
    provider = PriceProvider(FakePricing([make_product("0.1000000000")]))

    price = provider.ebs_gb_month("gp3", "ap-south-1")

    assert price.usd == 0.10
    assert price.source == "live"


def test_ambiguous_match_falls_back_to_default():
    provider = PriceProvider(FakePricing([make_product("0.1"), make_product("0.2")]))

    price = provider.ebs_gb_month("gp3", "ap-south-1")

    assert price.usd == DEFAULTS["ebs_gb_month"]
    assert price.source == "estimated"


def test_no_match_falls_back_to_default():
    provider = PriceProvider(FakePricing([]))

    assert provider.ebs_gb_month("gp3", "ap-south-1").source == "estimated"


def test_wrong_unit_falls_back_to_default():
    provider = PriceProvider(FakePricing([make_product("0.1", unit="Hrs")]))

    assert provider.ebs_gb_month("gp3", "ap-south-1").source == "estimated"


def test_aws_api_error_falls_back_to_default():
    error = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "denied"}},
        "GetProducts",
    )
    provider = PriceProvider(FakePricing(error=error))

    price = provider.ebs_gb_month("gp3", "ap-south-1")

    assert price.usd == DEFAULTS["ebs_gb_month"]
    assert price.source == "estimated"


def test_unexpected_bug_is_not_swallowed():
    provider = PriceProvider(FakePricing(error=RuntimeError("a real bug")))

    with pytest.raises(RuntimeError):
        provider.ebs_gb_month("gp3", "ap-south-1")


def test_results_are_cached_per_volume_type_and_region():
    fake = FakePricing([make_product("0.1")])
    provider = PriceProvider(fake)

    provider.ebs_gb_month("gp3", "ap-south-1")
    provider.ebs_gb_month("gp3", "ap-south-1")
    provider.ebs_gb_month("io2", "ap-south-1")

    assert fake.calls == 2


def test_no_client_uses_defaults_only():
    price = PriceProvider().ebs_gb_month("gp3", "ap-south-1")

    assert price.source == "estimated"


def test_ecr_price_is_always_labelled_estimated():
    price = PriceProvider(FakePricing([make_product("0.1")])).ecr_gb_month("ap-south-1")

    assert price.usd == DEFAULTS["ecr_gb_month"]
    assert price.source == "estimated"
