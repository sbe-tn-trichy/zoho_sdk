import csv
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from apps import neoseal_stock_count as cli
from workflows.neoseal_stock_count import (
    CountPlacement,
    SKUMappingRow,
    build_sku_cell_mappings,
    build_stock_count,
    default_placement,
    fetch_neoseal_stock_count,
    fill_quantities_from_mapping,
    format_cell_address,
    parse_cell_address,
    render_stock_count,
    write_flat_stock_count_to_sheet,
    write_mapping_to_sheet,
    write_stock_count,
    write_stock_count_to_sheet,
)


def item(item_id="1", **overrides):
    return {"item_id": item_id, "name": "105 PVC Solution 50 ml (Tin)",
            "sku": "105-50-PVC-CLR-TIN", "purchase_account_id": "account",
            "available_stock": "12.5", "stock_on_hand": "14", "unit": "NOS",
            "status": "active", **overrides}


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
        ("A2:A2", "18", "true"), ("A3:A3", "14", "true"),
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
    sheet.list_sheets.return_value = ["Sheet1", "Flat"]
    sheet.get_rows.side_effect = [
        [],
        [{"item_id": "1", "physical_count": "10", "remarks": "Top shelf"}],
    ]
    result = write_flat_stock_count_to_sheet(
        sheet, workbook_id="workbook", worksheet_name="Flat",
        count=build_stock_count([item()], purchase_account_id="account"),
    )
    assert result.rows_written == 1
    assert sheet.set_cell.call_count == 14
    rows = sheet.add_rows.call_args.args[2]
    assert rows[0]["group"] == "Solvent cement"
    assert rows[0]["subgroup"] == "PVC / Grade 105"
    assert rows[0]["source_group"] == ""
    assert rows[0]["physical_count"] == "10"
    assert rows[0]["remarks"] == "Top shelf"


def test_flat_sheet_refresh_removes_stale_rows_and_prefers_flat_manual_values():
    sheet = MagicMock()
    sheet.list_sheets.return_value = ["Sheet1", "Flat"]
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
            MagicMock(), workbook_id="workbook", worksheet_name="Sheet1",
            count=build_stock_count([], purchase_account_id="account"),
        )


@pytest.mark.parametrize("workbook,worksheet", [("", "Count"), ("workbook", " ")])
def test_sheet_writer_requires_target(workbook, worksheet):
    with pytest.raises(ValueError, match="required"):
        write_stock_count_to_sheet(MagicMock(), workbook_id=workbook, worksheet_name=worksheet,
                                   count=build_stock_count([], purchase_account_id="account"))


def test_cli_writes_sheet_and_accepts_layout(monkeypatch, tmp_path):
    inventory = MagicMock()
    sheet = MagicMock()
    sheet.list_sheets.return_value = []
    inventory.items.list_by_purchase_account.return_value = [item()]
    inventory.items.get_details.return_value = [item()]
    monkeypatch.setattr(cli, "get_inventory_client", lambda: inventory)
    monkeypatch.setattr(cli, "get_sheet_client", lambda: sheet)
    layout = tmp_path / "layout.csv"
    layout.write_text("item_id,group,subgroup,group_order,subgroup_order,item_order\n1,Rack A,Top,1,1,1\n")
    assert cli.main(["--purchase-account-id", "account", "--layout-csv", str(layout), "--sheet-id", "workbook"]) == 0
    assert [call.args for call in sheet.add_sheet.call_args_list] == [
        ("workbook", "Flat"), ("workbook", "Sheet1"), ("workbook", "Mapping"),
    ]
    assert sheet.add_rows.call_args_list[0].args[1] == "Flat"
    assert sheet.add_rows.call_args_list[1].args[1] == "Sheet1"
    assert sheet.add_rows.call_args_list[2].args[1] == "Mapping"


def test_cli_bad_layout_does_not_call_api(monkeypatch, tmp_path):
    factory = MagicMock()
    monkeypatch.setattr(cli, "get_inventory_client", factory)
    layout = tmp_path / "bad.csv"
    layout.write_text("sku\nABC\n")
    assert cli.main(["--purchase-account-id", "account", "--layout-csv", str(layout)]) == 1
    factory.assert_not_called()


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
    sheet.list_sheets.return_value = ["Sheet1"]
    count = build_stock_count([item("1", sku="SKU-1")], purchase_account_id="account")
    result = write_mapping_to_sheet(
        sheet, workbook_id="wb", worksheet_name="Mapping", count=count, count_worksheet_name="Sheet1",
    )
    assert result.created_worksheet is True
    assert result.rows_written == 1
    sheet.add_sheet.assert_called_once_with("wb", "Mapping")
    # Headers set for MAPPING_FIELDS (5 fields)
    assert sheet.set_cell.call_count == 5
    rows = sheet.add_rows.call_args.args[2]
    assert rows[0]["sku"] == "SKU-1"
    assert rows[0]["cell"] == "B4"
    assert rows[0]["stock_on_hand_cell"] == "H4"


def test_write_mapping_preserves_custom_cells():
    sheet = MagicMock()
    sheet.list_sheets.return_value = ["Sheet1", "Mapping"]
    sheet.get_rows.return_value = [
        {"row_index": 2, "sku": "SKU-1", "cell": "D10", "stock_on_hand_cell": "E10"},
    ]
    count = build_stock_count([item("1", sku="SKU-1")], purchase_account_id="account")
    result = write_mapping_to_sheet(
        sheet, workbook_id="wb", worksheet_name="Mapping", count=count, count_worksheet_name="Sheet1",
    )
    assert result.created_worksheet is False
    sheet.delete_rows.assert_called_once_with("wb", "Mapping", [2])
    rows = sheet.add_rows.call_args.args[2]
    assert rows[0]["sku"] == "SKU-1"
    assert rows[0]["cell"] == "D10"
    assert rows[0]["stock_on_hand_cell"] == "E10"


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
        sheet, workbook_id="wb", count_worksheet_name="Sheet1", count=count, mapping_rows=mappings,
    )
    assert updated == 1
    assert sheet.set_cell.call_args_list == [
        (("wb", "Sheet1", 4, 2, "15"),),
        (("wb", "Sheet1", 4, 8, "20"),),
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
        sheet, workbook_id="wb", count_worksheet_name="Sheet1", count=count,
        mapping_worksheet_name="Mapping",
    )
    assert updated == 1
    sheet.get_rows.assert_called_once_with("wb", "Mapping", limit=1000)
    sheet.set_cell.assert_called_once_with("wb", "Sheet1", 8, 3, "7")
