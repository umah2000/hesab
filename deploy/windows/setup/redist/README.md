# پیش‌نیازهای همراه setup.exe

فایل‌های این پوشه در گیت قرار نمی‌گیرند. پیش از ساخت setup.exe آن‌ها را با همین نام‌ها این‌جا بگذارید:

| فایل | از کجا |
|---|---|
| `python-amd64.exe` | python.org ← Downloads ← Windows ← آخرین Python 3.13، «Windows installer (64-bit)» (نام فایل را عوض کنید) |
| `msodbcsql.msi` | مستندات مایکروسافت «Download ODBC Driver for SQL Server» ← نسخه‌ی 18، x64 (نام فایل را عوض کنید) |
| `vc_redist.x64.exe` | خودکار با `build-setup.ps1` از https://aka.ms/vs/17/release/vc_redist.x64.exe |

هر کدام نباشد، setup.exe بدون آن ساخته می‌شود و روی سرور باید از قبل نصب شده باشد.
