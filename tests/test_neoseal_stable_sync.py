"""Stable count-page references survive Mapping reorder and product row moves."""

from workflows.neoseal_stock_count.stable_sync import build_stable_sync_plan


FLAT = {
    1: {1: "item_id", 2: "sku", 5: "available_quantity", 12: "packing"},
    2: {1: "101", 2: "SKU-A", 5: "3", 12: "24"},
    3: {1: "102", 2: "SKU-B", 5: "4", 12: "24"},
}
MAPPING = {
    1: {1: "sku", 2: "cell", 3: "name", 4: "item_id", 5: "stock_on_hand_cell", 6: "line_id"},
    2: {1: "SKU-A", 2: "C3", 3: "Product", 4: "101", 6: "SC-1"},
    3: {1: "SKU-B", 2: "C3", 3: "Product", 4: "102", 6: "SC-1"},
}
COUNT = {
    1: {1: "PRODUCT", 2: "PACK", 3: "QTY", 6: "PRODUCT", 7: "PACK", 8: "QTY",
        10: "left_line_id", 11: "right_line_id"},
    3: {1: "Product", 2: "24", 3: "7", 10: "SC-1"},
}


def test_reordered_mapping_keeps_sku_formulas_and_aggregates_duplicates():
    first = build_stable_sync_plan(FLAT, MAPPING, COUNT)
    reordered = {1: MAPPING[1], 2: MAPPING[3], 3: MAPPING[2]}
    second = build_stable_sync_plan(FLAT, reordered, COUNT)
    assert '"SKU-A"' in first.formulas["C3"]
    assert '"SKU-B"' in first.formulas["C3"]
    assert set(first.formulas) == set(second.formulas)
    assert first.new_line_ids == 0
    assert not first.changes


def test_moved_product_row_updates_mapping_address_by_line_id():
    moved = {1: COUNT[1], 5: COUNT[3]}
    plan = build_stable_sync_plan(FLAT, MAPPING, moved)
    assert {"B5", "C5"} == set(plan.formulas)
    assert {(c.sheet, c.row, c.column, c.content) for c in plan.changes} == {
        ("Mapping", 2, 2, "C5"), ("Mapping", 3, 2, "C5")
    }


def test_new_flat_item_is_reported_without_automatic_placement():
    extra = dict(FLAT)
    extra[4] = {1: "103", 2: "SKU-C", 5: "8", 12: "12"}
    plan = build_stable_sync_plan(extra, MAPPING, COUNT)
    assert plan.unplaced_skus == ("SKU-C",)
