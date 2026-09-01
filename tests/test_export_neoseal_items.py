from scripts.export_neoseal_items import build_parser, export_row


def test_purchase_account_id_is_required() -> None:
    parser = build_parser()
    try:
        parser.parse_args([])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("purchase account ID must be required")


def test_export_row_preserves_vendor_alias_and_flags_missing_value() -> None:
    populated = export_row(
        {
            "item_id": "item-1",
            "name": "105 PVC Solution 500ml (Tin)",
            "sku": "105-500-PVC-CLR-TIN",
            "alias_name": "  NEOSEAL 105 PVC SOLUTION - 500ML TIN CAN  ",
            "manufacturer": "Neoseal",
        }
    )
    assert populated["alias_name"] == "NEOSEAL 105 PVC SOLUTION - 500ML TIN CAN"
    assert populated["has_alias_name"] == "true"

    missing = export_row({"item_id": "item-2", "manufacturer": "Neoseal"})
    assert missing["alias_name"] == ""
    assert missing["has_alias_name"] == "false"
