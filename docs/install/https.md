# راه‌اندازی HTTPS

از فاز ۱۰، بهره‌برداری عادی **فقط با HTTPS** است.
- بدون HTTPS، رمزها و کوکی نشست روی شبکه به‌صورت متن ساده جابه‌جا می‌شوند.
- اپ ویزیتور در نسخه‌ی انتشار اصلاً به HTTP وصل نمی‌شود (Q21).

## معماری
```
صندوق‌ها / مرورگر / اپ ویزیتور ──HTTPS──▶ Caddy (پورت 443) ──HTTP روی 127.0.0.1──▶ NEXTCAM (پورت 8080)
```
- TLS در **Caddy** روی همان سرور تمام می‌شود.
- برنامه فقط روی `127.0.0.1` گوش می‌دهد، پس هیچ‌کس نمی‌تواند پراکسی را دور بزند.
- Caddy یک فایل اجرایی تک است و روی ویندوز به‌عنوان سرویس اجرا می‌شود.
- نمونه‌ی پیکربندی: [`deploy/https/Caddyfile`](../../deploy/https/Caddyfile).

## ۱. تنظیم برنامه
در `.env` سرور:
```ini
NEXTCAM_HOST=127.0.0.1
NEXTCAM_PORT=8080
NEXTCAM_TRUSTED_PROXY=127.0.0.1
NEXTCAM_COOKIE_SECURE=true
```
اثر این تنظیم‌ها:
- **`NEXTCAM_TRUSTED_PROXY`:** آدرس واقعی کاربر (برای قفل ورود، محدودیت تلاش و رویدادنگار) و `https` بودن درخواست، از سرآیندهای `X-Forwarded-*` همان پراکسی خوانده می‌شود.
- این سرآیندها اگر از هر آدرس دیگری بیایند دور ریخته می‌شوند.
- **`NEXTCAM_COOKIE_SECURE=true`:** کوکی‌ها `Secure` می‌شوند و سرآیند HSTS (یک سال) فرستاده می‌شود.

> ⚠️ **ترتیب کار:**
> - تا HTTPS کامل کار نکرده، `COOKIE_SECURE` را روشن نکنید؛ مرورگر کوکی Secure را روی HTTP نمی‌فرستد و کسی نمی‌تواند وارد شود.
> - بعد از روشن کردن آن، مرورگرها تا یک سال فقط با HTTPS به این نام وصل می‌شوند (HSTS).

قانون فایروال پورت 8080 (بخش ۵ راهنمای نصب) را حذف کنید و به‌جای آن 443 را باز کنید:
```powershell
Remove-NetFirewallRule -DisplayName "NEXTCAM 8080"
New-NetFirewallRule -DisplayName "NEXTCAM HTTPS" -Direction Inbound -Protocol TCP -LocalPort 80,443 -Action Allow -Profile Private
```
پورت 80 فقط برای انتقال خودکار به HTTPS است.

## ۲. Caddy در شبکه‌ی فروشگاه (گواهی داخلی)
1. `caddy_windows_amd64.zip` را از صفحه‌ی رسمی انتشار Caddy دریافت کنید و در `C:\nextcam\caddy\` بگذارید.
2. `deploy\https\Caddyfile` را کنار آن کپی کنید. `SERVER_NAME` و `SERVER_IP` را با نام و IP ثابت سرور جایگزین کنید (مثلاً `nextcam.local` و `192.168.1.10`).
3. بررسی: `caddy validate --config Caddyfile`
4. نصب به‌عنوان سرویس (با یک ابزار سرویس مثل WinSW یا NSSM، یا Task Scheduler «هنگام راه‌اندازی»). فرمان اجرا:
   `C:\nextcam\caddy\caddy.exe run --config C:\nextcam\caddy\Caddyfile`
5. با `tls internal`، Caddy یک مرجع گواهی (CA) محلی می‌سازد. گواهی ریشه‌ی آن را **یک بار روی هر صندوق** نصب کنید. فایل آن در پوشه‌ی داده‌ی Caddy است: `%AppData%\Caddy\pki\authorities\local\root.crt` (برای سرویس، پوشه‌ی کاربر همان سرویس).
   ```powershell
   Import-Certificate -FilePath root.crt -CertStoreLocation Cert:\LocalMachine\Root
   ```
   - Chrome و Edge روی ویندوز به همین مخزن اعتماد می‌کنند.
   - Device Agent هم به همین مخزن اعتماد می‌کند، چون Python روی ویندوز گواهی‌های مخزن سیستم را بارگذاری می‌کند.
6. آدرس سرور را در Agent هر صندوق به `https://<SERVER_NAME>` تغییر دهید (`agent.json` → `server_url`) و سرویس Agent را دوباره راه بیندازید.
7. میان‌بر مرورگر صندوق‌ها و مدیران را به `https://<SERVER_NAME>/` تغییر دهید.

**کلید CA محلی** در همان پوشه‌ی Caddy است و هر کس آن را داشته باشد، می‌تواند برای صندوق‌ها گواهی معتبر بسازد:
- دسترسی به این پوشه فقط برای مدیر سیستم باشد.
- در پشتیبان رمزنگاری‌شده‌ی سرور قرار بگیرد.

## ۳. اپ ویزیتور از اینترنت (Q21)
گوشی‌ها گواهی CA داخلی را نمی‌شناسند. دو راه هست:
- **دامنه‌ی عمومی (پیشنهادی):**
  1. یک دامنه (مثلاً `visit.example.com`) با IP ثابت فروشگاه.
  2. هدایت پورت‌های 80 و 443 مودم به سرور.
  3. فعال کردن بلوک دوم `Caddyfile`. Caddy گواهی عمومی Let's Encrypt را خودش می‌گیرد و تمدید می‌کند.
  4. این بلوک **فقط** مسیرهای اپ (`/api/v1/auth/mobile/` و `/api/v1/distribution/mobile/`) را عبور می‌دهد؛ پنل مدیریت و صندوق از اینترنت در دسترس نیستند.
- **VPN:** گوشی‌ها با VPN وارد شبکه‌ی فروشگاه می‌شوند. در این حالت گواهی باید برای گوشی‌ها هم معتبر باشد:
  - یا دامنه‌ی عمومی با گواهی عمومی؛
  - یا نصب CA داخلی روی گوشی‌ها. این کار در Android برای اپ‌ها پیکربندی جدا می‌خواهد و **ساخته نشده است**.

## ۴. بررسی پس از راه‌اندازی
```powershell
curl.exe -sI https://<SERVER_NAME>/api/v1/system/health
```
باید `HTTP/1.1 200` (یا `HTTP/2 200`) باشد و این سرآیندها را داشته باشد:
- `strict-transport-security`
- `content-security-policy` (روی صفحه‌ها)
- `x-frame-options: DENY`

`http://<SERVER_NAME>/` باید به `https://` منتقل شود (308).

## آنچه آزموده شد
آزمون در محیط توسعه (لینوکس)، با Caddy 2.10.2 و `tls internal` روی پورت 8443، جلوی `python -m app.serve`:
- گواهی با ریشه‌ی CA محلی Caddy معتبر شناخته شد (`curl --cacert root.crt`).
- ورود از طریق HTTPS؛ کوکی‌ها `Secure` و `HttpOnly` بودند (کوکی CSRF عمداً بدون HttpOnly است).
- HTTP با کد 308 به HTTPS منتقل شد.
- `X-Forwarded-For` جعلی که کاربر فرستاد در رویدادنگار ثبت نشد؛ آدرس واقعی ثبت شد.
- ۱۲ صفحه‌ی برنامه در Chromium از طریق HTTPS بدون خطای CSP باز شد.
- ⚠️ **آزموده‌نشده:**
  - اجرای Caddy به‌عنوان سرویس ویندوز.
  - نصب ریشه روی ویندوز واقعی.
  - Device Agent روی HTTPS روی ویندوز.
  - گواهی Let's Encrypt (نیازمند دامنه‌ی واقعی).
