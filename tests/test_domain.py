import pytest

from worker.domain import InvoiceError, parse_invoice
from worker.store import Store


@pytest.fixture
def source(tmp_path):
    store = Store(str(tmp_path / "parser.db"))
    store.seed()
    return store.source("acme-latest")


@pytest.mark.parametrize(
    "old,new",
    [
        ("1250.50", "1250.501"),
        ("1250.50", "-2"),
        ("1250.50", "0"),
        ("1250.50", "NaN"),
        ("1250.50", "1e3"),
        ("Currency: INR", "Currency: USD"),
        ("Due: 2026-11-15", "Due: tomorrow"),
        ("Due: 2026-11-15", "Due: 2026-10-01"),
        ("Vendor: acme", "Vendor: orbit"),
        ("Issued: 2026-10-20", "Issued: 2026-10-21"),
        ("ACM-1020", "../../etc/passwd"),
    ],
)
def test_parser_rejects_ambiguous_or_invalid_financial_fields(source, old, new):
    source["body"] = source["body"].replace(old, new)
    with pytest.raises(InvoiceError):
        parse_invoice(source)


def test_duplicate_label_is_rejected(source):
    source["body"] += "\nAmount: 10.00"
    with pytest.raises(InvoiceError):
        parse_invoice(source)


def test_minor_units_are_exact(source):
    source["body"] = source["body"].replace("1250.50", "0.29")
    assert parse_invoice(source)["amount_minor"] == 29
