# ADR-0002: SQL Server Standard به‌عنوان دیتابیس مرکزی

**وضعیت:** پذیرفته · ۱۴۰۵/۰۷/۱۹

## زمینه
مالک محصول SQL Server Standard را روی سیستم محلی نصب کرده است. مشتریان هدف ایرانی با SQL Server آشنا هستند.

## تصمیم
- دیتابیس مرکزی: SQL Server (Standard در production؛ Developer در توسعه و CI).
- **حداقل نسخه پشتیبانی‌شده: SQL Server 2019** (نسخه مشتری اول). CI روی 2019 اجرا می‌شود؛ از امکانات انحصاری 2022 استفاده نمی‌شود. نصب آخرین CU توصیه می‌شود.
- اتصال: SQLAlchemy 2 + `pyodbc` + **ODBC Driver 18 for SQL Server**؛ URL فقط از `NEXTCAM_DATABASE_URL`.
- Backend با یک کاربر SQL اختصاصی با کمترین دسترسی (`db_datareader`، `db_datawriter`، `EXECUTE`) اجرا می‌شود؛ Migration با کاربر جدا با دسترسی DDL.
- تست‌های دیتابیسی روی SQL Server واقعی (کانتینر `mcr.microsoft.com/mssql/server:2019-latest` در CI).
- SQLite فقط برای صف محلی Agent/کلاینت.
- Backup با SQL Server Agent (موجود در Standard).

## پیامدها
+ امکانات Standard: SQL Server Agent، حافظه و هسته بیشتر از Express.
− هزینه لایسنس برای هر مشتری؛ برای مشتریان کوچک باید سازگاری با Express (سقف ۱۰GB هر دیتابیس) در مستندات فروش مشخص شود.
− هر صندوق/سرور نیازمند نصب ODBC Driver 18.
