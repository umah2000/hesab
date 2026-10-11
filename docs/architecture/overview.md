# معماری کلان و نیازمندی‌ها

## ۱. نیازمندی‌ها و فرضیات

### فرضیات تأییدشده
| # | فرض | منبع |
|---|---|---|
| F1 | تک‌مستأجر: هر مشتری یک نصب و یک دیتابیس | مالک محصول |
| F2 | مشتری اول: سوپرمارکت، ابتدا یک شعبه | مالک محصول |
| F3 | SQL Server Standard روی سیستم محلی نصب و آماده است | مالک محصول |
| F4 | مؤدیان در نسخه بعد | مالک محصول |

### فرضیات کاری (نیازمند تأیید — در [`open-questions.md`](../open-questions.md))
| # | فرض |
|---|---|
| A1 | سوپرمارکت پایلوت: ۲ تا ۴ صندوق، ۱۰ تا ۳۰ هزار کالا، ۵۰۰ تا ۲۰۰۰ فاکتور در روز |
| A2 | صندوق‌ها ویندوز ۱۰/۱۱ با Chrome یا Edge |
| A3 | سرور (یا یکی از سیستم‌ها) در شبکه داخلی فروشگاه Backend و SQL Server را اجرا می‌کند |
| A4 | در فاز پایلوت، کارت‌خوان‌ها مستقل (غیرمتصل) کار می‌کنند و صندوق‌دار شماره پیگیری را دستی ثبت می‌کند |
| A5 | بارکدخوان‌ها Keyboard Wedge با پسوند Enter |
| A6 | ترازوی برچسب‌زن EAN-13 با پیشوند ۲۰–۲۹ تولید می‌کند (الگوی دقیق از ترازوی واقعی گرفته می‌شود) |

### نیازمندی‌های غیرعملکردی (هدف، نه تضمین — تا آزمون بار)
- جست‌وجوی بارکد در صندوق: p95 زیر ۱۰۰ms در شبکه داخلی با ۵۰ هزار کالا.
- ثبت نهایی فاکتور (فروش + انبار + سند): p95 زیر ۵۰۰ms.
- قطع اینترنت هیچ اثری بر حالت شبکه داخلی ندارد؛ قطع شبکه داخلی ← حالت آفلاین (فاز ۸).
- RPO پایلوت: ۱۵ دقیقه (Log Backup)؛ RTO: ۲ ساعت.

## ۲. نمودار اجزا

```mermaid
flowchart LR
  subgraph Store["شبکه داخلی فروشگاه"]
    subgraph POS["هر صندوق (ویندوز)"]
      Browser["مرورگر<br/>React SPA (POS)"]
      Scanner["بارکدخوان HID"] -- "کیبورد" --> Browser
      Agent["Device Agent<br/>127.0.0.1 — فاز ۶"]
      Browser -- "HTTPS محلی + توکن جفت‌سازی" --> Agent
      Agent --> Printer["پرینتر فیش ESC/POS"]
      Printer --> Drawer["کشوی پول"]
      Agent -- "ECR رسمی PSP<br/>(پس از تأیید)" --> PinPad["کارت‌خوان LAN"]
      Agent --> LocalQ[("SQLite<br/>صف آفلاین")]
    end
    subgraph Server["سرور فروشگاه"]
      API["Flask API<br/>Modular Monolith"]
      DB[("SQL Server Standard")]
      SQLAgent["SQL Server Agent<br/>Backup"]
      API -- "SQLAlchemy / ODBC 18" --> DB
      SQLAgent --> DB
    end
    Browser -- "HTTPS REST /api/v1" --> API
    Agent -- "همگام‌سازی صف" --> API
  end
  Mobile["Flutter ویزیتور<br/>فاز ۹"] -- "HTTPS + Token" --> API
  Backup[("مقصد Backup جدا")] 
  SQLAgent -. "کپی رمزنگاری‌شده" .-> Backup
  HQ["سرور مرکزی (آینده، چندشعبه)"] <-. "Sync API — فاز ۸" .-> API
```

**قواعد مرزی:**
- مرورگر، موبایل و Agent هرگز مستقیم به SQL Server وصل نمی‌شوند.
- Agent فقط روی `127.0.0.1` گوش می‌دهد؛ هیچ API اجرای فرمان یا SQL ندارد.
- کارت‌خوان فقط از Agent و فقط از پروتکل رسمی.
- بارکدخوان HID به Agent نیاز ندارد.

## ۳. لایه‌های Backend

```
HTTP → api (Blueprint) → schemas (Pydantic) → services (منطق کسب‌وکار، Unit of Work)
                                             ├→ domain rules (توازن، موجودی، Posting Rules)
                                             ├→ repository (SQLAlchemy)
                                             ├→ audit
                                             └→ permissions (چک در service و api)
```
- هر عملیات کسب‌وکار = یک `unit_of_work()` = یک تراکنش. خطا ← rollback کامل.
- ماژول‌ها فقط سرویس عمومی یکدیگر را صدا می‌زنند (مثلاً `sales` ← `inventory.services.issue_stock` و `accounting.services.post_voucher`).

### ماژول‌ها و وابستگی
```mermaid
flowchart TD
  core["core (config, db, errors, logging)"]
  auth["auth / users / permissions"] --> core
  audit --> core
  org["organization / branches"] --> auth
  accounting --> org
  parties --> org
  inventory --> accounting
  sales --> inventory
  sales --> parties
  sales --> treasury
  purchasing --> inventory
  purchasing --> parties
  treasury --> accounting
  payments["payments (terminal adapter)"] --> treasury
  reporting -.-> accounting & inventory & sales
  sync -.-> sales & inventory
```

## ۴. حالت‌های استقرار
1. **شبکه داخلی (پایلوت):** همه چیز در فروشگاه. اینترنت لازم نیست.
2. **سرور مرکزی:** Backend و SQL Server روی سرور (میزبانی در ایران)؛ شعب از طریق HTTPS/VPN.
3. **ترکیبی (فاز ۸):** هر شعبه Backend محلی + همگام‌سازی با مرکز طبق [`sync/protocol.md`](../sync/protocol.md).
