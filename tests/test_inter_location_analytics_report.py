import pytest

from workflows.inter_location_analytics_report import (
    build_inter_location_document_query,
    build_inter_location_query,
    validate_document_rows,
)
from zoho.analytics.resources import Views


def test_query_scopes_account_period_and_different_locations():
    sql = build_inter_location_query("1094368000002033114")
    assert sql.count('"Account ID" = 1094368000002033114') == 4
    assert 'CP."Location ID" <> VP."Location ID"' in sql
    assert 'CP."Location ID" <> JI."Location ID"' in sql
    assert sql.count("'2025-04-01'") == 2
    assert "Verify pairing" in sql


def test_query_rejects_unsafe_account_id():
    with pytest.raises(ValueError):
        build_inter_location_query("1 OR 1=1")


def test_create_query_table_posts_config():
    class Client:
        def request(self, method, endpoint, **kwargs):
            assert method == "POST"
            assert endpoint == "workspaces/w/querytables"
            assert "queryTableName" in kwargs["data"]["CONFIG"]
            return {"status": "success", "data": {"viewId": "123"}}

    assert Views(Client()).create_query_table("w", "Name", "SELECT 1") == "123"


def test_document_query_uses_source_document_locations():
    sql = build_inter_location_document_query("1094368000002033114")
    assert 'IP."Invoice ID" = I."Invoice ID"' in sql
    assert 'PM."Bill ID" = B."Bill ID"' in sql
    assert 'I."Location ID" AS "Invoice Location ID"' in sql
    assert 'B."Location ID" AS "Bill Location ID"' in sql
    assert "'Customer payment vs invoice' AS \"Issue Type\"" in sql
    assert "'Vendor payment vs bill' AS \"Issue Type\"" in sql
    assert 'CP."Location ID" <> I."Location ID"' in sql
    assert 'VP."Location ID" <> B."Location ID"' in sql
    assert 'CP."Account ID" = A."Account ID"' in sql
    assert 'VP."Account ID" = A."Account ID"' in sql
    assert sql.count('A."Account Type" = \'Bank\'') == 2
    assert 'CP."Account ID" AS "Bank Account ID"' in sql
    assert 'VP."Account ID" AS "Bank Account ID"' in sql
    assert sql.count('A."Account Name" AS "Bank Account Name"') == 3


def test_document_rows_require_source_locations():
    row = {
        "Debit Location ID": "1", "Credit Location ID": "2", "Debit Transaction ID": "a",
        "Credit Transaction ID": "b", "Credit Type": "Vendor Payment", "Invoice ID": "i",
        "Invoice Location ID": "2", "Bill ID": "bill", "Bill Location ID": "2",
    }
    assert validate_document_rows([row]) == {("a", "b")}
    with pytest.raises(ValueError, match="bill location"):
        validate_document_rows([{**row, "Bill Location ID": ""}])


def test_payment_document_mismatch_rows_are_validated():
    customer = {"Issue Type": "Customer payment vs invoice", "Debit Transaction ID": "cp",
                "Credit Transaction ID": "invoice", "Debit Location ID": "a",
                "Credit Location ID": "b", "Invoice ID": "invoice", "Invoice Location ID": "b"}
    vendor = {"Issue Type": "Vendor payment vs bill", "Debit Transaction ID": "vp",
              "Credit Transaction ID": "bill", "Debit Location ID": "a",
              "Credit Location ID": "b", "Bill ID": "bill", "Bill Location ID": "b"}
    assert validate_document_rows([customer, vendor]) == {("cp", "invoice"), ("vp", "bill")}
    with pytest.raises(ValueError, match="source invoice"):
        validate_document_rows([{**customer, "Invoice Location ID": ""}])
    with pytest.raises(ValueError, match="bill location"):
        validate_document_rows([{**vendor, "Bill Location ID": ""}])


def test_update_query_table_posts_config():
    class Client:
        def request(self, method, endpoint, **kwargs):
            assert method == "PUT"
            assert endpoint == "workspaces/w/querytables/v"
            assert "sqlQuery" in kwargs["data"]["CONFIG"]
            return {}

    Views(Client()).update_query_table("w", "v", "SELECT 1")
