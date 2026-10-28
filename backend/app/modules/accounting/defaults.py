"""Default commercial/retail chart of accounts and automatic-posting catalog.

The chart is a starting point the accountant can edit (Q7 = default). Codes:
group = 1 digit, general = 2 digits, subsidiary = 4 digits.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AccountDef:
    code: str
    name: str
    category: str = ""
    nature: str = ""
    requires_detail: bool = False


# (group, [(general, [subsidiaries])])
CHART: list[tuple[AccountDef, list[tuple[AccountDef, list[AccountDef]]]]] = [
    (
        AccountDef("1", "دارایی‌های جاری", "asset", "debit"),
        [
            (
                AccountDef("11", "موجودی نقد و بانک"),
                [
                    AccountDef("1101", "صندوق"),
                    AccountDef("1102", "تنخواه‌گردان"),
                    AccountDef("1103", "بانک‌ها", requires_detail=True),
                    AccountDef("1104", "وجوه در راه کارت‌خوان"),
                ],
            ),
            (
                AccountDef("12", "حساب‌ها و اسناد دریافتنی"),
                [
                    AccountDef("1201", "حساب‌های دریافتنی تجاری", requires_detail=True),
                    AccountDef("1202", "اسناد دریافتنی", requires_detail=True),
                ],
            ),
            (
                AccountDef("13", "موجودی کالا"),
                [
                    AccountDef("1301", "موجودی کالای تجاری"),
                ],
            ),
            (
                AccountDef("14", "پیش‌پرداخت‌ها"),
                [
                    AccountDef("1401", "پیش‌پرداخت خرید", requires_detail=True),
                    AccountDef("1402", "مالیات بر ارزش افزوده خرید"),
                ],
            ),
        ],
    ),
    (
        AccountDef("2", "دارایی‌های غیرجاری", "asset", "debit"),
        [
            (
                AccountDef("21", "دارایی‌های ثابت"),
                [
                    AccountDef("2101", "اثاثه و منصوبات"),
                    AccountDef("2102", "تجهیزات فروشگاهی"),
                    AccountDef("2103", "وسایط نقلیه"),
                ],
            ),
            (
                AccountDef("22", "استهلاک انباشته", nature="credit"),
                [
                    AccountDef("2201", "استهلاک انباشته دارایی‌های ثابت", nature="credit"),
                ],
            ),
        ],
    ),
    (
        AccountDef("3", "بدهی‌های جاری", "liability", "credit"),
        [
            (
                AccountDef("31", "حساب‌ها و اسناد پرداختنی"),
                [
                    AccountDef("3101", "حساب‌های پرداختنی تجاری", requires_detail=True),
                    AccountDef("3102", "اسناد پرداختنی", requires_detail=True),
                ],
            ),
            (
                AccountDef("32", "مالیات و عوارض"),
                [
                    AccountDef("3201", "مالیات و عوارض ارزش افزوده فروش"),
                    AccountDef("3202", "مالیات پرداختنی"),
                ],
            ),
            (
                AccountDef("33", "پیش‌دریافت‌ها"),
                [
                    AccountDef("3301", "پیش‌دریافت از مشتریان", requires_detail=True),
                ],
            ),
            (
                AccountDef("34", "سایر بدهی‌ها"),
                [
                    AccountDef("3401", "حقوق و دستمزد پرداختنی"),
                    AccountDef("3402", "بیمه پرداختنی"),
                ],
            ),
        ],
    ),
    (
        AccountDef("4", "حقوق مالکانه", "equity", "credit"),
        [
            (AccountDef("41", "سرمایه"), [AccountDef("4101", "سرمایه")]),
            (
                AccountDef("42", "سود و زیان"),
                [
                    AccountDef("4201", "سود (زیان) انباشته", nature="none"),
                ],
            ),
            (
                AccountDef("43", "برداشت‌ها", nature="debit"),
                [
                    AccountDef("4301", "برداشت مالک", nature="debit"),
                ],
            ),
        ],
    ),
    (
        AccountDef("5", "درآمدها", "revenue", "credit"),
        [
            (
                AccountDef("51", "فروش"),
                [
                    AccountDef("5101", "فروش کالا"),
                    AccountDef("5102", "برگشت از فروش", nature="debit"),
                    AccountDef("5103", "تخفیفات فروش", nature="debit"),
                ],
            ),
            (
                AccountDef("52", "سایر درآمدها"),
                [
                    AccountDef("5201", "درآمدهای متفرقه"),
                    AccountDef("5202", "اضافه صندوق"),
                    AccountDef("5203", "اضافه انبار"),
                ],
            ),
        ],
    ),
    (
        AccountDef("6", "بهای تمام‌شده", "expense", "debit"),
        [
            (
                AccountDef("61", "بهای تمام‌شده فروش"),
                [
                    AccountDef("6101", "بهای تمام‌شده کالای فروش‌رفته"),
                ],
            ),
        ],
    ),
    (
        AccountDef("7", "هزینه‌ها", "expense", "debit"),
        [
            (
                AccountDef("71", "هزینه‌های عملیاتی"),
                [
                    AccountDef("7101", "حقوق و دستمزد"),
                    AccountDef("7102", "اجاره"),
                    AccountDef("7103", "آب، برق و گاز"),
                    AccountDef("7104", "تلفن و اینترنت"),
                    AccountDef("7105", "کارمزد بانکی"),
                    AccountDef("7106", "هزینه استهلاک"),
                    AccountDef("7107", "کسری صندوق"),
                    AccountDef("7108", "کسری انبار"),
                    AccountDef("7199", "سایر هزینه‌ها"),
                ],
            ),
        ],
    ),
]


@dataclass(frozen=True)
class RoleDef:
    role: str
    label: str
    default_code: str


@dataclass(frozen=True)
class EventDef:
    event_type: str
    label: str
    roles: tuple[RoleDef, ...]


# Automatic vouchers resolve their accounts through these roles (posting-rules.md §2).
EVENTS: tuple[EventDef, ...] = (
    EventDef(
        "sales.invoice.finalized",
        "فروش",
        (
            RoleDef("cash", "دریافت نقدی", "1101"),
            RoleDef("card", "دریافت کارت‌خوان", "1104"),
            RoleDef("receivable", "فروش نسیه", "1201"),
            RoleDef("revenue", "درآمد فروش", "5101"),
            RoleDef("discount", "تخفیف فروش", "5103"),
            RoleDef("vat_payable", "مالیات و عوارض فروش", "3201"),
            RoleDef("cogs", "بهای تمام‌شده", "6101"),
            RoleDef("inventory", "موجودی کالا", "1301"),
        ),
    ),
    EventDef(
        "sales.return.finalized",
        "برگشت از فروش",
        (
            RoleDef("sales_return", "برگشت از فروش", "5102"),
            RoleDef("cash", "پرداخت نقدی", "1101"),
            RoleDef("card", "استرداد کارت", "1104"),
            RoleDef("receivable", "کاهش طلب مشتری", "1201"),
            RoleDef("vat_payable", "مالیات و عوارض فروش", "3201"),
            RoleDef("cogs", "بهای تمام‌شده", "6101"),
            RoleDef("inventory", "موجودی کالا", "1301"),
        ),
    ),
    EventDef(
        "purchase.invoice.finalized",
        "خرید",
        (
            RoleDef("inventory", "موجودی کالا", "1301"),
            RoleDef("vat_receivable", "مالیات خرید", "1402"),
            RoleDef("payable", "بدهی به تأمین‌کننده", "3101"),
        ),
    ),
    EventDef(
        "purchase.return.finalized",
        "برگشت از خرید",
        (
            RoleDef("payable", "کاهش بدهی به تأمین‌کننده", "3101"),
            RoleDef("inventory", "موجودی کالا", "1301"),
            RoleDef("vat_receivable", "مالیات خرید", "1402"),
            # Inventory value leaving differs from the amount refunded (landed costs,
            # last units at the running average).
            RoleDef("price_difference", "تفاوت بهای برگشت از خرید", "6101"),
        ),
    ),
    EventDef(
        "parties.opening",
        "مانده افتتاحیه طرف‌حساب",
        (
            RoleDef("receivable", "طلب از طرف‌حساب", "1201"),
            RoleDef("payable", "بدهی به طرف‌حساب", "3101"),
            RoleDef("offset", "طرف مقابل مانده افتتاحیه", "4101"),
        ),
    ),
    EventDef(
        "treasury.receipt.finalized",
        "دریافت",
        (
            RoleDef("cash", "صندوق", "1101"),
            RoleDef("bank", "بانک", "1103"),
            RoleDef("cheques_receivable", "اسناد دریافتنی", "1202"),
            RoleDef("receivable", "کاهش طلب از مشتری", "1201"),
            RoleDef("payable", "افزایش بدهی (دریافت از تأمین‌کننده)", "3101"),
        ),
    ),
    EventDef(
        "treasury.payment.finalized",
        "پرداخت",
        (
            RoleDef("payable", "کاهش بدهی به تأمین‌کننده", "3101"),
            RoleDef("receivable", "استرداد به مشتری", "1201"),
            RoleDef("cash", "صندوق", "1101"),
            RoleDef("bank", "بانک", "1103"),
            RoleDef("cheques_payable", "اسناد پرداختنی", "3102"),
        ),
    ),
    EventDef(
        "treasury.transfer.finalized",
        "انتقال وجه",
        (
            RoleDef("cash", "صندوق", "1101"),
            RoleDef("bank", "بانک", "1103"),
        ),
    ),
    EventDef(
        "treasury.cheque.changed",
        "تغییر وضعیت چک",
        (
            RoleDef("bank", "بانک", "1103"),
            RoleDef("cheques_receivable", "اسناد دریافتنی", "1202"),
            RoleDef("cheques_payable", "اسناد پرداختنی", "3102"),
            RoleDef("receivable", "طلب از مشتری", "1201"),
            RoleDef("payable", "بدهی به تأمین‌کننده", "3101"),
        ),
    ),
    EventDef(
        "inventory.opening.finalized",
        "موجودی اول دوره کالا",
        (
            RoleDef("inventory", "موجودی کالا", "1301"),
            RoleDef("offset", "طرف مقابل موجودی اول دوره", "4101"),
        ),
    ),
    EventDef(
        "inventory.adjustment.finalized",
        "تعدیل موجودی",
        (
            RoleDef("inventory", "موجودی کالا", "1301"),
            RoleDef("shortage", "کسری انبار", "7108"),
            RoleDef("surplus", "اضافه انبار", "5203"),
        ),
    ),
    EventDef(
        "sales.shift.closed",
        "بستن شیفت صندوق",
        (
            RoleDef("cash", "صندوق", "1101"),
            RoleDef("shortage", "کسری صندوق", "7107"),
            RoleDef("overage", "اضافه صندوق", "5202"),
        ),
    ),
    EventDef(
        "payments.card.settled",
        "تسویه کارت‌خوان",
        (
            RoleDef("bank", "بانک", "1103"),
            RoleDef("clearing", "وجوه در راه کارت‌خوان", "1104"),
            RoleDef("fee", "کارمزد بانکی", "7105"),
        ),
    ),
    # Weighbridge platform statements (ADR-0025). The retail chart has no haulage
    # accounts: the defaults are general ones for the accountant to replace.
    EventDef(
        "va.haulage",
        "صورت‌وضعیت حمل (سامانه باسکول)",
        (
            RoleDef("expense", "هزینه حمل", "7199"),
            RoleDef("vat_receivable", "مالیات خرید", "1402"),
            RoleDef("adjustments", "کسورات و اضافات صورت‌وضعیت", "7199"),
            RoleDef("payable", "بدهی به پیمانکار حمل", "3101"),
        ),
    ),
    EventDef(
        "va.sales",
        "صورت‌حساب فروش (سامانه باسکول)",
        (
            RoleDef("receivable", "طلب از مشتری", "1201"),
            RoleDef("revenue", "درآمد فروش", "5101"),
            RoleDef("adjustments", "تخفیف و اضافات فروش", "5103"),
            RoleDef("vat_payable", "مالیات و عوارض فروش", "3201"),
        ),
    ),
    EventDef(
        "fiscal.year.closed",
        "بستن سال مالی",
        (RoleDef("retained_earnings", "سود (زیان) انباشته", "4201"),),
    ),
)

EVENTS_BY_TYPE = {e.event_type: e for e in EVENTS}
