---
type: reference
description: Payment inspection and renumbering, customer validation and invoice-YAML workflow migration.
---

# Workflow helpers and API migration

## Shared workflow mechanics

Supported helpers are exported from `workflows.core`; their implementations stay
in small modules rather than a single generic workflow engine.

Generic Books document streaming and ordered labeled references are exported from
`zoho.helpers`. `format_reference_lines`, `parse_reference_lines` and
`update_reference_lines` retain repeated document labels and preserve unrelated
human notes while replacing managed lines idempotently. Polycab-specific PDF
interpretation, accounting eligibility, correction payloads and mutation guards
remain in the [credit-review domain package](polycab-credit-review.md); its
orchestrator contains only the review sequence.

- `core.snapshots.refresh_snapshot` owns scoped cache reuse, baseline freshness,
  complete 200-row change pagination, modified-time validation, ID overlays and
  atomic persistence. `SnapshotPolicy` carries schema/response keys and timestamp
  parsing; adapters provide Analytics loaders and converters. GSTR-2 bills retain
  the `bills` snapshot field and mandatory timezone timestamps; expense/credit
  snapshots retain `resource`/`rows`, alternate credit response keys and their
  Asia/Kolkata assumption for timezone-free row timestamps. Baseline freshness is
  checked before conversion. Adapters retain empty-data and tax-mapping rules.
- `core.payments` provides descending series request parameters, confirmed filter
  and sort validation, suffix extraction, and `PaymentState` read-back checks.
  Customer/vendor workflows pass their own response keys and bank-account fields,
  and retain allocation preflight, numbering, mutation and recovery policies.
- `PaymentEvidence`, `payment_evidence_matches` and `build_payment_indexes` share
  normalized reference/date/absolute-amount matching and native indexes. The two
  payment backfills retain opposite write directions and distinct identifier
  conflict rules. Customer-name matching is an explicit adapter; customer-ID
  matching does not substitute a display name.
- `core.matching.parse_currency_amount` preserves strict Decimal currency/grouping
  parsing for reviewed moves, including invalid-input exceptions. It does not
  impose a new finite/sign policy. `references_intersect` compares only nonempty,
  stripped, lowercased references; it does not remove punctuation.
- `core.checkpoint.atomic_text_writer` stages a unique file beside its target,
  preserves the prior target when formatting fails, closes before replacement,
  retries Windows file-lock errors and cleans staging files. `write_atomic_json`
  uses it and exposes indentation, ASCII escaping and serialization options.
  AIS, account mapping, collection review, payment-date checkpoints and GSTR-2
  snapshots use this shared persistence; GSTR-3B CSV retains its UTF-8 BOM.

Atomic replacement gives concurrent writers last-replacement-wins semantics,
not a read-modify-write transaction. Financial mutation and snapshot policies
remain in their domain workflows. Compatibility entry points are retained.

Generic document-number parsing lives in `zoho.helpers.sequences.parse_doc_number`.
It returns `(prefix, trailing_integer, observed_width)`; width zero means no
numeric suffix. The old Books GST import remains a lower-layer re-export.
`workflows.core.sequences.analyze_number_series` consumes supplied records only,
distinguishes blank/nonnumeric/numeric series, reports observed widths and
duplicates, and bounds missing-gap output using intervals rather than enumerated
integers. Gaps represent absent suffixes in the supplied population, not proof
of missing transactions across every fiscal year or location.

`workflows.core.dates.get_fy_date_range(value, reference_date=None)` returns
inclusive `date` boundaries and an identifier such as `2025-26`. Accepted input
includes current/previous aliases, two/four-digit consecutive pairs with `-` or
`/`, compact `2526`, and a four-digit start year. Four-digit values from 1900
through 2098 take precedence as start years. Other compact pairs use the 2000s;
supported resulting start years are 1900–2098. Invalid input raises `ValueError`.
Calendar comparisons reuse `workflows.core.matching.parse_date`; no implicit
`date`/`datetime` comparisons are supported.

## Payment applications

`workflows.payment_inspection` accepts an Analytics client and workspace ID,
fetches customer-payment records, filters calendar dates, and builds the existing
CLI summary fields with additive gap/duplicate/width metadata. Maximum observed
width in the legacy `digit_padding` field is not a guaranteed numbering policy.
Samples and mode ties are deterministic; date-filtered reports exclude invalid
dates. `apps/find_customer_payment_series.py` retains its flags and JSON/table
output. Invalid FY strings now fail rather than defaulting to last FY.

`workflows.payment_renumbering.build_renumber_plan` accepts a Books client,
Analytics discovery records, source/destination prefixes, inclusive dates, width,
and optional first sequence. It checks each live payment and reads every page of
Books customer payments to establish destination occupancy. Ordering is by date,
numeric original suffix and payment ID; intraday timestamp ordering is not used.
The previous fixed sequence ceiling and payment-specific recovery exception have
been removed.

`execute_renumbering` defaults to read-only dry-run. Execution requires a checkpoint
callback, preflights the entire batch, rechecks each source, submits an explicit
number-series update with the unchanged location, and verifies number and
financial fields including allocations through read-back. Checkpoints record
submission before the API call and preserve pending/completed rows. A failure
stops the batch and requires live-state reconciliation before resume; a verified
prior row that no longer matches is rejected. There is no automatic API rollback
or blind retry of an uncertain mutation, and concurrent writers can still race
destination checks. This refactor was verified with mocked requests, not live
renumbering.

`apps/renumber_sbe2627_payments.py` remains the FY-specific runner. It retains
`--execute` and `--output-dir`, adds explicit period/prefix/width/workspace/start
sequence options, and writes a unique audit before execution using the shared
atomic JSON writer. `--resume PATH` uses the exact saved plan, rather than
regenerating assignments; discovery options do not alter a resumed plan. Schema
version 1 is required; legacy reports are not automatically converted. Audit
files contain operational data and remain in ignored `output/`. Incomplete
execution exits unsuccessfully.

## Customer validation breaking migration

The SDK `ZohoBooksAPI.customer_validator` binding and
`zoho.books.resources.customer_validator` import were removed. Use:

```python
from workflows.customer_validation import CustomerValidator

report = CustomerValidator(books_client).validate_customer_data(limit=100)
offline_report = CustomerValidator().validate_records(contact_records)
```

Rules retain the existing geography, casing, phone, and required custom-field
behavior. Reports add selected/failed counts and failed contact IDs; failures are
not counted as successfully processed or compliant contacts. Fetching filters
vendor records locally and rejects missing/mismatched detail identity. Pure rule
validation requires no client. No SDK forwarder imports workflows.

## Sales-order import breaking migration

`SalesOrders.create_from_yaml` was removed. Use:

```python
from workflows.sales_order_import import create_sales_order_from_yaml

result = create_sales_order_from_yaml(
    books_client, invoice_yaml, customer_id,
    inventory_client=inventory_client, purchase_account_id=purchase_account_id,
)
```

The parser supports the existing flat/indented scalar invoice dialect, including
legacy `False` invoice-number keys and `DD.MM.YYYY`/ISO dates. It is not a general
YAML loader. Every line requires SKU, name, positive finite quantity and
nonnegative finite rate; invalid lines abort before API calls instead of being
silently dropped. Inventory lookups require exact SKU matches; vendor-scoped
imports supply `purchase_account_id`. Duplicate SKU lines reuse resolved IDs.

Missing-item creation remains opt-in and requires sales, purchase and inventory
accounts. `ItemCreationPolicy` exposes the existing heater/fan HSN, tax, unit and
purchase-rate rules. All lines and creation policy inputs are validated before
mutation. An import failure after mutation raises `SalesOrderImportError` with
known created item IDs; it does not delete items. Number fallback occurs only for
structured Books error code 4097. Transport uncertainty still requires manual
reconciliation; order creation is not an atomic transaction with item creation.

Creator registration stays as a thin application using native Creator operations;
there is no new domain contract that justifies adding redundant CRUD wrappers to
the customer-sync workflow.

Related: [Architecture](architecture.md), [Books](zoho-books.md),
[Inventory routing](zoho-inventory.md).
