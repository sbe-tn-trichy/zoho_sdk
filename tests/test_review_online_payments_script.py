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
batch = {entries: [{id: 'p1', reviewable: true}], bank_suggestions: [
  {transaction_id: 'ta1', kind: 'travel_allowance', description: 'Alice/TA'},
  {transaction_id: 'd1', kind: 'deposit', description: 'Customer deposit'}
]};
document.getElementById('filter').value = 'all';
batch.entries = [
  {id: 'missing', creator: {customer_name: 'No bank customer'}},
  {id: 'match', bank: {date: '2026-10-01', description: 'Matched narration'}, creator: {customer_name: 'Matched customer'}},
  {id: 'possible', possible_candidates: [{transaction_id: 'candidate', description: 'Possible narration'}], creator: {customer_name: 'Possible customer'}}
];
render();
assert.equal(document.getElementById('bankTab')['aria-selected'], 'true');
assert.doesNotMatch(document.getElementById('rows').innerHTML, /No bank customer/);
assert.ok(document.getElementById('rows').innerHTML.indexOf('Matched narration') < document.getElementById('rows').innerHTML.indexOf('Matched customer'));
assert.match(document.getElementById('rows').innerHTML, /Unmatched records/);
setPrimaryView('creator');
assert.equal(document.getElementById('otherBankLines').hidden, true);
assert.match(document.getElementById('rows').innerHTML, /No bank customer/);
assert.ok(document.getElementById('rows').innerHTML.indexOf('Matched customer') < document.getElementById('rows').innerHTML.indexOf('Matched narration'));
assert.ok(document.getElementById('rows').innerHTML.indexOf('Matched customer') < document.getElementById('rows').innerHTML.indexOf('No bank customer'));
setPrimaryView('bank');
document.getElementById('search').value = 'absent'; render();
assert.match(document.getElementById('rows').innerHTML, /Matched records .* · 0/);
document.getElementById('search').value = '';
document.getElementById('filter').value = 'expenses'; render();
assert.equal(document.getElementById('paymentTable').hidden, true);
assert.equal(document.getElementById('acceptSelected').hidden, true);
assert.match(document.getElementById('bankRows').innerHTML, /Alice\/TA/);
assert.match(document.getElementById('bankRows').innerHTML, /Categorize expense/);
assert.doesNotMatch(document.getElementById('bankRows').innerHTML, /Customer deposit/);
toggleVisibleExpenses(true);
assert.deepEqual([...selectedExpenses], ['ta1']);
assert.equal(document.getElementById('categorizeSelectedExpenses').disabled, false);
toggleVisibleExpenses(false);
assert.equal(selectedExpenses.size, 0);
document.getElementById('search').value = 'missing'; render();
assert.match(document.getElementById('bankRows').innerHTML, /No expense proposals/);
document.getElementById('search').value = 'alice'; render();
assert.match(document.getElementById('bankRows').innerHTML, /Alice\/TA/);
document.getElementById('search').value = '';
document.getElementById('filter').value = 'reviewable'; render();
assert.equal(document.getElementById('paymentTable').hidden, false);
assert.equal(document.getElementById('acceptSelected').hidden, false);
assert.match(document.getElementById('bankRows').innerHTML, /Customer deposit/);
batch.bank_suggestions = []; document.getElementById('filter').value = 'expenses'; render();
assert.match(document.getElementById('bankRows').innerHTML, /No expense proposals/);
batch.bank_suggestions = [
  {transaction_id: 'ok', kind: 'travel_allowance'},
  {transaction_id: 'bad', kind: 'travel_allowance'},
  {transaction_id: 'done', kind: 'travel_allowance', categorization_status: 'categorized'}
];
toggleVisibleExpenses(true);
assert.deepEqual([...selectedExpenses], ['ok', 'bad']);
const calls = [];
api = async path => {
  calls.push(path);
  if (path.includes('/bad/')) throw new Error('Changed bank line');
  if (path === '/api/batch') return batch;
  batch.bank_suggestions[0].categorization_status = 'categorized';
  return {};
};
categorizeSelectedExpenses().then(() => {
  assert.deepEqual(calls, ['/api/bank-lines/ok/categorize', '/api/bank-lines/bad/categorize', '/api/batch']);
  assert.deepEqual([...selectedExpenses], ['bad']);
  assert.equal(expensesBusy, false);
  assert.match(document.getElementById('notice').textContent, /1 expenses categorized; 1 failed/);
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
        self.assertIn('<option value="possible">Possible matches</option>', HTML)
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
