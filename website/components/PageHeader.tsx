import type { ReactNode } from "react";

/**
 * CC-1 Part D1 design token: every page's top-of-page title + description used
 * to hand-roll `font-serif text-3xl text-parchment` / `text-muted mt-2 max-w-2xl`
 * independently (confirmed by direct inspection across all 9 pages) -- this is
 * the single source of truth for that pairing, so the type scale and spacing
 * beneath a page title can never silently drift page to page again.
 */
export default function PageHeader({
  eyebrow,
  title,
  description,
}: {
  eyebrow?: string;
  title: string;
  description?: ReactNode;
}) {
  return (
    <div>
      {eyebrow ? (
        <div className="text-xs uppercase tracking-[0.25em] text-gold/80 mb-2">{eyebrow}</div>
      ) : null}
      <h1 className="font-serif text-3xl text-parchment">{title}</h1>
      {description ? <p className="text-muted mt-2 max-w-2xl">{description}</p> : null}
    </div>
  );
}
