import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

import { AppShell } from "@/components/shell/app-shell";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-code" });

export const metadata: Metadata = {
  title: "Kairos | Data Platform Intelligence",
  description: "A synthetic knowledge layer over your data platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // Light-first. The platform screens are dense and read better on a
  // near-white canvas, matching the tooling they sit alongside.
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`}>
      <body className={`${inter.className} bg-canvas text-ink antialiased`}>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
