# راهنمای نصب در شبکه داخلی فروشگاه (پایلوت فاز ۴)

> **از فاز ۱۰:** نصب و به‌روزرسانی استاندارد با بسته‌ی انتشار و اسکریپت است: [windows-installer.md](windows-installer.md) و [upgrade.md](upgrade.md). این صفحه جزئیات و پس‌زمینه‌ی همان مراحل است.

> این راهنما برای **یک سرور ویندوزی** در فروشگاه است که SQL Server و NEXTCAM روی آن اجرا می‌شوند. صندوق‌ها فقط با **مرورگر** به آن وصل می‌شوند و هرگز مستقیم به دیتابیس وصل نمی‌شوند (قاعده ۹).

## ۱. معماری نصب

```
[صندوق ۱..۷: Chrome/Edge] ──HTTP(S)، پورت 8080──▶ [سرور: NEXTCAM (waitress)] ──localhost:1433──▶ [SQL Server]
```
- **یک سرویس، یک پورت:** همان سرویس هم API و هم رابط کاربری ساخته‌شده (`frontend/dist`) را ارائه می‌کند.
- **پورت 1433 روی شبکه باز نمی‌شود.** فقط برنامه روی همان سرور به SQL Server وصل است.

## ۲. سرور

| مورد | حداقل | پیشنهاد |
|---|---|---|
| پردازنده | Core i3 نسل ۸ (موجود) | i5 |
| حافظه | ۴GB (موجود؛ ریسک ثبت‌شده) | **۸ تا ۱۶GB** |
| دیسک | SSD | SSD + **دیسک دوم برای پشتیبان** |
| SQL Server | 2019 **با آخرین Cumulative Update** | — |

با ۴GB حافظه، سقف حافظه SQL Server را محدود کنید تا ویندوز و برنامه جا داشته باشند (در SSMS):
```sql
EXEC sp_configure 'show advanced options', 1; RECONFIGURE;
EXEC sp_configure 'max server memory (MB)', 1536; RECONFIGURE;
```

## ۳. نصب برنامه

۱. پیش‌نیازها: Python 3.12+، ODBC Driver 18، (فقط برای ساختن رابط کاربری) Node.js 22+.
۲. کد را در `C:\nextcam` قرار دهید.
۳. Backend:
```powershell
cd C:\nextcam\backend
python -m venv .venv
.venv\Scripts\pip install .
copy .env.example .env
```
۴. رابط کاربری (یک‌بار، یا روی رایانه دیگر و کپی پوشه `dist`):
```powershell
cd C:\nextcam\frontend
npm ci
npx vite build
```
۵. فایل `C:\nextcam\backend\.env` را تنظیم کنید (فقط روی همین سرور؛ هرگز در گیت):
```ini
NEXTCAM_ENV=production
NEXTCAM_DATABASE_URL=mssql+pyodbc://nextcam_app:<رمز>@localhost:1433/nextcam?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes
NEXTCAM_SECRET_KEY=<خروجی: python -c "import secrets; print(secrets.token_urlsafe(48))">
NEXTCAM_STATIC_DIR=C:\nextcam\frontend\dist
NEXTCAM_PORT=8080
NEXTCAM_BACKUP_DIR=D:\nextcam-backup
NEXTCAM_BACKUP_KEEP=14
NEXTCAM_LOG_LEVEL=WARNING
# فقط تا راه‌اندازی HTTPS (بخش ۶ و https.md):
NEXTCAM_COOKIE_SECURE=false
```
> `NEXTCAM_ENABLE_MOCK_PAYMENT_TERMINAL` در production مجاز نیست و برنامه با آن بالا نمی‌آید.

**کارت‌خوان سامان، پی‌سی‌پوز مرکزی (اختیاری، ADR-0024).** این مقادیر را پرداخت الکترونیک سامان می‌دهد و فقط در همین فایل قرار می‌گیرند:
```ini
NEXTCAM_SEP_PCPOS_URL=https://<سرور سرویس>:<درگاه سرویس>
NEXTCAM_SEP_PCPOS_IDENTITY_URL=https://<سرور هویت>:<درگاه هویت>
NEXTCAM_SEP_PCPOS_CLIENT_ID=<نام کاربری کلاینت>
NEXTCAM_SEP_PCPOS_CLIENT_SECRET=<رمز کلاینت>
NEXTCAM_SEP_PCPOS_USERNAME=<نام کاربری>
NEXTCAM_SEP_PCPOS_PASSWORD=<رمز>
# فقط اگر سامان نشانی http در شبکه‌ی داخلی داده است:
# NEXTCAM_SEP_PCPOS_ALLOW_HTTP=true
# حداکثر انتظار برای کارت و رمز مشتری (ثانیه):
# NEXTCAM_SEP_PCPOS_TIMEOUT_SECONDS=100
```
- سپس در «دستگاه‌های صندوق ← کارت‌خوان‌های بانکی» هر دستگاه را با ارائه‌دهنده‌ی «پی‌سی‌پوز مرکزی» و **شماره‌ی ترمینال** تعریف کنید.
- سرور باید به نشانی سامان دسترسی شبکه داشته باشد.
- پیش از فروش واقعی، چک‌لیست آزمون در `docs/hardware/payment-terminal-adapter.md` (بخش ۸) را با ترمینال آزمایشی انجام دهید.

۶. دیتابیس و راه‌اندازی اولیه:
```powershell
cd C:\nextcam\backend
.venv\Scripts\alembic upgrade head
.venv\Scripts\flask --app app setup --org-name "نام فروشگاه"
.venv\Scripts\flask --app app seed-defaults
```
> Migration 0005 تنظیم `READ_COMMITTED_SNAPSHOT` دیتابیس را روشن می‌کند (ADR-0013) و برای آن به دسترسی انحصاری نیاز دارد: هنگام به‌روزرسانی، سرویس NEXTCAM را متوقف کنید.

۷. اجرا: `C:\nextcam\backend\.venv\Scripts\python -m app.serve` و از یک صندوق `http://<نام یا IP سرور>:8080` را باز کنید.

## ۴. اجرای خودکار با روشن شدن سرور
راه ساده و داخلی ویندوز، **Task Scheduler**:
- Trigger: At startup · «Run whether user is logged on or not» · Start in: `C:\nextcam\backend`
- Action: `C:\nextcam\backend\.venv\Scripts\python.exe` با آرگومان `-m app.serve`
- Settings: «If the task fails, restart every 1 minute».

(راه جایگزین: ابزار NSSM برای ساخت Windows Service از همین فرمان.)

## ۵. فایروال
فقط پورت برنامه و فقط در شبکه خصوصی:
```powershell
New-NetFirewallRule -DisplayName "NEXTCAM 8080" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow -Profile Private
```
پورت 1433 را باز **نکنید**.

## ۶. HTTPS
بهره‌برداری عادی فقط با HTTPS است: Caddy با گواهی داخلی جلوی برنامه و `NEXTCAM_COOKIE_SECURE=true`. راهنمای کامل: [https.md](https.md).
در دوره‌ی پایلوت، HTTP در شبکه‌ی داخلی جدا (بدون Wi-Fi مهمان) ریسک پذیرفته‌شده‌ی موقت بود.

## ۷. صندوق‌ها
- Chrome یا Edge به‌روز. آدرس `http://<سرور>:8080/pos` را به‌صورت میان‌بر تمام‌صفحه (F11) قرار دهید.
- بار اول، صندوق این رایانه انتخاب می‌شود (روی همان مرورگر ذخیره می‌شود).
- بارکدخوان USB در حالت **صفحه‌کلید (HID)** و با **Enter پس از بارکد** تنظیم شود. اگر صفحه‌کلید ویندوز فارسی باشد، برنامه ارقام و حروف را خودش اصلاح می‌کند.
- چاپگر فیش: در ویندوز به‌عنوان چاپگر **پیش‌فرض** همان صندوق، کاغذ ۸۰ میلی‌متر، حاشیه صفر. در Chrome برای حذف پنجره چاپ می‌توان میان‌بر را با `--kiosk-printing` اجرا کرد. چاپ مستقیم ESC/POS و کشوی پول در فاز ۶ (Device Agent) می‌آید.
- کارت‌خوان بانک ملت هنوز به نرم‌افزار وصل نیست: مبلغ روی دستگاه وارد می‌شود و پس از تأیید، **شماره پیگیری رسید** در صندوق ثبت می‌شود.

## ۸. پشتیبان‌گیری (ریسک R2)
در Task Scheduler دو کار بسازید (Start in: `C:\nextcam\backend`):

| کار | زمان | فرمان |
|---|---|---|
| پشتیبان روزانه | هر روز ۲۳:۳۰ | `.venv\Scripts\flask.exe --app app backup` |
| آزمون بازیابی | هفته‌ای یک‌بار | `.venv\Scripts\flask.exe --app app backup-restore-test` |

- پشتیبان با CHECKSUM گرفته و با `RESTORE VERIFYONLY` بررسی می‌شود؛ آزمون بازیابی آن را با نام موقت بازیابی، `DBCC CHECKDB` و سپس حذف می‌کند.
- حساب سرویس SQL Server باید روی پوشه پشتیبان مجوز نوشتن داشته باشد.
- اگر کاری از چند روز (قابل تنظیم) بگذرد، در داشبورد مدیر هشدار نمایش داده می‌شود:
  - پشتیبان روزانه؛
  - کپی بیرونی؛
  - آزمون بازیابی (۳۰ روز).

### ۸.۱ کپی رمزنگاری‌شده به مقصد دوم (فاز ۱۰ — روش پیشنهادی)
پشتیبانِ فقط روی همان سرور، با خرابی دیسک، سرقت یا باج‌افزار از بین می‌رود. برنامه هر پشتیبان را:
1. با **AES-256-GCM** رمزنگاری می‌کند؛
2. در یک **مقصد دوم** می‌نویسد؛
3. دوباره از همان مقصد می‌خواند و رمزگشایی می‌کند و با پشتیبان مقایسه می‌کند؛
4. آن را به‌عنوان کپی بیرونی ثبت می‌کند.

آزمون بازیابی هفتگی هم روی همین کپی رمزنگاری‌شده انجام می‌شود، چون در روز حادثه همین فایل به کار می‌آید.

**۱. ساخت کلید (یک بار):**
```powershell
.venv\Scripts\flask.exe --app app backup-keygen
```
خروجی را در `.env` بگذارید: `NEXTCAM_BACKUP_KEY=...`.

> ⚠️ **همان کلید را بیرون از سرور هم نگه دارید**، مثلاً روی کاغذ در گاوصندوق یا در مدیر رمز مالک.
> - بدون کلید هیچ نسخه‌ی رمزنگاری‌شده‌ای بازیابی نمی‌شود.
> - کلید را کنار فایل‌های پشتیبان نگذارید.
> - با عوض شدن کلید، نسخه‌های قدیمی فقط با کلید قدیمی باز می‌شوند.

**۲. مقصد دوم:** هر پوشه‌ای که روی دیسک دیگری از همین سرور نباشد:
- **دیسک USB:** دائم وصل باشد و حرف درایو ثابت داشته باشد.
- **پوشه‌ی اشتراکی NAS:** حساب سرویس برنامه روی آن مجوز نوشتن داشته باشد.
- **پوشه‌ی همگام‌شده با فضای ابری** (OneDrive، Google Drive): چون فایل رمزنگاری‌شده است، نگرانی محرمانگی ندارد.
```ini
NEXTCAM_BACKUP_DIR=D:\nextcam-backup
NEXTCAM_BACKUP_COPY_DIR=\\nas\nextcam-copy
NEXTCAM_BACKUP_COPY_KEEP=30
```
- **فقط کپی رمزنگاری‌شده:** برنامه بدون کلید، کپی ساده‌ی رمزنگاری‌نشده نمی‌سازد و با `BACKUP_COPY_DIR` بدون `BACKUP_KEY` اصلاً اجرا نمی‌شود.
- **پوشه‌ی پشتیبان در مسیر دیگر:** اگر برنامه پوشه‌ی پشتیبان SQL Server را با مسیر دیگری می‌بیند (SQL Server روی ماشین دیگر)، `NEXTCAM_BACKUP_READ_DIR` را به همان پوشه (مثلاً اشتراک شبکه) تنظیم کنید.

**۳. بررسی:** `flask --app app backup` باید دو خط `backup ok` و `encrypted copy ok ... decrypted and compared` چاپ کند. در «تنظیمات ← پشتیبان‌گیری» مقصد دوم با نشان سبز دیده می‌شود.

**بازیابی در روز حادثه** (روی سرور تازه، فقط با کلید):
```powershell
$env:NEXTCAM_BACKUP_KEY="..."   # کلید نگهداری‌شده
.venv\Scripts\python.exe -m app.modules.system.backup_crypto verify  E:\nextcam_20261019_233000.bak.ncbk
.venv\Scripts\python.exe -m app.modules.system.backup_crypto decrypt E:\nextcam_20261019_233000.bak.ncbk D:\restore\nextcam.bak
```
سپس `nextcam.bak` را در SQL Server Management Studio یا با `RESTORE DATABASE` بازیابی کنید.
- فایل ناقص، آسیب‌دیده یا با کلید دیگر، **پیام خطا** می‌دهد و هرگز نیمه‌کاره بازیابی نمی‌شود.

### ۸.۲ بدون مقصد دوم (فقط پایلوت)
**اپراتور** هر چند روز یک‌بار آخرین فایل `D:\nextcam-backup\nextcam_*.bak` را روی دیسک بیرونی کپی می‌کند و در «تنظیمات ← پشتیبان‌گیری» دکمه‌ی «کپی به بیرون را انجام دادم» را می‌زند. این فایل رمزنگاری نشده است؛ دیسک را در جای امن نگه دارید.

## ۹. آزمون بار (قبل از پایلوت، روی دیتابیس آزمون)
```powershell
$env:LOAD_ADMIN_USER="admin"; .venv\Scripts\python scripts\load_test.py --base http://127.0.0.1:8080 --setup
.venv\Scripts\python scripts\load_test.py --base http://127.0.0.1:8080 --registers 7 --seconds 120
```
**هرگز روی دیتابیس عملیاتی اجرا نشود** (کالا، کاربر و فروش آزمایشی می‌سازد).

## ۱۰. چک‌لیست روز اول پایلوت
- [ ] کدینگ، قواعد ثبت خودکار و نرخ مالیات با حسابدار فروشگاه بررسی شد.
- [ ] کالاها و موجودی اول دوره وارد و قطعی شد؛ قیمت‌ها کنترل شد.
- [ ] قاعده بارکد ترازو با برچسب واقعی آزموده شد.
- [ ] برای هر صندوق‌دار کاربر جدا و نقش «صندوق‌دار»، برای سرپرست نقش «سرپرست صندوق».
- [ ] سقف تخفیف صندوق‌دار و متن فیش تنظیم شد.
- [ ] یک پشتیبان دستی و یک آزمون بازیابی موفق ثبت شد.
- [ ] روی هر صندوق: اسکن، چاپ فیش، فروش نقد و کارت، برگشت و بستن شیفت آزمایش شد.
