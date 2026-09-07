"use client";
import { useT } from "@/lib/i18n";

export default function PrototypeBanner() {
  const t = useT();
  return (
    <div className="banner" role="note" aria-label="Prototype notice">
      {t("app.prototype")}
    </div>
  );
}
