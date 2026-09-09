"use client";
/**
 * "My listings" — every listing of the signed-in host in every status, with the edit form.
 * Editing creates a new version and sends the listing back to draft for re-validation; the form
 * says so before the host saves.
 */
import { useCallback, useEffect, useState } from "react";
import { useLang, useT } from "@/lib/i18n";
import styles from "./host.module.css";
import { getMyListings, getVillages, updateListing } from "./hostApi";
import { ListingDetailsFields, NarrativeFields } from "./ListingDetails";
import ListingPreview, { StatusBadge } from "./ListingPreview";
import type { Confirmations, Listing, ListingFormValues, ListingPayload, StructuredField, Village } from "./types";
import {
  confirmationsFromListing,
  describeError,
  formatDate,
  formFromListing,
  formToFields,
  unconfirmed,
  validateForm,
} from "./utils";

export default function MyListings() {
  const t = useT();
  const { lang } = useLang();
  const [listings, setListings] = useState<Listing[]>([]);
  const [villages, setVillages] = useState<Village[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState<ListingFormValues | null>(null);
  const [confirmed, setConfirmed] = useState<Confirmations | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setListings(await getMyListings());
    } catch (e) {
      setError(describeError(e, t));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
    getVillages()
      .then(setVillages)
      .catch(() => undefined);
    // `load` is stable per language; reloading on a language switch is harmless but unnecessary.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function startEdit(l: Listing) {
    setEditing(l.id);
    setForm(formFromListing(l));
    setConfirmed(confirmationsFromListing(l));
    setStatus("");
    setError(null);
  }

  function cancelEdit() {
    setEditing(null);
    setForm(null);
    setConfirmed(null);
  }

  async function save(l: Listing) {
    if (!form || !confirmed) return;
    const invalid = validateForm(form, t);
    if (invalid) {
      setError(invalid);
      return;
    }
    if (unconfirmed(confirmed).length > 0) {
      setError(t("host.confirm.blocked"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const payload: ListingPayload = { ...formToFields(form, confirmed) };
      if (form.village_id) payload.village_id = form.village_id;
      const updated = await updateListing(l.id, payload);
      setListings((rows) => rows.map((row) => (row.id === updated.id ? updated : row)));
      setStatus(t("host.listing.saved", { version: updated.version }));
      cancelEdit();
    } catch (e) {
      setError(describeError(e, t));
    } finally {
      setBusy(false);
    }
  }

  const patchForm = (patch: Partial<ListingFormValues>) => setForm((f) => (f ? { ...f, ...patch } : f));
  const setConfirmation = (field: StructuredField, value: boolean) =>
    setConfirmed((c) => (c ? { ...c, [field]: value } : c));

  return (
    <section aria-labelledby="listings-heading">
      <h2 id="listings-heading">{t("host.listings.heading")}</h2>
      <p>{t("host.listings.intro")}</p>
      <p role="status" aria-live="polite" className="small">
        {loading ? t("common.loading") : status}
      </p>
      {error ? (
        <p className="alert alert-danger" role="alert">
          {error}
        </p>
      ) : null}
      {!loading && listings.length === 0 ? <p className="card">{t("host.listings.empty")}</p> : null}

      <div className={styles.cards}>
        {listings.map((l) => (
          <article key={l.id} className="card">
            <div className={styles.cardHead}>
              <h3>{lang === "cnr" ? l.title_local || l.title_en : l.title_en || l.title_local}</h3>
              <StatusBadge status={l.status} />
            </div>
            <p className="small muted">
              {t("host.listing.meta", {
                version: l.version,
                updated: formatDate(lang, l.updated_at, true),
                method: t(`host.method.${l.extraction_method || "manual"}`),
              })}
              {l.is_sample ? ` — ${t("common.sample")}` : ""}
            </p>
            {editing === l.id && form && confirmed ? (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void save(l);
                }}
              >
                <p className="alert alert-warn" role="note">
                  {t("host.listing.editWarning")}
                </p>
                <NarrativeFields values={form} onChange={patchForm} idPrefix={`edit-${l.id}`} />
                <ListingDetailsFields
                  values={form}
                  onChange={patchForm}
                  confirmed={confirmed}
                  onConfirm={setConfirmation}
                  villages={villages}
                  idPrefix={`edit-${l.id}`}
                />
                <div className={styles.actions}>
                  <button type="submit" className="btn btn-primary" disabled={busy}>
                    {busy ? t("host.listing.saving") : t("common.save")}
                  </button>
                  <button type="button" className="btn btn-secondary" onClick={cancelEdit} disabled={busy}>
                    {t("common.cancel")}
                  </button>
                </div>
              </form>
            ) : (
              <>
                <ListingPreview listing={l} villages={villages} />
                <div className={styles.actions}>
                  <button type="button" className="btn btn-secondary" onClick={() => startEdit(l)}>
                    {t("host.listing.edit")}
                  </button>
                </div>
              </>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
