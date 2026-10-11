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
| ۲ | CRUD | `/accounting/accounts` · `/accounting/detail-accounts` | `accounting.account.*` | |
| ۲ | CRUD | `/accounting/fiscal-years` · `POST /{id}/close` | `accounting.fiscal.*` | |
| ۲ | POST | `/accounting/vouchers` | `accounting.voucher.create` | |
| ۲ | POST | `/accounting/vouchers/{id}/finalize` · `/reverse` | `.finalize` · `.reverse` | |
| ۲ | GET | `/accounting/reports/trial-balance` · `/ledger` · `/journal` | `accounting.report.view` | |
| ۳ | CRUD | `/inventory/items` · `/item-groups` · `/units` · `/price-lists` | `inventory.item.*` | |
| ۳ | GET | `/inventory/items/lookup?barcode=` | `sales.pos.use` | **مسیر داغ صندوق**؛ بارکد ترازو را هم تجزیه می‌کند |
| ۳ | POST | `/inventory/stock-documents` · `/{id}/finalize` | `inventory.stock.*` | رسید/حواله/انتقال/تعدیل |
| ۳ | GET | `/inventory/kardex?item_id=&warehouse_id=` · `/balances` | `inventory.report.view` | |
| ۳ | POST | `/import/{entity}` (preview) · `/import/{job}/commit` | `import.run` | Excel |
| ۴ | POST | `/sales/shifts/open` · `/sales/shifts/{id}/close` | `sales.shift.*` | |
| ۴ | POST | `/sales/invoices` · `/{id}/hold` · `/{id}/finalize` · `/{id}/void` | `sales.invoice.*` | finalize = فروش + انبار + سند در یک تراکنش |
| ۴ | POST | `/sales/invoices/{id}/returns` | `sales.return.create` | |
| ۴ | POST | `/payments/terminal-transactions` · `GET /{id}` · `POST /{id}/inquire` | `sales.payment.card` | |
| ۴ | GET | `/sales/reports/daily` · `/shift/{id}` | `sales.report.view` | |
| ۵ | … | `/parties` · `/purchasing/*` · `/treasury/*` | | |
| ۸ | POST | `/sync/push` · `GET /sync/pull?since=` | `sync.device` | [`protocol.md`](../sync/protocol.md) |
