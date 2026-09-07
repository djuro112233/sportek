"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useT } from "@/lib/i18n";
import LangToggle from "./LangToggle";

const LINKS = [
  { href: "/", key: "nav.home" },
  { href: "/visitor", key: "nav.visitor" },
  { href: "/host", key: "nav.host" },
  { href: "/validate", key: "nav.validate" },
  { href: "/dashboard", key: "nav.dashboard" },
];

export default function Nav() {
  const t = useT();
  const path = usePathname();
  return (
    <header className="nav">
      <Link href="/" className="brand">
        {t("app.name")}
      </Link>
      <nav aria-label="Main">
        <ul>
          {LINKS.map((l) => {
            const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
            return (
              <li key={l.href}>
                <Link href={l.href} aria-current={active ? "page" : undefined}>
                  {t(l.key)}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <LangToggle />
    </header>
  );
}
