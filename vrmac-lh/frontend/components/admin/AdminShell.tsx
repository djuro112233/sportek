"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useT } from "@/lib/i18n";
import { useAdminUser } from "./AdminContext";
import styles from "./admin.module.css";

export interface AdminTab {
  href: string;
  label: string;
  /** Exact match only (a section index that must not stay active on its sub-pages). */
  exact?: boolean;
}

/** Frame of the validator and dashboard sections: who is signed in, sign out, section tabs. */
export default function AdminShell({ tabs, children }: { tabs: AdminTab[]; children: React.ReactNode }) {
  const t = useT();
  const path = usePathname();
  const { user, signOut } = useAdminUser();

  return (
    <div className="stack">
      <div className={styles.userBar}>
        <p className="muted small" style={{ margin: 0 }}>
          {t("admin.shell.signedInAs", { name: user.display_name || user.email, role: t(`admin.role.${user.role}`) })}
        </p>
        <div className="row">
          <Link className="btn btn-small btn-secondary" href="/login">
            {t("admin.shell.account")}
          </Link>
          <button type="button" className="btn btn-small btn-secondary" onClick={signOut}>
            {t("admin.shell.logout")}
          </button>
        </div>
      </div>
      {tabs.length > 0 && (
        <nav aria-label={t("admin.shell.sectionNav")}>
          <ul className={styles.tabs}>
            {tabs.map((tab) => {
              const active = tab.exact ? path === tab.href : path === tab.href || path.startsWith(`${tab.href}/`);
              return (
                <li key={tab.href}>
                  <Link href={tab.href} aria-current={active ? "page" : undefined}>
                    {tab.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      )}
      {children}
    </div>
  );
}
