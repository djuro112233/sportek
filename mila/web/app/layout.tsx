import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';

import './globals.css';

export const metadata: Metadata = {
  title: 'MILA',
  description:
    'Voice-first information and referral assistant for reproductive and maternal health. Information and referral, never diagnosis.',
  applicationName: 'MILA',
  manifest: '/manifest.json',
  icons: { icon: '/icon.svg' },
  robots: { index: false, follow: false },
  formatDetection: { telephone: true, email: false, address: false },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: '#1d4ed8',
  colorScheme: 'light',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  // <html lang> is updated on the client once the user's language is known (see app/page.tsx).
  return (
    <html lang="sr">
      <body>{children}</body>
    </html>
  );
}
