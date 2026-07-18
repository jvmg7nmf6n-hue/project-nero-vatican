import type { Metadata } from "next";
import Link from "next/link";
import Logo from "@/components/Logo";
import "./globals.css";

export const metadata: Metadata = {
  title: "Vatican — Every signal. Every loss. On the record.",
  description:
    "Vatican is a paper-trading research platform for gold and crypto. Every signal and every loss is logged to a public Truth Ledger.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen flex flex-col font-sans">
        <header className="border-b border-gold/20">
          <div className="mx-auto max-w-5xl flex items-center justify-between px-4 py-4">
            <Link href="/" className="flex items-center gap-3">
              <Logo className="h-9 w-9" />
              <span className="font-serif tracking-[0.2em] text-parchment">VATICAN</span>
            </Link>
            <nav className="flex gap-6 text-sm text-muted">
              <Link href="/#ledger" className="hover:text-parchment">
                Ledger
              </Link>
              <Link href="/graveyard" className="hover:text-parchment">
                Graveyard
              </Link>
              <Link href="/methodology" className="hover:text-parchment">
                Methodology
              </Link>
              <Link href="/pricing" className="hover:text-parchment">
                Pricing
              </Link>
            </nav>
          </div>
        </header>

        <main className="flex-1 mx-auto w-full max-w-5xl px-4 py-10">{children}</main>

        <footer className="border-t border-gold/20 py-6">
          <div className="mx-auto max-w-5xl px-4 text-xs text-muted">
            Paper-trading research only. No financial advice. No guaranteed returns.
          </div>
        </footer>
      </body>
    </html>
  );
}
