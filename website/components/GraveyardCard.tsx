import type { GraveyardEntry } from "@/lib/types";

const REPO_BLOB_BASE =
  "https://github.com/jvmg7nmf6n-hue/project-nero-vatican/blob/main";

// Most source_doc values are a real docs/*.md path (hand-curated entries,
// safe to link to GitHub). LLM-drafted distillation entries never have a
// written report -- graveyard_distillation.py's _no_report_source_doc gives
// them an honest "no written report -- ..." sentinel instead of a fake
// path. Linking THAT to REPO_BLOB_BASE would produce a broken/nonsense
// GitHub URL, so it renders as plain text instead.
const DOC_PATH_PATTERN = /^docs\/.+\.md$/;

export default function GraveyardCard({ entry }: { entry: GraveyardEntry }) {
  const hasSourceDoc = DOC_PATH_PATTERN.test(entry.source_doc);
  return (
    <div className="rounded-lg border border-loss/30 bg-ink p-4">
      <h3 className="font-serif text-lg text-parchment">{entry.name}</h3>
      <p className="text-muted text-sm">{entry.family}</p>
      <p className="mt-2 text-sm text-parchment">
        <span className="text-muted">Tested: </span>
        {entry.what_was_tested}
      </p>
      <p className="mt-2 text-sm text-loss">{entry.why_it_died}</p>
      {hasSourceDoc ? (
        <a
          href={`${REPO_BLOB_BASE}/${entry.source_doc}`}
          className="mt-3 inline-block text-xs text-teal underline"
          target="_blank"
          rel="noreferrer"
        >
          Source report
        </a>
      ) : (
        <p className="mt-3 text-xs text-muted">{entry.source_doc}</p>
      )}
    </div>
  );
}
