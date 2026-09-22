"""Read-only hints for uncategorized Books bank statement lines."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from ..core.matching import to_text


_SPACES = re.compile(r"[^a-z0-9]+")
_TA_SUFFIX = re.compile(r"(?:^|/)TA\s*$", re.IGNORECASE)

GENERIC_NARRATION_TOKENS = {
    "upi", "cr", "dr", "no remark", "payment from ph", "sent using payt",
    "payment", "fund transfer", "bill", "urgent", "ta", "salary",
    "imps", "neft", "rtgs", "chq dep", "cts clg", "cts clg1", "by transfer",
    "transfer", "credit", "debit", "auto sweep", "sweep", "sweepout", "funds insufficient",
    "chq dep ret", "neft cr", "neft dr", "inward", "outward", "interest", "charges",
}

GENERIC_BANKS = {
    "state bank of i", "state bank of india", "indian bank", "indian overseas",
    "canara bank", "hdfc bank ltd", "hdfc", "icici", "union bank of i",
    "karur vysa bank", "city union bank", "axis bank", "bank of india",
    "idfc", "idfc first bank", "idfc bank", "idfc fir", "kotak", "kotak mahindra",
    "sbi", "sbin", "ioba", "ubin", "idib", "ciub", "hdfcbank", "okaxis",
    "okhdfcbank", "oksbi", "okicici", "ybl", "ibl", "axl", "ptyes", "ptsbi",
}


def extract_remitter_tokens(description: Any) -> list[str]:
    """Extract distinct search tokens (UPI VPA, phone, remitter name) from bank narration."""
    text = to_text(description).strip()
    if not text:
        return []
    tokens: set[str] = set()

    # 1. 10-digit mobile numbers
    for m in re.finditer(r"\b[6-9]\d{9}\b", text):
        tokens.add(m.group(0))

    # 2. VPA handles (e.g. user@bank, user@okaxis)
    for m in re.finditer(r"[a-zA-Z0-9._]{3,}@[a-zA-Z0-9]+", text):
        vpa = m.group(0)
        tokens.add(vpa)
        prefix = vpa.split("@")[0]
        if len(prefix) >= 5 and not re.match(r"^x+$", prefix, re.IGNORECASE):
            tokens.add(prefix)

    # 3. Delimited segments
    for seg in re.split(r"[/:\-]", text):
        s = seg.strip(" -/:._")
        s_lower = s.lower()
        if (
            len(s) >= 4
            and s_lower not in GENERIC_NARRATION_TOKENS
            and s_lower not in GENERIC_BANKS
            and not (s.isdigit() and len(s) != 10)  # non-phone numbers (amounts, cheques, years)
            and not re.match(r"^\d{10,}$", s)  # reference number or phone already handled
            and not re.match(r"^x+\d*$", s, re.IGNORECASE)  # masked account xxxxx6216
            and not re.match(r"^[a-zA-Z]{4}0[0-9a-zA-Z]{6}$", s)  # IFSC code
            and not re.match(r"^[a-zA-Z0-9]{12,}$", s)  # bank hashes / UTRs without spaces
            and not any(sw in s_lower for sw in ("sweep", "fd 10", "charge", "interest"))
        ):
            tokens.add(s)

    return sorted(tokens, key=lambda x: (-len(x), x))


def _words(value: Any) -> str:
    return " ".join(_SPACES.sub(" ", to_text(value).casefold()).split())


def is_travel_allowance_withdrawal(transaction: Mapping[str, Any]) -> bool:
    direction = to_text(transaction.get("debit_or_credit") or transaction.get("transaction_type")).casefold()
    return direction in {"credit", "withdrawal", "expense"} and bool(
        _TA_SUFFIX.search(to_text(transaction.get("description") or transaction.get("narration")))
    )


class CustomerFinderIndex:
    """Index Finder names and narrations once for a bank statement refresh."""

    def __init__(self, finder_rows: Sequence[Mapping[str, Any]]) -> None:
        self.aliases: dict[str, set[str]] = {}
        self.descriptions: dict[str, set[str]] = {}
        for row in finder_rows:
            if not isinstance(row, Mapping):
                continue
            name = to_text(row.get("Customer Name"))
            normalized = _words(name)
            if not normalized:
                continue
            for alias in {normalized, _words(name.split(" - ", 1)[0])}:
                if len(alias) >= 8 and len(alias.split()) >= 2:
                    self.aliases.setdefault(alias, set()).add(name)
            description = _words(row.get("Description"))
            if len(description) >= 12:
                self.descriptions.setdefault(description, set()).add(name)

    def suggest(self, transaction: Mapping[str, Any]) -> list[str]:
        description = _words(transaction.get("description") or transaction.get("narration"))
        if not description:
            return []
        names = set(self.descriptions.get(description, ()))
        padded = f" {description} "
        for alias, matching_names in self.aliases.items():
            if f" {alias} " in padded:
                names.update(matching_names)
        return sorted(names, key=str.casefold)


def customer_name_suggestions(
    transaction: Mapping[str, Any], finder_rows: Sequence[Mapping[str, Any]]
) -> list[str]:
    """Find customer names from matching Finder names or descriptions."""
    return CustomerFinderIndex(finder_rows).suggest(transaction)


def bank_line_kind(transaction: Mapping[str, Any]) -> str:
    kind = to_text(transaction.get("debit_or_credit") or transaction.get("transaction_type")).casefold()
    if is_travel_allowance_withdrawal(transaction):
        return "travel_allowance"
    if kind in {"debit", "deposit", "income"}:
        return "deposit"
    if kind in {"credit", "withdrawal", "expense"}:
        return "withdrawal"
    return "other"
