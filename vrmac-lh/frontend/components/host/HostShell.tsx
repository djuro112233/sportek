"use client";
/**
 * Frame shared by every host screen: the service worker registration (PWA), the auth gate for the
 * `host` and `ambassador` roles, the signed-in user with a log-out button, the sub-navigation and
 * the offline capture queue, which lives here so a recording survives moving between screens.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import AuthGate from "@/components/AuthGate";
import RegisterSW from "@/components/RegisterSW";
import { useT } from "@/lib/i18n";
import styles from "./host.module.css";
import { OfflineQueueProvider } from "./offlineQueue";
import type { HostUser } from "./types";

const LINKS = [
  { href: "/host", key: "host.nav.home" },
  { href: "/host/new", key: "host.nav.new" },
  { href: "/host/listings", key: "host.nav.listings" },
  { href: "/host/requests", key: "host.nav.requests" },
];

export default function HostShell({ children }: { children: (user: HostUser) => React.ReactNode }) {
  const t = useT();
  const path = usePathname();
  return (
    <>
      <RegisterSW />
      <AuthGate roles={["host", "ambassador"]}>
        {(user, signOut) => (
          <OfflineQueueProvider>
            <div className={styles.shell}>
              <div className={styles.shellHead}>
                <h1>{t("host.title")}</h1>
                <div className={styles.who}>
                  <span>
                    {t("host.signedInAs", { name: user.display_name || user.email, role: t(`host.role.${user.role}`) })}
                  </span>
                  <button type="button" className="btn btn-secondary btn-small" onClick={signOut}>
                    {t("auth.logout")}
                  </button>
                </div>
              </div>
              <nav className={styles.subnav} aria-label={t("host.nav.label")}>
                <ul>
                  {LINKS.map((l) => {
                    const active = l.href === "/host" ? path === "/host" : path.startsWith(l.href);
                    return (
                      <li key={l.href}>
                        <Link href={l.href} aria-current={active ? "page" : undefined}>
                          {t(l.key)}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </nav>
              {children(user as HostUser)}
            </div>
          </OfflineQueueProvider>
        )}
      </AuthGate>
    </>
  );
}
