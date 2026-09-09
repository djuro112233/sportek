"use client";
/**
 * The two halves of a listing, kept visibly apart:
 *
 * * `NarrativeFields` — title and description in both languages. These are the *only* fields the
 *   assistant ever drafts, and the host edits them freely.
 * * `ListingDetailsFields` — price, season, capacity, accessibility, coordinates, category and
 *   village. These are **never inferred**: the host types them and confirms each group. The confirm
 *   boxes fill `confirmed_fields`; without them the API answers 422 and the UI blocks submission.
 */
import { useState } from "react";
import { useLang, useT } from "@/lib/i18n";
import styles from "./host.module.css";
import type { Confirmations, ListingFormValues, StructuredField, Village } from "./types";
import { CATEGORIES, STRUCTURED_FIELDS } from "./types";
import { MONTHS, monthName } from "./utils";

interface NarrativeProps {
  values: ListingFormValues;
  onChange: (patch: Partial<ListingFormValues>) => void;
  idPrefix: string;
  extractionMethod?: string;
  translationPending?: boolean;
}

export function NarrativeFields({ values, onChange, idPrefix, extractionMethod, translationPending }: NarrativeProps) {
  const t = useT();
  const id = (k: string) => `${idPrefix}-${k}`;
  return (
    <fieldset className={styles.group}>
      <legend>{t("host.draft.legend")}</legend>
      <p className={styles.hint}>{t("host.draft.hint")}</p>
      {extractionMethod ? (
        <p className="small">
          <span className="badge">{t("host.draft.method", { method: t(`host.method.${extractionMethod}`) })}</span>
        </p>
      ) : null}
      {translationPending ? (
        <p className="alert alert-warn" role="note">
          {t("host.draft.translationPending")}
        </p>
      ) : null}
      <div className={styles.twoCol}>
        <label className="field" htmlFor={id("title_local")}>
          <span>{t("host.field.title_local")}</span>
          <input
            id={id("title_local")}
            value={values.title_local}
            maxLength={90}
            onChange={(e) => onChange({ title_local: e.target.value })}
          />
        </label>
        <label className="field" htmlFor={id("title_en")}>
          <span>{t("host.field.title_en")}</span>
          <input
            id={id("title_en")}
            value={values.title_en}
            maxLength={90}
            onChange={(e) => onChange({ title_en: e.target.value })}
          />
        </label>
      </div>
      <div className={styles.twoCol}>
        <label className="field" htmlFor={id("description_local")}>
          <span>{t("host.field.description_local")}</span>
          <textarea
            id={id("description_local")}
            rows={6}
            value={values.description_local}
            onChange={(e) => onChange({ description_local: e.target.value })}
          />
        </label>
        <label className="field" htmlFor={id("description_en")}>
          <span>{t("host.field.description_en")}</span>
          <textarea
            id={id("description_en")}
            rows={6}
            value={values.description_en}
            onChange={(e) => onChange({ description_en: e.target.value })}
          />
        </label>
      </div>
    </fieldset>
  );
}

interface DetailsProps {
  values: ListingFormValues;
  onChange: (patch: Partial<ListingFormValues>) => void;
  confirmed: Confirmations;
  onConfirm: (field: StructuredField, value: boolean) => void;
  villages: Village[];
  idPrefix: string;
}

export function ListingDetailsFields({ values, onChange, confirmed, onConfirm, villages, idPrefix }: DetailsProps) {
  const t = useT();
  const { lang } = useLang();
  const [geoState, setGeoState] = useState<"idle" | "busy" | "error" | "unsupported">("idle");
  const id = (k: string) => `${idPrefix}-${k}`;
  const allConfirmed = STRUCTURED_FIELDS.every((f) => confirmed[f]);
  const selectedVillage = villages.find((v) => v.id === values.village_id) ?? null;

  const useMyLocation = () => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setGeoState("unsupported");
      return;
    }
    setGeoState("busy");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        onChange({
          lat: pos.coords.latitude.toFixed(6),
          lng: pos.coords.longitude.toFixed(6),
        });
        setGeoState("idle");
      },
      () => setGeoState("error"),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
    );
  };

  const confirmBox = (field: StructuredField) => (
    <div className={`${styles.confirmBox} ${confirmed[field] ? "" : styles.pending}`}>
      <label className={styles.check} htmlFor={id(`confirm-${field}`)}>
        <input
          id={id(`confirm-${field}`)}
          type="checkbox"
          checked={confirmed[field]}
          onChange={(e) => onConfirm(field, e.target.checked)}
        />
        <span>
          {t(`host.confirm.${field}`)}
          {confirmed[field] ? "" : ` — ${t("host.confirm.required")}`}
        </span>
      </label>
    </div>
  );

  return (
    <div>
      <p className="alert alert-warn" role="note">
        {t("host.details.neverInferred")}
      </p>

      <label className={styles.check} htmlFor={id("confirm-all")}>
        <input
          id={id("confirm-all")}
          type="checkbox"
          checked={allConfirmed}
          onChange={(e) => {
            for (const f of STRUCTURED_FIELDS) onConfirm(f, e.target.checked);
          }}
        />
        <span>
          <strong>{t("host.confirm.all")}</strong>
        </span>
      </label>

      <fieldset className={styles.group}>
        <legend>{t("host.group.category")}</legend>
        <label className="field" htmlFor={id("category")}>
          <span>{t("host.field.category")}</span>
          <select id={id("category")} value={values.category} onChange={(e) => onChange({ category: e.target.value })}>
            <option value="">{t("host.field.choose")}</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {t(`host.category.${c}`)}
              </option>
            ))}
          </select>
        </label>
        {confirmBox("category")}
      </fieldset>

      <fieldset className={styles.group}>
        <legend>{t("host.group.price")}</legend>
        <p className={styles.hint}>{t("host.group.priceHint")}</p>
        <div className={styles.twoCol}>
          <label className="field" htmlFor={id("price_min")}>
            <span>{t("host.field.price_min")}</span>
            <input
              id={id("price_min")}
              inputMode="decimal"
              value={values.price_min}
              onChange={(e) => onChange({ price_min: e.target.value })}
            />
          </label>
          <label className="field" htmlFor={id("price_max")}>
            <span>{t("host.field.price_max")}</span>
            <input
              id={id("price_max")}
              inputMode="decimal"
              value={values.price_max}
              onChange={(e) => onChange({ price_max: e.target.value })}
            />
          </label>
          <label className="field" htmlFor={id("currency")}>
            <span>{t("host.field.currency")}</span>
            <select id={id("currency")} value={values.currency} onChange={(e) => onChange({ currency: e.target.value })}>
              <option value="EUR">EUR</option>
            </select>
          </label>
        </div>
        <div className={styles.twoCol}>
          <label className="field" htmlFor={id("price_note_local")}>
            <span>{t("host.field.price_note_local")}</span>
            <input
              id={id("price_note_local")}
              maxLength={255}
              value={values.price_note_local}
              onChange={(e) => onChange({ price_note_local: e.target.value })}
            />
          </label>
          <label className="field" htmlFor={id("price_note_en")}>
            <span>{t("host.field.price_note_en")}</span>
            <input
              id={id("price_note_en")}
              maxLength={255}
              value={values.price_note_en}
              onChange={(e) => onChange({ price_note_en: e.target.value })}
            />
          </label>
        </div>
        <p className={styles.hint}>{t("host.group.noPayments")}</p>
        {confirmBox("price_range")}
      </fieldset>

      <fieldset className={styles.group}>
        <legend>{t("host.group.season")}</legend>
        <label className={styles.check} htmlFor={id("season_all_year")}>
          <input
            id={id("season_all_year")}
            type="checkbox"
            checked={values.season_all_year}
            onChange={(e) => onChange({ season_all_year: e.target.checked })}
          />
          <span>{t("host.field.season_all_year")}</span>
        </label>
        {!values.season_all_year && (
          <div className={styles.twoCol}>
            <label className="field" htmlFor={id("season_from")}>
              <span>{t("host.field.season_from")}</span>
              <select
                id={id("season_from")}
                value={values.season_from}
                onChange={(e) => onChange({ season_from: e.target.value })}
              >
                <option value="">{t("host.field.choose")}</option>
                {MONTHS.map((m) => (
                  <option key={m} value={String(m)}>
                    {monthName(lang, m)}
                  </option>
                ))}
              </select>
            </label>
            <label className="field" htmlFor={id("season_to")}>
              <span>{t("host.field.season_to")}</span>
              <select
                id={id("season_to")}
                value={values.season_to}
                onChange={(e) => onChange({ season_to: e.target.value })}
              >
                <option value="">{t("host.field.choose")}</option>
                {MONTHS.map((m) => (
                  <option key={m} value={String(m)}>
                    {monthName(lang, m)}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
        {confirmBox("season")}
      </fieldset>

      <fieldset className={styles.group}>
        <legend>{t("host.group.capacity")}</legend>
        <label className="field" htmlFor={id("capacity")}>
          <span>{t("host.field.capacity")}</span>
          <input
            id={id("capacity")}
            inputMode="numeric"
            value={values.capacity}
            onChange={(e) => onChange({ capacity: e.target.value })}
            aria-describedby={id("capacity-hint")}
          />
        </label>
        <p className={styles.hint} id={id("capacity-hint")}>
          {t("host.field.capacityHint")}
        </p>
        {confirmBox("capacity")}
      </fieldset>

      <fieldset className={styles.group}>
        <legend>{t("host.group.accessibility")}</legend>
        <fieldset className={styles.radioRow} style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="visually-hidden">{t("host.field.step_free")}</legend>
          <span>{t("host.field.step_free")}</span>
          <label className={styles.check} htmlFor={id("step_free_yes")}>
            <input
              id={id("step_free_yes")}
              type="radio"
              name={`${idPrefix}-step_free`}
              checked={values.accessibility_step_free === "yes"}
              onChange={() => onChange({ accessibility_step_free: "yes" })}
            />
            <span>{t("common.yes")}</span>
          </label>
          <label className={styles.check} htmlFor={id("step_free_no")}>
            <input
              id={id("step_free_no")}
              type="radio"
              name={`${idPrefix}-step_free`}
              checked={values.accessibility_step_free === "no"}
              onChange={() => onChange({ accessibility_step_free: "no" })}
            />
            <span>{t("common.no")}</span>
          </label>
        </fieldset>
        <div className={styles.twoCol}>
          <label className="field" htmlFor={id("accessibility_note_local")}>
            <span>{t("host.field.accessibility_note_local")}</span>
            <textarea
              id={id("accessibility_note_local")}
              rows={3}
              value={values.accessibility_note_local}
              onChange={(e) => onChange({ accessibility_note_local: e.target.value })}
            />
          </label>
          <label className="field" htmlFor={id("accessibility_note_en")}>
            <span>{t("host.field.accessibility_note_en")}</span>
            <textarea
              id={id("accessibility_note_en")}
              rows={3}
              value={values.accessibility_note_en}
              onChange={(e) => onChange({ accessibility_note_en: e.target.value })}
            />
          </label>
        </div>
        {confirmBox("accessibility")}
      </fieldset>

      <fieldset className={styles.group}>
        <legend>{t("host.group.location")}</legend>
        <label className="field" htmlFor={id("village")}>
          <span>{t("host.field.village")}</span>
          <select id={id("village")} value={values.village_id} onChange={(e) => onChange({ village_id: e.target.value })}>
            <option value="">{t("host.field.choose")}</option>
            {villages.map((v) => (
              <option key={v.id} value={v.id}>
                {`${lang === "cnr" ? v.name_local : v.name_en} — ${v.municipality}${
                  v.facts_verified ? "" : ` (${t("host.village.unverified")})`
                }`}
              </option>
            ))}
          </select>
        </label>
        {selectedVillage && !selectedVillage.facts_verified ? (
          <p className="alert alert-warn small" role="note">
            {t("host.village.unverifiedNote", { note: selectedVillage.verification_note || "" })}
          </p>
        ) : null}
        <div className={styles.twoCol}>
          <label className="field" htmlFor={id("lat")}>
            <span>{t("host.field.lat")}</span>
            <input id={id("lat")} inputMode="decimal" value={values.lat} onChange={(e) => onChange({ lat: e.target.value })} />
          </label>
          <label className="field" htmlFor={id("lng")}>
            <span>{t("host.field.lng")}</span>
            <input id={id("lng")} inputMode="decimal" value={values.lng} onChange={(e) => onChange({ lng: e.target.value })} />
          </label>
        </div>
        <div className="row">
          <button type="button" className="btn btn-secondary" onClick={useMyLocation} disabled={geoState === "busy"}>
            {geoState === "busy" ? t("host.geo.busy") : t("host.geo.use")}
          </button>
          <span className="small" role="status">
            {geoState === "error" ? t("host.geo.error") : geoState === "unsupported" ? t("host.geo.unsupported") : ""}
          </span>
        </div>
        <label className={styles.check} htmlFor={id("coords_approximate")}>
          <input
            id={id("coords_approximate")}
            type="checkbox"
            checked={values.coords_approximate}
            onChange={(e) => onChange({ coords_approximate: e.target.checked })}
          />
          <span>{t("host.field.coords_approximate")}</span>
        </label>
        <p className={styles.hint}>{t("host.field.coordsHint")}</p>
        {confirmBox("coordinates")}
      </fieldset>
    </div>
  );
}
