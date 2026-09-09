"use client";
import Link from "next/link";
import { FormEvent, useState } from "react";
import { pick, useLang, useT } from "@/lib/i18n";
import { createHeritageEntry, errorMessage, getVillages } from "@/components/admin/api";
import { HERITAGE_KINDS, type HeritageKind, type SourceRef } from "@/components/admin/types";
import { ErrorAlert, Loading } from "@/components/admin/ui";
import { useAsync } from "@/components/admin/useAsync";
import { sortedVillages } from "@/components/admin/villages";
import styles from "@/components/admin/admin.module.css";

function numOrNull(s: string): number | null {
  if (s.trim() === "") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

/** Create a heritage entry. It is always stored as a **draft**: nothing skips the validation gate. */
export default function NewHeritageEntryPage() {
  const t = useT();
  const { lang } = useLang();
  const villagesQ = useAsync(() => getVillages(), []);
  const villages = villagesQ.data ?? [];

  const [village, setVillage] = useState("");
  const [kind, setKind] = useState<HeritageKind>("place");
  const [titleLocal, setTitleLocal] = useState("");
  const [titleEn, setTitleEn] = useState("");
  const [summaryLocal, setSummaryLocal] = useState("");
  const [summaryEn, setSummaryEn] = useState("");
  const [bodyLocal, setBodyLocal] = useState("");
  const [bodyEn, setBodyEn] = useState("");
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");
  const [approximate, setApproximate] = useState(true);
  const [coordsSource, setCoordsSource] = useState("");
  const [eventDate, setEventDate] = useState("");
  const [establishedYear, setEstablishedYear] = useState("");
  const [source, setSource] = useState("");
  const [sources, setSources] = useState<SourceRef[]>([{ title: "", url: "" }]);
  const [factsVerified, setFactsVerified] = useState(true);
  const [verificationNote, setVerificationNote] = useState("");
  const [tags, setTags] = useState("");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<{ id: string; slug: string } | null>(null);

  function setSourceAt(i: number, patch: Partial<SourceRef>) {
    setSources((prev) => prev.map((s, j) => (i === j ? { ...s, ...patch } : s)));
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setCreated(null);
    setBusy(true);
    try {
      const entry = await createHeritageEntry({
        village,
        kind,
        title_local: titleLocal.trim(),
        title_en: titleEn.trim(),
        summary_local: summaryLocal,
        summary_en: summaryEn,
        body_local: bodyLocal,
        body_en: bodyEn,
        lat: numOrNull(lat),
        lng: numOrNull(lng),
        coords_approximate: approximate,
        coords_source: coordsSource,
        event_date: eventDate || null,
        established_year: numOrNull(establishedYear),
        source: source.trim(),
        sources: sources
          .filter((s) => s.title.trim() !== "")
          .map((s) => ({ title: s.title.trim(), url: s.url?.trim() ? s.url.trim() : null })),
        facts_verified: factsVerified,
        verification_note: verificationNote,
        tags: tags
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      });
      setCreated({ id: entry.id, slug: entry.slug });
      setTitleLocal("");
      setTitleEn("");
      setSummaryLocal("");
      setSummaryEn("");
      setBodyLocal("");
      setBodyEn("");
      setLat("");
      setLng("");
      setEventDate("");
      setEstablishedYear("");
      setSource("");
      setSources([{ title: "", url: "" }]);
      setVerificationNote("");
      setTags("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <section>
        <h1>{t("admin.new.title")}</h1>
        <p className="muted">{t("admin.new.lead")}</p>
      </section>

      {villagesQ.loading && <Loading />}
      <ErrorAlert error={villagesQ.error} onRetry={villagesQ.reload} />

      <p role="status" aria-live="polite" className={created ? "alert alert-ok" : "visually-hidden"}>
        {created ? (
          <>
            {t("admin.new.created", { slug: created.slug })}{" "}
            <Link href={`/validate/heritage_entry/${created.id}`}>{t("admin.new.openItem")}</Link>
          </>
        ) : (
          ""
        )}
      </p>

      <form className="card stack" onSubmit={submit}>
        <fieldset className="stack" style={{ border: 0, margin: 0, padding: 0 }}>
          <legend>
            <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{t("admin.new.sectionBasics")}</h2>
          </legend>
          <label className="field">
            <span>{t("admin.new.village")} *</span>
            <select value={village} onChange={(e) => setVillage(e.target.value)} required>
              <option value="">{t("admin.new.pickVillage")}</option>
              {sortedVillages(lang, villages).map((v) => (
                <option key={v.id} value={v.slug}>
                  {pick(lang, v.name_local, v.name_en)} ({v.municipality})
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>{t("admin.new.kind")}</span>
            <select value={kind} onChange={(e) => setKind(e.target.value as HeritageKind)}>
              {HERITAGE_KINDS.map((k) => (
                <option key={k} value={k}>
                  {t(`admin.kind.${k}`)}
                </option>
              ))}
            </select>
          </label>
        </fieldset>

        <fieldset className="stack" style={{ border: 0, margin: 0, padding: 0 }}>
          <legend>
            <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{t("admin.new.sectionText")}</h2>
          </legend>
          <p className="muted small" style={{ margin: 0 }}>
            {t("admin.new.bothLanguages")}
          </p>
          <div className={styles.pair}>
            <label className="field">
              <span lang="cnr">{t("admin.new.titleLocal")} *</span>
              <input value={titleLocal} onChange={(e) => setTitleLocal(e.target.value)} lang="cnr" required maxLength={255} />
            </label>
            <label className="field">
              <span lang="en">{t("admin.new.titleEn")} *</span>
              <input value={titleEn} onChange={(e) => setTitleEn(e.target.value)} lang="en" required maxLength={255} />
            </label>
          </div>
          <div className={styles.pair}>
            <label className="field">
              <span lang="cnr">{t("admin.new.summaryLocal")}</span>
              <textarea value={summaryLocal} onChange={(e) => setSummaryLocal(e.target.value)} lang="cnr" />
            </label>
            <label className="field">
              <span lang="en">{t("admin.new.summaryEn")}</span>
              <textarea value={summaryEn} onChange={(e) => setSummaryEn(e.target.value)} lang="en" />
            </label>
          </div>
          <div className={styles.pair}>
            <label className="field">
              <span lang="cnr">{t("admin.new.bodyLocal")}</span>
              <textarea value={bodyLocal} onChange={(e) => setBodyLocal(e.target.value)} lang="cnr" />
            </label>
            <label className="field">
              <span lang="en">{t("admin.new.bodyEn")}</span>
              <textarea value={bodyEn} onChange={(e) => setBodyEn(e.target.value)} lang="en" />
            </label>
          </div>
        </fieldset>

        <fieldset className="stack" style={{ border: 0, margin: 0, padding: 0 }}>
          <legend>
            <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{t("admin.new.sectionCoords")}</h2>
          </legend>
          <div className={styles.pair}>
            <label className="field">
              <span>{t("admin.new.lat")}</span>
              <input value={lat} onChange={(e) => setLat(e.target.value)} inputMode="decimal" placeholder="42.41" />
            </label>
            <label className="field">
              <span>{t("admin.new.lng")}</span>
              <input value={lng} onChange={(e) => setLng(e.target.value)} inputMode="decimal" placeholder="18.71" />
            </label>
          </div>
          <label className="row">
            <input
              type="checkbox"
              checked={approximate}
              onChange={(e) => setApproximate(e.target.checked)}
              style={{ width: "auto", minHeight: "auto" }}
            />
            <span>{t("admin.new.approximate")}</span>
          </label>
          <label className="field">
            <span>{t("admin.new.coordsSource")}</span>
            <input value={coordsSource} onChange={(e) => setCoordsSource(e.target.value)} />
          </label>
          <div className={styles.pair}>
            <label className="field">
              <span>{t("admin.new.eventDate")}</span>
              <input type="date" value={eventDate} onChange={(e) => setEventDate(e.target.value)} />
            </label>
            <label className="field">
              <span>{t("admin.new.establishedYear")}</span>
              <input value={establishedYear} onChange={(e) => setEstablishedYear(e.target.value)} inputMode="numeric" />
            </label>
          </div>
        </fieldset>

        <fieldset className="stack" style={{ border: 0, margin: 0, padding: 0 }}>
          <legend>
            <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{t("admin.new.sectionSources")}</h2>
          </legend>
          <label className="field">
            <span>{t("admin.new.source")} *</span>
            <textarea
              value={source}
              onChange={(e) => setSource(e.target.value)}
              required
              aria-describedby="source-help"
              style={{ minHeight: "4rem" }}
            />
          </label>
          <p id="source-help" className="muted small" style={{ margin: 0 }}>
            {t("admin.new.sourceHelp")}
          </p>

          {sources.map((s, i) => (
            <div key={i} className={styles.sourceRow}>
              <label className="field">
                <span>{t("admin.new.sourceTitle", { n: i + 1 })}</span>
                <input value={s.title} onChange={(e) => setSourceAt(i, { title: e.target.value })} />
              </label>
              <label className="field">
                <span>{t("admin.new.sourceUrl", { n: i + 1 })}</span>
                <input
                  type="url"
                  value={s.url ?? ""}
                  onChange={(e) => setSourceAt(i, { url: e.target.value })}
                  placeholder="https://"
                />
              </label>
              <button
                type="button"
                className="btn btn-small btn-secondary"
                onClick={() => setSources((prev) => (prev.length === 1 ? [{ title: "", url: "" }] : prev.filter((_, j) => j !== i)))}
              >
                {t("admin.new.removeSource")}
              </button>
            </div>
          ))}
          <div>
            <button type="button" className="btn btn-small btn-secondary" onClick={() => setSources((p) => [...p, { title: "", url: "" }])}>
              {t("admin.new.addSource")}
            </button>
          </div>

          <label className="row">
            <input
              type="checkbox"
              checked={factsVerified}
              onChange={(e) => setFactsVerified(e.target.checked)}
              style={{ width: "auto", minHeight: "auto" }}
              aria-describedby="facts-help"
            />
            <span>{t("admin.new.factsVerified")}</span>
          </label>
          <p id="facts-help" className="muted small" style={{ margin: 0 }}>
            {t("admin.new.factsVerifiedHelp")}
          </p>
          <label className="field">
            <span>{t("admin.new.verificationNote")}</span>
            <input value={verificationNote} onChange={(e) => setVerificationNote(e.target.value)} />
          </label>
          <label className="field">
            <span>{t("admin.new.tags")}</span>
            <input value={tags} onChange={(e) => setTags(e.target.value)} placeholder={t("admin.new.tagsPlaceholder")} />
          </label>
        </fieldset>

        {error && (
          <p className="alert alert-danger" role="alert">
            {error}
          </p>
        )}

        <div className={styles.actions}>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? t("admin.new.saving") : t("admin.new.submit")}
          </button>
          <Link className="btn btn-secondary" href="/validate">
            {t("admin.common.cancel")}
          </Link>
        </div>
        <p className="muted small" style={{ margin: 0 }}>
          {t("admin.new.draftNote")}
        </p>
      </form>
    </div>
  );
}
