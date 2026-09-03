import os
import json
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from dotenv import load_dotenv
except ImportError:  # The base SDK can still use dependency-light workflows.
    def load_dotenv(*args, **kwargs):
        return False

# 1. Project root & .env loading
root_dir = Path(__file__).resolve().parent.parent.parent.parent
env_path = root_dir / '.env'
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()


def _load_config_dict(
    project_root: Optional[Path] = None,
    home: Optional[Path] = None,
) -> Dict[str, Any]:
    """Load the highest-priority JSON configuration file.

    Project configuration intentionally takes precedence over user-level
    defaults. An existing but invalid file is an error: silently falling back
    could select identifiers for a different Zoho tenant.
    """
    project_root = project_root or root_dir
    home = home or Path.home()
    candidate_paths = [
        project_root / "zoho_config.json",
        home / ".config" / "zoho" / "config.json",
        home / ".zoho" / "config.json",
    ]
    for path in candidate_paths:
        if path.exists() and path.is_file():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"Unable to load Zoho configuration from {path}.") from exc
            if not isinstance(data, dict):
                raise ValueError(f"Zoho configuration in {path} must be a JSON object.")
            active_profile = data.get("active_profile")
            if active_profile:
                profiles = data.get("profiles")
                if not isinstance(profiles, dict):
                    raise ValueError(
                        f"Zoho configuration in {path} declares an active profile "
                        "without a profiles object."
                    )
                profile = profiles.get(active_profile)
                if not isinstance(profile, dict):
                    raise ValueError(
                        f"Active Zoho configuration profile {active_profile!r} "
                        f"was not found in {path}."
                    )
                return profile
            return data
    return {}


_FILE_CONFIG = _load_config_dict()


def get_config(key: str, default: Any = "") -> Any:
    """Resolve config key: Environment variable -> file config -> default."""
    if key in os.environ:
        return os.environ[key]
    key_lower = key.lower()
    if key_lower in _FILE_CONFIG:
        return _FILE_CONFIG[key_lower]
    if key in _FILE_CONFIG:
        return _FILE_CONFIG[key]
    return default


class Config:
    PROJECT_ROOT = str(root_dir)

    # API Access
    TOKEN_URL = get_config("TOKEN_URL", "http://localhost:3000/server/new/tokens")
    ORG_ID = get_config("ORG_ID", "")
    DOMAIN = get_config("DOMAIN", "in")
    CREATOR_OWNER_NAME = get_config(
        "CREATOR_OWNER_NAME", get_config("CREATOR_ACCOUNT_OWNER_NAME", "")
    )
    PAYMENT_CREATOR_APP_LINK_NAME = get_config(
        "PAYMENT_CREATOR_APP_LINK_NAME", "order-management-new"
    )

    # Zoho WorkDrive Configurations
    POLYCAB_FOLDER_ID = get_config("POLYCAB_FOLDER_ID", "")

    # Local Directory Paths
    FILES_DIR = get_config("FILES_DIR", str(root_dir / "input_files" / "polycab" / "cn"))
    POLYCAB_LEDGER_PATH = get_config(
        "POLYCAB_LEDGER_PATH", 
        str(root_dir / "input_files" / "polycab" / "ledger" / "277498_ReconciliationLedger_1-Jan-26_to_31-Mar-26.xls")
    )

    # Zoho Books Entity IDs
    POLYCAB_VENDOR_ID = get_config("POLYCAB_VENDOR_ID", "")
    NEOSEAL_PURCHASE_ACCOUNT_ID = get_config("NEOSEAL_PURCHASE_ACCOUNT_ID", "")
    NEOSEAL_PRICE_LIST_GOOGLE_SHEET_ID = get_config(
        "NEOSEAL_PRICE_LIST_GOOGLE_SHEET_ID", ""
    )
    FAN_PURCHASE_ACCOUNT_ID = get_config("FAN_PURCHASE_ACCOUNT_ID", "")
    ZOHO_RSO_CN_ITEM_ID = get_config("ZOHO_RSO_CN_ITEM_ID", "")
    ZOHO_SCHEME_CN_ITEM_ID = get_config("ZOHO_SCHEME_CN_ITEM_ID", "")
    ZOHO_GST0_TAX_ID = get_config("ZOHO_GST0_TAX_ID", "")
    ZOHO_TAX_SETTINGS_ID = get_config("ZOHO_TAX_SETTINGS_ID", "")
    RSO_CUSTOMER_ID = get_config("RSO_CUSTOMER_ID", "")

    # Zeiss
    ZEISS_VENDOR_ID = get_config("ZEISS_VENDOR_ID", "")
    ZEISS_LEDGER_PATH = get_config(
        "ZEISS_LEDGER_PATH",
        str(root_dir / "input_files" / "zeiss" / "ZeissOct2025_Statement - ZeissOct2025_Statement.csv")
    )

    # Location / Branch Config
    EXPECTED_LOCATION_ID = get_config("EXPECTED_LOCATION_ID", "")
    EXPECTED_LOCATION_NAME = get_config("EXPECTED_LOCATION_NAME", "")

    # Bank Account IDs
    BANK_ACCOUNT_IDFC = get_config("BANK_ACCOUNT_IDFC", "")
    BANK_ACCOUNT_HDFC = get_config("BANK_ACCOUNT_HDFC", "")
    BANK_ACCOUNT_HDFC_AGENCIES = get_config("BANK_ACCOUNT_HDFC_AGENCIES", "")
    BANK_ACCOUNT_ICICI = get_config("BANK_ACCOUNT_ICICI", "")

    # GSTIN Map
    try:
        raw_gstin_map = get_config("GSTIN_TO_VENDOR_ID", "{}")
        GSTIN_TO_VENDOR_ID = json.loads(raw_gstin_map) if isinstance(raw_gstin_map, str) else raw_gstin_map
    except Exception:
        GSTIN_TO_VENDOR_ID = {}
