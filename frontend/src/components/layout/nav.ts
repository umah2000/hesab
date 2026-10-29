import {
  BookOpenText,
  Boxes,
  ChartColumnBig,
  LayoutDashboard,
  Printer,
  type LucideIcon,
  ReceiptText,
  ScrollText,
  Settings,
  ShieldCheck,
  ShoppingBasket,
  ShoppingCart,
  Truck,
  UserRound,
  Users,
  Wallet,
} from "lucide-react";

export type NavItem = {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Any of these permissions shows the item (the backend still checks each call). */
  permission?: string | string[];
  /** Roadmap phase in which the module ships; shown disabled until then. */
  comingInPhase?: number;
  keywords?: string;
};

export const NAV_MAIN: NavItem[] = [
  { to: "/", label: "داشبورد", icon: LayoutDashboard, keywords: "خانه dashboard" },
  { to: "/pos", label: "صندوق فروش", icon: ShoppingCart, permission: "sales.pos.use", keywords: "صندوق فروش pos فاکتور" },
  {
    to: "/sales",
    label: "فروش و شیفت‌ها",
    icon: ReceiptText,
    permission: ["sales.report.view", "sales.return.create", "inventory.price.manage", "payments.reconcile", "sync.resolve"],
    keywords: "فاکتور برگشت شیفت پروموشن گزارش فروش آفلاین تعارض",
  },
  {
    to: "/inventory",
    label: "کالا و انبار",
    icon: Boxes,
    permission: ["inventory.item.manage", "inventory.price.manage", "inventory.stock.create", "inventory.stock.adjust", "inventory.report.view", "import.run"],
    keywords: "کالا انبار موجودی بارکد کاردکس inventory stock item",
  },
  {
    to: "/accounting",
    label: "حسابداری",
    icon: BookOpenText,
    permission: ["accounting.account.manage", "accounting.voucher.create", "accounting.voucher.finalize", "accounting.report.view"],
    keywords: "سند دفتر تراز accounting voucher",
  },
  {
    to: "/parties",
    label: "طرف‌حساب‌ها",
    icon: UserRound,
    permission: ["parties.view", "parties.manage"],
    keywords: "مشتری تأمین‌کننده طرف حساب بدهکار بستانکار party",
  },
  {
    to: "/purchasing",
    label: "خرید",
    icon: ShoppingBasket,
    permission: "purchasing.manage",
    keywords: "خرید فاکتور سفارش تأمین‌کننده سررسید purchase",
  },
  {
    to: "/treasury",
    label: "خزانه‌داری",
    icon: Wallet,
    permission: "treasury.manage",
    keywords: "صندوق بانک دریافت پرداخت چک مغایرت treasury",
  },
  {
    to: "/distribution",
    label: "ویزیتور و توزیع",
    icon: Truck,
    permission: ["distribution.manage", "treasury.manage"],
    keywords: "ویزیتور سفارش توزیع مسیر بازدید وصول هدف مشتری جدید visitor order",
  },
  {
    to: "/reports",
    label: "گزارش‌ها",
    icon: ChartColumnBig,
    permission: ["reports.dashboard", "sales.report.view", "inventory.report.view", "accounting.report.view", "parties.view", "treasury.manage"],
    keywords: "گزارش سود زیان ترازنامه بدهکاران کم‌گردش انقضا report",
  },
];

export const NAV_ADMIN: NavItem[] = [
  { to: "/users", label: "کاربران", icon: Users, permission: "users.manage", keywords: "user" },
  { to: "/roles", label: "نقش‌ها و مجوزها", icon: ShieldCheck, permission: "roles.manage", keywords: "role permission" },
  { to: "/audit", label: "رویدادهای ممیزی", icon: ScrollText, permission: "audit.view", keywords: "audit log" },
  { to: "/devices", label: "دستگاه‌های صندوق", icon: Printer, permission: "devices.manage", keywords: "چاپگر فیش کشو agent printer device" },
  { to: "/settings", label: "تنظیمات", icon: Settings, keywords: "settings شعبه صندوق" },
];
