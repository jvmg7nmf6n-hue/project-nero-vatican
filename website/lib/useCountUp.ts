"use client";

import { useEffect, useState } from "react";

const DURATION_MS = 1200;
const STEP_MS = 30;

// Ticks 0 -> target over DURATION_MS using setInterval (not
// requestAnimationFrame) specifically so it's deterministic under
// jest.useFakeTimers() in tests. Non-positive or non-finite targets (e.g.
// null stats coerced to 0, or an unresolved days-since calculation) render
// immediately with no animation.
export function useCountUp(target: number): number {
  const [value, setValue] = useState(target > 0 ? 0 : target);

  useEffect(() => {
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
