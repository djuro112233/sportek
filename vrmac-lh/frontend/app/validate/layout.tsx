"use client";
import AuthGate from "@/components/AuthGate";
import { AdminProvider } from "@/components/admin/AdminContext";
import AdminShell, { type AdminTab } from "@/components/admin/AdminShell";
import { useT } from "@/lib/i18n";

/** Validator / ambassador section: login gate, signed-in user, section tabs. */
export default function ValidateLayout({ children }: { children: React.ReactNode }) {
  const t = useT();
  return (
    <AuthGate roles={["validator", "ambassador"]}>
      {(user, signOut) => {
        const tabs: AdminTab[] = [
          { href: "/validate", label: t("admin.tab.queue"), exact: true },
          { href: "/validate/new", label: t("admin.tab.newEntry") },
          ...(user.role === "validator" ? [{ href: "/validate/audit", label: t("admin.tab.audit") }] : []),
        ];
        return (
          <AdminProvider user={user} signOut={signOut}>
            <AdminShell tabs={tabs}>{children}</AdminShell>
          </AdminProvider>
        );
      }}
    </AuthGate>
  );
}
