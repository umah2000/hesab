# ADR-0004: مدل احراز هویت

**وضعیت:** پیشنهادی (اجرا در فاز ۱)

## تصمیم
- **وب (React):** نشست سمت سرور با کوکی `HttpOnly; Secure; SameSite=Lax`؛ محافظت CSRF با double-submit token در هدر `X-CSRF-Token` برای همه درخواست‌های تغییردهنده. توکن در `localStorage` نگهداری نمی‌شود.
- **موبایل و Device Agent:** Access Token کوتاه‌عمر (۱۵ دقیقه) + Refresh Token چرخشی با امکان ابطال؛ موبایل در Keystore/Keychain.
- رمز عبور: Argon2id؛ قفل موقت پس از ۵ تلاش ناموفق؛ Rate limit روی `/auth/*`.
- MFA (TOTP) اختیاری برای نقش‌های مدیریتی.
- هر نشست به کاربر، دستگاه و شعبه فعال گره خورده و در ممیزی ثبت می‌شود.

## پیامدها
+ کوکی HttpOnly در برابر سرقت توکن با XSS مقاوم‌تر است.
− Frontend و API باید هم‌مبدأ باشند یا CORS با credentials دقیق تنظیم شود.
