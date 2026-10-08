---
type: Concept
description: Paired customer registration in Books and Creator with explicit partial-failure recovery.
---

# Customer registration

`workflows.register_customer` receives Books and Creator clients and creates a
Books customer contact followed by a Creator `Customer_Registration` record.
Creator `Customer_Id` stores the returned Books `contact_id`, and `Customer_no`
(Customer#) stores Books `contact_number`. Registration uses the create/recovery
response number, falling back to contact detail if needed. A missing or blank
Books number stops Creator creation and reports the Books ID for recovery;
caller-supplied `Customer_no` is replaced by the Books number. Dry-run shows
the number as pending until creation or lookup. Results include `books_contact_number`. The default app is
`order-management-new`. Its registration form uses `Name`, which supplies the default Books
`contact_name`; all other Books fields must be supplied explicitly through
`books_data`. The former `Customer_Name` input is still accepted for custom forms;
use `Name` for the live registration form. Creator data and Books data are separate and are not mutated.

The workflow, `create_customer_record` helper and `apps/register_customer.py create`
create records by default. Use `dry_run=True` in Python or `--dry-run` on the CLI
to preview without writes. `--apply` remains accepted as an explicit creation flag.
The helper returns a structured paired result rather than the former Creator-only response.
The CLI retains `inspect` as its default action and accepts inline JSON:

```sh
.venv/bin/python apps/register_customer.py create '{"Name":"Example"}'
.venv/bin/python apps/register_customer.py create '{"Name":"Example"}' --dry-run --books-data '{"company_name":"Example"}'
```

Creator requests use `skip_workflow=["all"]` to prevent form automation from
creating another Books contact. This also skips other form workflows and schedules;
supply their required fields directly. See the
[Creator add-record API](https://www.zoho.com/creator/help/api/v2.1/add-records.html).

Creation is sequential, not atomic. No automatic rollback or retries are performed.
A Creator rejection, malformed response or transport exception raises
`CustomerRegistrationError` with `books_contact_id`. Check both services after
an uncertain response before retrying. The recovery flag
`--existing-books-contact-id ID` verifies an existing Books customer then creates
only the Creator record; it does not update the Books contact. Do not use recovery
if Creator already contains the record. A supplied Creator `Customer_Id` must
match the explicit recovery ID. Books transport errors or missing creation IDs
require inspecting Books before retrying. Repeated normal registrations create
new contacts; there is no automatic name-based deduplication.


## Targeted number backfill

`workflows.sync_customer_numbers` fills blank `Customer_no` fields for an explicit
list of Books contact IDs. `Customer_Id` matches each Books `contact_id`; the
Creator report must include `Customer_no`. The workflow defaults to preview,
validates the whole plan before writing, rejects duplicate links, missing Books
numbers, existing conflicting numbers and number collisions, and leaves matching
numbers unchanged. It never creates or deletes records. Applied updates skip
Creator automation and are reread to verify the number and linked Books ID.
An API or verification failure stops the run; prior writes are not rolled back.

```sh
.venv/bin/python apps/sync_customer_numbers.py --books-contact-id BOOKS_ID
.venv/bin/python apps/sync_customer_numbers.py --books-contact-id BOOKS_ID --apply
```

Repeat `--books-contact-id` for multiple customers. Backfill uses a separate
preview default; new registration still creates records by default.
