import os
import json
import logging
from pathlib import Path
from typing import Any, Dict

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


def _load_config_dict() -> Dict[str, Any]:
    """Load configuration from local or user-home config files in priority order."""
    candidate_paths = [
        Path.home() / ".config" / "zoho" / "config.json",
        Path.home() / ".zoho" / "config.json",
        root_dir / "zoho_config.json",
    ]
    for path in candidate_paths:
        if path.exists() and path.is_file():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        # Support active profile selection or flat dictionary
                        active_profile = data.get("active_profile")
                        if active_profile and isinstance(data.get("profiles"), dict):
                            profile = data["profiles"].get(active_profile, {})
                            if isinstance(profile, dict):
                                return profile
                        return data
            except Exception:
                continue
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

