"use client";

import { useEffect, useRef, useState } from "react";

const DURATION_MS = 1200;
const STEP_MS = 30;

// ROOT CAUSE OF THE HOMEPAGE-LOOKS-BROKEN BUG (see docs/investigations/
// live_strategy_backtest_and_universe_expansion_report.md's follow-up):
// this hook used to initialize its OWN state to 0 for any positive target
// (`useState(target > 0 ? 0 : target)`) and only set the real value inside
// a useEffect, which never runs during server-side rendering and hasn't
// run yet on the very first client paint either. That means the server-
// rendered HTML -- what any crawler, social-media unfurl, screenshot tool,
// or a real visitor whose JS hasn't finished hydrating yet actually sees --
// ALWAYS showed a placeholder 0 for Configs tested / Live signals /
// Verified configs / Tracking days, regardless of the real (large, correct)
// numbers underneath. The data was never wrong; the first paint was always
// lying about it. A static sublabel like "4 distinct families" (plain text,
// never routed through this hook) rendered correctly at the same moment,
// which is exactly the contradiction reported.
//
// FIX: render the real `target` immediately on the very first render (SSR
// and first client paint both show the correct number, never a fake 0).
// The count-up animation is preserved for a genuine value CHANGE after
// mount (e.g. a future live-updating dashboard) via `hasAnimatedInitialMount`
// -- only the initial mount skips animating from zero.
export function useCountUp(target: number): number {
  const [value, setValue] = useState(target);
  const hasMountedRef = useRef(false);

  useEffect(() => {
    if (!hasMountedRef.current) {
      hasMountedRef.current = true;
      setValue(target);
      return;
    }

    if (!Number.isFinite(target) || target <= 0) {
      setValue(target);
      return;
    }

    setValue(0);
    const steps = Math.max(1, Math.round(DURATION_MS / STEP_MS));
    let currentStep = 0;

    const id = setInterval(() => {
      currentStep += 1;
      const progress = Math.min(1, currentStep / steps);
      setValue(Math.round(target * progress));
      if (currentStep >= steps) {
        clearInterval(id);
      }
    }, STEP_MS);

    return () => clearInterval(id);
  }, [target]);

  return value;
}
