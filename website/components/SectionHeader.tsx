import type { ReactNode } from "react";

/**
 * CC-1 Part D1 design token: standardizes the within-page `<h2>` treatment.
 * Before this token existed, pages disagreed on the exact scale/spacing pair
 * (e.g. quant/page.tsx used `text-xl mb-2`, lab/page.tsx used `text-2xl mb-4`
 * for the identical role) -- confirmed by direct inspection, not assumed.
 * `text-2xl mb-4` is kept (the lab/page.tsx variant) as the standard going
 * forward since it reads better against PageHeader's own text-3xl h1.
 */
export default function SectionHeader({
  title,
  description,
}: {
  title: string;
  description?: ReactNode;
}) {
  return (
    <div className="mb-4">
      <h2 className="font-serif text-2xl text-parchment">{title}</h2>
      {description ? <p className="text-muted text-sm mt-1 max-w-2xl">{description}</p> : null}
    </div>
  );
}
