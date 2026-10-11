import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Construction } from "lucide-react";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router";
import { Toaster } from "sonner";
import { AppShell } from "@/components/layout/AppShell";
import { Card } from "@/components/ui/card";
import { EmptyState, Spinner } from "@/components/ui/feedback";
import { AuditPage } from "@/features/audit/AuditPage";
import { AccountPage, ForcePasswordChange } from "@/features/auth/AccountPage";
import { useMe, useUnauthorizedListener } from "@/features/auth/auth";
import { LoginPage } from "@/features/auth/LoginPage";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { RolesPage } from "@/features/roles/RolesPage";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { UsersPage } from "@/features/users/UsersPage";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } },
});

function NotFound() {
  return (
    <Card>
      <EmptyState icon={Construction} title="صفحه یافت نشد" description="این بخش وجود ندارد یا هنوز فعال نشده است." />
    </Card>
  );
}

const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "users", element: <UsersPage /> },
      { path: "roles", element: <RolesPage /> },
      { path: "audit", element: <AuditPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "account", element: <AccountPage /> },
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
