"use client";

import { useEffect, useRef, useState } from "react";
import Logo from "./Logo";
import styles from "./SplashScreen.module.css";

const SESSION_STORAGE_KEY = "vatican-splash-seen";
const AUTO_DISMISS_MS = 2800;
const REDUCED_MOTION_DISMISS_MS = 700;
const FADE_OUT_MS = 500;

// Full-viewport intro overlay, shown once per browser session (sessionStorage,
// not localStorage -- a fresh tab/visit should see it again, unlike a
// permanently-dismissed banner). Purely atmospheric: the loading bar and
// scanline texture are CSS animations with no real loading logic tied to them.
export default function SplashScreen() {
  const [visible, setVisible] = useState(true);
  const [dismissing, setDismissing] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reducedMotionRef = useRef(false);

  function dismiss() {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (reducedMotionRef.current) {
      // No fade for a user who has asked for reduced motion -- respect that
      // on manual dismissal too, not just the automatic one.
      setVisible(false);
      return;
    }
    setDismissing(true);
    timerRef.current = setTimeout(() => setVisible(false), FADE_OUT_MS);
  }

  useEffect(() => {
    let alreadySeen = false;
    try {
      alreadySeen = window.sessionStorage.getItem(SESSION_STORAGE_KEY) === "true";
    } catch {
      alreadySeen = false;
    }
    if (alreadySeen) {
      setVisible(false);
      return;
    }

    // Mark the session as seen as soon as we decide to SHOW the splash, not
    // only once it's dismissed -- otherwise a user who navigates away (or a
    // component unmount from fast client-side routing) before the timer fires
    // or a click happens would never get the flag set, and the splash would
    // incorrectly replay on the next page in the same session.
    try {
      window.sessionStorage.setItem(SESSION_STORAGE_KEY, "true");
    } catch {
      // sessionStorage unavailable (private browsing, etc.) -- not fatal, the
      // splash may simply replay next time; never block showing it on this.
    }

    const prefersReducedMotion =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    reducedMotionRef.current = prefersReducedMotion;
    setReducedMotion(prefersReducedMotion);

    timerRef.current = setTimeout(
      dismiss,
      prefersReducedMotion ? REDUCED_MOTION_DISMISS_MS : AUTO_DISMISS_MS
    );

    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
      }
    };
    // Mount-only: dismiss reads mutable refs/setters, never stale props or state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!visible) {
    return null;
  }

  return (
    <div
      data-testid="splash-screen"
      role="button"
      tabIndex={0}
      aria-label="Skip intro"
      onClick={dismiss}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          dismiss();
        }
      }}
      className={`fixed inset-0 z-50 flex cursor-pointer items-center justify-center bg-ink transition-opacity duration-500 ${
        dismissing ? "opacity-0" : "opacity-100"
      } ${reducedMotion ? "" : styles.scanlines}`}
    >
      <div className="flex flex-col items-center px-4 text-center">
        <div className={`relative ${reducedMotion ? "" : styles.reticle}`}>
          {reducedMotion ? null : (
            <>
              <span className={`${styles.corner} ${styles.cornerTopLeft}`} aria-hidden="true" />
              <span className={`${styles.corner} ${styles.cornerTopRight}`} aria-hidden="true" />
              <span className={`${styles.corner} ${styles.cornerBottomLeft}`} aria-hidden="true" />
              <span className={`${styles.corner} ${styles.cornerBottomRight}`} aria-hidden="true" />
            </>
          )}
          <Logo
            animated={!reducedMotion}
            className="h-[160px] w-[160px] sm:h-[220px] sm:w-[220px] md:h-[280px] md:w-[280px]"
          />
        </div>

        <div className="mt-6 font-serif text-3xl tracking-[0.3em] text-parchment sm:text-4xl md:text-5xl">
          VATICAN
        </div>

        <div
          data-testid="splash-loading-bar"
          className="mt-6 h-[2px] w-40 overflow-hidden rounded-full bg-muted/20 sm:w-56"
        >
          <div className={`h-full bg-gold ${reducedMotion ? "w-full" : styles.loadingBarFill}`} />
        </div>

        <p className="mt-6 text-sm tracking-wide text-muted">
          Every signal. Every loss. On the record.
        </p>
      </div>
    </div>
  );
}
