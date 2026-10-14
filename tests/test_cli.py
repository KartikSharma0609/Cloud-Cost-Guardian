from guardian.cli import print_spend_report
from tests.helpers import FakeCostExplorer, make_ce_page


class FakeSession:
    def __init__(self, ce):
        self._ce = ce

    def client(self, service, region_name=None):
        assert service == "ce"
        return self._ce


def test_spend_report_labels_what_each_scanner_checks(capsys):
    ce = FakeCostExplorer(
        [
            make_ce_page(
                {
                    "Amazon Simple Queue Service": "8.07",
                    "Amazon Virtual Private Cloud": "3.59",
                    "AWS Secrets Manager": "0.00003",
                }
            )
        ]
    )

    print_spend_report(FakeSession(ce))
    out = capsys.readouterr().err

    assert "no scanner yet" in out
    assert "checks: elastic_ip" in out
    assert "Secrets Manager" not in out  # below the noise threshold
    assert "$8.07 of usage is in services with no scanner yet" in out
    assert "does not explain" in out
