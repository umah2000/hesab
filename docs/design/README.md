# سیستم طراحی NEXTCAM — «Glass 2026»

مبنا: طرح نمونه مالک محصول (گلس‌مورفیسم، بنفش/آبی، RTL) + استانداردهای کاربردپذیری ۲۰۲۶ برای نرم‌افزار اداری/فروشگاهی که روزانه ساعت‌ها استفاده می‌شود. تصمیم: [ADR-0010](../architecture/decisions/0010-glass-design-system.md).

## اصول

| # | اصل | پیاده‌سازی |
|---|---|---|
| 1 | **شیشه برای قاب، سطح مات برای داده** | `glass` فقط برای sidebar، header، کارت‌ها و دیالوگ؛ جدول‌ها و فرم‌ها روی `surface` تقریباً مات تا متن خوانا بماند (کنتراست AA) |
| 2 | **حالت سبک برای سخت‌افزار ضعیف** | منوی کاربر ← «حالت سبک»: blur حذف، سطوح مات (`data-perf="lite"`)؛ برای صندوق‌های Core i3 / RAM کم توصیه می‌شود. `prefers-reduced-transparency` هم رعایت می‌شود |
| 3 | **وضعیت فقط با رنگ نیست** | هر Badge متن + آیکون دارد (موفق، هشدار، خطا) |
| 4 | **RTL واقعی** | `dir="rtl"` سراسری، کلاس‌های منطقی (`ps/pe`, `start/end`)، فیلدهای لاتین (نام کاربری، رمز) `dir="ltr"` |
| 5 | **ارقام فارسی در نمایش، پذیرش هر دو در ورودی** | `toFaDigits` / `toEnDigits`؛ تاریخ شمسی با `Intl` (بدون کتابخانه)، منطقه زمانی تهران |
| 6 | **مبلغ با رشته، نه float** | `formatMoney` تبدیل ریال/تومان را با عملیات رشته‌ای انجام می‌دهد |
| 7 | **صفحه‌کلید اول** | Ctrl+K برای پرش سریع؛ صندوق: کلیدهای F برای همه عملیات |
| 8 | **بدون وابستگی اینترنتی** | فونت وزیرمتن و همه منابع داخل باندل؛ شبکه داخلی فروشگاه ممکن است اینترنت نداشته باشد |
| 9 | **ماژول‌های آینده صادقانه** | آیتم‌های منوی ماژول‌های پیاده‌نشده غیرفعال با برچسب «فاز N»؛ داشبورد عدد ساختگی نشان نمی‌دهد |
| 10 | **حالت تیره** | توکن‌های رنگی جدا برای تیره؛ ترجیح سیستم‌عامل به‌عنوان پیش‌فرض |

## توکن‌ها
در `frontend/src/index.css` (`@theme` در Tailwind v4): رنگ برند (بنفش ۲۷۵°)، `ink` سه سطح، success / warning / danger / info، شعاع‌ها، سایه‌ها، `--blur`.

## مؤلفه‌ها (`frontend/src/components/ui`)
Button (primary / secondary / ghost / danger / outline، حالت loading)، Input، Select، Checkbox، Field (برچسب + خطا + راهنما)، Card، Dialog، Table + Pagination، Badge، Spinner، EmptyState، ErrorBox (با کد پیگیری)، Skeleton.
به سبک shadcn/ui و روی Radix نوشته شده‌اند. CLI خود shadcn نصب نشد، چون دسترسی به رجیستری آن در محیط توسعه مسدود است.

## تصاویر
| فایل | توضیح | داده |
|---|---|---|
| `screenshots/01-login.png` | ورود | — |
| `screenshots/02-dashboard.png` | داشبورد روشن | واقعی (دیتابیس توسعه) |
| `screenshots/08-dashboard-dark.png` | داشبورد تیره | واقعی |
| `screenshots/03-users.png` | کاربران | واقعی |
| `screenshots/04-user-dialog-validation.png` | فرم کاربر جدید با خطای اعتبارسنجی | — |
| `screenshots/05-roles.png` | نقش‌ها | واقعی |
| `screenshots/06-audit.png` | ممیزی | واقعی |
| `screenshots/07-settings.png` | تنظیمات، شعب و صندوق‌ها | واقعی |
| `screenshots/09-command-palette-dark.png` | پرش سریع Ctrl+K | — |
| `screenshots/10-users-mobile.png` | موبایل | واقعی |
| `screenshots/11-pos-mockup.png` | **طرح پیشنهادی صندوق (فاز ۴)** | **نمونه** — `mockups/pos.html` |
| `screenshots/12-vouchers.png` | فهرست اسناد | واقعی |
| `screenshots/13-voucher-editor.png` | ثبت سند با صفحه‌کلید | واقعی (e2e) |
| `screenshots/14-voucher-final.png` | سند قطعی | واقعی |
| `screenshots/15-voucher-unbalanced-draft.png` | پیش‌نویس نامتوازن | واقعی |
| `screenshots/16-chart-of-accounts.png` | کدینگ درختی | واقعی |
| `screenshots/17-trial-balance.png` | تراز آزمایشی سطح کل | واقعی |
| `screenshots/18-ledger.png` | دفتر معین بانک با مانده جاری | واقعی |
| `screenshots/19-fiscal-years.png` | سال و دوره مالی | واقعی |
| `screenshots/20-posting-rules.png` | قواعد ثبت خودکار | واقعی |
| `screenshots/21-items.png` | فهرست کالاها | نمونه (داده آزمایشی دیتابیس توسعه) |
| `screenshots/22-item-dialog.png` | کارت کالا: واحد فرعی، بارکد بسته، قیمت هر واحد | نمونه |
| `screenshots/23-stock-doc-scan.png` | سند تعدیل با اسکن بارکد، بارکد بسته و برچسب ترازو | نمونه (e2e) |
| `screenshots/23b-stock-doc-final.png` | سند انبار قطعی با پیوند سند حسابداری | نمونه (e2e) |
| `screenshots/24-balances-kardex.png` | موجودی، ارزش کل و کاردکس | نمونه |
| `screenshots/25-inventory-settings-scale.png` | قاعده بارکد ترازو و آزمایشگر | نمونه |
| `screenshots/26-scale-rule-dialog.png` | تعریف قاعده ترازو با الگوی آماده | — |
| `screenshots/27-labels.png` | پیش‌نمایش برچسب قیمت | نمونه |
| `screenshots/28-import.png` | ورود از Excel | — |
| `screenshots/29-items-dark.png` | کالاها، حالت تیره | نمونه |
| `screenshots/30-pos-open-shift.png` | صندوق: شروع شیفت | — |
| `screenshots/31-pos-cart.png` | صندوق: سبد با اسکن، بارکد بسته، پروموشن و برچسب ترازو | نمونه (e2e) |
| `screenshots/32-pos-supervisor-approval.png` | تأیید سرپرست برای حذف ردیف | نمونه (e2e) |
| `screenshots/33-pos-payment-cash.png` | دریافت نقد و باقی‌مانده | نمونه (e2e) |
| `screenshots/34-pos-sale-done.png` | پس از ثبت فروش | نمونه (e2e) |
| `screenshots/35-receipt-80mm.png` | فیش ۸۰ میلی‌متری (نمای چاپ) | نمونه (e2e) |
| `screenshots/36-pos-card-unknown.png` | کارت‌خوان آزمایشی: وضعیت نامشخص و استعلام | **Mock** |
| `screenshots/37-pos-held.png` | فاکتورهای معلق | نمونه (e2e) |
| `screenshots/38-pos-shift-closed.png` | بستن شیفت با شمارش کور | نمونه (e2e) |
| `screenshots/39-dashboard-backup-warning.png` | هشدار پشتیبان‌گیری در داشبورد | واقعی (دیتابیس توسعه) |
| `screenshots/40-sales-invoices.png` | فهرست فاکتورها | نمونه |
| `screenshots/41-invoice-detail.png` | جزئیات فاکتور و فیش چاپ مجدد | نمونه |
| `screenshots/42-return-dialog.png` | برگشت از فروش | نمونه (e2e) |
| `screenshots/43-daily-report.png` | گزارش فروش روزانه | نمونه |
| `screenshots/44-shifts.png` | شیفت‌ها و گزارش شیفت | نمونه |
| `screenshots/45-promotions.png` | پروموشن‌ها | نمونه |
| `screenshots/46-settings-sales-backup.png` | تنظیمات فروش و پشتیبان‌گیری | نمونه |

## طرح صندوق (فاز ۴) — تصمیم‌های کلیدی
- فیلد اسکن همیشه فوکوس دارد و بزرگ است؛ نتیجه آخرین اسکن کنار آن نمایش داده می‌شود.
- مبلغ قابل پرداخت بزرگ‌ترین عنصر صفحه است.
- دکمه‌های پرداخت بزرگ (مناسب لمسی) با کلید F.
- وضعیت سرور، بارکدخوان، پرینتر و کارت‌خوان همیشه در نوار بالا با متن.
- کارت‌خوان تا اتصال رسمی PSP برچسب «آزمایش‌نشده» دارد.
- در صندوق، شیشه کمتر استفاده می‌شود (سرعت و خوانایی مقدم است).
