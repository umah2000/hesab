import {
  BookOpenText,
  Boxes,
  ChartColumnBig,
  LayoutDashboard,
  type LucideIcon,
  ScrollText,
  Settings,
  ShieldCheck,
  ShoppingBasket,
  ShoppingCart,
  Truck,
  Users,
  Wallet,
} from "lucide-react";

export type NavItem = {
  to: string;
  label: string;
  icon: LucideIcon;
  permission?: string;
  /** Roadmap phase in which the module ships; shown disabled until then. */
  comingInPhase?: number;
  keywords?: string;
};

export const NAV_MAIN: NavItem[] = [
  { to: "/", label: "داشبورد", icon: LayoutDashboard, keywords: "خانه dashboard" },
  { to: "/pos", label: "صندوق فروش", icon: ShoppingCart, comingInPhase: 4 },
  { to: "/inventory", label: "کالا و انبار", icon: Boxes, comingInPhase: 3 },
  { to: "/accounting", label: "حسابداری", icon: BookOpenText, comingInPhase: 2 },
  { to: "/purchasing", label: "خرید", icon: ShoppingBasket, comingInPhase: 5 },
  { to: "/treasury", label: "خزانه‌داری", icon: Wallet, comingInPhase: 5 },
  { to: "/distribution", label: "ویزیتور و توزیع", icon: Truck, comingInPhase: 9 },
  { to: "/reports", label: "گزارش‌ها", icon: ChartColumnBig, comingInPhase: 7 },
];

export const NAV_ADMIN: NavItem[] = [
  { to: "/users", label: "کاربران", icon: Users, permission: "users.manage", keywords: "user" },
  { to: "/roles", label: "نقش‌ها و مجوزها", icon: ShieldCheck, permission: "roles.manage", keywords: "role permission" },
  { to: "/audit", label: "رویدادهای ممیزی", icon: ScrollText, permission: "audit.view", keywords: "audit log" },
  { to: "/settings", label: "تنظیمات", icon: Settings, keywords: "settings شعبه صندوق" },
];
