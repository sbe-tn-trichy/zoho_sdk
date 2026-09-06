from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class CreatorCustomerSyncConfig:
    """Configuration settings for Zoho Creator customer record sync workflow."""

    app_link_name: str
    report_link_name: str
    creator_id_field: str = "Customer_Id"
    books_id_field: str = "contact_id"
    books_status_filter: str = "all"
    dry_run: bool = True
    max_deletion_limit: int = 50
    max_deletion_percentage: float = 15.0
    output_dir: Path = field(default_factory=lambda: Path("output"))
    soft_delete_field: Optional[str] = None
    soft_delete_value: Any = True

    form_link_name: Optional[str] = None
    # Creator field link name -> Books field name; identity is added automatically.
    field_mapping: Dict[str, str] = field(default_factory=lambda: {"Customer_Name": "contact_name"})

    books_branch_name: Optional[str] = None
    books_branch_field: str = "cf_b_name"
