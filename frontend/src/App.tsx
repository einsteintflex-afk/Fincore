import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppShell } from "@/components/Layout";
import { Spinner } from "@/components/ui";
import { isStaff, useAuth } from "@/lib/auth";
import * as Auth from "@/pages/auth/AuthPages";
import * as P from "@/pages/public/PublicPages";

// Each portal is its own chunk so customers don't download the admin console.
function lazyNs<T extends Record<string, any>>(load: () => Promise<T>): T {
  const cache: Record<string, unknown> = {};
  return new Proxy({} as T, {
    get: (_, name: string) => (cache[name] ??= lazy(() => load().then((m) => ({ default: m[name] })))),
  });
}
const C = lazyNs(() => import("@/pages/customer/CustomerPages"));
const M = lazyNs(() => import("@/pages/merchant/MerchantPages"));
const Dev = lazyNs(() => import("@/pages/developer/DeveloperPages"));
const Admin = lazyNs(() => import("@/pages/admin/AdminPages"));

function RequireAuth({ children, staff }: { children: ReactNode; staff?: boolean }) {
  const { user, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <Spinner label="Loading FinCore…" />;
  if (!user) return <Navigate to="/login" state={{ from: loc.pathname + loc.search }} replace />;
  if (staff && !isStaff(user)) return <Navigate to="/app" replace />;
  return <Suspense fallback={<Spinner />}>{children}</Suspense>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<P.LandingPage />} />
      <Route path="/login" element={<Auth.LoginPage />} />
      <Route path="/register" element={<Auth.RegisterPage />} />
      <Route path="/forgot-password" element={<Auth.ForgotPasswordPage />} />
      <Route path="/reset-password" element={<Auth.ResetPasswordPage />} />
      <Route path="/verify-email" element={<Auth.VerifyEmailPage />} />
      <Route path="/checkout/:reference" element={<P.CheckoutPage />} />
      <Route path="/pay/:slug" element={<P.PaymentLinkPage />} />
      <Route path="/verify" element={<P.VerifyReceiptPage />} />

      <Route path="/app" element={<RequireAuth><AppShell portal="app" /></RequireAuth>}>
        <Route index element={<C.CustomerDashboard />} />
        <Route path="send" element={<C.SendPage />} />
        <Route path="deposit" element={<C.DepositPage />} />
        <Route path="withdraw" element={<C.WithdrawPage />} />
        <Route path="transactions" element={<C.TransactionsPage />} />
        <Route path="beneficiaries" element={<C.BeneficiariesPage />} />
        <Route path="statements" element={<C.StatementsPage />} />
        <Route path="verification" element={<C.VerificationPage />} />
        <Route path="security" element={<C.SecurityPage />} />
        <Route path="support" element={<C.SupportPage />} />
      </Route>

      <Route path="/merchant" element={<RequireAuth><AppShell portal="app" /></RequireAuth>}>
        <Route index element={<M.MerchantHome />} />
        <Route path="new" element={<M.CreateBusiness />} />
      </Route>
      <Route path="/merchant/:bizId" element={<RequireAuth><AppShell portal="merchant" /></RequireAuth>}>
        <Route index element={<M.MerchantOverview />} />
        <Route path="payments" element={<M.MerchantPayments />} />
        <Route path="links" element={<M.MerchantLinks />} />
        <Route path="transactions" element={<M.MerchantTransactions />} />
        <Route path="settlements" element={<M.MerchantSettlements />} />
        <Route path="reports" element={<M.MerchantReports />} />
        <Route path="team" element={<M.MerchantTeam />} />
        <Route path="settings" element={<M.MerchantSettings />} />
      </Route>

      <Route path="/developer/:bizId" element={<RequireAuth><AppShell portal="developer" /></RequireAuth>}>
        <Route index element={<Dev.DeveloperApps />} />
        <Route path="docs" element={<Dev.DeveloperDocs />} />
      </Route>

      <Route path="/admin" element={<RequireAuth staff><AppShell portal="admin" /></RequireAuth>}>
        <Route index element={<Admin.AdminOverview />} />
        <Route path="users" element={<Admin.AdminUsers />} />
        <Route path="users/:userId" element={<Admin.AdminUserDetail />} />
        <Route path="kyc" element={<Admin.AdminKyc />} />
        <Route path="businesses" element={<Admin.AdminBusinesses />} />
        <Route path="transactions" element={<Admin.AdminTransactions />} />
        <Route path="fraud" element={<Admin.AdminFraud />} />
        <Route path="finance" element={<Admin.AdminFinance />} />
        <Route path="approvals" element={<Admin.AdminApprovals />} />
        <Route path="config" element={<Admin.AdminConfig />} />
        <Route path="support" element={<Admin.AdminSupport />} />
        <Route path="audit" element={<Admin.AdminAudit />} />
      </Route>

      <Route path="*" element={<P.NotFoundPage />} />
    </Routes>
  );
}
