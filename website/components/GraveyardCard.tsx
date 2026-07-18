import type { GraveyardEntry } from "@/lib/types";

const REPO_BLOB_BASE =
  "https://github.com/jvmg7nmf6n-hue/project-nero-vatican/blob/main";

export default function GraveyardCard({ entry }: { entry: GraveyardEntry }) {
  return (
    <div className="rounded-lg border border-loss/30 bg-ink p-4">
      <h3 className="font-serif text-lg text-parchment">{entry.name}</h3>
      <p className="text-muted text-sm">{entry.family}</p>
      <p className="mt-2 text-sm text-parchment">
        <span className="text-muted">Tested: </span>
        {entry.what_was_tested}
      </p>
      <p className="mt-2 text-sm text-loss">{entry.why_it_died}</p>
      <a
        href={`${REPO_BLOB_BASE}/${entry.source_doc}`}
        className="mt-3 inline-block text-xs text-teal underline"
        target="_blank"
        rel="noreferrer"
      >
        Source report
      </a>
    </div>
  );
}
