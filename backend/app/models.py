"""Import every model module so Base.metadata is complete (used by Alembic)."""

from app.core.idempotency import IdempotencyRecord
from app.core.numbering import NumberSequence
from app.modules.accounting.models import (
    Account,
    DetailAccount,
    FiscalPeriod,
    FiscalYear,
    PostingRule,
    Voucher,
    VoucherLine,
)
from app.modules.audit.models import AuditEvent
from app.modules.iam.models import AppUser, Permission, Role, UserScope, UserSession
from app.modules.inventory.models import (
    Item,
    ItemBarcode,
    ItemGroup,
    ItemPrice,
    ItemUnit,
    PriceList,
    ScaleBarcodeRule,
    StockBalance,
    StockDocument,
    StockDocumentLine,
    StockLedger,
    Unit,
    Warehouse,
)
from app.modules.organization.models import Branch, CashRegister, Organization
from app.modules.parties.models import Party, PartyGroup, PartyNote
from app.modules.purchasing.models import (
    PurchaseCharge,
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseOrder,
    PurchaseOrderLine,
)
from app.modules.sales.models import (
    CashShift,
    Promotion,
    SalesApproval,
    SalesInvoice,
    SalesInvoiceLine,
    SalesPayment,
    TerminalTransaction,
)
from app.modules.system.models import BackupLog

__all__ = [
    "PurchaseCharge",
    "PurchaseInvoice",
    "PurchaseInvoiceLine",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "Party",
    "PartyGroup",
    "PartyNote",
    "BackupLog",
    "CashShift",
    "Promotion",
    "SalesApproval",
    "SalesInvoice",
    "SalesInvoiceLine",
    "SalesPayment",
    "TerminalTransaction",
    "Item",
    "ItemBarcode",
    "ItemGroup",
    "ItemPrice",
    "ItemUnit",
    "PriceList",
    "ScaleBarcodeRule",
    "StockBalance",
    "StockDocument",
    "StockDocumentLine",
    "StockLedger",
    "Unit",
    "Warehouse",
    "Account",
    "DetailAccount",
    "FiscalPeriod",
    "FiscalYear",
    "NumberSequence",
    "PostingRule",
    "Voucher",
    "VoucherLine",
    "AppUser",
    "AuditEvent",
    "Branch",
    "CashRegister",
    "IdempotencyRecord",
    "Organization",
    "Permission",
    "Role",
    "UserScope",
    "UserSession",
]
