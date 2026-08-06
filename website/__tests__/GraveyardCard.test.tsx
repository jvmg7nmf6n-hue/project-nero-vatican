import { render, screen } from "@testing-library/react";
import GraveyardCard from "@/components/GraveyardCard";
import type { GraveyardEntry } from "@/lib/types";

function makeEntry(overrides: Partial<GraveyardEntry> = {}): GraveyardEntry {
  return {
    name: "FVG_REVERSION",
    family: "Fair Value Gap",
    what_was_tested: "gap-touch fade",
    why_it_died: "no edge over random entry timing",
    source_doc: "docs/fvg_reversion_report.md",
    ...overrides,
  };
}

describe("GraveyardCard source_doc rendering", () => {
  it("links to the GitHub blob for a real docs/*.md source_doc", () => {
    render(<GraveyardCard entry={makeEntry()} />);
    const link = screen.getByRole("link", { name: "Source report" });
    expect(link).toHaveAttribute(
      "href",
      "https://github.com/jvmg7nmf6n-hue/project-nero-vatican/blob/main/docs/fvg_reversion_report.md"
    );
  });

  it("2026-08-06 incident regression: renders plain text, not a broken GitHub link, for a no-written-report source_doc", () => {
    // Real incident: an LLM-drafted distillation entry's source_doc was
    // free text ("eve-origin graveyard review: ..."), and this component
    // unconditionally built a GitHub blob URL from it -- a nonsense link
    // on the live public graveyard page.
    render(
      <GraveyardCard
        entry={makeEntry({
          source_doc:
            "no written report -- LLM-drafted synthesis of 4 DIED hypotheses in the 'Range Mean Reversion' family (A, B, C, D)",
        })}
      />
    );
    expect(screen.queryByRole("link", { name: "Source report" })).not.toBeInTheDocument();
    expect(screen.getByText(/no written report --/)).toBeInTheDocument();
  });
});
