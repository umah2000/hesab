# NEXTCAM ERP

سامانه حسابداری، فروش و صندوق، انبارداری و مدیریت شعب — Flask · React · SQL Server.

- 📄 [پرامپت اصلی (نسخه ۲)](docs/MASTER_PROMPT.md)
- 🗺️ [نقشه راه و وضعیت فازها](docs/ROADMAP.md)
- 🏛️ [معماری](docs/architecture/overview.md) · [تصمیم‌ها](docs/architecture/decisions/)
- ❓ [سؤال‌های باز](docs/open-questions.md)

**وضعیت فعلی:** فازهای ۱ تا ۴ پیاده‌سازی شده‌اند: کاربران و مجوزها، حسابداری، کالا و انبار، صندوق فروش، شیفت، برگشت و پشتیبان‌گیری. فاز ۴ منتظر پایلوت است. نصب در فروشگاه: [راهنمای نصب در شبکه داخلی](docs/install/lan-install.md). [تصاویر و سیستم طراحی](docs/design/README.md)

## اجرای Backend روی ویندوز با SQL Server محلی

### ۱. پیش‌نیازها
- Python 3.12 یا جدیدتر
- [Microsoft ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server)
- SQL Server Standard (نصب‌شده)

### ۲. ساخت دیتابیس و کاربر اختصاصی (در SSMS)
```sql
CREATE DATABASE nextcam;
CREATE DATABASE nextcam_test;          -- فقط برای تست‌ها
GO
CREATE LOGIN nextcam_app WITH PASSWORD = 'یک رمز قوی';
GO
USE nextcam;      CREATE USER nextcam_app FOR LOGIN nextcam_app; ALTER ROLE db_owner ADD MEMBER nextcam_app;
USE nextcam_test; CREATE USER nextcam_app FOR LOGIN nextcam_app; ALTER ROLE db_owner ADD MEMBER nextcam_app;
```
> در محیط توسعه `db_owner` کافی است. در production کاربر برنامه فقط `db_datareader`/`db_datawriter` می‌گیرد و Migration با کاربر جدا اجرا می‌شود (ADR-0002).
> اگر از SQL Login استفاده می‌کنید، «SQL Server and Windows Authentication mode» باید فعال و TCP/IP روی پورت 1433 در SQL Server Configuration Manager روشن باشد.

### ۳. نصب و اجرا
```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env      # سپس NEXTCAM_DATABASE_URL و NEXTCAM_SECRET_KEY را در .env تنظیم کنید
alembic upgrade head
flask --app app setup --org-name "نام فروشگاه"     # یک‌بار: سازمان، شعبه اصلی، نقش‌ها و کاربر admin (رمز را می‌پرسد)
flask --app app seed-defaults                      # پس از به‌روزرسانی: کدینگ، سال مالی، واحدها و انبارهای پیش‌فرض (تکرارپذیر)
flask --app app run          # توسعه؛ در فروشگاه: python -m app.serve (راهنمای نصب)
```
بررسی: `http://127.0.0.1:5000/api/v1/system/ready` باید `{"database": "up", "status": "ok"}` برگرداند.

> اگر روی `http` (بدون HTTPS) در شبکه داخلی اجرا می‌کنید، در `.env` بنویسید `NEXTCAM_COOKIE_SECURE=false`؛ وگرنه مرورگر کوکی نشست را نگه نمی‌دارد. HTTPS در فاز نصب (۴) راه‌اندازی می‌شود.

### ۳-ب. رابط کاربری (پنجره دوم PowerShell)
پیش‌نیاز: Node.js 22 یا جدیدتر.
```powershell
cd frontend
npm ci
npx vite
```
سپس `http://localhost:5173` را باز کنید و با `admin` و رمزی که در `setup` تعیین کردید وارد شوید.

### ۴. تست‌ها
```powershell
$env:TEST_DATABASE_URL = "mssql+pyodbc://nextcam_app:رمز@localhost:1433/nextcam_test?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
pytest -q
```
اگر `TEST_DATABASE_URL` تنظیم نشود، تست‌های دیتابیسی skip می‌شوند (نه pass).

## ساختار مخزن
```
backend/   Flask API (Modular Monolith)، Alembic، تست‌ها
frontend/  React + TypeScript + Vite + Tailwind (RTL، شیشه‌ای)
docs/      پرامپت، نقشه راه، معماری، ADRها، مدل داده، API، مجوزها، همگام‌سازی، سخت‌افزار، تست
.github/   CI: Backend (lint + type + تست روی SQL Server 2019) و Frontend (type + تست + build)
```
`device-agent/` و `mobile/` در فازهای ۶ و ۹ اضافه می‌شوند.
