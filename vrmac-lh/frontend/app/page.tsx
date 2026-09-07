"use client";
import Link from "next/link";
import { useT } from "@/lib/i18n";

const APPS = [
  { href: "/visitor", title: "home.visitor", desc: "home.visitor.desc" },
  { href: "/host", title: "home.host", desc: "home.host.desc" },
  { href: "/validate", title: "home.validate", desc: "home.validate.desc" },
  { href: "/dashboard", title: "home.dashboard", desc: "home.dashboard.desc" },
];

export default function Home() {
  const t = useT();
  return (
    <div className="stack">
      <section>
        <h1>{t("app.name")}</h1>
        <p className="lead">{t("home.lead")}</p>
      </section>
      <section className="grid" aria-label="Apps">
        {APPS.map((a) => (
          <Link key={a.href} href={a.href} className="card" style={{ textDecoration: "none", color: "inherit" }}>
            <h2 style={{ marginTop: 0 }}>{t(a.title)}</h2>
            <p className="muted">{t(a.desc)}</p>
          </Link>
        ))}
      </section>
      <section className="card">
        <h2>{t("home.claims")}</h2>
        <ol>
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <li key={i}>{t(`home.claim${i}`)}</li>
          ))}
        </ol>
        <p className="muted small">
          API: <a href="/api/docs">/api/docs</a> · NGSI-LD: <a href="/api/export/ngsi-ld">/api/export/ngsi-ld</a> · DCAT-AP:{" "}
          <a href="/api/export/dcat-ap">/api/export/dcat-ap</a>
        </p>
      </section>
    </div>
  );
}
