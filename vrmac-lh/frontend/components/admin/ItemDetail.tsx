"use client";
import { useLang, useT } from "@/lib/i18n";
import { fmtCoord, fmtDateTime, fmtNumber, fmtValue, monthName } from "./format";
import { UnverifiedFlag, YesNo } from "./ui";
import { villageWithMunicipality } from "./villages";
import type { ItemType, RawItem, SourceRef, Village } from "./types";
import styles from "./admin.module.css";

/* ---------- typed access to a loosely typed payload ---------- */

const str = (o: RawItem, k: string): string => (typeof o[k] === "string" ? (o[k] as string) : "");
const num = (o: RawItem, k: string): number | null => (typeof o[k] === "number" ? (o[k] as number) : null);
const bool = (o: RawItem, k: string): boolean | null => (typeof o[k] === "boolean" ? (o[k] as boolean) : null);
const list = (o: RawItem, k: string): unknown[] => (Array.isArray(o[k]) ? (o[k] as unknown[]) : []);
const has = (o: RawItem, k: string): boolean => Object.prototype.hasOwnProperty.call(o, k);

/** Text fields that exist in both languages, rendered side by side. */
const PAIRS: Record<string, string[]> = {
  heritage_entry: ["title", "summary", "body"],
  listing: ["title", "description", "price_note", "accessibility_note"],
  trail_segment: ["name", "description"],
  trail_report: ["note"],
};

/** Single-language fields, in the order the validator reads them. */
const SCALARS: Record<string, string[]> = {
  heritage_entry: ["slug", "kind", "event_date", "recurrence_rule", "established_year", "elevation_m", "tags"],
  listing: ["slug", "category", "photo_url", "is_sample"],
  trail_segment: ["slug", "from_name", "to_name", "length_m", "ascent_m", "difficulty", "gpx_file", "village_slugs"],
  trail_report: ["segment_id", "condition", "reported_at", "reporter_role", "is_sample"],
};

const COORD_KEYS = ["lat", "lng", "coords_approximate", "coords_source"];
const SOURCE_KEYS = ["source", "sources", "facts_verified", "verification_note"];
const HOST_CONFIRMED_KEYS = [
  "price_min", "price_max", "currency", "season_from", "season_to", "season_all_year", "capacity",
  "accessibility_step_free", "confirmed_fields", "missing_fields", "extraction_method", "translation_pending",
  "consent_record_id", "consent_present",
];
const HEADER_KEYS = ["id", "village_id", "village", "municipality", "status", "version"];
const TIMESTAMP_KEYS = ["created_at", "updated_at", "approved_at", "published_at"];

function Row({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

/** One field in both languages, each half marked with its `lang` attribute. */
function LangPair({ base, item, label }: { base: string; item: RawItem; label: string }) {
  const t = useT();
  const local = str(item, `${base}_local`);
  const en = str(item, `${base}_en`);
  if (!has(item, `${base}_local`) && !has(item, `${base}_en`)) return null;
  return (
    <div>
      <h4 style={{ margin: "0 0 .35rem" }}>{label}</h4>
      <div className={styles.pair}>
        <div>
          <h4>{t("admin.lang.local")}</h4>
          <p className={styles.pre} lang="cnr">
            {local || "—"}
          </p>
        </div>
        <div>
          <h4>{t("admin.lang.en")}</h4>
          <p className={styles.pre} lang="en">
            {en || "—"}
          </p>
        </div>
      </div>
    </div>
  );
}

function SourceList({ sources }: { sources: unknown[] }) {
  const t = useT();
  if (sources.length === 0) return <span className="muted">{t("admin.item.noExtraSources")}</span>;
  return (
    <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
      {sources.map((s, i) => {
        const ref = (s ?? {}) as SourceRef;
        const title = typeof ref.title === "string" ? ref.title : JSON.stringify(s);
        const url = typeof ref.url === "string" && ref.url ? ref.url : null;
        return (
          <li key={i}>
            {url ? (
              <a href={url} rel="noreferrer noopener" target="_blank">
                {title}
              </a>
            ) : (
              title
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Every field of a validation item, in a definition list, with the two languages side by side,
 * the coordinates and their "approximate" flag, and — for listings — the host-confirmed
 * structured fields (a model never fills those).
 */
export default function ItemDetail({
  itemType,
  item,
  villages,
}: {
  itemType: ItemType | string;
  item: RawItem;
  villages: Village[];
}) {
  const t = useT();
  const { lang } = useLang();

  const pairs = PAIRS[itemType] ?? [];
  const scalars = SCALARS[itemType] ?? [];
  const consumed = new Set<string>([
    ...HEADER_KEYS,
    ...TIMESTAMP_KEYS,
    ...COORD_KEYS,
    ...SOURCE_KEYS,
    ...scalars,
    ...pairs.flatMap((p) => [`${p}_local`, `${p}_en`]),
    ...(itemType === "listing" ? HOST_CONFIRMED_KEYS : []),
    ...(itemType === "trail_segment" ? ["geometry"] : []),
  ]);
  const leftovers = Object.keys(item).filter((k) => !consumed.has(k));

  const factsVerified = bool(item, "facts_verified");
  const villageKey = str(item, "village_id") || str(item, "village");
  const geometry = (item.geometry ?? null) as { type?: string; coordinates?: unknown } | null;
  const geometryPoints = Array.isArray(geometry?.coordinates) ? geometry.coordinates.length : null;

  const consentId = str(item, "consent_record_id");
  const consentFlag = bool(item, "consent_present");
  const consentKnown = has(item, "consent_record_id") || has(item, "consent_present");
  const consentPresent = consentFlag === true || consentId.length > 0;

  return (
    <div className="stack">
      {/* --- identity & gate --- */}
      <section aria-labelledby="fields-identity">
        <h3 id="fields-identity">{t("admin.item.identity")}</h3>
        <dl className={styles.dl}>
          <Row label={t("admin.item.type")}>{t(`admin.itemType.${itemType}`)}</Row>
          <Row label={t("admin.item.id")}>
            <span className={styles.mono}>{str(item, "id") || "—"}</span>
          </Row>
          <Row label={t("admin.item.village")}>
            {villageWithMunicipality(lang, villages, villageKey, str(item, "municipality") || null)}
          </Row>
          <Row label={t("admin.item.version")}>{fmtNumber(lang, num(item, "version"))}</Row>
          {TIMESTAMP_KEYS.filter((k) => has(item, k)).map((k) => (
            <Row key={k} label={t(`admin.field.${k}`)}>
              {fmtDateTime(lang, str(item, k) || null)}
            </Row>
          ))}
        </dl>
      </section>

      {/* --- both languages --- */}
      {pairs.length > 0 && (
        <section aria-labelledby="fields-text" className="stack">
          <h3 id="fields-text">{t("admin.item.textFields")}</h3>
          {pairs.map((p) => (
            <LangPair key={p} base={p} item={item} label={t(`admin.field.${p}`)} />
          ))}
        </section>
      )}

      {/* --- listing: host-entered and host-confirmed structured fields --- */}
      {itemType === "listing" && (
        <section aria-labelledby="fields-host">
          <h3 id="fields-host">{t("admin.item.hostConfirmed")}</h3>
          <p className="muted small" style={{ marginTop: 0 }}>
            {t("admin.item.hostConfirmedHelp")}
          </p>
          <dl className={styles.dl}>
            <Row label={t("admin.field.price")}>
              {num(item, "price_min") === null && num(item, "price_max") === null
                ? "—"
                : `${fmtNumber(lang, num(item, "price_min"))} – ${fmtNumber(lang, num(item, "price_max"))} ${str(item, "currency") || "EUR"}`}
            </Row>
            <Row label={t("admin.field.price_note")}>
              <span lang="cnr">{str(item, "price_note_local") || "—"}</span>
              {" / "}
              <span lang="en">{str(item, "price_note_en") || "—"}</span>
            </Row>
            <Row label={t("admin.field.season")}>
              {bool(item, "season_all_year")
                ? t("admin.field.seasonAllYear")
                : num(item, "season_from") === null && num(item, "season_to") === null
                  ? "—"
                  : t("admin.field.seasonRange", {
                      from: monthName(lang, num(item, "season_from")),
                      to: monthName(lang, num(item, "season_to")),
                    })}
            </Row>
            <Row label={t("admin.field.capacity")}>{fmtNumber(lang, num(item, "capacity"))}</Row>
            <Row label={t("admin.field.accessibility_step_free")}>
              <YesNo value={bool(item, "accessibility_step_free")} />
            </Row>
            <Row label={t("admin.field.accessibility_note")}>
              <span lang="cnr">{str(item, "accessibility_note_local") || "—"}</span>
              {" / "}
              <span lang="en">{str(item, "accessibility_note_en") || "—"}</span>
            </Row>
            <Row label={t("admin.field.confirmed_fields")}>
              {list(item, "confirmed_fields").length === 0 ? (
                <span className="muted">{t("admin.item.nothingConfirmed")}</span>
              ) : (
                <span className={styles.mono}>{list(item, "confirmed_fields").join(", ")}</span>
              )}
            </Row>
            <Row label={t("admin.field.missing_fields")}>
              {list(item, "missing_fields").length === 0 ? (
                "—"
              ) : (
                <strong className={styles.bad}>{list(item, "missing_fields").join(", ")}</strong>
              )}
            </Row>
            <Row label={t("admin.field.extraction_method")}>{str(item, "extraction_method") || "—"}</Row>
            <Row label={t("admin.field.translation_pending")}>
              <YesNo value={bool(item, "translation_pending")} />
            </Row>
            <Row label={t("admin.field.consent")}>
              {!consentKnown ? (
                <span className="muted">{t("admin.item.consentUnknown")}</span>
              ) : consentPresent ? (
                <span className={styles.ok}>
                  {t("admin.item.consentPresent")}
                  {consentId && <span className={styles.mono}> ({consentId})</span>}
                </span>
              ) : (
                <strong className={styles.bad}>{t("admin.item.consentMissing")}</strong>
              )}
            </Row>
          </dl>
        </section>
      )}

      {/* --- other single-language fields --- */}
      {scalars.some((k) => has(item, k)) && (
        <section aria-labelledby="fields-scalars">
          <h3 id="fields-scalars">
            {itemType === "trail_report" ? t("admin.item.reportFields") : t("admin.item.otherFields")}
          </h3>
          <dl className={styles.dl}>
            {scalars
              .filter((k) => has(item, k))
              .map((k) => (
                <Row key={k} label={t(`admin.field.${k}`)}>
                  {typeof item[k] === "boolean" ? <YesNo value={item[k] as boolean} /> : fmtValue(lang, item[k])}
                </Row>
              ))}
          </dl>
        </section>
      )}

      {/* --- coordinates --- */}
      {(has(item, "lat") || has(item, "lng")) && (
        <section aria-labelledby="fields-coords">
          <h3 id="fields-coords">{t("admin.item.coordinates")}</h3>
          <dl className={styles.dl}>
            <Row label={t("admin.item.point")}>
              <span className={styles.mono}>
                {fmtCoord(num(item, "lat"))}, {fmtCoord(num(item, "lng"))}
              </span>
            </Row>
            <Row label={t("admin.field.coords_approximate")}>
              {bool(item, "coords_approximate") ? (
                <strong className="badge badge-reviewed">{t("admin.item.approximate")}</strong>
              ) : (
                <span>{t("admin.item.exact")}</span>
              )}
            </Row>
            {has(item, "coords_source") && (
              <Row label={t("admin.field.coords_source")}>{str(item, "coords_source") || "—"}</Row>
            )}
          </dl>
        </section>
      )}

      {/* --- trail geometry --- */}
      {itemType === "trail_segment" && geometry && (
        <section aria-labelledby="fields-geometry">
          <h3 id="fields-geometry">{t("admin.field.geometry")}</h3>
          <p className="muted small" style={{ margin: 0 }}>
            {t("admin.item.geometrySummary", {
              type: geometry.type ?? "—",
              points: geometryPoints === null ? "—" : String(geometryPoints),
            })}
          </p>
        </section>
      )}

      {/* --- provenance of the facts --- */}
      <section aria-labelledby="fields-source">
        <h3 id="fields-source">{t("admin.item.sourceSection")}</h3>
        <dl className={styles.dl}>
          <Row label={t("admin.field.source")}>
            <span className={styles.pre}>{str(item, "source") || "—"}</span>
          </Row>
          {has(item, "sources") && (
            <Row label={t("admin.field.sources")}>
              <SourceList sources={list(item, "sources")} />
            </Row>
          )}
          {factsVerified !== null && (
            <Row label={t("admin.field.facts_verified")}>
              <UnverifiedFlag verified={factsVerified} />
            </Row>
          )}
          {has(item, "verification_note") && (
            <Row label={t("admin.field.verification_note")}>{str(item, "verification_note") || "—"}</Row>
          )}
        </dl>
      </section>

      {/* --- anything the backend added that this screen does not know by name --- */}
      {leftovers.length > 0 && (
        <section aria-labelledby="fields-rest">
          <h3 id="fields-rest">{t("admin.item.remainingFields")}</h3>
          <dl className={styles.dl}>
            {leftovers.map((k) => (
              <Row key={k} label={<span className={styles.mono}>{k}</span>}>
                {fmtValue(lang, item[k])}
              </Row>
            ))}
          </dl>
        </section>
      )}
    </div>
  );
}
