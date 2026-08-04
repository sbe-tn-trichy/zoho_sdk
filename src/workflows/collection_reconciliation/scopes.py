from typing import Iterable, List, Set, Tuple


REQUIRED_OAUTH_SCOPES: Tuple[str, ...] = (
    "ZohoCreator.meta.form.READ",
    "ZohoCreator.report.READ",
    "ZohoCreator.form.CREATE",
    "ZohoCreator.report.UPDATE",
    "ZohoBooks.banking.READ",
    "ZohoBooks.banking.CREATE",
    "ZohoBooks.customerpayments.CREATE",
    "ZohoBooks.settings.READ",
    "ZohoBooks.settings.CREATE",
    "ZohoAnalytics.data.read",
)


def missing_oauth_scopes(granted_scopes: Iterable[str]) -> List[str]:
    granted: Set[str] = {str(scope).strip() for scope in granted_scopes}
    return [scope for scope in REQUIRED_OAUTH_SCOPES if scope not in granted]
