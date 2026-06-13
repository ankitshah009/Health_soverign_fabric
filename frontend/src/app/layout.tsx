import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import Sidebar from "@/components/Sidebar";
import ChatFab from "@/components/ChatFab";

const sovereignSans = localFont({
  src: "./fonts/GeistSansLatin.woff2",
  variable: "--font-sans",
  weight: "100 900",
  display: "swap",
});

const sovereignMono = localFont({
  src: "./fonts/GeistMonoLatin.woff2",
  variable: "--font-mono",
  weight: "100 900",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Sovereign | Your AI Patient Advocate",
  description: "Sovereign finds medical-bill overcharges, flags illegal balance-billing, and fights insurance denials — with a provable conscience.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${sovereignSans.variable} ${sovereignMono.variable} antialiased`}
      >
        <Sidebar />
        <main className="min-h-screen transition-[margin-left] duration-300" style={{ marginLeft: "var(--sidebar-width, 64px)" }}>
          <div className="p-6 lg:p-8 max-w-[1440px]">{children}</div>
        </main>
        <ChatFab />
      </body>
    </html>
  );
}
