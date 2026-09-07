"use client";
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import enCommon from "@/locales/en/common.json";
import enHost from "@/locales/en/host.json";
import enVisitor from "@/locales/en/visitor.json";
import enAdmin from "@/locales/en/admin.json";
import cnrCommon from "@/locales/cnr/common.json";
import cnrHost from "@/locales/cnr/host.json";
import cnrVisitor from "@/locales/cnr/visitor.json";
import cnrAdmin from "@/locales/cnr/admin.json";

export type Lang = "cnr" | "en";
export const LANGS: Lang[] = ["cnr", "en"];

type Dict = Record<string, string>;
const dict: Record<Lang, Dict> = {
  en: { ...enCommon, ...enHost, ...enVisitor, ...enAdmin } as Dict,
  cnr: { ...cnrCommon, ...cnrHost, ...cnrVisitor, ...cnrAdmin } as Dict,
};

export type Translate = (key: string, vars?: Record<string, string | number>) => string;

interface LangContextValue {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: Translate;
}

const LangContext = createContext<LangContextValue>({
  lang: "cnr",
  setLang: () => undefined,
  t: (k) => k,
});

const STORAGE_KEY = "vrmac.lang";

export function LangProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("cnr");

  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved === "en" || saved === "cnr") setLangState(saved);
    } catch {
      /* storage unavailable */
    }
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* ignore */
    }
  }, []);

  const t = useCallback<Translate>(
    (key, vars) => {
      let s = dict[lang][key] ?? dict.en[key] ?? key;
      if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(String(v));
      return s;
    },
    [lang],
  );

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

export function useLang() {
  return useContext(LangContext);
}

export function useT(): Translate {
  return useContext(LangContext).t;
}

/** Pick the field for the active language, falling back to the other one. */
export function pick(lang: Lang, local: string | null | undefined, en: string | null | undefined): string {
  return lang === "cnr" ? local || en || "" : en || local || "";
}
