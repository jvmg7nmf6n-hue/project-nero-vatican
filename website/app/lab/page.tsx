import RepairWorkbench from "@/components/RepairWorkbench";
import ResearchScoreboard from "@/components/ResearchScoreboard";
import { fetchFailurePatterns, fetchGraveyard, fetchRepairCandidates, fetchStats, fetchStrategies } from "@/lib/data";
import { buildResearchScoreboard } from "@/lib/researchScoreboard";

export const revalidate = 300;

export const metadata = {
  title: "Research Lab — Vatican",
};

export default async function LabPage() {
  const [strategiesExport, statsExport, graveyard, failurePatterns, repairCandidates] = await Promise.all([
    fetchStrategies(),
    fetchStats(),
    fetchGraveyard(),
    fetchFailurePatterns(),
    fetchRepairCandidates(),
  ]);

  const rows = buildResearchScoreboard(
    strategiesExport?.strategies ?? [],
    statsExport?.strategies ?? [],
    graveyard ?? [],
    failurePatterns ?? []
  );

  return (
    <div className="flex flex-col gap-10">
      <div>
        <h1 className="font-serif text-3xl text-parchment">Research Lab</h1>
        <p className="text-muted mt-2 max-w-2xl">
          Every strategy this project has ever tested — verified, watchlisted, killed, or
          blocked on missing data — plus the active workbench where diagnosed graveyard
          failures get a mechanism-justified second attempt.
        </p>
      </div>

      <section>
        <h2 className="font-serif text-2xl text-parchment mb-4">Research Scoreboard</h2>
        <ResearchScoreboard rows={rows} />
      </section>

      <section>
        <h2 className="font-serif text-2xl text-parchment mb-4">Repair Workbench</h2>
        <RepairWorkbench candidates={repairCandidates ?? []} />
      </section>
    </div>
  );
}
