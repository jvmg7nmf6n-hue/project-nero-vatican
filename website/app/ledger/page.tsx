import LedgerTable from "@/components/LedgerTable";
import PageHeader from "@/components/PageHeader";
import { fetchLedgerFull, fetchSiteSummary } from "@/lib/data";

export const revalidate = 300;

// CC-1 overnight directive, Part 5: relocated off the homepage onto its own
// page so it can show the FULL real ledger (fetchLedgerFull) rather than the
// homepage's recent-only teaser (fetchLedgerRecent, still used there for the
// Markets Overview section) -- "briefing all trades" and this site's own
// "Every signal. Every loss." tagline both call for the complete history,
// not a duplicate of the abbreviated homepage view.
export default async function LedgerPage() {
  const [ledger, summary] = await Promise.all([fetchLedgerFull(), fetchSiteSummary()]);
  const rows = ledger?.rows ?? [];

  return (
    <div>
      <PageHeader
        eyebrow="Every signal. Every loss."
        title="Truth Ledger"
        description="Every real signal this system has logged, in full -- entries, exits, and
        the losses that stay on the record. Nothing here is curated or trimmed."
      />

      <div className="mt-8">
        <LedgerTable rows={rows} trackingSince={summary?.tracking_since} />
      </div>
    </div>
  );
}
