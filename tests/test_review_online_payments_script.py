import io
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from apps.payment_review import HTML, _clients, main
from workflows.core.config import Config


class TestReviewOnlinePaymentsScript(unittest.TestCase):
    def test_expenses_filter_search_empty_and_return_to_payments(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is needed to exercise the review JavaScript")
        self.assertIn('<option value="expenses">Expenses</option>', HTML)
        script = re.search(r"<script>(.*?)</script>", HTML, re.DOTALL).group(1)
        harness = r"""
const vm = require('node:vm');
const assert = require('node:assert/strict');
const elements = new Map();
const document = {
  querySelector() { return {content: 'token'}; },
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, {value: '', style: {}, addEventListener() {}, setAttribute(name, value) { this[name] = value; }});
    return elements.get(id);
  }
};
vm.runInNewContext(require('node:fs').readFileSync(0, 'utf8') + String.raw`
assert.equal(dateSortKey('31-Feb-2026'), Infinity);
assert.equal(dateSortKey('bad'), Infinity);
assert.equal(compareDates('', ''), 0);
assert.equal(compareDates('03-Oct-2026', '2026-10-03'), 0);
assert.equal(compareDates('03/10/2026', '2026-10-03'), 0);
const savedBatch = batch;
batch = {entries: [
  {id: 'later', creator: {date: '05-Oct-2026'}},
  {id: 'missing', creator: {date: ''}},
  {id: 'early', creator: {date: '2026-09-30'}},
  {id: 'tie', creator: {date: '30-Sep-2026'}}
], bank_records: [
  {transaction_id: 'later', date: '2026-10-05', kind: 'salary'},
  {transaction_id: 'missing', date: '', kind: 'salary'},
  {transaction_id: 'early', date: '2026-09-30', kind: 'salary'}
]};
document.getElementById('source').value = 'creator';
document.getElementById('category').value = 'customers';
document.getElementById('filter').value = 'unmatched';
assert.deepEqual(visiblePayments().map(e => e.id), ['early', 'tie', 'later', 'missing']);
assert.equal(batch.entries[0].id, 'later');
document.getElementById('source').value = 'bank';
document.getElementById('category').value = 'expenses';
document.getElementById('filter').value = 'reviewable';
assert.deepEqual(visibleBankRows().map(e => e.transaction_id), ['early', 'later', 'missing']);
assert.equal(batch.bank_records[0].transaction_id, 'later');
batch = savedBatch;
document.getElementById('source').value = 'bank';
document.getElementById('category').value = 'customers';
document.getElementById('filter').value = 'reviewable';
batch = {entries: [
  {id: 'missing', creator: {customer_name: 'No bank customer'}},
  {id: 'match', reviewable: true, bank_account_id: 'bank', bank: {transaction_id: 'matched', description: 'Matched narration'}, creator: {customer_name: 'Matched customer'}},
  {id: 'possible', possible_candidates: [{transaction_id: 'candidate'}]},
  {id: 'conflict', bank: {}, customer_name_valid: false},
  {id: 'done', reviewable: true, bank: {}, push_status: 'pushed'}
], bank_suggestions: [
  {transaction_id: 'ta1', kind: 'travel_allowance', description: 'Alice/TA'},
  {transaction_id: 'salary', kind: 'salary'},
  {transaction_id: 'vendor', kind: 'vendor_advance'},
  {transaction_id: 'cash', kind: 'cash_deposit'},
  {transaction_id: 'unknown', kind: 'deposit'},
  {transaction_id: 'matched', bank_account_id: 'bank', kind: 'deposit', creator_entry_ids: ['match']},
  {transaction_id: 'uncertain', kind: 'deposit', creator_entry_ids: ['possible', 'conflict']}
]};
batch.bank_records = batch.bank_suggestions;
render();
assert.equal(visiblePayments().length, 0);
assert.deepEqual(visibleBankRows().map(e => e.transaction_id), ['matched']);
assert.match(document.getElementById('bankRows').innerHTML, /Matched customer/);
assert.match(document.getElementById('bankRows').innerHTML, /Accept &amp; Push/);
assert.equal(document.getElementById('paymentTable').hidden, true);
document.getElementById('filter').value = 'ambiguous'; render();
assert.equal(visiblePayments().length, 0);
assert.deepEqual(visibleBankRows().map(e => e.transaction_id), ['uncertain']);
document.getElementById('filter').value = 'unmatched'; render();
assert.equal(visiblePayments().length, 0);
assert.deepEqual(visibleBankRows().map(e => e.transaction_id), ['unknown']);
document.getElementById('source').value = 'creator'; render();
assert.deepEqual(visiblePayments().map(e => e.id), ['missing']);
assert.equal(document.getElementById('otherBankLines').hidden, true);
document.getElementById('category').value = 'expenses'; render();
assert.equal(document.getElementById('emptyCategory').hidden, false);
assert.equal(visibleBankRows().length, 0);
document.getElementById('source').value = 'bank';
document.getElementById('filter').value = 'reviewable'; render();
assert.equal(document.getElementById('paymentTable').hidden, true);
assert.deepEqual(visibleBankRows().map(e => e.transaction_id), ['ta1', 'salary']);
toggleVisibleBankLines(true);
assert.deepEqual([...selectedBankLines], ['ta1', 'salary']);
toggleVisibleBankLines(false);
document.getElementById('search').value = 'alice'; render();
assert.deepEqual(visibleBankRows().map(e => e.transaction_id), ['ta1']);
document.getElementById('search').value = 'absent'; render();
assert.match(document.getElementById('bankRows').innerHTML, /No records match/);
document.getElementById('search').value = '';
document.getElementById('category').value = 'vendors'; render();
assert.deepEqual(visibleBankRows().map(e => e.transaction_id), ['vendor']);
toggleVisibleBankLines(true); assert.deepEqual([...selectedBankLines], ['vendor']);
toggleVisibleBankLines(false);
assert.equal(document.getElementById('selectBankLines').hidden, false);
assert.match(document.getElementById('bankRows').innerHTML, /Select bank line/);
document.getElementById('category').value = 'transfers'; render();
assert.deepEqual(visibleBankRows().map(e => e.transaction_id), ['cash']);
toggleVisibleBankLines(true); assert.deepEqual([...selectedBankLines], ['cash']);
toggleVisibleBankLines(false);
assert.equal(document.getElementById('categorizeSelectedBankLines').hidden, false);
document.getElementById('filter').value = 'ambiguous'; render();
assert.equal(visibleBankRows().length, 0);
document.getElementById('category').value = 'expenses';
document.getElementById('filter').value = 'reviewable';
batch.bank_suggestions = [
  {transaction_id: 'ok', kind: 'travel_allowance'},
  {transaction_id: 'bad', kind: 'travel_allowance'},
  {transaction_id: 'done', kind: 'travel_allowance', categorization_status: 'categorized'}
];
batch.bank_records = batch.bank_suggestions;
toggleVisibleBankLines(true);
assert.deepEqual([...selectedBankLines], ['ok', 'bad']);
const calls = [];
api = async path => {
  calls.push(path);
  if (path.includes('/bad/')) throw new Error('Changed bank line');
  if (path === '/api/batch') return batch;
  batch.bank_suggestions[0].categorization_status = 'categorized';
  return {};
};
categorizeSelectedBankLines().then(async () => {
  assert.deepEqual(calls, ['/api/bank-lines/ok/categorize', '/api/bank-lines/bad/categorize', '/api/batch']);
  assert.deepEqual([...selectedBankLines], ['bad']);
  assert.equal(bankLinesBusy, false);
  assert.match(document.getElementById('notice').textContent, /1 records categorized; 1 failed/);
  for (const [category, kind] of [['vendors', 'vendor_advance'], ['transfers', 'cash_deposit']]) {
    selectedBankLines.clear(); calls.length = 0;
    batch.bank_records = batch.bank_suggestions = [{transaction_id: 'ok', kind}, {transaction_id: 'bad', kind}];
    document.getElementById('category').value = category;
    toggleVisibleBankLines(true);
    assert.deepEqual([...selectedBankLines], ['ok', 'bad']);
    await categorizeSelectedBankLines();
    assert.deepEqual(calls, ['/api/bank-lines/ok/categorize', '/api/bank-lines/bad/categorize', '/api/batch']);
    assert.deepEqual([...selectedBankLines], ['bad']);
  }
}).catch(error => { console.error(error); process.exitCode = 1; });
`, {document, assert, console, process, confirm() {return true;}, setTimeout() {}, fetch() {return new Promise(() => {});}});
"""
        subprocess.run([node, "-e", harness], input=script, encoding="utf-8", check=True,
                       capture_output=True)

    def test_html_offers_ambiguous_review_with_candidate_details(self):
        self.assertIn('<option value="ambiguous">Ambiguous</option>', HTML)
        self.assertIn("e.ambiguous_candidates", HTML)
        self.assertIn("matching bank lines", HTML)

    def test_html_offers_possible_match_review_with_candidate_details(self):
        self.assertIn("isPossible(e) ? 'reviewable' : 'ambiguous'", HTML)
        self.assertIn("e.possible_candidates", HTML)
        self.assertIn("reference differs", HTML)
        self.assertIn("selectPossibleCandidate", HTML)
        self.assertIn("allow_reference_override", HTML)

    def test_html_offers_bank_line_suggestions_and_travel_categorization(self):
        self.assertIn("Other uncategorized bank lines", HTML)
        self.assertIn('id="bankRows"', HTML)
        self.assertIn("categorizeTravel", HTML)
        self.assertIn("/api/bank-lines/", HTML)
        self.assertIn("/categorize-travel", HTML)

    @patch("apps.payment_review.get_books_client")
    @patch("apps.payment_review.get_creator_client")
    def test_clients_use_centralized_factories(self, creator_factory, books_factory):
        creator, books = _clients("http://token", "owner", "org", "in")

        self.assertIs(creator, creator_factory.return_value)
        self.assertIs(books, books_factory.return_value)
        creator_factory.assert_called_once_with(
            owner_name="owner", domain="in", token_url="http://token"
        )
        books_factory.assert_called_once_with(
            org_id="org", domain="in", token_url="http://token"
        )

    @patch("apps.payment_review.OnlinePaymentReviewService")
    @patch("apps.payment_review.get_analytics_client")
    @patch("apps.payment_review._clients")
    @patch.object(
        Config,
        "PAYMENT_CREATOR_REPORTS",
        {
            "online": "Configured_Online",
            "cheque": "Configured_Cheques",
            "cheque_detail": "Configured_Cheque_Details",
            "customer": "Configured_Customers",
            "checkpoint": "Configured_All_Payments",
        },
    )
    def test_refresh_only_updates_preview_and_exits(self, clients, analytics_factory, service_class):
        clients.return_value = (MagicMock(), MagicMock())
        service_class.return_value.refresh.return_value = {
            "entries": [
                {"reviewable": True, "push_status": "not_started"},
                {"reviewable": False, "push_status": "not_started"},
            ]
        }

        with tempfile.TemporaryDirectory() as directory, patch(
            "sys.stdout", new_callable=io.StringIO
        ) as stdout:
            state = Path(directory) / "review.json"
            result = main(["--refresh-only", "--state", str(state)])

        self.assertEqual(result, 0)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {"entries": 2, "ready": 1, "other_bank_lines": 0, "state": str(state), "preview_cache_hits": {}},
        )
        review_config = service_class.call_args.args[2]
        self.assertEqual(
            review_config.payment_reports,
            (("Online", "Configured_Online"), ("Cheque", "Configured_Cheques")),
        )
        self.assertEqual(
            review_config.cheque_detail_report_link_name,
            "Configured_Cheque_Details",
        )
        self.assertEqual(
            review_config.customer_report_link_name,
            "Configured_Customers",
        )
        self.assertEqual(
            review_config.creator_checkpoint_report_link_name,
            "Configured_All_Payments",
        )
        service_class.return_value.refresh.assert_called_once_with(force_refresh=False)

    def test_handler_routes_categorize_travel_expense(self):
        from apps.payment_review import make_handler

        service = MagicMock()
        service.categorize_travel_expense.return_value = {
            "transaction_id": "tx-123",
            "categorization_status": "categorized",
        }
        handler_cls = make_handler(service, "test-token")
        handler = handler_cls.__new__(handler_cls)
        body = json.dumps({"confirm": True}).encode("utf-8")
        handler.headers = {"X-Review-Token": "test-token", "Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.path = "/api/bank-lines/tx-123/categorize-travel"
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        handler.do_POST()

        service.categorize_travel_expense.assert_called_once_with("tx-123")
        handler.send_response.assert_called_once_with(200)
        response = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(response["categorization_status"], "categorized")


if __name__ == "__main__":
    unittest.main()
