import os
import json
import logging
from pathlib import Path
try:
    from dotenv import load_dotenv
except ImportError:  # The base SDK can still use dependency-light workflows.
    def load_dotenv(*args, **kwargs):
        return False

# Load .env file from the root directory of the project
# We check if .env exists in the current directory, parent, or project root
root_dir = Path(__file__).resolve().parent.parent.parent.parent
env_path = root_dir / '.env'

if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

class Config:
    # API Access
    TOKEN_URL = os.getenv("TOKEN_URL", "http://localhost:3000/server/new/tokens")
    ORG_ID = os.getenv("ORG_ID", "60018185359")
    DOMAIN = os.getenv("DOMAIN", "in")

    # Zoho WorkDrive Configurations
    POLYCAB_FOLDER_ID = os.getenv("POLYCAB_FOLDER_ID", "wue3rf80474a32d3f4b67af8652d97ea5ab6c")

    # Local Directory Paths
    PROJECT_ROOT = str(root_dir)
    FILES_DIR = os.getenv("FILES_DIR", str(root_dir / "input_files" / "polycab" / "cn"))
    POLYCAB_LEDGER_PATH = os.getenv(
        "POLYCAB_LEDGER_PATH", 
        str(root_dir / "input_files" / "polycab" / "ledger" / "277498_ReconciliationLedger_1-Jan-26_to_31-Mar-26.xls")
    )

    # Zoho Books Entity IDs
    POLYCAB_VENDOR_ID = os.getenv("POLYCAB_VENDOR_ID", "1094368000000175001")
    ZOHO_RSO_CN_ITEM_ID = os.getenv("ZOHO_RSO_CN_ITEM_ID", "1094368000028456138")
    ZOHO_SCHEME_CN_ITEM_ID = os.getenv("ZOHO_SCHEME_CN_ITEM_ID", "1094368000000311103")
    ZOHO_GST0_TAX_ID = os.getenv("ZOHO_GST0_TAX_ID", "1094368000000014279")
    ZOHO_TAX_SETTINGS_ID = os.getenv("ZOHO_TAX_SETTINGS_ID", "1094368000000000271")

    # Zeiss
    ZEISS_VENDOR_ID = os.getenv("ZEISS_VENDOR_ID", "1094368000002502821")
    ZEISS_LEDGER_PATH = os.getenv(
        "ZEISS_LEDGER_PATH",
        str(root_dir / "input_files" / "zeiss" / "ZeissOct2025_Statement - ZeissOct2025_Statement.csv")
    )

    # Location / Branch Config
    EXPECTED_LOCATION_ID = os.getenv("EXPECTED_LOCATION_ID", "1094368000000443455")
    EXPECTED_LOCATION_NAME = os.getenv("EXPECTED_LOCATION_NAME", "Sri Bharath Electricals")

    # Bank Account IDs
    BANK_ACCOUNT_IDFC = os.getenv("BANK_ACCOUNT_IDFC", "1094368000045308003")
    BANK_ACCOUNT_HDFC = os.getenv("BANK_ACCOUNT_HDFC", "1094368000000081927")
    BANK_ACCOUNT_HDFC_AGENCIES = os.getenv(
        "BANK_ACCOUNT_HDFC_AGENCIES", "1094368000000468208"
    )
    BANK_ACCOUNT_ICICI = os.getenv("BANK_ACCOUNT_ICICI", "1094368000056644467")
    # GSTIN Map
    try:
        GSTIN_TO_VENDOR_ID = json.loads(os.getenv("GSTIN_TO_VENDOR_ID", "{}"))
    except Exception:
        GSTIN_TO_VENDOR_ID = {}

# Warn if default config is loaded
logger = logging.getLogger("workflows.config")
if Config.ORG_ID == "60018185359":
    logger.debug("Config: Relying on default Zoho Books ORG_ID. Ensure this is intentional.")
if Config.POLYCAB_FOLDER_ID == "wue3rf80474a32d3f4b67af8652d97ea5ab6c":
    logger.debug("Config: Relying on default Polycab WorkDrive folder ID. Ensure this is intentional.")
