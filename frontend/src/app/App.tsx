import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Construction } from "lucide-react";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router";
import { Toaster } from "sonner";
import { AppShell } from "@/components/layout/AppShell";
import { Card } from "@/components/ui/card";
import { EmptyState, Spinner } from "@/components/ui/feedback";
import { AccountingLayout } from "@/features/accounting/AccountingLayout";
import { AccountsPage } from "@/features/accounting/AccountsPage";
import { DetailsPage } from "@/features/accounting/DetailsPage";
import { FiscalPage } from "@/features/accounting/FiscalPage";
import { PostingRulesPage } from "@/features/accounting/PostingRulesPage";
import { ReportsPage } from "@/features/accounting/ReportsPage";
import { VoucherEditorPage } from "@/features/accounting/VoucherEditor";
import { VouchersPage } from "@/features/accounting/VouchersPage";
import { WeighbridgePage } from "@/features/accounting/WeighbridgePage";
import { AuditPage } from "@/features/audit/AuditPage";
import { AccountPage, ForcePasswordChange } from "@/features/auth/AccountPage";
import { useMe, useUnauthorizedListener } from "@/features/auth/auth";
import { BalancesPage } from "@/features/inventory/BalancesPage";
import { ImportPage } from "@/features/inventory/ImportPage";
import { InventoryLayout } from "@/features/inventory/InventoryLayout";
import { InventorySettingsPage } from "@/features/inventory/InventorySettingsPage";
import { ItemsPage } from "@/features/inventory/ItemsPage";
import { LabelsPage } from "@/features/inventory/LabelsPage";
import { PriceTicketsPage } from "@/features/inventory/PriceTicketsPage";
import { StockDocEditorPage, StockDocsPage } from "@/features/inventory/StockDocsPage";
import { AboutPage } from "@/features/about/AboutPage";
import { LoginPage } from "@/features/auth/LoginPage";
import { DevicesPage } from "@/features/devices/DevicesPage";
import {
  DistributionLayout,
  OrderPage,
  OrdersPage as DistributionOrdersPage,
  VisitorPage,
  VisitorsPage,
  VisitsPage,
} from "@/features/distribution/DistributionPages";
import { CollectionsPage, CustomerRequestsPage, DistributionHome, TargetsPage } from "@/features/distribution/FieldPages";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import {
  FollowUpsPage,
  PartiesImportPage,
  PartiesLayout,
  PartiesListPage,
  PartyDetailPage,
} from "@/features/parties/PartiesPages";
import {
  PurchaseDuesPage,
  PurchaseInvoicePage,
  PurchaseInvoicesPage,
  PurchaseOrderPage,
  PurchaseOrdersPage,
  PurchasingLayout,
} from "@/features/purchasing/PurchasingPages";
import { ReportPage, ReportsHome } from "@/features/reports/ReportsPage";
import { RolesPage } from "@/features/roles/RolesPage";
import { CustomerDisplayPage } from "@/features/sales/CustomerDisplay";
import { OfflineSalesPage } from "@/features/sales/OfflineSalesPage";
import { PosPage } from "@/features/sales/PosPage";
import {
  CardTransactionsPage,
  DailyReportPage,
  InvoiceDetailPage,
  InvoicesPage,
  PromotionsPage,
  SalesLayout,
  ShiftsPage,
} from "@/features/sales/SalesPages";
import { SettingsPage } from "@/features/settings/SettingsPage";
import {
  ChequesPage,
  MoneyAccountsPage,
  ReconciliationPage,
  TreasuryDocumentPage,
  TreasuryDocumentsPage,
  TreasuryLayout,
} from "@/features/treasury/TreasuryPages";
import { UsersPage } from "@/features/users/UsersPage";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } },
});

function RouteError() {
  return (
    <Card className="m-4">
      <EmptyState
        icon={Construction}
        title="خطای غیرمنتظره در نمایش صفحه"
        description="صفحه را تازه کنید. اگر تکرار شد، زمان رخداد را به پشتیبانی اطلاع دهید."
        action={<a className="text-brand-600 underline" href="/">بازگشت به داشبورد</a>}
      />
    </Card>
  );
}

function NotFound() {
  return (
    <Card>
      <EmptyState icon={Construction} title="صفحه یافت نشد" description="این بخش وجود ندارد یا هنوز فعال نشده است." />
    </Card>
  );
}

const router = createBrowserRouter([
  // Full-screen register, outside the back-office shell.
  { path: "/pos", element: <PosPage />, errorElement: <RouteError /> },
  // Second monitor at the register: what the customer sees (fed by the POS tab).
  { path: "/display", element: <CustomerDisplayPage />, errorElement: <RouteError /> },
  {
    path: "/",
    element: <AppShell />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "users", element: <UsersPage /> },
      { path: "roles", element: <RolesPage /> },
      { path: "audit", element: <AuditPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "devices", element: <DevicesPage /> },
      { path: "reports", element: <ReportsHome /> },
      { path: "reports/:key", element: <ReportPage /> },
      { path: "account", element: <AccountPage /> },
      { path: "about", element: <AboutPage /> },
      {
        path: "accounting",
        element: <AccountingLayout />,
        children: [
          { index: true, element: <Navigate to="vouchers" replace /> },
          { path: "vouchers", element: <VouchersPage /> },
          { path: "vouchers/:id", element: <VoucherEditorPage /> },
          { path: "reports", element: <ReportsPage /> },
          { path: "accounts", element: <AccountsPage /> },
          { path: "details", element: <DetailsPage /> },
          { path: "fiscal-years", element: <FiscalPage /> },
          { path: "posting-rules", element: <PostingRulesPage /> },
          { path: "weighbridge", element: <WeighbridgePage /> },
        ],
      },
      {
        path: "inventory",
        element: <InventoryLayout />,
        children: [
          { index: true, element: <Navigate to="items" replace /> },
          { path: "items", element: <ItemsPage /> },
          { path: "documents", element: <StockDocsPage /> },
          { path: "documents/:id", element: <StockDocEditorPage /> },
          { path: "balances", element: <BalancesPage /> },
          { path: "labels", element: <LabelsPage /> },
          { path: "price-tickets", element: <PriceTicketsPage /> },
          { path: "import", element: <ImportPage /> },
          { path: "settings", element: <InventorySettingsPage /> },
        ],
      },
      {
        path: "sales",
        element: <SalesLayout />,
        children: [
          { index: true, element: <Navigate to="invoices" replace /> },
          { path: "invoices", element: <InvoicesPage /> },
          { path: "invoices/:id", element: <InvoiceDetailPage /> },
          { path: "shifts", element: <ShiftsPage /> },
          { path: "daily", element: <DailyReportPage /> },
          { path: "promotions", element: <PromotionsPage /> },
          { path: "card-transactions", element: <CardTransactionsPage /> },
          { path: "offline", element: <OfflineSalesPage /> },
        ],
      },
      {
        path: "distribution",
        element: <DistributionLayout />,
        children: [
          { index: true, element: <DistributionHome /> },
          { path: "orders", element: <DistributionOrdersPage /> },
          { path: "orders/:id", element: <OrderPage /> },
          { path: "visitors", element: <VisitorsPage /> },
          { path: "visitors/:id", element: <VisitorPage /> },
          { path: "visits", element: <VisitsPage /> },
          { path: "collections", element: <CollectionsPage /> },
          { path: "customer-requests", element: <CustomerRequestsPage /> },
          { path: "targets", element: <TargetsPage /> },
        ],
      },
      {
        path: "parties",
        element: <PartiesLayout />,
        children: [
          { index: true, element: <Navigate to="list" replace /> },
          { path: "list", element: <PartiesListPage /> },
          { path: "follow-ups", element: <FollowUpsPage /> },
          { path: "import", element: <PartiesImportPage /> },
          { path: ":id", element: <PartyDetailPage /> },
        ],
      },
      {
        path: "purchasing",
        element: <PurchasingLayout />,
        children: [
          { index: true, element: <Navigate to="invoices" replace /> },
          { path: "invoices", element: <PurchaseInvoicesPage /> },
          // One route for "new" and ids: saving a new invoice keeps the page mounted.
          { path: "invoices/:id", element: <PurchaseInvoicePage /> },
          { path: "orders", element: <PurchaseOrdersPage /> },
          { path: "orders/:id", element: <PurchaseOrderPage /> },
          { path: "dues", element: <PurchaseDuesPage /> },
        ],
      },
      {
        path: "treasury",
        element: <TreasuryLayout />,
        children: [
          { index: true, element: <Navigate to="documents" replace /> },
          { path: "documents", element: <TreasuryDocumentsPage /> },
          { path: "documents/:id", element: <TreasuryDocumentPage /> },
          { path: "cheques", element: <ChequesPage /> },
          { path: "accounts", element: <MoneyAccountsPage /> },
          { path: "reconciliation", element: <ReconciliationPage /> },
        ],
      },
      { path: "login", element: <Navigate to="/" replace /> },
      { path: "*", element: <NotFound /> },
    ],
  },
]);

function Gate() {
  useUnauthorizedListener();
  const me = useMe();
  if (me.isLoading) return <Spinner label="در حال بررسی نشست…" />;
  if (!me.data) return <LoginPage />;
  if (me.data.must_change_password) return <ForcePasswordChange />;
  return <RouterProvider router={router} />;
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Gate />
      <Toaster dir="rtl" position="bottom-left" richColors toastOptions={{ style: { fontFamily: "inherit" } }} />
    </QueryClientProvider>
  );
}
