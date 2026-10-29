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
| ✅ | POST | `/integrations/va/webhook` | بدون نشست؛ امضای HMAC (ADR-0025) | ۲۰۰ ثبت/تکراری، ۲۰۲ نگه‌داشته، ۴۰۴ اگر پیکربندی نشده |
| ✅ | GET | `/integrations/va/status` · `/integrations/va/documents` | `accounting.integration.manage` یا `accounting.report.view` | |
| ✅ | POST | `/integrations/va/documents/{id}/retry` | `accounting.integration.manage` | |
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
| ۱۰ | GET · POST | `/system/license` | GET: `settings.manage` / `reports.dashboard` / `audit.view`؛ POST: `settings.manage` | مجوز و کد درخواست فعال‌سازی (ADR-0021). CLI: `flask backup-keygen` برای کلید پشتیبان رمزنگاری‌شده (ADR-0020) |
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
| ۶ | GET/POST · GET/PUT | `/devices` · `/devices/{id}` | `devices.manage` | کد جفت‌سازی فقط در پاسخ ایجاد |
| ۶ | POST | `/devices/{id}/pairing-code` · `/revoke` · `/test-print` · `GET /devices/{id}/jobs` | `devices.manage` | |
| ۶ | GET · POST | `/devices/registers/{register_id}` · `/devices/print-receipt` (`paper=false`: فقط کشو) · `GET /devices/jobs/{id}` | `sales.pos.use` / گزارش فروش | چاپ از Agent؛ در خطا چاپ مرورگر |
| ۶ | POST | `/devices/open-drawer` | `sales.drawer.open` | با علت؛ ممیزی |
| ۶ | POST | `/devices/agent/pair` | عمومی، ۱۰ در دقیقه | کد یک‌بارمصرف ← توکن دستگاه |
| ۶ | POST | `/devices/agent/poll` · `/devices/agent/jobs/{id}/result` | `Authorization: Bearer` توکن دستگاه | بدون کوکی |
| ۷ | GET | `/reports` | هر مجوز گزارش | فهرست گزارش‌های مجاز کاربر |
| ۷ | GET | `/reports/dashboard?date_from&date_to&branch_id` | `reports.dashboard` | شاخص‌ها، نمودار روزانه، پرفروش‌ها، مانده‌ها |
| ۷ | GET | `/reports/{key}?…[&format=xlsx]` | مجوز همان گزارش (ADR-0016) | `sales`، `cash-shortages`، `stock-movement`، `slow-moving`، `near-expiry`، `debtors`، `creditors`، `money-flow`، `profit-loss`، `balance-sheet`؛ خروجی Excel ممیزی می‌شود |
| ۷ | GET · POST · DELETE | `/reports/saved-filters` · `/{id}` | هر مجوز گزارش | فقط فیلترهای خود کاربر |
| ۸ | GET | `/sync/agent/snapshot` (If-None-Match) | `Authorization: Bearer` توکن دستگاه | داده‌ی فروش آفلاین صندوق؛ بدون تغییر ← 304 ([`protocol.md`](../sync/protocol.md)) |
| ۸ | POST | `/sync/agent/push` `{ops: [...]}` | `Authorization: Bearer` توکن دستگاه | هر عملیات جدا و یک‌بار؛ `applied`/`rejected`/`conflict` |
| ۸ | GET · GET | `/sync/operations?status=open\|conflict\|…&device_id` · `/sync/operations/{id}` | `sync.resolve` | محدوده‌ی شعبه |
| ۸ | POST | `/sync/operations/{id}/resolve` `{action: apply\|discard, note}` (If-Match) | `sync.resolve` | ممیزی؛ ردشده فقط discard |
| ۸ | POST | `/devices/agent/poll` با `offline_queue` | توکن دستگاه | تا صف صفر نشود بستن شیفت آن صندوق ممکن نیست |
| ۹ | POST | `/auth/mobile/login` · `/auth/mobile/refresh` | عمومی، محدودیت نرخ | توکن دسترسی ۱۵ دقیقه + توکن تمدید یک‌بارمصرف (ADR-0018)؛ فقط `distribution.visitor` |
| ۹ | POST | `/auth/mobile/logout` | Bearer اپ | |
| ۹ | GET | `/distribution/mobile/bootstrap` (If-None-Match) | `distribution.visitor` (Bearer اپ) | مشتریان تخصیص‌یافته، کالا، واحد، قیمت فهرست، موجودی |
| ۹ | POST | `/distribution/mobile/quote` | `distribution.visitor` | قیمت قطعی سرور و اعتبار پس از سفارش |
| ۹ | POST · GET | `/distribution/mobile/orders` (id از گوشی؛ ارسال دوباره ← همان سفارش، 200) | `distribution.visitor` | سفارش‌های ۶۰ روز اخیر با وضعیت |
| ۹ | POST | `/distribution/mobile/orders/{id}/cancel` · `/distribution/mobile/visits` | `distribution.visitor` | لغو فقط پیش از بررسی؛ بازدید با id گوشی |
| ۹ | GET | `/distribution/mobile/customers/{id}/history` · `/account` · `GET /distribution/mobile/invoices/{id}` | `distribution.visitor` | فقط مشتری تخصیص‌یافته؛ کانال mine/visitor/shop، فقط مشاهده (ADR-0026) |
| ۹ | PUT | `/distribution/mobile/customers/{id}/location` | `distribution.visitor` | 204 |
| ۹ | GET | `/distribution/mobile/report?period=day\|week\|month&date` | `distribution.visitor` | فقط سفارش‌های خود ویزیتور |
| ۹ | POST · GET | `/distribution/mobile/collections` · `/distribution/mobile/customer-requests` (id از گوشی) | `distribution.visitor` | درخواست؛ اثر مالی فقط پس از تأیید |
| ۹ | GET · POST | `/distribution/mobile/notifications?since` · `/distribution/mobile/notifications/read` | `distribution.visitor` | |
| ۹ | GET · POST | `/distribution/collections` · `/{id}/approve\|reject` (If-Match) | فهرست: `distribution.manage` یا `treasury.manage`؛ تأیید و رد: `treasury.manage` | تأیید ← سند دریافت خزانه |
| ۹ | GET · POST | `/distribution/customer-requests` · `/{id}/approve\|reject` (If-Match) | `distribution.manage` | تأیید ← طرف‌حساب + تخصیص |
| ۹ | GET · PUT | `/distribution/targets?year&month` · `/distribution/visitors/{id}/targets/{year}/{month}` (If-Match برای تغییر) | `distribution.manage` | |
| ۹ | GET/POST · GET/PUT | `/distribution/visitors` · `/{id}` · `GET /distribution/candidates` | `distribution.manage` | ویزیتور از کاربر دارای نقش ویزیتور |
| ۹ | GET · PUT | `/distribution/visitors/{id}/customers` | `distribution.manage` | جایگزینی کامل فهرست مشتریان و روز بازدید |
| ۹ | GET | `/distribution/orders?status=open\|…&visitor_id&date_from&date_to` · `/{id}` | `distribution.manage` | محدوده‌ی شعبه |
| ۹ | POST | `/distribution/orders/{id}/approve\|reject\|invoice\|deliver` (If-Match) | `distribution.manage` | کنترل سقف اعتبار در تأیید و فاکتور؛ فاکتور نسیه با `cash_register_id`؛ ممیزی |
| ۹ | GET | `/distribution/visits` · `/reports/visitor-performance` | `distribution.manage` | |
