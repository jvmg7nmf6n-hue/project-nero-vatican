import GraveyardCard from "@/components/GraveyardCard";
import PageHeader from "@/components/PageHeader";
import { fetchGraveyard } from "@/lib/data";

export const revalidate = 300;

export default async function GraveyardPage() {
  const graveyard = await fetchGraveyard();

  return (
    <div>
      <PageHeader
        eyebrow="No quiet failures"
        title="The Graveyard"
        description="Every strategy family we tested and killed on the evidence, with the report
        it came from. We don't quietly drop failed research — it stays here."
      />

      {graveyard === null ? (
        <p className="text-muted mt-8">
          The graveyard is temporarily unavailable. Please check back shortly.
        </p>
      ) : graveyard.length === 0 ? (
        <p className="text-muted mt-8">Nothing has been retired yet.</p>
      ) : (
        <div className="mt-8 grid gap-4 sm:grid-cols-2">
          {graveyard.map((entry) => (
            <GraveyardCard key={`${entry.name}-${entry.family}`} entry={entry} />
          ))}
        </div>
      )}
    </div>
  );
}
