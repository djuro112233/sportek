"use client";
import { LANGS, useLang } from "@/lib/i18n";

export default function LangToggle() {
  const { lang, setLang, t } = useLang();
  return (
    <div className="lang-toggle" role="group" aria-label={t("lang.switch")}>
      {LANGS.map((l) => (
        <button
          key={l}
          type="button"
          className={`btn btn-small ${l === lang ? "btn-primary" : "btn-secondary"}`}
          aria-pressed={l === lang}
          onClick={() => setLang(l)}
          lang={l}
        >
          {t(`lang.${l}`)}
        </button>
      ))}
    </div>
  );
}
