import Link from "next/link";
import GraveyardCard from "@/components/GraveyardCard";
import LedgerTable from "@/components/LedgerTable";
import StatsStrip from "@/components/StatsStrip";
import VerdictGrid from "@/components/VerdictGrid";
import {
  fetchGraveyard,
  fetchLedgerRecent,
  fetchSiteSummary,
  fetchStrategies,
} from "@/lib/data";

export const revalidate = 300;

export default async function HomePage() {
  const [ledger, strategies, summary, graveyard] = await Promise.all([
    fetchLedgerRecent(),
    fetchStrategies(),
    fetchSiteSummary(),
    fetchGraveyard(),
  ]);

  const rows = ledger?.rows ?? [];
  const roster = strategies?.strategies ?? [];
  const graveyardEntries = graveyard ?? [];

  return (
    <div className="flex flex-col gap-16">
      <section className="text-center py-10">
        <h1 className="font-serif text-4xl sm:text-5xl text-parchment">
          Every signal. Every loss. On the record.
        </h1>
        <p className="mt-4 text-muted max-w-2xl mx-auto">
          Vatican is a paper-trading research platform for gold and crypto. Every
          signal our strategies generate — and every loss they take — is logged to a
          public Truth Ledger. Nothing is hidden after the fact.
        </p>
        <div className="mt-6 flex justify-center gap-4">
          <a
            href="#ledger"
            className="rounded-md bg-gold px-5 py-2 text-ink font-medium hover:opacity-90"
          >
            View the live ledger
          </a>
          <Link
            href="/methodology"
            className="rounded-md border border-gold/50 px-5 py-2 text-parchment hover:bg-gold/10"
          >
            How we test
          </Link>
        </div>
      </section>

      <section>
        <StatsStrip summary={summary} />
      </section>

      <section>
        <h2 className="font-serif text-2xl text-parchment mb-4">Live council verdicts</h2>
        <VerdictGrid strategies={roster} recentRows={rows} />
      </section>

      <section id="ledger">
        <h2 className="font-serif text-2xl text-parchment mb-4">Truth Ledger</h2>
        <LedgerTable rows={rows} trackingSince={summary?.tracking_since} />
      </section>

      <section>
        <div className="rounded-lg border border-loss/30 bg-ink p-6 flex items-center justify-between gap-4">
          <div>
            <h2 className="font-serif text-xl text-parchment">The graveyard</h2>
            <p className="text-muted text-sm mt-1">
              {graveyardEntries.length} strategy famil
              {graveyardEntries.length === 1 ? "y" : "ies"} killed by the evidence so
              far.
            </p>
          </div>
          <Link
            href="/graveyard"
            className="rounded-md border border-gold/50 px-4 py-2 text-sm text-parchment hover:bg-gold/10 whitespace-nowrap"
          >
            View graveyard
          </Link>
        </div>
      </section>
    </div>
  );
}
