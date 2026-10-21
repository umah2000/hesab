# NEXTCAM ERP

سامانه حسابداری، فروش و صندوق، انبارداری و مدیریت شعب — Flask · React · SQL Server.

- 📄 [پرامپت اصلی (نسخه ۲)](docs/MASTER_PROMPT.md)
- 🗺️ [نقشه راه و وضعیت فازها](docs/ROADMAP.md)
- 🏛️ [معماری](docs/architecture/overview.md) · [تصمیم‌ها](docs/architecture/decisions/)
- ❓ [سؤال‌های باز](docs/open-questions.md)

**وضعیت فعلی:** فازهای ۱ تا ۱۰ نسخه‌ی ۱ پیاده‌سازی شده‌اند و منتظر بازبینی، پایلوت و آزمون سخت‌افزار واقعی‌اند ([جدول وضعیت](docs/ROADMAP.md)).
- **نصب در فروشگاه:** [راهنمای نصب](docs/install/README.md)
- **راهنمای کاربری:** [docs/user](docs/user/)
- **طراحی:** [تصاویر و سیستم طراحی](docs/design/README.md)

این صفحه اجرای **محیط توسعه** روی رایانه‌ی خودتان است (ویندوز؛ روی لینوکس و مک هم همین دستورها با مسیرهای `.venv/bin`).

## ۱. پیش‌نیازها
| ابزار | نسخه | برای |
|---|---|---|
| Python | 3.12 یا 3.13 (گزینه‌ی «Add python.exe to PATH») | Backend، Device Agent |
| SQL Server | 2019 یا جدیدتر؛ Developer یا Express کافی است | دیتابیس |
| [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server) | 18 | اتصال Python به SQL Server |
| Node.js | 22 یا جدیدتر | رابط کاربری |
| Git | — | دریافت کد |
| Flutter (اختیاری) | 3.47.7 و Android SDK | فقط اپ ویزیتور |

```powershell
git clone https://github.com/umah2000/hesab.git
cd hesab
```

## ۲. دیتابیس (در SSMS)
```sql
CREATE DATABASE nextcam;
CREATE DATABASE nextcam_test;          -- فقط برای تست‌ها؛ هر اجرای تست آن را پاک و از نو می‌سازد
GO
CREATE LOGIN nextcam_app WITH PASSWORD = 'یک رمز قوی';
GO
USE nextcam;      CREATE USER nextcam_app FOR LOGIN nextcam_app; ALTER ROLE db_owner ADD MEMBER nextcam_app;
USE nextcam_test; CREATE USER nextcam_app FOR LOGIN nextcam_app; ALTER ROLE db_owner ADD MEMBER nextcam_app;
GO
ALTER DATABASE nextcam      SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE;
ALTER DATABASE nextcam_test SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE;
```
- **دسترسی:** در توسعه `db_owner` کافی است. در فروشگاه کاربر برنامه دسترسی محدود دارد ([deploy/windows/create-database.sql](deploy/windows/create-database.sql)).
- **SQL Login:** در SQL Server Configuration Manager حالت «SQL Server and Windows Authentication» و TCP/IP روی پورت 1433 باید فعال باشد. پس از تغییر، سرویس SQL Server را restart کنید.

## ۳. Backend
```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -e ..\packages\nextcam-core -e ".[dev]"     # nextcam-core اول نصب شود
copy .env.example .env
```
در `.env` این مقادیر را تنظیم کنید:
- `NEXTCAM_DATABASE_URL`: رمز را جایگزین کنید. کاراکتر خاص رمز URL-encode شود (`@` ← `%40`).
- `NEXTCAM_SECRET_KEY`: خروجی `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
- `NEXTCAM_COOKIE_SECURE=false`: فقط در توسعه روی `http`؛ بدون آن مرورگر کوکی نشست را نگه نمی‌دارد.

```powershell
flask --app app upgrade --skip-backup                 # ساخت جداول (دیتابیس خالی)
flask --app app setup --org-name "فروشگاه آزمایشی"     # یک‌بار: سازمان، شعبه، نقش‌ها، کاربر admin (رمز را می‌پرسد)
flask --app app check-integrity                       # همه باید ok باشند
flask --app app run                                   # http://127.0.0.1:5000
```
- **بررسی:** `http://127.0.0.1:5000/api/v1/system/ready` باید `"status": "ok"` برگرداند.
- **اجرای مثل فروشگاه:** به‌جای `flask run`، دستور `python -m app.serve` (waitress).

## ۴. رابط کاربری (پنجره‌ی دوم PowerShell)
```powershell
cd frontend
npm ci
npx vite
```
`http://localhost:5173` را باز کنید و با `admin` و رمز `setup` وارد شوید. Vite درخواست‌های `/api` را به `127.0.0.1:5000` می‌فرستد.

**ترتیب پیشنهادی آزمون دستی:**
1. تنظیمات: سال مالی، صندوق‌ها، کاربر صندوق‌دار.
2. کالا: تعریف یا ورود از Excel، سپس سند موجودی اول دوره.
3. صندوق: باز کردن شیفت، فروش، برگشت، بستن شیفت.
4. گزارش‌ها و داشبورد، سند حسابداری خودکار، پشتیبان‌گیری.

## ۵. Device Agent بدون چاپگر (اختیاری)
```powershell
cd device-agent
python -m venv .venv
.venv\Scripts\activate
pip install -e ..\packages\nextcam-core -e ".[dev,windows]"
```
1. **تعریف دستگاه:** در برنامه به «دستگاه‌های صندوق» ← «دستگاه جدید» بروید و کد جفت‌سازی بگیرید.
2. **جفت‌سازی:** `nextcam-agent pair --server http://127.0.0.1:5000 --code <کد>`
3. **چاپ در فایل:** در `C:\ProgramData\NEXTCAM\agent\agent.json` مقدار `"printer_override": "file:C:\\temp\\receipts.bin"` را بگذارید (فقط توسعه؛ هرگز روی صندوق).
4. **اجرا:** `nextcam-agent run`. صندوق آفلاین از `http://127.0.0.1:47616/pos` باز می‌شود.

راهنمای کامل: [docs/install/device-agent.md](docs/install/device-agent.md).

## ۶. تست‌ها
همه‌ی دستورها همان‌هایی است که CI اجرا می‌کند.

**Backend** (از `backend`):
```powershell
$env:TEST_DATABASE_URL = "mssql+pyodbc://nextcam_app:رمز@localhost:1433/nextcam_test?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
$env:TEST_BACKUP_DIR = "C:\Program Files\Microsoft SQL Server\MSSQL16.MSSQLSERVER\MSSQL\Backup"   # پوشه‌ی Backup نسخه‌ی شما
ruff check . ; ruff format --check . ; mypy app
pytest -q
```
- **بدون `TEST_DATABASE_URL`:** تست‌های دیتابیسی skip می‌شوند، نه pass.
- **`TEST_BACKUP_DIR`:** پوشه‌ی Backup خودِ SQL Server است. حساب سرویس SQL Server باید در آن بنویسد.
- **تست کپی رمزنگاری‌شده:** این تست به `TEST_BACKUP_READ_DIR` هم نیاز دارد. روی همان رایانه، مقدار آن همان `TEST_BACKUP_DIR` است.

**هسته‌ی مشترک** (از `packages/nextcam-core`):
```powershell
pip install -e ".[dev]" jdatetime
pytest -q
```

**Device Agent** (از `device-agent`):
```powershell
pytest -q
```

**Frontend** (از `frontend`):
```powershell
npx tsc --noEmit -p . ; npx vitest run ; npx vite build
```

**اپ ویزیتور** (از `mobile`؛ اختیاری): [mobile/README.md](mobile/README.md)

**آزمون بار:** با چند صندوق هم‌زمان، روی یک دیتابیس دورریختنی. راهنما و اعداد مرجع: [docs/testing/volume-test.md](docs/testing/volume-test.md).

## ساختار مخزن
```
backend/            Flask API (Modular Monolith)، Alembic، تست‌ها، اسکریپت‌های آزمون بار
frontend/           React + TypeScript + Vite + Tailwind (RTL)
packages/nextcam-core/  منطق مشترک سرور و صندوق آفلاین (قیمت‌گذاری، ترازو، رسید)
device-agent/       Agent صندوق: چاپ، کشو، نمایشگر مشتری، دروازه‌ی آفلاین
mobile/             اپ اندروید ویزیتور (Flutter)
deploy/             نصب ویندوز و HTTPS
tools/              ساخت بسته‌ی انتشار و ابزار مجوز فروشنده
docs/               نقشه راه، معماری و ADRها، نصب، راهنمای کاربری، تست، امنیت
.github/            CI: Backend روی SQL Server 2019، هسته، Agent روی ویندوز و لینوکس، Frontend، اپ، امنیت
```
