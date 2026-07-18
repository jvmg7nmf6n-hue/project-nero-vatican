import GraveyardCard from "@/components/GraveyardCard";
import { fetchGraveyard } from "@/lib/data";

export const revalidate = 300;

export default async function GraveyardPage() {
  const graveyard = await fetchGraveyard();

  return (
    <div>
      <h1 className="font-serif text-3xl text-parchment">The Graveyard</h1>
      <p className="text-muted mt-2 max-w-2xl">
        Every strategy family we tested and killed on the evidence, with the report
        it came from. We don&apos;t quietly drop failed research — it stays here.
      </p>

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
