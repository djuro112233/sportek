"use client";
/**
 * Frame shared by every host screen: the service worker registration (PWA), the auth gate for the
 * `host` and `ambassador` roles, the signed-in user with a log-out button, the sub-navigation and
 * the offline capture queue, which lives here so a recording survives moving between screens.
 *
 * The queue is mounted **outside** the auth gate on purpose. `AuthGate` calls `me()`, which cannot
 * tell "signed out" from "no connection" and returns null either way, so a host who reloads the app
 * on the plateau is shown the login form — with no way to see the recordings the copy promises are
 * safe. The provider therefore wraps the gate, and while the gate is showing the login form
 * {@link QueueOutsideTheGate} shows the queue underneath it, as long as there is something in it.
 * Uploading needs no `me()`: the bearer token in this browser is attached to every request, and the
 * queue simply waits while there is none.
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import AuthGate from "@/components/AuthGate";
import RegisterSW from "@/components/RegisterSW";
import { useT } from "@/lib/i18n";
import styles from "./host.module.css";
import { OfflineQueueProvider, useOfflineQueue } from "./offlineQueue";
import OfflineQueuePanel from "./OfflineQueuePanel";
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
  const [insideGate, setInsideGate] = useState(false);
  const enter = useCallback((yes: boolean) => setInsideGate(yes), []);
  return (
    <>
      <RegisterSW />
      <OfflineQueueProvider>
        <AuthGate roles={["host", "ambassador"]}>
          {(user, signOut) => (
            <InsideGate onChange={enter}>
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
            </InsideGate>
          )}
        </AuthGate>
        {insideGate ? null : <QueueOutsideTheGate />}
      </OfflineQueueProvider>
    </>
  );
}

/** Tells the shell whether the gate is currently showing the app or the login form. */
function InsideGate({ onChange, children }: { onChange: (v: boolean) => void; children: React.ReactNode }) {
  useEffect(() => {
    onChange(true);
    return () => onChange(false);
  }, [onChange]);
  return <>{children}</>;
}

/**
 * The queue, shown under the login form while the gate has nobody signed in — which offline is not
 * a statement about the host at all, only about `me()` not being reachable. Nothing is shown when
 * the device holds no recordings, so the ordinary sign-in screen is unchanged.
 */
function QueueOutsideTheGate() {
  const t = useT();
  const { items } = useOfflineQueue();
  if (items.length === 0) return null;
  return (
    <div className={styles.shell}>
      <section className="card">
        <p className="alert alert-ok small" role="note">
          {t("host.queue.outsideGate")}
        </p>
        <OfflineQueuePanel />
      </section>
    </div>
  );
}
