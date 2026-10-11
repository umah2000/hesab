# ماتریس نقش و مجوز

- قالب مجوز: `module.resource.action`. اعمال **فقط در Backend** (دکوراتور روی endpoint + بررسی محدوده در service).
- محدوده (scope): شعبه، انبار، صندوق — از `user_scope`. کاربر بدون scope یک شعبه، هیچ داده‌ای از آن نمی‌بیند.
- نقش‌ها قابل تعریف توسط مدیر؛ نقش‌های زیر پیش‌فرض (seed) هستند.

**نقش‌ها:** ADM مدیر سیستم · MGR مدیر فروشگاه · ACC حسابدار · CSH صندوق‌دار · SUP سرپرست صندوق · WHK انباردار · PUR کارپرداز/خرید · AUD حسابرس (فقط مشاهده)

| مجوز | ADM | MGR | ACC | SUP | CSH | WHK | PUR | AUD |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `users.manage` · `roles.manage` | ✓ | | | | | | | |
| `settings.manage` | ✓ | | | | | | | |
| `audit.view` | ✓ | ✓ | | | | | | ✓ |
| `accounting.account.manage` | | | ✓ | | | | | |
| `accounting.voucher.create` | | | ✓ | | | | | |
| `accounting.voucher.finalize` | | ✓ | ✓ | | | | | |
| `accounting.voucher.reverse` | | ✓ | ✓* | | | | | |
| `accounting.fiscal.close` | | ✓ | | | | | | |
| `accounting.report.view` | | ✓ | ✓ | | | | | ✓ |
| `inventory.item.manage` | | ✓ | | | | ✓ | ✓ | |
| `inventory.price.manage` | | ✓ | | | | | | |
| `inventory.stock.create` | | | | | | ✓ | | |
| `inventory.stock.adjust` | | ✓ | | | | ✓* | | |
| `inventory.report.view` | | ✓ | ✓ | | | ✓ | ✓ | ✓ |
| `sales.pos.use` | | | | ✓ | ✓ | | | |
| `sales.shift.open` · `.close` | | | | ✓ | ✓ | | | |
| `sales.invoice.discount` (≤ سقف) | | ✓ | | ✓ | ✓¹ | | | |
| `sales.invoice.line_delete_after_scan` | | ✓ | | ✓ | | | | |
| `sales.invoice.void` | | ✓ | | ✓ | | | | |
| `sales.return.create` | | ✓ | | ✓ | | | | |
| `sales.payment.card` · `.cash` | | | | ✓ | ✓ | | | |
| `sales.payment.credit` (نسیه) | | ✓ | | ✓ | | | | |
| `sales.report.view` | | ✓ | ✓ | ✓² | | | | ✓ |
| `payments.reconcile` | | ✓ | ✓ | | | | | |
| `purchasing.*` | | ✓ | | | | | ✓ | |
| `treasury.*` | | ✓ | ✓ | | | | | |
| `import.run` | ✓ | ✓ | | | | | | |

\* نیازمند تأیید نقش دوم (four-eyes) در مبالغ بالاتر از سقف تنظیمی.
¹ صندوق‌دار فقط تا سقف درصد تنظیمی؛ بالاتر ← تأیید سرپرست روی همان صندوق (ورود رمز سرپرست، ثبت در ممیزی).
² فقط شیفت‌های شعبه خود.

**رویدادهای ممیزی اجباری:** ورود/خروج/قفل، تغییر نقش و مجوز، تخفیف بالای سقف، حذف ردیف پس از اسکن، ابطال فاکتور، برگشت، باز/بسته شدن شیفت و کسری، قطعی/برگشت سند، تعدیل موجودی، تغییر قیمت، تغییر تنظیمات، هر تراکنش کارت‌خوان، Restore.
