import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Set

_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Known sensitive parameter keys (case-insensitive)
SENSITIVE_PARAM_KEYS: Set[str] = {
    # Auth & Tokens
    "authtoken",
    "auth_token",
    "authorization",
    "access_token",
    "refresh_token",
    "client_secret",
    "password",
    "passcode",
    "secret",
    "api_key",
    "apikey",
    "code",
    # Tax & Statutory Identifiers
    "gst_no",
    "gstin",
    "gst_number",
    "pan",
    "pan_number",
    "tax_id",
    "tax_number",
    "vat_number",
    "tin",
    # Banking & Financial
    "account_number",
    "bank_account_number",
    "account_no",
    "iban",
    "ifsc",
    "card_number",
    "card_no",
    "cvv",
    "cvc",
    "pin",
    "routing_number",
    "swift_code",
    "upi_id",
    "vpa",
    # Personally Identifiable Information
    "email",
    "email_address",
    "contact_email",
    "phone",
    "phone_number",
    "mobile",
    "mobile_number",
    "aadhaar",
    "ssn",
    "national_id",
}


def mask_sensitive_value(val: Any) -> str:
    """
    Mask a sensitive string while preserving the last 4 characters for identification.
    Values with 4 or fewer characters are masked as '****'.
    """
    if val is None:
        return ""
    s = str(val).strip()
    if not s:
        return ""
    if len(s) <= 4:
        return "****"
    return f"***{s[-4:]}"


def sanitize_log_params(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Recursively sanitize query parameters or payload dictionaries for logging.
    Sensitive keys are masked showing only their last 4 characters.
    """
    if not params or not isinstance(params, dict):
        return params

    sanitized = {}
    for k, v in params.items():
        k_lower = str(k).lower().strip()
        if k_lower in SENSITIVE_PARAM_KEYS or any(sens in k_lower for sens in ("token", "secret", "password", "gstin", "pan_no", "account_no")):
            sanitized[k] = mask_sensitive_value(v)
        elif isinstance(v, dict):
            sanitized[k] = sanitize_log_params(v)
        elif isinstance(v, list):
            sanitized[k] = [
                sanitize_log_params(item) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            sanitized[k] = v
    return sanitized


def sanitize_filename(name: Optional[str], fallback: str = "unnamed") -> str:
    """
    Sanitize an untrusted filename to prevent path traversal and invalid filesystem characters.
    Extracts the basename and strips dangerous characters.
    """
    if not name:
        return fallback

    # Extract base filename to neutralize path traversal sequences (e.g., ../ or C:\)
    candidate = os.path.basename(str(name).strip())
    # Strip dangerous/invalid characters
    candidate = _UNSAFE_FILENAME_CHARS.sub("_", candidate)
    # Strip trailing spaces or dots (problematic on Windows/POSIX)
    candidate = candidate.rstrip(" .")
    
    # Avoid reserved or empty names
    if candidate in {"", ".", "..", "..."}:
        return fallback
    return candidate


def resolve_output_path(
    save_path: str,
    base_dir: str = "output",
    strict_containment: bool = False,
) -> str:
    """
    Safely resolve an output file path.
    - If save_path is relative, confines it inside base_dir, preventing directory traversal.
    - If strict_containment is True, absolute paths outside base_dir raise ValueError.
    """
    base_path = Path(base_dir).expanduser().resolve()
    target_path = Path(save_path).expanduser()

    if not target_path.is_absolute():
        # If relative, anchor to base_dir
        resolved = (base_path / target_path).resolve()
    else:
        resolved = target_path.resolve()

    if strict_containment:
        try:
            resolved.relative_to(base_path)
        except ValueError:
            raise ValueError(
                f"Strict containment violation: target path '{save_path}' is outside allowed directory '{base_dir}'."
            )

    # If the path was relative, verify it has not escaped base_dir
    if not target_path.is_absolute():
        try:
            resolved.relative_to(base_path)
        except ValueError:
            # Traversal attempted; sanitize target name within base_dir
            safe_name = sanitize_filename(target_path.name)
            resolved = base_path / safe_name

    return str(resolved)

