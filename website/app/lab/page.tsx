import PageHeader from "@/components/PageHeader";
import RepairWorkbench from "@/components/RepairWorkbench";
import ResearchAgentPanel from "@/components/ResearchAgentPanel";
import ResearchScoreboard from "@/components/ResearchScoreboard";
import SectionHeader from "@/components/SectionHeader";
import {
  fetchAgentHypotheses,
  fetchAgentPerformance,
  fetchAgentRunSummaries,
  fetchAgentTestResults,
  fetchFailurePatterns,
  fetchGraveyard,
  fetchRepairCandidates,
  fetchStats,
  fetchStrategies,
} from "@/lib/data";
import { buildResearchScoreboard } from "@/lib/researchScoreboard";

export const revalidate = 300;

export const metadata = {
  title: "Research Lab — Vatican",
};

export default async function LabPage() {
  const [
    strategiesExport,
    statsExport,
    graveyard,
    failurePatterns,
    repairCandidates,
    agentHypotheses,
    agentTestResults,
    agentPerformance,
    agentRunSummaries,
  ] = await Promise.all([
    fetchStrategies(),
    fetchStats(),
    fetchGraveyard(),
    fetchFailurePatterns(),
    fetchRepairCandidates(),
    fetchAgentHypotheses(),
    fetchAgentTestResults(),
    fetchAgentPerformance(),
    fetchAgentRunSummaries(),
  ]);

  const rows = buildResearchScoreboard(
    strategiesExport?.strategies ?? [],
    statsExport?.strategies ?? [],
    graveyard ?? [],
    failurePatterns ?? []
  );

  return (
    <div className="flex flex-col gap-10">
      <PageHeader
        title="Research Lab"
        description="Every strategy this project has ever tested — verified, watchlisted, killed, or
          blocked on missing data — plus the active workbench where diagnosed graveyard
          failures get a mechanism-justified second attempt."
      />

      <section>
        <SectionHeader title="Research Scoreboard" />
        <ResearchScoreboard rows={rows} />
      </section>

      <section>
        {/* CC-1 directive item 8a: renamed from "Repair Workbench" -- that name
            now belongs to item 5's real repair_lab.py-driven Repair->Trial
            pipeline (see /factory-loop), and this section is the small,
            hand-curated repair_candidates.json list, matching its own file name. */}
        <SectionHeader title="Repair Candidates" />
        <RepairWorkbench candidates={repairCandidates ?? []} />
      </section>

      <section>
        <SectionHeader title="Research Agent" />
        <ResearchAgentPanel
          hypotheses={agentHypotheses ?? []}
          testResults={agentTestResults ?? []}
          performance={agentPerformance}
          runSummaries={agentRunSummaries ?? []}
        />
      </section>
    </div>
  );
}
