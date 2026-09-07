import type { Metadata, Viewport } from "next";
import "./globals.css";
import { LangProvider } from "@/lib/i18n";
import PrototypeBanner from "@/components/PrototypeBanner";
import Nav from "@/components/Nav";
import Footer from "@/components/Footer";

export const metadata: Metadata = {
  title: "Vrmac Living Heritage — prototype",
  description: "Prototype built for the SMART ERA application, September–October 2026. Sample data.",
  manifest: "/manifest.json",
  icons: { icon: "/icons/icon.svg" },
};

export const viewport: Viewport = { themeColor: "#2f6b4f", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="cnr">
      <body>
        <LangProvider>
          <a href="#main" className="skip-link">
            Skip to content / Preskoči na sadržaj
          </a>
          <PrototypeBanner />
          <Nav />
          <main id="main">{children}</main>
          <Footer />
        </LangProvider>
      </body>
    </html>
  );
}
