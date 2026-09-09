"use client";
/**
 * Host home — the entry screen of the host PWA.
 *
 * It explains, in the host's own language, what the module does and what it does not do: the
 * assistant drafts the title and the description, the host enters and confirms every fact, the
 * clock measures active authoring time, a recording survives being offline, and nothing is
 * published before Napredak has approved it. The offline capture queue and the voluntary
 * self-report about the host's own data live here, next to the links into the flow.
 */
import Link from "next/link";
import GenderPanel from "@/components/host/GenderPanel";
import HostShell from "@/components/host/HostShell";
import OfflineQueuePanel from "@/components/host/OfflineQueuePanel";
import styles from "@/components/host/host.module.css";
import { useT } from "@/lib/i18n";

export default function HostHomePage() {
  const t = useT();
  return (
    <HostShell>
      {(user) => (
        <div className="stack">
          <section className="card" aria-labelledby="host-home-heading">
            <h2 id="host-home-heading">{t("host.home.heading")}</h2>
            <p>{t("host.home.lead")}</p>
            <h3>{t("host.home.stepsHeading")}</h3>
            <ol>
              <li>{t("host.home.step1")}</li>
              <li>{t("host.home.step2")}</li>
              <li>{t("host.home.step3")}</li>
              <li>{t("host.home.step4")}</li>
              <li>{t("host.home.step5")}</li>
            </ol>
            <div className={styles.actions}>
              <Link className="btn btn-primary" href="/host/new">
                {t("host.home.start")}
              </Link>
              <Link className="btn btn-secondary" href="/host/listings">
                {t("host.home.toListings")}
              </Link>
              <Link className="btn btn-secondary" href="/host/requests">
                {t("host.home.toRequests")}
              </Link>
            </div>
          </section>

          <section className="card" aria-labelledby="host-home-rules">
            <h2 id="host-home-rules">{t("host.home.rulesHeading")}</h2>
            <dl className={styles.facts}>
              <dt>{t("host.home.draftsHeading")}</dt>
              <dd>{t("host.home.drafts")}</dd>
              <dt>{t("host.home.timerHeading")}</dt>
              <dd>{t("host.home.timer")}</dd>
              <dt>{t("host.home.offlineHeading")}</dt>
              <dd>{t("host.home.offline")}</dd>
              <dt>{t("host.home.consentHeading")}</dt>
              <dd>{t("host.home.consent")}</dd>
            </dl>
            <p className="small muted">{t("host.home.prototype")}</p>
          </section>

          <OfflineQueuePanel />

          <GenderPanel user={user} />
        </div>
      )}
    </HostShell>
  );
}
