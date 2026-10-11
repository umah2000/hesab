const LABELS: Record<string, string> = {
  "auth.login": "ورود به سامانه",
  "auth.logout": "خروج از سامانه",
  "auth.login_failed": "تلاش ناموفق برای ورود",
  "auth.user_locked": "قفل شدن حساب",
  "auth.password_changed": "تغییر رمز عبور",
  "users.created": "ایجاد کاربر",
  "users.updated": "ویرایش کاربر",
  "users.password_reset": "تعیین رمز جدید برای کاربر",
  "users.unlocked": "رفع قفل حساب",
  "roles.created": "ایجاد نقش",
  "roles.updated": "ویرایش نقش و مجوزها",
  "settings.updated": "تغییر تنظیمات سازمان",
  "branches.created": "ایجاد شعبه",
  "branches.updated": "ویرایش شعبه",
  "registers.created": "ایجاد صندوق",
  "registers.updated": "ویرایش صندوق",
  "setup.completed": "راه‌اندازی اولیه",
};

export function actionLabel(action: string): string {
  return LABELS[action] ?? action;
}

export const ACTION_GROUPS = [
  { value: "", label: "همه رویدادها" },
  { value: "auth", label: "ورود و خروج" },
  { value: "users", label: "کاربران" },
  { value: "roles", label: "نقش‌ها" },
  { value: "settings", label: "تنظیمات" },
  { value: "branches", label: "شعب" },
  { value: "registers", label: "صندوق‌ها" },
];
