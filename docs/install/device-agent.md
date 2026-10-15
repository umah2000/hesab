# نصب Device Agent روی رایانه صندوق

Device Agent چاپگر فیش و کشوی پول را از طرف سرور NEXTCAM کنترل می‌کند ([ADR-0015](../architecture/decisions/0015-device-agent.md)).
- خودش به سرور وصل می‌شود؛ روی صندوق هیچ درگاه ورودی باز نمی‌شود.
- تا Agent نصب نشده، فیش مثل قبل از طریق مرورگر چاپ می‌شود.

> ⚠️ این مراحل هنوز روی ویندوز و چاپگر واقعی فروشگاه آزموده نشده است. اولین نصب را با [چک‌لیست رجیستری سازگاری](../hardware/compatibility-registry.md) انجام دهید و نتیجه را ثبت کنید.

## پیش‌نیاز
- Windows 10/11 (۶۴ بیتی) روی همان رایانه‌ی صندوق.
- Python 3.12 برای همه‌ی کاربران (گزینه‌ی «Add python.exe to PATH» را بزنید).
- دسترسی صندوق به سرور NEXTCAM در شبکه، همان نشانی‌ای که صندوق با آن باز می‌شود (مثلاً `http://192.168.1.10:8080`).
- **چاپگر شبکه:** IP ثابت یا DHCP Reservation.
- **چاپگر USB:** درایور سازنده نصب باشد و نام چاپگر در «Printers & scanners» مشخص باشد.

## ۱. نصب
در PowerShell با دسترسی Administrator:
```powershell
cd C:\NEXTCAM\device-agent        # پوشه device-agent از بسته نصب
py -3.12 -m venv C:\NEXTCAM\agent-venv
C:\NEXTCAM\agent-venv\Scripts\pip install ".[windows]"      # برای چاپگر سریال: ".[windows,serial]"
```

## ۲. تعریف دستگاه در NEXTCAM
1. با کاربر دارای مجوز «تعریف و تنظیم Device Agent» (مدیر سیستم یا مدیر فروشگاه) به **دستگاه‌های صندوق** بروید ← **دستگاه جدید**.
2. صندوق، نوع اتصال و نشانی چاپگر را وارد کنید:
   - **شبکه:** `192.168.1.50:9100`
   - **USB:** نام چاپگر در ویندوز
   - **سریال:** `COM3:9600`
3. عرض کاغذ را انتخاب کنید. اگر کشو به چاپگر وصل است، «کشوی پول» را فعال کنید.
4. کد جفت‌سازی نمایش داده می‌شود. **۱۵ دقیقه اعتبار دارد و فقط یک بار دیده می‌شود.**

## ۳. جفت‌سازی و اجرای آزمایشی
```powershell
C:\NEXTCAM\agent-venv\Scripts\nextcam-agent pair --server http://192.168.1.10:8080 --code ABCD-EFGH
C:\NEXTCAM\agent-venv\Scripts\nextcam-agent run
```
- در صفحه‌ی دستگاه‌ها وضعیت باید «متصل» شود.
- **چاپ آزمایشی** را بزنید: متن فارسی باید خوانا و راست‌چین باشد.
- با `Ctrl+C` متوقف کنید.

## ۴. نصب به‌صورت سرویس ویندوز
```powershell
C:\NEXTCAM\agent-venv\Scripts\python -m nextcam_agent.service --startup auto install
C:\NEXTCAM\agent-venv\Scripts\python -m nextcam_agent.service start
```
- سرویس «NEXTCAM Device Agent» با ویندوز بالا می‌آید.
- تنظیمات و توکن در `C:\ProgramData\NEXTCAM\agent` است. توکن با DPAPI همان رایانه رمز شده و روی رایانه‌ی دیگر قابل استفاده نیست.
- گزارش‌ها در `agent.log` همان پوشه نوشته می‌شوند. اگر توکن را جای دیگری پیدا کردید، آن را باطل کنید.

## عیب‌یابی
| نشانه | بررسی |
|---|---|
| وضعیت دستگاه «قطع» است | `nextcam-agent status` روی صندوق (فقط روی همان رایانه، `http://127.0.0.1:47615/status`)؛ دسترسی شبکه به سرور؛ اجرای سرویس |
| «توکن دستگاه باطل شده» | دستگاه باطل شده یا Agent دیگری با کد جدید جفت شده است. کد تازه بگیرید و دوباره جفت کنید |
| «چاپگر شبکه پاسخ نمی‌دهد» | IP و درگاه چاپگر؛ `Test-NetConnection 192.168.1.50 -Port 9100` |
| چاپگر USB چیزی چاپ نمی‌کند | نام دقیق چاپگر؛ چاپ صفحه‌ی آزمایشی خود ویندوز. برخی درایورها RAW را نمی‌پذیرند؛ با پشتیبانی سازنده بررسی کنید |
| کشو باز نمی‌شود | پایه‌ی کشو (۲ یا ۵) را در تنظیمات دستگاه عوض کنید؛ اتصال کابل RJ11 کشو به چاپگر |
| سرویس شروع نمی‌شود (خطای ۱۰۵۳) | pywin32 داخل venv گاهی به اجرای `C:\NEXTCAM\agent-venv\Scripts\python C:\NEXTCAM\agent-venv\Scripts\pywin32_postinstall.py -install` نیاز دارد؛ تا رفع، `nextcam-agent run` را با Task Scheduler هنگام روشن شدن اجرا کنید |
| کاراکترهای نامفهوم چاپ می‌شود | چاپگر دستور تصویری `GS v 0` را پشتیبانی نمی‌کند. مدل را در رجیستری «Unsupported» ثبت کنید و فعلاً از چاپ مرورگر استفاده کنید |

## حذف
```powershell
C:\NEXTCAM\agent-venv\Scripts\python -m nextcam_agent.service stop
C:\NEXTCAM\agent-venv\Scripts\python -m nextcam_agent.service remove
C:\NEXTCAM\agent-venv\Scripts\nextcam-agent unpair
```
سپس دستگاه را در NEXTCAM **باطل** کنید.
