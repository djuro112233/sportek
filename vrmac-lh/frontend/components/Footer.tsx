"use client";
import { useT } from "@/lib/i18n";

export default function Footer() {
  const t = useT();
  return (
    <footer>
      <p>{t("app.prototype")}</p>
      <p>{t("footer.noPersonalData")}</p>
      <p>{t("footer.license")}</p>
    </footer>
  );
}
