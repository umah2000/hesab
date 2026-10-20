# نصب با بسته‌ی انتشار (ویندوز)

از فاز ۱۰، نصب سرور با **بسته‌ی انتشار** و اسکریپت‌های PowerShell انجام می‌شود. راهنمای دستی ([lan-install.md](lan-install.md)) پس‌زمینه و جزئیات است؛ این صفحه روش استاندارد است.

> ⚠️ **وضعیت آزمون:** این اسکریپت‌ها روی **ویندوز واقعی اجرا نشده‌اند**.
> - در محیط توسعه (لینوکس) فقط با PowerShell 7 تجزیه (parse) شده‌اند.
> - مراحلی که اسکریپت‌ها با برنامه انجام می‌دهند روی SQL Server 2019 واقعی آزموده شده‌اند: `flask upgrade`، `setup`، `backup`، `backup-restore-test` و `check-integrity`، با همان دسترسی حداقلی `create-database.sql`.
> - **اولین نصب روی سرور فروشگاه** را با حضور پشتیبان انجام دهید و نتیجه را در چک‌لیست تحویل ثبت کنید.

## بسته‌ی انتشار
`nextcam-<نسخه>.zip`، ساخته‌شده با `tools/release/build_release.py --build-frontend --wheels`. همراه آن فایل `.sha256` است. محتوا:

| پوشه | محتوا |
|---|---|
| `backend/` | برنامه‌ی سرور و migrationها |
| `frontend-dist/` | رابط کاربری ساخته‌شده |
| `packages/nextcam-core/`، `device-agent/` | هسته‌ی مشترک و برنامه‌ی صندوق |
| `wheels/` | بسته‌های پایتون ویندوز؛ نصب **بدون اینترنت** |
| `deploy/windows/` | اسکریپت‌های نصب، به‌روزرسانی، حذف و SQL |
| `deploy/https/` | `Caddyfile` |
| `docs/install/` | همین راهنماها |
| `VERSION`، `SHA256SUMS` | نسخه و چکیده‌ی همه‌ی فایل‌ها |

پیش از نصب، چکیده‌ی بسته را با فایل `.sha256` مقایسه کنید:
```powershell
(Get-FileHash .\nextcam-1.0.0.zip -Algorithm SHA256).Hash
```

## پیش‌نیازهای سرور
1. **SQL Server 2019** (یا بالاتر) با آخرین CU. پورت 1433 روی شبکه باز نباشد.
2. **Python 3.13 (64 بیتی)** از python.org، همراه «py launcher».
3. **ODBC Driver 18 for SQL Server**.
4. یک دیسک دوم یا پوشه‌ی شبکه برای کپی رمزنگاری‌شده‌ی پشتیبان ([lan-install.md](lan-install.md) بخش ۸.۱).

## ۱. دیتابیس و کاربر برنامه (یک بار، در SSMS)
فایل `deploy\windows\create-database.sql` را باز کنید، **رمز** را جایگزین کنید و اجرا کنید. این اسکریپت کمترین دسترسی لازم را می‌دهد:
- **`db_owner` روی دیتابیس خود برنامه:** برای migrationها.
- **`dbcreator`:** برای آزمون بازیابی هفتگی.
- **خواندن دو جدول `msdb`:** برای اندازه‌ی پشتیبان.

## ۲. نصب
PowerShell را **Run as administrator** باز کنید، بسته را باز کنید و:
```powershell
cd C:\Temp\nextcam-1.0.0
powershell -ExecutionPolicy Bypass -File .\deploy\windows\install.ps1 `
  -OrgName "سوپرمارکت نمونه" -BackupDir D:\nextcam-backup -CopyDir \\nas\nextcam-copy
```
پارامترهای مهم:

| پارامتر | پیش‌فرض | توضیح |
|---|---|---|
| `-Root` | `C:\nextcam` | محل نصب |
| `-SqlServer` | `localhost` | نام سرور SQL |
| `-Database` | `nextcam` | نام دیتابیس |
| `-SqlUser` | `nextcam_app` | کاربر برنامه؛ **رمز آن پرسیده می‌شود** |
| `-Port` | `8080` | پورت برنامه |
| `-BackupDir` | `D:\nextcam-backup` | پشتیبان روزانه |
| `-CopyDir` | خالی | مقصد دوم کپی رمزنگاری‌شده |
| `-Https` | خاموش | برنامه فقط روی 127.0.0.1 و پشت Caddy ([https.md](https.md)) |

اسکریپت به ترتیب این کارها را انجام می‌دهد:
1. پیش‌نیازها را بررسی می‌کند.
2. برنامه را در `C:\nextcam\releases\<نسخه>` با محیط پایتون جدا نصب می‌کند (از `wheels`، بدون اینترنت).
3. فایل `C:\nextcam\config\.env` را می‌سازد:
   - `SECRET_KEY` و **کلید پشتیبان** تصادفی ساخته می‌شوند؛
   - دسترسی فقط برای Administrators و SYSTEM است.
4. ساختار دیتابیس را می‌سازد.
5. سازمان و مدیر سیستم را تعریف می‌کند. **رمز مدیر پرسیده می‌شود.**
6. کارهای زمان‌بندی‌شده را تعریف می‌کند:

   | کار | زمان |
   |---|---|
   | `NEXTCAM Server` | با روشن شدن سرور؛ در صورت خطا دوباره اجرا می‌شود |
   | `NEXTCAM Backup` | هر شب ۲۳:۳۰ |
   | `NEXTCAM Restore Test` | جمعه‌ها ساعت ۴ صبح |
7. قانون فایروال را می‌سازد، فقط برای شبکه‌ی خصوصی.
8. سرور را اجرا و اولین پشتیبان را تهیه می‌کند.

> ⚠️ در پایان، **کلید پشتیبان** نمایش داده می‌شود. آن را یادداشت کنید و **بیرون از سرور** نگه دارید (چک‌لیست تحویل).

گزارش‌ها در `C:\nextcam\logs\` (`server.log` و `backup.log`) نوشته می‌شوند.

## ۳. صندوق‌ها (Device Agent)
روی هر رایانه‌ی صندوق، از همان بسته:
```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\windows\install-agent.ps1 -Server https://nextcam.local -PairCode ABCD-EFGH
```
کد جفت‌سازی را از «دستگاه‌های صندوق ← دستگاه جدید» بگیرید. جزئیات در [device-agent.md](device-agent.md) است.

## ۴. به‌روزرسانی
[upgrade.md](upgrade.md).

## ۵. حذف
```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\windows\uninstall.ps1
```
- **حذف می‌شوند:** کارهای زمان‌بندی‌شده، قوانین فایروال و فایل‌های برنامه.
- **باقی می‌مانند:**
  - دیتابیس؛
  - پشتیبان‌ها؛
  - `config\.env` (مگر با `-RemoveConfig`).
- حذف دیتابیس هرگز با اسکریپت انجام نمی‌شود.
