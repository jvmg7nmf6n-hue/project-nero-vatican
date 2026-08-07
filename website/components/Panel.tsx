import type { ReactNode } from "react";

/**
 * CC-1 Part D1 design token: the bordered-card container. Before this token,
 * each bordered block on the site hand-rolled its own combination of
 * `rounded-lg border ... p-6` (pricing tiers used `border-gold/30 bg-ink`,
 * the homepage's graveyard teaser used `border-loss/30 bg-ink`, agents.tsx
 * used yet another variant) -- `tone` below is the same three accent colors
 * already established elsewhere on the site (gold/teal/loss), now expressed
 * as one shared component instead of three independently-drifting copies.
 */
const TONE_BORDER: Record<string, string> = {
  default: "border-muted/25",
  gold: "border-gold/30",
  teal: "border-teal/40",
  loss: "border-loss/30",
};

export default function Panel({
  tone = "default",
  className = "",
  children,
}: {
  tone?: "default" | "gold" | "teal" | "loss";
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={`rounded-lg border ${TONE_BORDER[tone]} bg-ink p-6 ${className}`}>
      {children}
    </div>
  );
}
