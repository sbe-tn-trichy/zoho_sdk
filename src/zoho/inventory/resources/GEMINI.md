# Folder Index: `zoho/inventory/resources`

Zoho Inventory Resource modules mapping to specific API endpoints.

## Files and Available Classes/Methods

### [batches.py](file:///d:/workplace/zoho_sdk/src/zoho/inventory/resources/batches.py)
- **[Batches](file:///d:/workplace/zoho_sdk/src/zoho/inventory/resources/batches.py#L5)** (inherits `BaseResource` from `inventory/base.py`)
  - `mark_as_active(self, batch_id: str) -> Dict[str, Any]`
  - `mark_as_inactive(self, batch_id: str) -> Dict[str, Any]`

### [bins.py](file:///d:/workplace/zoho_sdk/src/zoho/inventory/resources/bins.py)
- **[Bins](file:///d:/workplace/zoho_sdk/src/zoho/inventory/resources/bins.py#L5)** (inherits `BaseResource` from `inventory/base.py`)
  - Standard CRUD: `list()`, `get()`, `create()`, `update()`, `delete()`

### [inventory_adjustments.py](file:///d:/workplace/zoho_sdk/src/zoho/inventory/resources/inventory_adjustments.py)
- **[InventoryAdjustments](file:///d:/workplace/zoho_sdk/src/zoho/inventory/resources/inventory_adjustments.py#L5)** (inherits `BaseResource` from `inventory/base.py`)
  - Standard CRUD: `list()`, `get()`, `create()`, `update()`, `delete()`

### [items.py](file:///d:/workplace/zoho_sdk/src/zoho/inventory/resources/items.py)
- **[Items](file:///d:/workplace/zoho_sdk/src/zoho/inventory/resources/items.py#L5)** (inherits `BaseResource` from `inventory/base.py`)
  - Standard CRUD: `list()`, `get()`, `create()`, `update()`, `delete()`

### [move_orders.py](file:///d:/workplace/zoho_sdk/src/zoho/inventory/resources/move_orders.py)
- **[MoveOrders](file:///d:/workplace/zoho_sdk/src/zoho/inventory/resources/move_orders.py#L5)** (inherits `BaseResource` from `inventory/base.py`)
  - `mark_as_confirmed(self, move_order_id: str) -> Dict[str, Any]`
  - `mark_as_in_progress(self, move_order_id: str) -> Dict[str, Any]`
  - `mark_as_completed(self, move_order_id: str) -> Dict[str, Any]`

### [packages.py](file:///d:/workplace/zoho_sdk/src/zoho/inventory/resources/packages.py)
- **[Packages](file:///d:/workplace/zoho_sdk/src/zoho/inventory/resources/packages.py#L5)** (inherits `BaseResource` from `inventory/base.py`)
  - Standard CRUD: `list()`, `get()`, `create()`, `update()`, `delete()`

### [picklists.py](file:///d:/workplace/zoho_sdk/src/zoho/inventory/resources/picklists.py)
- **[Picklists](file:///d:/workplace/zoho_sdk/src/zoho/inventory/resources/picklists.py#L5)** (inherits `BaseResource` from `inventory/base.py`)
  - `mark_status(self, picklist_id: str, status: str) -> Dict[str, Any]`

### [shipments.py](file:///d:/workplace/zoho_sdk/src/zoho/inventory/resources/shipments.py)
- **[Shipments](file:///d:/workplace/zoho_sdk/src/zoho/inventory/resources/shipments.py#L5)** (inherits `BaseResource` from `inventory/base.py`)
  - `mark_as_delivered(self, shipment_id: str) -> Dict[str, Any]`

### [transfer_orders.py](file:///d:/workplace/zoho_sdk/src/zoho/inventory/resources/transfer_orders.py)
- **[TransferOrders](file:///d:/workplace/zoho_sdk/src/zoho/inventory/resources/transfer_orders.py#L5)** (inherits `BaseResource` from `inventory/base.py`)
  - `mark_as_in_transit(self, transfer_order_id: str) -> Dict[str, Any]`
  - `mark_as_received(self, transfer_order_id: str) -> Dict[str, Any]`
  - `submit_for_approval(self, transfer_order_id: str) -> Dict[str, Any]`
  - `approve(self, transfer_order_id: str) -> Dict[str, Any]`
  - `reject(self, transfer_order_id: str) -> Dict[str, Any]`
