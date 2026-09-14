import csv
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from apps import neoseal_stock_count as cli
from workflows.neoseal_stock_count import (
    CUSTOM_STOCK_COUNT_MAPPING,
    CountPlacement,
    SKUMappingRow,
    build_sku_cell_mappings,
    build_stock_count,
    default_placement,
    fetch_neoseal_stock_count,
    fetch_neoseal_flat_stock,
    delete_approved_missing_flat_items,
    fill_quantities_from_mapping,
    format_cell_address,
    format_custom_stock_count_sheet,
    parse_cell_address,
    render_stock_count,
    write_flat_stock_count_to_sheet,
    upsert_flat_stock_to_sheet,
    write_mapping_to_sheet,
    write_stock_count,
    write_stock_count_to_sheet,
    zero_unmapped_stockcount_quantities,
)



def item(item_id="1", **overrides):
    return {"item_id": item_id, "name": "105 PVC Solution 50 ml (Tin)",
            "sku": "105-50-PVC-CLR-TIN", "purchase_account_id": "account",
            "available_stock": "12.5", "stock_on_hand": "14", "unit": "NOS",
            "status": "active", "track_inventory": True, **overrides}


def test_group_subgroup_and_natural_count_order_are_stable():
    items = [item("3", name="PTFE Tape 10 m"), item("2", name="105 PVC Solution 100 ml (Tin)"),
             item("1"), item("4", name="PTFE Tape 5 m")]
    result = build_stock_count(items, purchase_account_id="account")
    assert [r.item_id for r in result.rows] == ["1", "2", "4", "3"]
    assert [r.sort_order for r in result.rows] == [1, 2, 3, 4]
    assert result.rows[0].placement.group == "Solvent cement"
    assert result.rows[0].placement.subgroup == "PVC / Grade 105"
    assert result.rows[0].available_quantity == Decimal("12.5")
    assert result.rows[0].stock_on_hand == Decimal("14")
    assert result.rows == build_stock_count(list(reversed(items)), purchase_account_id="account").rows


@pytest.mark.parametrize("name,group", [
    ("CPVC Ball Valve GS PLUS", "Ball valves"),
    ("701 GP Silicone Sealant", "Sealants"),
    ("501 SBR Latex 1 kg", "Construction chemicals"),
    ("ND40 Lubricant", "Maintenance"),
    ("Solvent Rate Difference", "Adjustments"),
    ("Unknown widget", "Other items"),
])
def test_default_families(name, group):
    assert default_placement({"name": name}).group == group


def test_zero_negative_inactive_and_unknown_are_not_dropped():
    rows = build_stock_count([
        item("1", available_stock=0, stock_on_hand=0, status="inactive"),
        item("2", available_stock=-2), item("3", available_stock="NaN", stock_on_hand=None),
    ], purchase_account_id="account").rows
    assert len(rows) == 3
    assert rows[0].available_quantity == 0
    assert rows[0].status == "inactive"
    assert rows[1].available_quantity == -2
    assert rows[2].available_quantity is None
    assert "Available quantity unknown" in rows[2].warnings


def test_selected_location_uses_only_its_balances_and_keeps_missing_rows():
    rows = build_stock_count([item(locations=[
        {"location_id": "A", "location_available_stock": "3", "location_stock_on_hand": "4"},
        {"location_id": "B", "location_available_stock": "90", "location_stock_on_hand": "100"},
    ]), item("2")], purchase_account_id="account", location_id="A").rows
    assert rows[0].available_quantity == 3
    assert rows[0].stock_on_hand == 4
    assert rows[1].available_quantity is None
    assert "Location balance missing" in rows[1].warnings


def test_custom_shelf_layout_controls_group_subgroup_and_item_order():
    layout = {"1": CountPlacement("Shelf B", "Bottom", 20, 10, 2),
              "2": CountPlacement("Shelf A", "Top", 10, 10, 0),
              "3": CountPlacement("Shelf B", "Bottom", 20, 10, 1)}
    rows = build_stock_count([item("1"), item("2"), item("3")], purchase_account_id="account", layout=layout).rows
    assert [r.item_id for r in rows] == ["2", "3", "1"]


@pytest.mark.parametrize("items", [[item(purchase_account_id="other")], [item(), item()], [item(item_id="")]])
def test_scope_and_identity_errors(items):
    with pytest.raises(ValueError):
        build_stock_count(items, purchase_account_id="account")


def test_invalid_layout_fails_instead_of_silently_ignoring_it():
    with pytest.raises(ValueError, match="outside this count"):
        build_stock_count([item()], purchase_account_id="account", layout={"99": CountPlacement("A", "B")})
    with pytest.raises(ValueError, match="Conflicting"):
        build_stock_count([item(), item("2")], purchase_account_id="account", layout={
            "1": CountPlacement("A", "B", 1), "2": CountPlacement("A", "C", 2)})
    with pytest.raises(ValueError, match="non-negative"):
        CountPlacement("A", "B", item_order=-1)


def test_fetch_uses_scoped_inventory_and_bulk_details():
    inventory = MagicMock()
    inventory.items.list_by_purchase_account.return_value = [item(available_stock="stale")]
    inventory.items.get_details.return_value = [item(available_stock=5)]
    result = fetch_neoseal_stock_count(inventory, purchase_account_id="account")
    inventory.items.list_by_purchase_account.assert_called_once_with("account", status="active")
    inventory.items.get_details.assert_called_once_with(["1"])
    assert result.rows[0].available_quantity == 5
    inventory.items.update.assert_not_called()


def test_fetch_empty_scope_does_not_read_details():
    inventory = MagicMock()
    inventory.items.list_by_purchase_account.return_value = []
    assert not fetch_neoseal_stock_count(inventory, purchase_account_id="account").rows
    inventory.items.get_details.assert_not_called()


def test_fetch_refuses_incomplete_detail_response_and_propagates_api_errors():
    inventory = MagicMock()
    inventory.items.list_by_purchase_account.return_value = [item()]
    inventory.items.get_details.return_value = []
    with pytest.raises(ValueError, match="Incomplete"):
        fetch_neoseal_stock_count(inventory, purchase_account_id="account")
    inventory.items.get_details.side_effect = RuntimeError("API failed")
    with pytest.raises(RuntimeError, match="API failed"):
        fetch_neoseal_stock_count(inventory, purchase_account_id="account")


def test_fetch_rejects_non_active_status():
    with pytest.raises(ValueError, match="active items only"):
        fetch_neoseal_stock_count(MagicMock(), purchase_account_id="account", status="all")


def test_count_files_have_grouping_quantities_and_blank_count_fields(tmp_path):
    result = build_stock_count([item(name="Widget | special\nname"), item("2", available_stock=None)], purchase_account_id="account")
    paths = write_stock_count(result, str(tmp_path))
    with paths.csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert {r["available_quantity"] for r in rows} == {"12.5", ""}
    assert all(r["physical_count"] == "" for r in rows)
    text = paths.markdown_path.read_text(encoding="utf-8")
    assert "## Other items" in text
    assert "### Unclassified" in text
    assert "Widget \\| special name" in text
    assert "Unknown" in text
    assert "No items found" in render_stock_count(build_stock_count([], purchase_account_id="account"))


def test_sheet_writer_creates_worksheet_and_writes_ordered_active_count():
    sheet = MagicMock()
    sheet.list_sheets.return_value = ["Other"]
    count = build_stock_count([item()], purchase_account_id="account")
    result = write_stock_count_to_sheet(
        sheet, workbook_id="workbook", worksheet_name="Neoseal Stock Count", count=count,
    )
    assert result.created_worksheet is True
    assert result.rows_written == 1
    sheet.add_sheet.assert_called_once_with("workbook", "Neoseal Stock Count")
    sheet.get_rows.assert_not_called()
    sheet.truncate_sheet.assert_not_called()
    assert sheet.set_cell.call_count == 10
    assert sheet.set_cell.call_args_list[0].args == ("workbook", "Neoseal Stock Count", 1, 1, "count_label")
    rows = sheet.add_rows.call_args.args[2]
    assert [(row["count_label"], row["row_type"]) for row in rows] == [
        ("Solvent cement", "group"), ("PVC / Grade 105", "subgroup"),
        ("105 PVC Solution 50 ml (Tin)", "item"),
    ]
    assert rows[2]["stock_on_hand"] == "14"
    assert rows[2]["physical_count"] == ""
    formats = sheet.format_ranges.call_args.args[1]
    assert [(f["range"], f["font_size"], f["bold"]) for f in formats] == [
        ("A2:A2", "16", "true"), ("A3:A3", "14", "true"), ("A4:J4", "10", "false"),
    ]


def test_sheet_writer_preserves_manual_count_and_remarks_for_matching_item_id():
    sheet = MagicMock()
    sheet.list_sheets.return_value = ["Neoseal Stock Count"]
    sheet.get_rows.return_value = [
        {"row_index": 2, "item_id": "1", "physical_count": "10", "remarks": "Top shelf"},
        {"row_index": 3, "item_id": "stale", "physical_count": "4"},
    ]
    write_stock_count_to_sheet(
        sheet, workbook_id="workbook", worksheet_name="Neoseal Stock Count",
        count=build_stock_count([item()], purchase_account_id="account"),
    )
    sheet.delete_rows.assert_called_once_with("workbook", "Neoseal Stock Count", [2, 3])
    rows = sheet.add_rows.call_args.args[2]
    assert rows[2]["physical_count"] == "10"
    assert rows[2]["remarks"] == "Top shelf"


def test_flat_sheet_restores_all_columns_and_preserves_manual_count():
    sheet = MagicMock()
    sheet.list_sheets.return_value = ["StockCount", "Flat"]
    sheet.get_rows.side_effect = [
        [],
        [{"item_id": "1", "physical_count": "10", "remarks": "Top shelf"}],
    ]
    result = write_flat_stock_count_to_sheet(
        sheet, workbook_id="workbook", worksheet_name="Flat",
        count=build_stock_count([item()], purchase_account_id="account"),
    )
    assert result.rows_written == 1
    assert sheet.set_cell.call_count == 11
    rows = sheet.add_rows.call_args.args[2]
    assert "group" not in rows[0]
    assert "subgroup" not in rows[0]
    assert "sort_order" not in rows[0]
    assert rows[0]["source_group"] == ""
    assert rows[0]["physical_count"] == "10"
    assert rows[0]["remarks"] == "Top shelf"


def test_flat_sheet_refresh_removes_stale_rows_and_prefers_flat_manual_values():
    sheet = MagicMock()
    sheet.list_sheets.return_value = ["StockCount", "Flat"]
    sheet.get_rows.side_effect = [
        [{"row_index": 2, "item_id": "1", "physical_count": "12"},
         {"row_index": 3, "item_id": "stale"}],
        [{"item_id": "1", "physical_count": "10"}],
    ]
    write_flat_stock_count_to_sheet(
        sheet, workbook_id="workbook", worksheet_name="Flat",
        count=build_stock_count([item()], purchase_account_id="account"),
    )
    sheet.delete_rows.assert_called_once_with("workbook", "Flat", [2, 3])
    assert sheet.add_rows.call_args.args[2][0]["physical_count"] == "12"


def test_flat_sheet_refuses_same_worksheet_as_count_view():
    with pytest.raises(ValueError, match="distinct"):
        write_flat_stock_count_to_sheet(
            MagicMock(), workbook_id="workbook", worksheet_name="StockCount",
            count=build_stock_count([], purchase_account_id="account"),
        )


@pytest.mark.parametrize("workbook,worksheet", [("", "Count"), ("workbook", " ")])
def test_sheet_writer_requires_target(workbook, worksheet):
    with pytest.raises(ValueError, match="required"):
        write_stock_count_to_sheet(MagicMock(), workbook_id=workbook, worksheet_name=worksheet,
                                   count=build_stock_count([], purchase_account_id="account"))


def test_cli_upserts_flat_only(monkeypatch):
    inventory = MagicMock()
    sheet = MagicMock()
    sheet.list_sheets.return_value = []
    inventory.items.list_by_purchase_account.return_value = [item()]
    inventory.items.get_details.return_value = [item()]
    monkeypatch.setattr(cli, "get_inventory_client", lambda: inventory)
    monkeypatch.setattr(cli, "get_sheet_client", lambda: sheet)
    assert cli.main(["--purchase-account-id", "account", "--sheet-id", "workbook"]) == 0
    assert [call.args for call in sheet.add_sheet.call_args_list] == [("workbook", "Flat")]
    assert sheet.add_rows.call_args_list[0].args[1] == "Flat"
    sheet.delete_rows.assert_not_called()


def test_flat_fetch_preserves_inventory_order_without_grouping():
    inventory = MagicMock()
    inventory.items.list_by_purchase_account.return_value = [item("2"), item("1")]
    inventory.items.get_details.return_value = [item("2", available_stock="3"), item("1")]
    result = fetch_neoseal_flat_stock(inventory, purchase_account_id="account")
    assert [row.item_id for row in result.rows] == ["2", "1"]
    assert result.rows[0].available_quantity == Decimal("3")
    assert not hasattr(result.rows[0], "placement")


def test_flat_fetch_excludes_untracked_items_before_bulk_details():
    inventory = MagicMock()
    inventory.items.list_by_purchase_account.return_value = [
        item("1"), item("2", track_inventory=False),
    ]
    inventory.items.get_details.return_value = [item("1")]
    result = fetch_neoseal_flat_stock(inventory, purchase_account_id="account")
    assert [row.item_id for row in result.rows] == ["1"]
    inventory.items.get_details.assert_called_once_with(["1"])


def test_flat_fetch_rejects_missing_tracking_flag():
    inventory = MagicMock()
    catalog_item = item()
    del catalog_item["track_inventory"]
    inventory.items.list_by_purchase_account.return_value = [catalog_item]
    with pytest.raises(ValueError, match="track_inventory"):
        fetch_neoseal_flat_stock(inventory, purchase_account_id="account")
    inventory.items.get_details.assert_not_called()


def test_flat_fetch_rejects_incomplete_details_and_marks_missing_location_unknown():
    inventory = MagicMock()
    inventory.items.list_by_purchase_account.return_value = [item()]
    inventory.items.get_details.return_value = []
    with pytest.raises(ValueError, match="Incomplete"):
        fetch_neoseal_flat_stock(inventory, purchase_account_id="account")
    inventory.items.get_details.return_value = [item()]
    row = fetch_neoseal_flat_stock(inventory, purchase_account_id="account", location_id="A").rows[0]
    assert row.available_quantity is None
    assert "Location balance missing" in row.warnings


def test_flat_upsert_updates_existing_and_adds_missing_without_touching_manual_fields():
    sheet = MagicMock()
    sheet.request.return_value = {"range_details": []}
    sheet.list_sheets.return_value = ["Flat", "StockCount", "Mapping"]
    sheet.get_rows.return_value = [{"row_index": 2, "item_id": "1", "physical_count": "9", "remarks": "checked"}]
    inventory = MagicMock()
    inventory.items.list_by_purchase_account.return_value = [item("1"), item("2")]
    inventory.items.get_details.return_value = [
        item("1", custom_fields=[{"api_name": "cf_pack_size", "label": "Pack Size", "value": "24"}]),
        item("2", custom_fields=[{"api_name": "cf_pack_size", "value": "12"}]),
    ]
    snapshot = fetch_neoseal_flat_stock(inventory, purchase_account_id="account")
    result = upsert_flat_stock_to_sheet(sheet, workbook_id="wb", worksheet_name="Flat", snapshot=snapshot)
    assert result.rows_written == 2
    sheet.truncate_sheet.assert_called_once_with("wb", "Flat", criteria='"item_id" != \'\'')
    sheet.update_rows.assert_not_called()
    added = sheet.add_rows.call_args.args[2]
    assert len(added) == 2
    assert added[0]["item_id"] == "1"
    assert added[0]["available_quantity"] == "12.5"
    assert added[0]["packing"] == "24"
    assert added[0]["physical_count"] == "9" and added[0]["remarks"] == "checked"
    assert added[1]["item_id"] == "2"
    assert added[1]["packing"] == "12"
    sheet.set_cell.assert_called_once_with("wb", "Flat", 1, 12, "packing")
    sheet.delete_rows.assert_not_called()


def test_flat_packing_missing_field_is_blank_and_occupied_column_stops_upsert():
    inventory = MagicMock()
    inventory.items.list_by_purchase_account.return_value = [item("1")]
    inventory.items.get_details.return_value = [item("1")]
    snapshot = fetch_neoseal_flat_stock(inventory, purchase_account_id="account")
    assert snapshot.rows[0].packing == ""
    sheet = MagicMock()
    sheet.list_sheets.return_value = ["Flat"]
    sheet.get_rows.return_value = [{"row_index": 2, "item_id": "1"}]
    sheet.request.side_effect = [
        {"range_details": []},
        {"range_details": []},
        {"range_details": [{"row_details": [{"content": "another_field"}]}]},
    ]
    with pytest.raises(ValueError, match="column L is occupied"):
        upsert_flat_stock_to_sheet(sheet, workbook_id="wb", worksheet_name="Flat", snapshot=snapshot)
    sheet.update_rows.assert_not_called()
    sheet.set_cell.assert_not_called()


def test_flat_upsert_reports_old_rows_after_add_without_deleting_them():
    sheet = MagicMock()
    sheet.request.return_value = {"range_details": []}
    sheet.list_sheets.return_value = ["Flat"]
    sheet.get_rows.return_value = [{"row_index": 2, "item_id": "9", "sku": "OLD", "name": "Old item"}]
    inventory = MagicMock()
    inventory.items.list_by_purchase_account.return_value = [item("1")]
    inventory.items.get_details.return_value = [item("1")]
    snapshot = fetch_neoseal_flat_stock(inventory, purchase_account_id="account")
    result = upsert_flat_stock_to_sheet(sheet, workbook_id="wb", worksheet_name="Flat", snapshot=snapshot)
    assert [(row.item_id, row.sku, row.name, row.row_index) for row in result.missing_items] == [
        ("9", "OLD", "Old item", 2),
    ]
    sheet.truncate_sheet.assert_called_once_with("wb", "Flat", criteria='"item_id" != \'\'')
    sheet.update_rows.assert_not_called()
    added = sheet.add_rows.call_args.args[2]
    assert len(added) == 2
    assert added[0]["item_id"] == "9" and added[0]["name"] == "Old item"
    assert added[1]["item_id"] == "1"
    sheet.delete_rows.assert_not_called()


def test_flat_upsert_reads_items_after_a_deleted_row_gap():
    sheet = MagicMock()
    sheet.list_sheets.return_value = ["Flat"]
    sheet.get_rows.return_value = [{"row_index": 2, "item_id": "1"}]
    sheet.request.side_effect = [
        {"range_details": []},
        {"range_details": [
            {"row_index": 2, "row_details": [{"column_index": 1, "content": "1"}]},
            {"row_index": 4, "row_details": [{"column_index": 1, "content": "2"}]},
        ]},
        {"range_details": []},
    ]
    inventory = MagicMock()
    inventory.items.list_by_purchase_account.return_value = [item("1"), item("2")]
    inventory.items.get_details.return_value = [item("1"), item("2")]
    snapshot = fetch_neoseal_flat_stock(inventory, purchase_account_id="account")
    result = upsert_flat_stock_to_sheet(sheet, workbook_id="wb", worksheet_name="Flat", snapshot=snapshot)
    assert result.rows_written == 2
    sheet.truncate_sheet.assert_called_once_with("wb", "Flat", criteria='"item_id" != \'\'')
    sheet.update_rows.assert_not_called()
    added = sheet.add_rows.call_args.args[2]
    assert [r["item_id"] for r in added] == ["1", "2"]


def test_flat_upsert_rejects_shifted_headers_before_writing():
    sheet = MagicMock()
    sheet.list_sheets.return_value = ["Flat"]
    sheet.request.return_value = {"range_details": [{"row_details": [
        {"column_index": 1, "content": "group"},
        {"column_index": 2, "content": "subgroup"},
    ]}]}
    inventory = MagicMock()
    inventory.items.list_by_purchase_account.return_value = [item("1")]
    inventory.items.get_details.return_value = [item("1")]
    snapshot = fetch_neoseal_flat_stock(inventory, purchase_account_id="account")
    with pytest.raises(ValueError, match="headers do not match"):
        upsert_flat_stock_to_sheet(sheet, workbook_id="wb", worksheet_name="Flat", snapshot=snapshot)
    sheet.truncate_sheet.assert_not_called()
    sheet.add_rows.assert_not_called()


def test_missing_flat_delete_requires_exact_current_missing_ids():
    sheet = MagicMock()
    sheet.request.return_value = {"range_details": []}
    sheet.get_rows.return_value = [
        {"row_index": 2, "item_id": "1"},
        {"row_index": 3, "item_id": "9"},
    ]
    inventory = MagicMock()
    inventory.items.list_by_purchase_account.return_value = [item("1")]
    inventory.items.get_details.return_value = [item("1")]
    snapshot = fetch_neoseal_flat_stock(inventory, purchase_account_id="account")
    with pytest.raises(ValueError, match="no longer missing"):
        delete_approved_missing_flat_items(sheet, workbook_id="wb", worksheet_name="Flat",
                                           snapshot=snapshot, approved_item_ids=["1"])
    sheet.delete_rows.assert_not_called()
    assert delete_approved_missing_flat_items(sheet, workbook_id="wb", worksheet_name="Flat",
                                              snapshot=snapshot, approved_item_ids=["9"]) == 1
    sheet.delete_rows.assert_called_once_with("wb", "Flat", [3])


def test_missing_flat_deletes_disjoint_rows_individually_from_bottom():
    sheet = MagicMock()
    sheet.request.return_value = {"range_details": []}
    sheet.get_rows.return_value = [
        {"row_index": 2, "item_id": "8"},
        {"row_index": 3, "item_id": "1"},
        {"row_index": 4, "item_id": "9"},
    ]
    inventory = MagicMock()
    inventory.items.list_by_purchase_account.return_value = [item("1")]
    inventory.items.get_details.return_value = [item("1")]
    snapshot = fetch_neoseal_flat_stock(inventory, purchase_account_id="account")
    assert delete_approved_missing_flat_items(
        sheet, workbook_id="wb", worksheet_name="Flat", snapshot=snapshot,
        approved_item_ids=["8", "9"],
    ) == 2
    assert [call.args[2] for call in sheet.delete_rows.call_args_list] == [[4], [2]]


def test_cli_prints_missing_items_without_deleting(monkeypatch, capsys):
    inventory = MagicMock()
    inventory.items.list_by_purchase_account.return_value = [item("1")]
    inventory.items.get_details.return_value = [item("1")]
    sheet = MagicMock()
    sheet.request.return_value = {"range_details": []}
    sheet.list_sheets.return_value = ["Flat"]
    sheet.get_rows.return_value = [{"row_index": 2, "item_id": "9", "sku": "OLD", "name": "Old item"}]
    monkeypatch.setattr(cli, "get_inventory_client", lambda: inventory)
    monkeypatch.setattr(cli, "get_sheet_client", lambda: sheet)
    assert cli.main(["--purchase-account-id", "account", "--sheet-id", "wb"]) == 0
    output = capsys.readouterr().out
    assert "9 | OLD | Old item" in output
    assert "Deletion requires approval" in output
    sheet.delete_rows.assert_not_called()


def test_flat_upsert_rejects_duplicate_existing_ids():
    sheet = MagicMock()
    sheet.request.return_value = {"range_details": []}
    sheet.list_sheets.return_value = ["Flat"]
    sheet.get_rows.return_value = [{"item_id": "1"}, {"item_id": "1"}]
    inventory = MagicMock()
    inventory.items.list_by_purchase_account.return_value = [item()]
    inventory.items.get_details.return_value = [item()]
    with pytest.raises(ValueError, match="duplicate item IDs"):
        upsert_flat_stock_to_sheet(sheet, workbook_id="wb", worksheet_name="Flat",
                                   snapshot=fetch_neoseal_flat_stock(inventory, purchase_account_id="account"))
    sheet.update_rows.assert_not_called()


def test_cli_missing_sheet_target_fails_before_auth(monkeypatch):
    inventory_factory = MagicMock()
    sheet_factory = MagicMock()
    monkeypatch.setattr(cli, "get_inventory_client", inventory_factory)
    monkeypatch.setattr(cli, "get_sheet_client", sheet_factory)
    with pytest.raises(SystemExit):
        cli.main(["--purchase-account-id", "account", "--sheet-id", ""])
    inventory_factory.assert_not_called()
    sheet_factory.assert_not_called()


def test_cli_missing_account_fails_before_auth(monkeypatch):
    factory = MagicMock()
    monkeypatch.setattr(cli, "get_inventory_client", factory)
    with pytest.raises(SystemExit):
        cli.main(["--purchase-account-id", ""])
    factory.assert_not_called()


def test_parse_and_format_cell_address():
    assert format_cell_address(4, 2) == "B4"
    assert parse_cell_address("B4") == (4, 2)
    assert format_cell_address(1, 1) == "A1"
    assert parse_cell_address("a1") == (1, 1)
    assert format_cell_address(10, 27) == "AA10"
    assert parse_cell_address("AA10") == (10, 27)

    with pytest.raises(ValueError, match="positive integers"):
        format_cell_address(0, 1)
    with pytest.raises(ValueError, match="positive integers"):
        format_cell_address(1, 0)
    with pytest.raises(ValueError, match="Invalid cell address"):
        parse_cell_address("123")
    with pytest.raises(ValueError, match="Invalid cell address"):
        parse_cell_address("ABC")
    with pytest.raises(ValueError, match="Invalid cell address"):
        parse_cell_address("1A")


def test_build_sku_cell_mappings():
    items = [
        item("1", sku="SKU-1", name="Item 1"),
        item("2", sku="SKU-2", name="Item 2"),
    ]
    count = build_stock_count(items, purchase_account_id="account")
    mappings = build_sku_cell_mappings(count)
    assert len(mappings) == 2
    # Row 1 is header.
    # Group 1 header is Row 2.
    # Subgroup 1 header is Row 3.
    # Item 1 is Row 4 -> Qty is B4, SOH is H4
    # Item 2 is Row 5 -> Qty is B5, SOH is H5
    assert mappings[0].sku == "SKU-1"
    assert mappings[0].cell == "B4"
    assert mappings[0].stock_on_hand_cell == "H4"
    assert mappings[1].sku == "SKU-2"
    assert mappings[1].cell == "B5"
    assert mappings[1].stock_on_hand_cell == "H5"


def test_write_mapping_to_sheet_creates_and_populates():
    sheet = MagicMock()
    sheet.list_sheets.return_value = ["StockCount"]
    sheet.request.return_value = {"range_details": [
        {"row_index": 4, "row_details": [{"column_index": 1, "content": "Count item"}]},
    ]}
    count = build_stock_count([item("1", sku="SKU-1")], purchase_account_id="account")
    result = write_mapping_to_sheet(
        sheet, workbook_id="wb", worksheet_name="Mapping", count=count, count_worksheet_name="StockCount",
    )
    assert result.created_worksheet is True
    assert result.rows_written == 1
    sheet.add_sheet.assert_called_once_with("wb", "Mapping")
    # Column C holds the name visible in StockCount.
    assert sheet.set_cell.call_count == 5
    assert sheet.set_cell.call_args_list[2].args == ("wb", "Mapping", 1, 3, "name")
    rows = sheet.add_rows.call_args.args[2]
    assert rows[0]["sku"] == "SKU-1"
    assert rows[0]["cell"] == "B4"
    assert rows[0]["name"] == "Count item"
    assert rows[0]["stock_on_hand_cell"] == "H4"


def test_write_mapping_preserves_custom_cells():
    sheet = MagicMock()
    sheet.list_sheets.return_value = ["StockCount", "Mapping"]
    sheet.request.return_value = {"range_details": [
        {"row_index": 10, "row_details": [{"column_index": 1, "content": "Custom count label"}]},
    ]}
    sheet.get_rows.return_value = [
        {"row_index": 2, "sku": "SKU-1", "cell": "D10", "stock_on_hand_cell": "E10"},
    ]
    count = build_stock_count([item("1", sku="SKU-1")], purchase_account_id="account")
    result = write_mapping_to_sheet(
        sheet, workbook_id="wb", worksheet_name="Mapping", count=count, count_worksheet_name="StockCount",
    )
    assert result.created_worksheet is False
    sheet.delete_rows.assert_called_once_with("wb", "Mapping", [2])
    rows = sheet.add_rows.call_args.args[2]
    assert rows[0]["sku"] == "SKU-1"
    assert rows[0]["cell"] == "D10"
    assert rows[0]["name"] == "Custom count label"
    assert rows[0]["stock_on_hand_cell"] == "E10"


def test_write_mapping_refuses_missing_stockcount_name():
    sheet = MagicMock()
    sheet.list_sheets.return_value = ["StockCount"]
    sheet.request.return_value = {"range_details": []}
    count = build_stock_count([item("1", sku="SKU-1")], purchase_account_id="account")
    with pytest.raises(ValueError, match="product name is missing"):
        write_mapping_to_sheet(
            sheet, workbook_id="wb", worksheet_name="Mapping", count=count,
            count_worksheet_name="StockCount",
        )
    sheet.add_rows.assert_not_called()


def test_fill_quantities_from_mapping():
    sheet = MagicMock()
    count = build_stock_count([
        item("1", sku="SKU-1", available_stock=15, stock_on_hand=20),
    ], purchase_account_id="account")
    mappings = [
        SKUMappingRow(sku="SKU-1", cell="B4", item_id="1", name="Item 1", stock_on_hand_cell="H4"),
        SKUMappingRow(sku="UNKNOWN", cell="B5", item_id="2", name="Unknown"),
    ]
    updated = fill_quantities_from_mapping(
        sheet, workbook_id="wb", count_worksheet_name="StockCount", count=count, mapping_rows=mappings,
    )
    assert updated == 1
    assert sheet.set_cell.call_args_list == [
        (("wb", "StockCount", 4, 2, "15"),),
        (("wb", "StockCount", 4, 8, "20"),),
    ]


def test_fill_quantities_from_mapping_reads_sheet_when_not_provided():
    sheet = MagicMock()
    sheet.get_rows.return_value = [
        {"sku": "SKU-1", "cell": "C8", "stock_on_hand_cell": ""},
    ]
    count = build_stock_count([
        item("1", sku="SKU-1", available_stock=7),
    ], purchase_account_id="account")
    updated = fill_quantities_from_mapping(
        sheet, workbook_id="wb", count_worksheet_name="StockCount", count=count,
        mapping_worksheet_name="Mapping",
    )
    assert updated == 1
    sheet.get_rows.assert_called_once_with("wb", "Mapping", limit=1000)
    sheet.set_cell.assert_called_once_with("wb", "StockCount", 8, 3, "7")


def test_zero_unmapped_stockcount_quantities_only_changes_item_lines():
    sheet = MagicMock()
    sheet.get_rows.return_value = [{"sku": "A", "cell": "C3"}]
    sheet.request.return_value = {"used_row": 5, "range_details": [
        {"row_index": 1, "row_details": [
            {"column_index": c, "content": value} for c, value in
            ((1, "PRODUCT"), (2, "PACK"), (3, "QTY"),
             (6, "PRODUCT"), (7, "PACK"), (8, "QTY"))]},
        {"row_index": 2, "row_details": [{"column_index": 1, "content": "Category"}]},
        {"row_index": 3, "row_details": [
            {"column_index": 1, "content": "Mapped"},
            {"column_index": 2, "content": "24"},
            {"column_index": 3, "content": "9"},
            {"column_index": 6, "content": "Unmapped"},
            {"column_index": 7, "content": "12"},
            {"column_index": 8, "content": "7"}]},
        {"row_index": 4, "row_details": [
            {"column_index": 1, "content": "Unmapped blank"},
            {"column_index": 2, "content": "20"}]},
        {"row_index": 5, "row_details": [
            {"column_index": 1, "content": "Already zero"},
            {"column_index": 2, "content": "20"},
            {"column_index": 3, "content": "0"}]},
    ]}
    assert zero_unmapped_stockcount_quantities(sheet, workbook_id="wb") == 2
    assert [call.args for call in sheet.set_cell.call_args_list] == [
        ("wb", "StockCount", 3, 8, "0"), ("wb", "StockCount", 4, 3, "0"),
    ]


def test_zero_unmapped_stockcount_quantities_rejects_wrong_layout():
    sheet = MagicMock()
    sheet.get_rows.return_value = []
    sheet.request.return_value = {"range_details": []}
    with pytest.raises(ValueError, match="two-table"):
        zero_unmapped_stockcount_quantities(sheet, workbook_id="wb")
    sheet.set_cell.assert_not_called()


def test_format_custom_stock_count_sheet_success():
    sheet = MagicMock()
    sheet.get_sheet_id.return_value = "0#"
    sheet.request.return_value = {
        "used_row": 4,
        "range_details": [
            {
                "row_index": 1,
                "row_details": [
                    {"column_index": 1, "content": "PRODUCT"},
                    {"column_index": 2, "content": "PACK"},
                    {"column_index": 3, "content": "QTY"},
                    {"column_index": 4, "content": "AVL"},
                    {"column_index": 6, "content": "PRODUCT"},
                    {"column_index": 7, "content": "PACK"},
                    {"column_index": 8, "content": "QTY"},
                    {"column_index": 9, "content": "AVL"},
                ],
            },
            {
                "row_index": 2,
                "row_details": [
                    {"column_index": 1, "content": "105 PVC SOLVENT"},
                    {"column_index": 6, "content": "PVC BALL VALVE"},
                ],
            },
            {
                "row_index": 3,
                "row_details": [
                    {"column_index": 1, "content": "105 - 50ml"},
                    {"column_index": 2, "content": "24"},
                    {"column_index": 3, "content": "40.8"},
                    {"column_index": 6, "content": "3/4\""},
                    {"column_index": 7, "content": "20"},
                    {"column_index": 8, "content": "64"},
                ],
            },
        ],
    }

    result = format_custom_stock_count_sheet(sheet, workbook_id="wb123", worksheet_name="StockCount")
    assert result["workbook_id"] == "wb123"
    assert result["worksheet_name"] == "StockCount"
    assert result["merged_headers_count"] == 2
    sheet.format_ranges.assert_called_once()
    formats = sheet.format_ranges.call_args[0][1]
    # Check that merge rules are generated for the two category headers
    merge_ranges = [f["range"] for f in formats if f.get("merge_cell") == "merge_range"]
    assert "A2:D2" in merge_ranges
    assert "F2:I2" in merge_ranges


def test_format_custom_stock_count_sheet_validates_inputs():
    sheet = MagicMock()
    with pytest.raises(ValueError, match="workbook_id and worksheet_name are required"):
        format_custom_stock_count_sheet(sheet, workbook_id="", worksheet_name="StockCount")
    with pytest.raises(ValueError, match="workbook_id and worksheet_name are required"):
        format_custom_stock_count_sheet(sheet, workbook_id="wb", worksheet_name="  ")


def test_fill_quantities_from_mapping_aggregates_multiple_skus_to_same_cell():
    sheet = MagicMock()
    count = build_stock_count([
        item("1", sku="SKU-RED", available_stock=10, stock_on_hand=12),
        item("2", sku="SKU-BLU", available_stock=25, stock_on_hand=30),
        item("3", sku="SKU-GRN", available_stock=5, stock_on_hand=7),
    ], purchase_account_id="account")
    mappings = [
        SKUMappingRow(sku="SKU-RED", cell="D35", item_id="1", name="Red", stock_on_hand_cell=""),
        SKUMappingRow(sku="SKU-BLU", cell="D35", item_id="2", name="Blue", stock_on_hand_cell=""),
        SKUMappingRow(sku="SKU-GRN", cell="D35", item_id="3", name="Green", stock_on_hand_cell=""),
    ]
    updated = fill_quantities_from_mapping(
        sheet, workbook_id="wb", count_worksheet_name="StockCount", count=count, mapping_rows=mappings,
    )
    # Cell D35 is row 35, col 4. Sum is 10 + 25 + 5 = 40.
    assert updated == 1
    sheet.set_cell.assert_called_once_with("wb", "StockCount", 35, 4, "40")


def test_build_sku_cell_mappings_with_custom_mapping():
    count = build_stock_count([
        item("1", sku="105-50-PVC-CLR-TIN"),
        item("2", sku="DRAIN-50"),
    ], purchase_account_id="account")
    custom_map = {"105-50-PVC-CLR-TIN": "D3", "DRAIN-50": "I40"}
    mappings = build_sku_cell_mappings(count, custom_mapping=custom_map)
    assert len(mappings) == 2
    by_sku = {m.sku: m.cell for m in mappings}
    assert by_sku["105-50-PVC-CLR-TIN"] == "D3"
    assert by_sku["DRAIN-50"] == "I40"


def test_write_mapping_preserves_empty_unmapped_cell():
    sheet = MagicMock()
    sheet.list_sheets.return_value = ["StockCount", "Mapping"]
    sheet.get_rows.return_value = [
        {"row_index": 2, "sku": "SKU-1", "cell": "", "stock_on_hand_cell": ""},
    ]
    count = build_stock_count([item("1", sku="SKU-1")], purchase_account_id="account")
    result = write_mapping_to_sheet(
        sheet, workbook_id="wb", worksheet_name="Mapping", count=count, count_worksheet_name="StockCount",
    )
    assert result.created_worksheet is False
    rows = sheet.add_rows.call_args.args[2]
    assert rows[0]["sku"] == "SKU-1"
    # An intentional empty string in prior rows must be preserved, not overwritten with default cell address
    assert rows[0]["cell"] == ""


def test_custom_stock_count_mapping_covers_expected_items():
    assert len(CUSTOM_STOCK_COUNT_MAPPING) == 90
    assert CUSTOM_STOCK_COUNT_MAPPING["105-50-PVC-CLR-TIN"] == "C3"
    assert CUSTOM_STOCK_COUNT_MAPPING["6M-INSULATION-BLACK"] == "C35"
    assert CUSTOM_STOCK_COUNT_MAPPING["6M-INSULATION-BLUE"] == "C35"
    assert CUSTOM_STOCK_COUNT_MAPPING["0.75-PVC-GSP"] == "H3"
    assert CUSTOM_STOCK_COUNT_MAPPING["507-20-L"] == "H68"
    assert CUSTOM_STOCK_COUNT_MAPPING["609-1"] == ""
    assert CUSTOM_STOCK_COUNT_MAPPING["Neoseal CN"] == ""
