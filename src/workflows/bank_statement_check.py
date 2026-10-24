"""Read-only HDFC CSV comparison against Analytics' Books statement lines."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import csv
import re
from typing import Any, Literal, Mapping, Sequence

from workflows.analytics_catalog import AnalyticsCatalog
from workflows.core.matching import normalize_payment_reference, parse_currency_amount, parse_date, to_text

DEFAULT_WORKSPACE_ID = "264324000000002043"
DEFAULT_VIEW_ID = "264324000005829009"


@dataclass(frozen=True)
class StatementLine:
    source_id: str
    date: date
    direction: Literal["deposit", "withdrawal"]
    amount: Decimal
    reference: str
    description: str


@dataclass(frozen=True)
class LineResult:
    line: StatementLine
    status: Literal["matched", "probable", "missing", "duplicate_shortfall", "review"]
    books_line_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class StatementComparison:
    account_id: str
    start: date
    end: date
    csv_count: int
    books_count: int
    results: tuple[LineResult, ...]
    unmatched_books_ids: tuple[str, ...]


def _amount(value: Any, context: str) -> Decimal:
    try:
        amount = parse_currency_amount(value)
        if not amount.is_finite() or amount < 0 or amount != amount.quantize(Decimal("0.01")):
            raise ValueError("invalid amount")
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{context}: expected a nonnegative INR amount in paise, got {value!r}") from exc
    return amount


def read_hdfc_csv(path: Path) -> list[StatementLine]:
    """Read the seven-column HDFC export without coercing reference numbers."""
    lines = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        expected = {"Date", "Narration", "Chq./Ref.No.", "Value Dt", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"}
        if reader.fieldnames is None or len(reader.fieldnames) != len(expected) or set(reader.fieldnames) != expected:
            raise ValueError("Expected HDFC CSV headers: " + ", ".join(sorted(expected)))
        for row in reader:
            context = f"CSV line {reader.line_num}"
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{context}: malformed CSV column count")
            try:
                posted = datetime.strptime(row["Date"].strip(), "%d/%m/%y").date()
                datetime.strptime(row["Value Dt"].strip(), "%d/%m/%y")
            except ValueError as exc:
                raise ValueError(f"{context}: invalid HDFC date") from exc
            withdrawal = _amount(row["Withdrawal Amt."], context) if row["Withdrawal Amt."].strip() else Decimal(0)
            deposit = _amount(row["Deposit Amt."], context) if row["Deposit Amt."].strip() else Decimal(0)
            if (withdrawal > 0) == (deposit > 0):
                raise ValueError(f"{context}: exactly one positive deposit or withdrawal is required")
            lines.append(StatementLine(str(reader.line_num), posted,
                "deposit" if deposit else "withdrawal", deposit or withdrawal,
                row["Chq./Ref.No."].strip(), row["Narration"].strip()))
    if not lines:
        raise ValueError("HDFC CSV contains no transactions")
    return lines


def parse_analytics_lines(rows: Sequence[Mapping[str, Any]], *, account_id: str,
                          start: date, end: date) -> list[StatementLine]:
    """Validate every scoped row; Analytics debit means deposit for this table."""
    lines = []
    seen: set[str] = set()
    for row in rows:
        identifier = to_text(row.get("Statement Line ID"))
        if to_text(row.get("Account ID")) != account_id:
            raise ValueError(f"Analytics line {identifier}: account differs from requested account")
        posted = parse_date(row.get("Date"))
        if posted is None or not start <= posted <= end:
            raise ValueError(f"Analytics line {identifier}: invalid or out-of-period date")
        if not identifier or identifier in seen:
            raise ValueError(f"Missing or duplicate Analytics Statement Line ID: {identifier!r}")
        seen.add(identifier)
        direction = to_text(row.get("Debit or Credit")).casefold()
        if direction not in {"debit", "credit"}:
            raise ValueError(f"Analytics line {identifier}: unknown direction {direction!r}")
        amount = _amount(row.get("Amount"), f"Analytics line {identifier}")
        if amount == 0:
            raise ValueError(f"Analytics line {identifier}: zero amount")
        lines.append(StatementLine(identifier, posted,
            "deposit" if direction == "debit" else "withdrawal", amount,
            to_text(row.get("Reference Number")), to_text(row.get("Description"))))
    return lines


def _reference(value: str) -> str:
    normalized = normalize_payment_reference(value)
    return normalized.lstrip("0") if normalized.isdigit() else normalized


def _description(value: str) -> str:
    return " ".join(value.casefold().split())


def _narration_matches(left: str, right: str) -> bool:
    left, right = _description(left), _description(right)
    if not left or not right:
        return False
    if left == right:
        return True
    # Existing Books imports mask account digits while retaining transaction
    # identity. Match only numeric redactions in the otherwise complete text;
    # a four-digit masked reference alone never establishes a match.
    def masked_match(masked: str, plain: str) -> bool:
        masks = list(re.finditer(r"(?:x{2,}|\*{2,})(?=\d)", masked))
        if not masks:
            return False
        visible = re.sub(r"(?:x{2,}|\*{2,})(?=\d)", "", masked)
        if sum(char.isalnum() for char in visible) < 12:
            return False
        parts = []
        offset = 0
        for mask in masks:
            parts.append(re.escape(masked[offset:mask.start()]))
            parts.append(r"[0-9]{" + str(mask.end() - mask.start()) + "}")
            offset = mask.end()
        parts.append(re.escape(masked[offset:]))
        return re.fullmatch("".join(parts), plain) is not None
    return masked_match(left, right) or masked_match(right, left)


def _identity_matches(left: StatementLine, right: StatementLine) -> bool:
    reference = _reference(left.reference)
    if reference and reference == _reference(right.reference):
        return True
    # Full UPI transaction references survive even imports masking account/VPA
    # text. Whole numeric tokens avoid matching a suffix of another reference.
    if reference.isdigit() and len(reference) >= 6:
        if reference in {value.lstrip("0") for value in re.findall(r"(?<![a-z0-9])\d{6,}(?![a-z0-9])", right.description.casefold())}:
            return True
    return _narration_matches(left.description, right.description)


def _masked_cheque_matches(left: StatementLine, right: StatementLine) -> bool:
    prefix = _description(left.description).split(":", 1)[0].strip()
    if not prefix.startswith("chq dep - cts clg1") or prefix != _description(right.description):
        return False
    masked = re.fullmatch(r"[x*]{2,}(\d{4,})", right.reference.casefold())
    reference = normalize_payment_reference(left.reference)
    return bool(masked and reference.isdigit() and reference.endswith(masked.group(1)))


def compare_statement_lines(csv_lines: Sequence[StatementLine], books_lines: Sequence[StatementLine], *,
                            account_id: str) -> StatementComparison:
    """Match date/direction/amount plus reference or full narration, one-to-one.

    A maximum bipartite match preserves duplicate multiplicity. When equivalent
    CSV occurrences outnumber Books occurrences, the unmatched occurrence is a
    count shortage, not proof that a particular identical CSV row was omitted.
    Same-date/amount candidates without matching identity remain review items.
    """
    if not csv_lines or not account_id:
        raise ValueError("CSV transactions and an explicit Books account ID are required")
    start, end = min(line.date for line in csv_lines), max(line.date for line in csv_lines)
    if len({line.source_id for line in csv_lines}) != len(csv_lines):
        raise ValueError("Duplicate CSV source IDs")
    if len({line.source_id for line in books_lines}) != len(books_lines):
        raise ValueError("Duplicate Books source IDs")
    if any(not start <= line.date <= end for line in books_lines):
        raise ValueError("Books lines fall outside the CSV period")
    grouped: dict[tuple[date, str, Decimal], list[int]] = defaultdict(list)
    for j, line in enumerate(books_lines):
        grouped[line.date, line.direction, line.amount].append(j)
    edges: dict[int, list[int]] = {}
    for i, line in enumerate(csv_lines):
        edges[i] = [j for j in grouped[line.date, line.direction, line.amount]
                    if _identity_matches(line, books_lines[j])]
    owner: dict[int, int] = {}

    assigned: dict[int, int] = {}

    def assign(start_index: int) -> None:
        pending = deque([start_index])
        visited_left = {start_index}
        parent: dict[int, int] = {}
        while pending:
            i = pending.popleft()
            for j in edges[i]:
                if j in parent:
                    continue
                parent[j] = i
                if j not in owner:
                    # Reassign along the augmenting path without recursion,
                    # including large groups of duplicate transactions.
                    while True:
                        left_index = parent[j]
                        previous = assigned.get(left_index)
                        owner[j] = left_index
                        assigned[left_index] = j
                        if previous is None:
                            return
                        j = previous
                elif owner[j] not in visited_left:
                    visited_left.add(owner[j])
                    pending.append(owner[j])

    for i in sorted(edges, key=lambda index: len(edges[index])):
        assign(i)
    matched = {i: j for j, i in owner.items()}
    # Truncated cheque narrations plus four visible reference digits are weaker
    # evidence: accept only a unique pair on both sides, and report as probable.
    weak = {i: [j for j in grouped[line.date, line.direction, line.amount]
                if j not in owner and _masked_cheque_matches(line, books_lines[j])]
            for i, line in enumerate(csv_lines) if i not in matched}
    claims: dict[int, list[int]] = defaultdict(list)
    for i, candidates in weak.items():
        for j in candidates:
            claims[j].append(i)
    probable = {i: candidates[0] for i, candidates in weak.items()
                if len(candidates) == 1 and len(claims[candidates[0]]) == 1}
    owner.update({j: i for i, j in probable.items()})
    results = []
    for i, line in enumerate(csv_lines):
        if i in matched:
            results.append(LineResult(line, "matched", books_lines[matched[i]].source_id))
        elif i in probable:
            results.append(LineResult(line, "probable", books_lines[probable[i]].source_id,
                "Unique date/direction/amount, cheque prefix and masked reference suffix; full identity unavailable"))
        elif edges[i]:
            results.append(LineResult(line, "duplicate_shortfall", reason="Insufficient distinct Books lines with matching reference/narration"))
        elif grouped[line.date, line.direction, line.amount]:
            results.append(LineResult(line, "review", reason="Date, direction and amount exist; reference/narration differ"))
        else:
            results.append(LineResult(line, "missing", reason="No Books line with this date, direction and amount"))
    return StatementComparison(account_id, start, end, len(csv_lines), len(books_lines), tuple(results),
        tuple(line.source_id for j, line in enumerate(books_lines) if j not in owner))


def fetch_statement_snapshot(analytics: Any, *, catalog: AnalyticsCatalog, account_id: str,
                             start: date, end: date, view_id: str = DEFAULT_VIEW_ID) -> dict[str, Any]:
    """Use cached table design and a scoped live SQL export; never refresh metadata."""
    if not re.fullmatch(r"\d+", account_id) or start > end:
        raise ValueError("A numeric account ID and ordered dates are required")
    metadata = catalog.analyze(view_id)
    required = {"Statement Line ID", "Account ID", "Date", "Debit or Credit", "Amount", "Description", "Reference Number"}
    with catalog.cached_store() as store:
        names = {column["name"] for column in store.get_columns(view_id)}
    if not required <= names:
        raise ValueError(f"Statement table lacks required columns: {sorted(required - names)}")
    table = metadata["views"][0]["name"].replace('"', '""')
    sql = ('SELECT ' + ', '.join('"' + name + '"' for name in sorted(required)) +
           f' FROM "{table}" WHERE "Account ID" = \'{account_id}\' AND "Date" >= \'{start.isoformat()}\'' +
           f' AND "Date" < \'{(end + timedelta(days=1)).isoformat()}\' ORDER BY "Date", "Statement Line ID"')
    rows = analytics.queries.execute(catalog.workspace_id, sql)
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise ValueError("Analytics returned an invalid statement export")
    parse_analytics_lines(rows, account_id=account_id, start=start, end=end)
    return {"schema_version": 1, "workspace_id": catalog.workspace_id, "view_id": view_id,
            "account_id": account_id, "start": start.isoformat(), "end": end.isoformat(),
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "last_successful_metadata_sync_at": metadata["last_successful_sync_at"], "sql": sql, "rows": rows}


def comparison_dict(comparison: StatementComparison) -> dict[str, Any]:
    """JSON-ready report preserving exact decimal amounts."""
    result = asdict(comparison)
    result["start"], result["end"] = comparison.start.isoformat(), comparison.end.isoformat()
    for item in result["results"]:
        item["line"]["date"] = item["line"]["date"].isoformat()
        item["line"]["amount"] = str(item["line"]["amount"])
    return result


__all__ = ["StatementLine", "LineResult", "StatementComparison", "read_hdfc_csv",
           "parse_analytics_lines", "compare_statement_lines", "fetch_statement_snapshot", "comparison_dict"]
