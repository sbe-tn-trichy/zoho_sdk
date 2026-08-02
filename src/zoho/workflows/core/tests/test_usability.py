import unittest
from zoho.workflows import (
    DotDict,
    ZohoUsableError,
    ZohoAuthError,
    LedgerParsingError,
    ReconciliationError
)

class TestUsability(unittest.TestCase):
    def test_dot_dict_basic(self):
        d = DotDict({"a": 1, "b": {"c": 2}})
        self.assertEqual(d.a, 1)
        self.assertEqual(d["a"], 1)
        
        # Verify nested wrapping
        self.assertTrue(isinstance(d.b, DotDict))
        self.assertEqual(d.b.c, 2)
        self.assertEqual(d.b["c"], 2)

    def test_dot_dict_list_wrapping(self):
        d = DotDict({
            "items": [
                {"name": "item1"},
                {"name": "item2"}
            ]
        })
        self.assertEqual(len(d.items), 2)
        self.assertTrue(isinstance(d.items[0], DotDict))
        self.assertEqual(d.items[0].name, "item1")

    def test_dot_dict_list_of_tuples_wrapping(self):
        d = DotDict({
            "matches": [
                ({"tx_id": "tx1"}, {"payment_id": "pay1"})
            ]
        })
        self.assertEqual(len(d.matches), 1)
        bank_tx, payment = d.matches[0]
        self.assertTrue(isinstance(bank_tx, DotDict))
        self.assertTrue(isinstance(payment, DotDict))
        self.assertEqual(bank_tx.tx_id, "tx1")
        self.assertEqual(payment.payment_id, "pay1")

    def test_dot_dict_attribute_errors(self):
        d = DotDict({"a": 1})
        with self.assertRaises(AttributeError):
            _ = d.non_existent
            
        with self.assertRaises(AttributeError):
            del d.non_existent

    def test_dot_dict_deletion(self):
        d = DotDict({"a": 1})
        self.assertEqual(d.a, 1)
        del d.a
        self.assertNotIn("a", d)

    def test_custom_exceptions_catchability(self):
        # Verify specific exception inherits from ZohoUsableError and ValueError
        try:
            raise ZohoAuthError("Auth failed")
        except ZohoAuthError as e:
            self.assertEqual(str(e), "Auth failed")
            
        try:
            raise ZohoAuthError("Auth failed")
        except ZohoUsableError as e:
            self.assertEqual(str(e), "Auth failed")
            
        try:
            raise ZohoAuthError("Auth failed")
        except ValueError as e:
            self.assertEqual(str(e), "Auth failed")

        # Verify LedgerParsingError
        try:
            raise LedgerParsingError("Parse error")
        except ValueError as e:
            self.assertEqual(str(e), "Parse error")

        # Verify ReconciliationError
        try:
            raise ReconciliationError("Process error")
        except ValueError as e:
            self.assertEqual(str(e), "Process error")
