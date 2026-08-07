import type { Metadata } from "next";
import Link from "next/link";
import Logo from "@/components/Logo";
import "./globals.css";

export const metadata: Metadata = {
  title: "Vatican — The Book of Records. Every signal. Every loss.",
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
              <Link href="/heatmap" className="hover:text-parchment">
                Heatmap
              </Link>
              <Link href="/signals" className="hover:text-parchment">
                Signals
              </Link>
              <Link href="/quant" className="hover:text-parchment">
                Quant
              </Link>
              <Link href="/graveyard" className="hover:text-parchment">
                Graveyard
              </Link>
              <Link href="/factory-loop" className="hover:text-parchment">
                Factory Loop
              </Link>
              <Link href="/agents" className="hover:text-parchment">
                Agents
              </Link>
              <Link href="/lab" className="hover:text-parchment">
                Lab
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
          <div className="mx-auto max-w-5xl px-4 text-xs text-muted flex flex-wrap gap-x-3 gap-y-1">
            <span>Paper-trading research only. No financial advice. No guaranteed returns.</span>
            <span>
              Charts by{" "}
              <a
                href="https://github.com/tradingview/lightweight-charts"
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-parchment"
              >
                TradingView Lightweight Charts
              </a>{" "}
              (Apache-2.0).
            </span>
          </div>
        </footer>
      </body>
    </html>
  );
}
