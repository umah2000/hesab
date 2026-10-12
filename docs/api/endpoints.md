# فهرست APIهای اصلی

قراردادها:
- پیشوند `/api/v1`؛ JSON؛ مبالغ به‌صورت رشته (`"125000.0000"`).
- خطا: `{"error": {"code", "message", "details?", "incident?"}}` — پیاده‌شده در `backend/app/core/errors.py`.
- صفحه‌بندی: `?page=&page_size=` (حداکثر ۲۰۰) ← `{"items": [], "total", "page", "page_size"}`.
- ایجاد سند: هدر الزامی `Idempotency-Key`.
- ویرایش: هدر `If-Match: <row_version>`؛ ناسازگاری ← 409.
- هر endpoint یک مجوز مشخص دارد ([`permissions.md`](../security/permissions.md)).
- مستند OpenAPI از schemaهای Pydantic تولید می‌شود (فاز ۱).

| فاز | روش | مسیر | مجوز | توضیح |
|---|---|---|---|---|
| ۰ ✅ | GET | `/system/health` | عمومی | زنده بودن |
| ۰ ✅ | GET | `/system/ready` | عمومی | اتصال دیتابیس |
| ۱ ✅ | POST | `/auth/login` · `/auth/logout` | عمومی (Rate limited) / نشست | کوکی httpOnly + CSRF |
| ۱ ✅ | GET | `/auth/me` | نشست | کاربر، مجوزها، محدوده |
| ۱ ✅ | POST | `/auth/change-password` | نشست | |
| ۱ ✅ | GET/POST | `/users` · GET/PATCH `/users/{id}` | `users.manage` | |
| ۱ ✅ | POST | `/users/{id}/reset-password` · `/users/{id}/unlock` | `users.manage` | |
| ۱ ✅ | GET | `/roles` · `/roles/permissions` | `roles.manage` (یا `users.manage` برای فهرست) | |
| ۱ ✅ | POST/PATCH | `/roles` · `/roles/{id}` | `roles.manage` | |
| ۱ ✅ | GET | `/audit/events` | `audit.view` | |
| ۱ ✅ | GET/PUT | `/organization/settings` | نشست / `settings.manage` | |
| ۱ ✅ | GET/POST/PATCH | `/organization/branches` · `/branches/{id}` | نشست / `branches.manage` | |
| ۱ ✅ | GET/POST/PATCH | `/organization/branches/{id}/cash-registers` · `/organization/cash-registers` | نشست / `branches.manage` | |
| ۱ ✅ | GET | `/openapi.json` | عمومی | مستند OpenAPI 3.1 |
| ۲ ✅ | GET/POST/PATCH | `/accounting/accounts` · `/accounts/{id}` | خواندن: هر مجوز حسابداری / نوشتن: `accounting.account.manage` | |
| ۲ ✅ | GET/POST/PATCH | `/accounting/detail-accounts` · `/detail-accounts/{id}` | همان | |
| ۲ ✅ | GET/POST | `/accounting/fiscal-years` | خواندن / `accounting.fiscal.close` | ایجاد با سال شمسی |
| ۲ ✅ | PUT | `/accounting/fiscal-periods/{id}/lock` | `accounting.fiscal.close` | |
| ۲ ✅ | POST | `/accounting/fiscal-years/{id}/close` | `accounting.fiscal.close` | بستن سال |
| ۲ ✅ | GET | `/accounting/vouchers` · `/vouchers/{id}` | هر مجوز حسابداری | فیلتر سال/وضعیت/تاریخ/شماره |
| ۲ ✅ | POST/PUT/DELETE | `/accounting/vouchers` · `/vouchers/{id}` | `accounting.voucher.create` | فقط پیش‌نویس |
| ۲ ✅ | POST | `/accounting/vouchers/{id}/finalize` | `accounting.voucher.finalize` | If-Match |
| ۲ ✅ | POST | `/accounting/vouchers/{id}/reverse` | `accounting.voucher.reverse` | If-Match |
| ۲ ✅ | GET/PUT | `/accounting/posting-rules` | خواندن / `accounting.account.manage` | |
| ۲ ✅ | GET | `/accounting/reports/trial-balance` · `/ledger` · `/journal` | `accounting.report.view` | |
| ۳ | GET | `/inventory/units` · `/groups` · `/price-lists` · `/warehouses` | هر مجوز انبار | `POST /groups` با `inventory.item.manage`؛ `POST /warehouses` با `branches.manage` |
| ۳ | GET/POST/PUT | `/inventory/items` · `/items/{id}` | `inventory.item.manage` (قیمت: `inventory.price.manage`) | جست‌وجو در کد، نام و بارکد؛ فیلتر گروه و زیر حداقل |
| ۳ | GET | `/inventory/items/lookup?barcode=` | `sales.pos.use` · `inventory.item.manage` · `inventory.stock.create` | **مسیر داغ صندوق**: بارکد ← بارکد بسته ← برچسب ترازو ← کد کالا |
| ۳ | GET/POST/PUT | `/inventory/scale-rules` | `inventory.item.manage` | |
| ۳ | GET/POST/PUT/DELETE | `/inventory/stock-documents` · `/{id}/finalize` | `inventory.stock.create` (تعدیل/شمارش: `inventory.stock.adjust`) | اول دوره، تعدیل، انتقال، شمارش |
| ۳ | GET | `/inventory/balances` · `/kardex?item_id=&warehouse_id=` | `inventory.report.view` | balances جمع ارزش را هم برمی‌گرداند |
| ۳ | GET/POST | `/inventory/import/{items,opening}/template` · `/preview` · `/commit` | `import.run` | multipart؛ همه یا هیچ؛ حداکثر ۲۵MB |
| ۴ | GET | `/sales/registers/{id}/state` | `sales.pos.use` / گزارش | شیفت، معلق‌ها، کارت‌خوان، مجوزهای صندوق‌دار |
| ۴ | POST | `/sales/shifts/open` · `/sales/shifts/{id}/close` (If-Match) | `sales.shift.open` / `sales.shift.close` | بستن با شمارش کور؛ کسری/اضافه سند می‌خورد |
| ۴ | GET | `/sales/shifts` · `/sales/shifts/{id}/report` | صندوق‌دار (شیفت خود) / `sales.report.view` | |
| ۴ | POST | `/sales/quote` | `sales.pos.use` | قیمت‌گذاری سبد بدون ثبت؛ هر اسکن |
| ۴ | POST | `/sales/invoices` (Idempotency-Key) | `sales.pos.use` + مجوز هر روش پرداخت | فروش + انبار + سند + شماره در یک تراکنش |
| ۴ | GET | `/sales/invoices` · `/sales/invoices/{id}` | `sales.report.view` / `sales.return.create` / صندوق‌دار (فاکتور خود) | |
| ۴ | POST | `/sales/invoices/{id}/returns` (Idempotency-Key) | `sales.return.create` | با یک روش استرداد، مبلغ را سرور تعیین می‌کند |
| ۴ | POST/GET | `/sales/held` · `/sales/held/{id}/recall` | `sales.pos.use` | تعلیق و بازیابی بین صندوق‌های شعبه |
| ۴ | POST | `/sales/approvals` | `sales.pos.use` (+ رمز سرپرست) | محدودیت نرخ ۱۰ در دقیقه؛ یک‌بارمصرف، ۳ دقیقه |
| ۴ | POST | `/sales/line-removals` | `sales.pos.use` (+ تأیید) | ممیزی حذف کالای اسکن‌شده |
| ۴ | GET | `/sales/customers?q=` | `sales.payment.credit` / گزارش | سقف، مانده و اعتبار باقی‌مانده |
| ۴ | GET/POST/PUT | `/sales/promotions` | `inventory.price.manage` | |
| ۴ | GET | `/sales/reports/daily?date=` | `sales.report.view` | |
| ۴ | POST/GET | `/payments/terminal-transactions` · `/{id}` · `/{id}/inquire` | `sales.payment.card` | فعلاً فقط Mock در dev/test |
| ۴ | GET · POST | `/payments/terminal-transactions` (نامشخص‌ها) · `/{id}/resolve` | `payments.reconcile` | تطبیق دستی با گزارش بانک |
| ۴ | GET · POST | `/system/backups` · `/system/backups/run` · `/system/backups/offsite-copied` | `settings.manage` / `audit.view` | CLI: `flask backup`، `flask backup-restore-test` |
| ۵ | GET/POST · GET/PUT | `/parties` · `/parties/{id}` | `parties.view` / `parties.manage` | فیلتر نقش و مانده؛ اطلاعات حساس بدون manage پوشیده |
| ۵ | GET | `/parties/{id}/statement?date_from&date_to` | `parties.view` | گردش و مانده از اسناد قطعی |
| ۵ | GET/POST · POST | `/parties/{id}/notes` · `/parties/notes/{id}/done` · `GET /parties/follow-ups` | `parties.view` | یادداشت و پیگیری |
| ۵ | GET · POST | `/parties/import/template` · `/preview` · `/commit` | `import.run` (+ `parties.manage`) | مانده افتتاحیه ← سند پیش‌نویس |
| ۵ | GET/POST · GET/PUT · POST | `/purchasing/orders` · `/{id}` · `/{id}/approve\|cancel\|close` | `purchasing.manage` | |
| ۵ | GET/POST · GET/PUT/DELETE | `/purchasing/invoices` · `/{id}` | `purchasing.manage` | پیش‌نویس با محاسبه سرور و هشدار قیمت |
| ۵ | POST | `/purchasing/invoices/{id}/finalize` (If-Match) | `purchasing.manage` | رسید انبار + سند + شماره |
| ۵ | POST | `/purchasing/invoices/{id}/returns` (Idempotency-Key) | `purchasing.manage` | برگشت با بهای ورود |
| ۵ | GET | `/purchasing/items/{id}/price-history` · `/purchasing/dues?days=` | `purchasing.manage` | |
| ۵ | GET/POST · PUT | `/treasury/accounts` · `/{id}` | `treasury.manage` | صندوق و بانک با مانده |
| ۵ | POST | `/treasury/receipts` · `/payments` · `/transfers` · `/settlements` (Idempotency-Key) | `treasury.manage` | قطعی هنگام ثبت |
| ۵ | GET · POST | `/treasury/documents` · `/{id}` · `/{id}/reverse` (If-Match) | `treasury.manage` | برگشت با سند معکوس |
| ۵ | GET · POST | `/treasury/cheques` · `/{id}` · `/{id}/actions` (If-Match) | `treasury.manage` | واگذاری، وصول، برگشت، استرداد، ابطال |
| ۵ | GET · POST | `/treasury/statements/template` · `/treasury/accounts/{id}/statement` · `/preview` · `/commit` · `/auto-match` | `treasury.manage` | ردیف تکراری نادیده |
| ۵ | GET · POST | `/treasury/accounts/{id}/reconciliation?as_of=` · `/treasury/statement-lines/{id}/candidates` · `/match` · `/unmatch` | `treasury.manage` | مغایرت‌گیری |
| ۸ | POST | `/sync/push` · `GET /sync/pull?since=` | `sync.device` | [`protocol.md`](../sync/protocol.md) |
