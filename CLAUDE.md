# NEXTCAM ERP — قواعد توسعه

مرجع کامل: `docs/MASTER_PROMPT.md` · نقشه راه و وضعیت: `docs/ROADMAP.md` · تصمیم‌ها: `docs/architecture/decisions/`.
قبل از هر کار: ROADMAP را بخوان، فاز جاری را مشخص کن و وضعیت واقعی کد را بررسی کن.

## زمینه
- تک‌مستأجر (یک نصب = یک سازمان = یک دیتابیس)، چندشعبه با `branch_id`.
- مشتری اول سوپرمارکت. مؤدیان و حقوق و دستمزد در نسخه ۲.
- Backend: Flask (Application Factory، Blueprint برای هر ماژول در `backend/app/modules/<name>/`)، SQLAlchemy 2، Alembic، Pydantic v2.
- دیتابیس: SQL Server (ODBC Driver 18). SQLite فقط برای صف محلی Agent/کلاینت.

## قواعد غیرقابل‌مذاکره
1. مبلغ `Decimal`/`DECIMAL(19,4)` ریال؛ مقدار `DECIMAL(19,3)`. **هرگز float.** مبلغ در JSON به‌صورت رشته.
2. زمان UTC در دیتابیس؛ تاریخ شمسی فقط در نمایش.
3. PK = UUID؛ ایجاد سند با `Idempotency-Key`؛ ویرایش با `row_version`.
4. منطق کسب‌وکار در `services`، نه در `api` و نه در Frontend. هر عملیات = یک `unit_of_work()`.
5. سند قطعی حذف یا ویرایش نمی‌شود؛ فقط برگشت/اصلاح با سابقه. سند نامتوازن قطعی نمی‌شود.
6. موجودی فقط از گردش انبار (`stock_ledger`) تغییر می‌کند.
7. سند خودکار از `posting_rule`؛ حساب hard-code نمی‌شود.
8. مجوز در Backend برای هر endpoint؛ مخفی‌کردن دکمه کنترل امنیتی نیست.
9. هرگز اتصال مستقیم کلاینت به دیتابیس.
10. کارت‌خوان: timeout ≠ شکست؛ Unknown بدون استعلام دوباره پرداخت نمی‌شود؛ Mock هرگز در production؛ PAN/PIN هرگز ذخیره یا لاگ نمی‌شود. درباره مدل، SDK یا پروتکل اطلاعات ساختگی نساز.
11. تعارض آفلاین مالی/موجودی هرگز Last-Write-Wins.
12. اسرار فقط در Environment (`NEXTCAM_*`)؛ هیچ رمز یا connection string واقعی در گیت.
13. پیام خطای عمومی بدون جزئیات داخلی.

## روال کار
- شاخه از `main`، PR، CI سبز. Conventional Commits.
- تغییر مدل داده = Migration Alembic + تست upgrade/downgrade.
- تصمیم معماری جدید = ADR جدید.
- تست‌های دیتابیسی روی SQL Server واقعی (`TEST_DATABASE_URL`)، نه SQLite.
- **هیچ تستی را موفق اعلام نکن مگر واقعاً اجرا شده باشد.** Mock جایگزین تست سخت‌افزار واقعی نیست.
- پایان هر فاز: گزارش تغییرات، تست‌های اجراشده و نتیجه، محدودیت‌ها؛ به‌روزرسانی جدول وضعیت ROADMAP.

## دستورات (از `backend/`)
```bash
uv venv .venv && uv pip install -p .venv -e ".[dev]"    # یا: python -m venv .venv && pip install -e ".[dev]"
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy app
TEST_DATABASE_URL='mssql+pyodbc://...' .venv/bin/pytest -q
.venv/bin/alembic upgrade head          # نیازمند NEXTCAM_DATABASE_URL
```
SQL Server محلی برای تست در کانتینر ابری:
`docker run -d --name mssql -e ACCEPT_EULA=Y -e MSSQL_SA_PASSWORD=... -p 1433:1433 mcr.microsoft.com/mssql/server:2022-latest`
