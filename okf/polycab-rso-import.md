---
type: Concept
title: Polycab RSO Import
description: Parsing Polycab return-sales-order PDFs into Zoho Books sales orders with duplicate and attachment handling.
tags: [polycab, rso, sales-orders, pdf, zoho-books]
sources:
  - id: rso-processor
    resource: https://github.com/sbe-tn-trichy/zoho_sdk/blob/main/src/workflows/polycab_rso/processor.py
    title: Polycab RSO processor
    author: team:sbe-tn-trichy
    last_modified: 2026-08-17
status: active
---

# Polycab RSO Import

`parse_polycab_rso_pdf(pdf_path)` reads a machine-readable Polycab Sales Order
PDF and extracts its external sales-order number, customer metadata, entered and
booked dates, order type, subtotal, grand total, and item SKU/quantity/rate rows.

Polycab PDFs repeat the products in a later `LINE DETAILS` table. The parser
starts at the first `ITEM DETAILS` heading and stops at the first `Total Rs.`
row. It requires contiguous item sequence numbers and reconciles the parsed line
amounts to that subtotal before returning data. Rows after the total are never
eligible for import.

`import_polycab_rso_pdf(books_client, pdf_path, customer_id, location_id)`:

1. Parses and validates the PDF without mutating Books.
2. Finds an existing sales order using the RSO number as either the reference or
   sales-order number.
3. Resolves every unique Polycab SKU to an existing Books item, trying both the
   compact printed code and the Books convention with a hyphen after its
   six-character prefix, and refuses to create the order if any SKU is missing.
   Approved replacements currently map `FTANSST033P` to `FTANSS-T024P` and
   `FCEECST303M` to `FCEECS-T187M`, and `LDO0119012` to
   `LP0302-012RDCW` before lookup.
4. Creates one sales-order line per first-table PDF row, preserving duplicate
   SKUs that occur on distinct source rows.
5. Sends the configured customer and location IDs, using Sri Bharath
   Electricals as the default location.
6. Attaches the source PDF through the Books Sales Order attachment endpoint.

If the order already exists, creation is skipped. A missing attachment is added;
an attachment already reported by Books is left unchanged. The CLI entry point
is `python scripts/import_polycab_rso.py <pdf-path>`.
