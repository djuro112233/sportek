"use client";
import Link from "next/link";
import AuthGate from "@/components/AuthGate";
import { useT } from "@/lib/i18n";
import type { Role } from "@/components/admin/types";
import styles from "@/components/admin/admin.module.css";

/** Sample accounts of the seed. Fictional people, one per role; the password is not a secret. */
const SAMPLE_ACCOUNTS: { role: Role; email: string }[] = [
  { role: "host", email: "host1@example.org" },
  { role: "ambassador", email: "ambassador1@example.org" },
  { role: "validator", email: "validator1@example.org" },
  { role: "institution", email: "institution1@example.org" },
];

const SAMPLE_PASSWORD = "prototype123";

/** Where each role goes after signing in. */
const APPS: Record<Role, { href: string; key: string }[]> = {
  host: [{ href: "/host", key: "admin.login.appHost" }],
  ambassador: [
    { href: "/validate", key: "admin.login.appValidate" },
    { href: "/host", key: "admin.login.appHost" },
  ],
  validator: [
    { href: "/validate", key: "admin.login.appValidate" },
    { href: "/dashboard", key: "admin.login.appDashboard" },
  ],
  institution: [{ href: "/dashboard", key: "admin.login.appDashboard" }],
};

function SampleAccounts() {
  const t = useT();
  return (
    <section className="card">
      <h2 style={{ marginTop: 0 }}>{t("admin.login.sampleTitle")}</h2>
      <p className="muted small">{t("admin.login.sampleLead", { password: SAMPLE_PASSWORD })}</p>
      <div className="table-wrap">
        <table className="table">
          <caption className="visually-hidden">{t("admin.login.sampleCaption")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("admin.login.colRole")}</th>
              <th scope="col">{t("admin.login.colEmail")}</th>
              <th scope="col">{t("admin.login.colPassword")}</th>
            </tr>
          </thead>
          <tbody>
            {SAMPLE_ACCOUNTS.map((a) => (
              <tr key={a.email}>
                <th scope="row" style={{ fontWeight: 600 }}>
                  {t(`admin.role.${a.role}`)}
                </th>
                <td className={styles.mono}>{a.email}</td>
                <td className={styles.mono}>{SAMPLE_PASSWORD}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">{t("admin.login.sampleNote")}</p>
    </section>
  );
}

/** Sign in to the prototype: one gate for all four roles, with the sample accounts in the open. */
export default function LoginPage() {
  const t = useT();
  return (
    <div className="stack">
      <section>
        <h1>{t("admin.login.title")}</h1>
        <p className="muted">{t("admin.login.lead")}</p>
      </section>

      <AuthGate roles={["host", "ambassador", "validator", "institution"]}>
        {(user, signOut) => (
          <section className="card stack">
            <h2 style={{ margin: 0 }}>{t("admin.login.signedIn")}</h2>
            <dl className={styles.dl}>
              <dt>{t("admin.login.name")}</dt>
              <dd>{user.display_name || "—"}</dd>
              <dt>{t("admin.login.colEmail")}</dt>
              <dd className={styles.mono}>{user.email}</dd>
              <dt>{t("admin.login.colRole")}</dt>
              <dd>
                <strong>{t(`admin.role.${user.role}`)}</strong>
                <span className="muted small"> ({user.role})</span>
              </dd>
            </dl>
            <p className="muted small" style={{ margin: 0 }}>
              {t(`admin.login.roleHelp.${user.role}`)}
            </p>
            <nav aria-label={t("admin.login.yourApps")}>
              <h3 style={{ marginBottom: ".4rem" }}>{t("admin.login.yourApps")}</h3>
              <div className={styles.actions}>
                {(APPS[user.role] ?? []).map((a) => (
                  <Link key={a.href} className="btn btn-primary" href={a.href}>
                    {t(a.key)}
                  </Link>
                ))}
                <Link className="btn btn-secondary" href="/visitor">
                  {t("admin.login.appVisitor")}
                </Link>
              </div>
            </nav>
            <div>
              <button type="button" className="btn btn-secondary" onClick={signOut}>
                {t("admin.shell.logout")}
              </button>
            </div>
          </section>
        )}
      </AuthGate>

      <SampleAccounts />
    </div>
  );
}
