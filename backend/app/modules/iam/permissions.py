"""Permission catalog and default roles (docs/security/permissions.md).

The catalog lives in code and is synced into the ``permission`` table; roles
reference permissions by code. Enforcement is always server side.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionDef:
    code: str
    group: str
    label: str


CATALOG: tuple[PermissionDef, ...] = (
    PermissionDef("users.manage", "مدیریت سیستم", "مدیریت کاربران"),
    PermissionDef("roles.manage", "مدیریت سیستم", "مدیریت نقش‌ها و مجوزها"),
    PermissionDef("settings.manage", "مدیریت سیستم", "تنظیمات سازمان"),
    PermissionDef("branches.manage", "مدیریت سیستم", "مدیریت شعب و صندوق‌ها"),
    PermissionDef("audit.view", "مدیریت سیستم", "مشاهده رویدادهای ممیزی"),
    PermissionDef("import.run", "مدیریت سیستم", "ورود اطلاعات از Excel"),
    PermissionDef("accounting.account.manage", "حسابداری", "مدیریت کدینگ حساب‌ها"),
    PermissionDef("accounting.voucher.create", "حسابداری", "ثبت سند"),
    PermissionDef("accounting.voucher.finalize", "حسابداری", "قطعی کردن سند"),
    PermissionDef("accounting.voucher.reverse", "حسابداری", "برگشت سند"),
    PermissionDef("accounting.fiscal.close", "حسابداری", "بستن دوره مالی"),
    PermissionDef("accounting.report.view", "حسابداری", "گزارش‌های حسابداری"),
    PermissionDef(
        "accounting.integration.manage", "حسابداری", "رسیدگی به اسناد رسیده از سامانه باسکول"
    ),
    PermissionDef("inventory.item.manage", "انبار", "مدیریت کالاها"),
    PermissionDef("inventory.price.manage", "انبار", "مدیریت قیمت‌ها"),
    PermissionDef("inventory.stock.create", "انبار", "ثبت رسید و حواله"),
    PermissionDef("inventory.stock.adjust", "انبار", "تعدیل موجودی"),
    PermissionDef("inventory.report.view", "انبار", "گزارش‌های انبار"),
    PermissionDef("sales.pos.use", "فروش", "استفاده از صندوق فروش"),
    PermissionDef("sales.shift.open", "فروش", "باز کردن شیفت"),
    PermissionDef("sales.shift.close", "فروش", "بستن شیفت"),
    PermissionDef("sales.invoice.discount", "فروش", "اعمال تخفیف (تا سقف صندوق‌دار)"),
    PermissionDef("sales.invoice.discount_over_limit", "فروش", "تخفیف بالاتر از سقف / تأیید آن"),
    PermissionDef("sales.invoice.line_delete_after_scan", "فروش", "حذف ردیف پس از اسکن"),
    PermissionDef("sales.invoice.void", "فروش", "ابطال فاکتور"),
    PermissionDef("sales.return.create", "فروش", "برگشت از فروش"),
    PermissionDef("sales.payment.cash", "فروش", "دریافت نقدی"),
    PermissionDef("sales.payment.card", "فروش", "دریافت با کارت‌خوان"),
    PermissionDef("sales.payment.credit", "فروش", "فروش نسیه"),
    PermissionDef("sales.report.view", "فروش", "گزارش‌های فروش"),
    PermissionDef("payments.reconcile", "خزانه", "تطبیق تراکنش‌های نامشخص"),
    PermissionDef("parties.view", "طرف‌حساب", "مشاهده طرف‌حساب‌ها، مانده و گردش"),
    PermissionDef("parties.manage", "طرف‌حساب", "مدیریت طرف‌حساب‌ها و اطلاعات حساس"),
    PermissionDef("purchasing.manage", "خرید", "مدیریت خرید"),
    PermissionDef("treasury.manage", "خزانه", "مدیریت دریافت و پرداخت"),
    PermissionDef("sync.resolve", "صندوق", "رسیدگی به تعارض فروش‌های آفلاین"),
    PermissionDef("distribution.visitor", "ویزیتور و توزیع", "کار با اپلیکیشن ویزیتور"),
    PermissionDef(
        "distribution.manage",
        "ویزیتور و توزیع",
        "تعریف ویزیتور، تخصیص مشتری، تأیید و تحویل سفارش",
    ),
    PermissionDef("reports.dashboard", "گزارش", "داشبورد مدیریتی (فروش، سود، موجودی، طلب)"),
    PermissionDef("devices.manage", "سخت‌افزار", "تعریف و تنظیم Device Agent و چاپگر"),
    PermissionDef("sales.drawer.open", "فروش", "باز کردن کشوی پول بدون فروش"),
)

CODES: frozenset[str] = frozenset(p.code for p in CATALOG)


def _all_starting(*prefixes: str) -> frozenset[str]:
    return frozenset(c for c in CODES if c.startswith(prefixes))


@dataclass(frozen=True)
class RoleDef:
    code: str
    name: str
    permissions: frozenset[str]


SYSTEM_ROLES: tuple[RoleDef, ...] = (
    RoleDef(
        "ADM",
        "مدیر سیستم",
        frozenset(
            {
                "users.manage",
                "roles.manage",
                "settings.manage",
                "branches.manage",
                "audit.view",
                "import.run",
                "devices.manage",
            }
        ),
    ),
    RoleDef(
        "MGR",
        "مدیر فروشگاه",
        frozenset(
            {
                "audit.view",
                "import.run",
                "accounting.voucher.finalize",
                "accounting.voucher.reverse",
                "accounting.fiscal.close",
                "accounting.report.view",
                "inventory.item.manage",
                "inventory.price.manage",
                "inventory.stock.adjust",
                "inventory.report.view",
                "sales.invoice.discount",
                "sales.invoice.discount_over_limit",
                "sales.invoice.line_delete_after_scan",
                "sales.invoice.void",
                "sales.return.create",
                "sales.payment.credit",
                "sales.report.view",
                "payments.reconcile",
                "purchasing.manage",
                "treasury.manage",
                "parties.view",
                "parties.manage",
                "devices.manage",
                "sales.drawer.open",
                "reports.dashboard",
                "sync.resolve",
                "distribution.manage",
            }
        ),
    ),
    RoleDef(
        "ACC",
        "حسابدار",
        _all_starting("accounting.") - {"accounting.fiscal.close"}
        | {
            "inventory.report.view",
            "sales.report.view",
            "payments.reconcile",
            "treasury.manage",
            "parties.view",
            "parties.manage",
            "reports.dashboard",
        },
    ),
    RoleDef(
        "SUP",
        "سرپرست صندوق",
        _all_starting("sales."),
    ),
    RoleDef(
        "CSH",
        "صندوق‌دار",
        frozenset(
            {
                "sales.pos.use",
                "sales.shift.open",
                "sales.shift.close",
                "sales.payment.cash",
                "sales.payment.card",
            }
        ),
    ),
    RoleDef("VIS", "ویزیتور", frozenset({"distribution.visitor"})),
    RoleDef(
        "WHK",
        "انباردار",
        frozenset(
            {
                "inventory.item.manage",
                "inventory.stock.create",
                "inventory.stock.adjust",
                "inventory.report.view",
            }
        ),
    ),
    RoleDef(
        "PUR",
        "کارپرداز خرید",
        frozenset(
            {
                "inventory.item.manage",
                "inventory.report.view",
                "purchasing.manage",
                "parties.view",
                "parties.manage",
            }
        ),
    ),
    RoleDef(
        "AUD",
        "حسابرس",
        frozenset(
            {
                "audit.view",
                "accounting.report.view",
                "inventory.report.view",
                "sales.report.view",
                "parties.view",
                "reports.dashboard",
            }
        ),
    ),
)

ADMIN_ROLE = "ADM"

for _role in SYSTEM_ROLES:
    _unknown = _role.permissions - CODES
    assert not _unknown, f"role {_role.code} references unknown permissions {_unknown}"
