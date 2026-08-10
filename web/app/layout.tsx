import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "Lusmaker — routes op gesprek",
  description: "Bouw, bewaar en download persoonlijke fiets- en traillussen.",
  applicationName: "Lusmaker",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Ommeke",
  },
  icons: {
    icon: "/favicon.svg",
    apple: "/apple-touch-icon.png",
  },
};

export const viewport: Viewport = {
  themeColor: "#183f30",
  colorScheme: "light",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="nl">
      <body>{children}</body>
    </html>
  );
}
