# ADR-0001: monorepo و Modular Monolith

**وضعیت:** پذیرفته · ۱۴۰۵/۰۷/۱۹

## زمینه
چهار کدبیس (Backend، Frontend، Device Agent، Mobile) با قراردادهای API مشترک؛ تیم کوچک.

## تصمیم
- یک مخزن (`umah2000/hesab`) با پوشه‌های `backend/`، `frontend/`، `device-agent/`، `mobile/`، `docs/`.
- Backend به‌صورت Modular Monolith: هر ماژول در `backend/app/modules/<name>/` با لایه‌های `api` (Blueprint)، `schemas` (Pydantic)، `services`، `models`، `repository`.
- ماژول‌ها فقط از طریق `services` عمومی یکدیگر ارتباط دارند؛ دسترسی مستقیم به جدول ماژول دیگر ممنوع.
- `main` محافظت‌شده؛ تغییرات با PR و CI سبز؛ پیام commit به سبک Conventional Commits؛ نسخه SemVer با تگ.

## پیامدها
+ تغییر قرارداد API و مصرف‌کننده‌ها در یک PR.
+ یک دیتابیس و تراکنش واحد برای عملیات چندماژولی (فروش ← انبار ← حسابداری).
− CI باید براساس مسیر فایل‌ها فیلتر شود تا کند نشود.
