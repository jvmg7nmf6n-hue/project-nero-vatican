"use client";

// Wise Man -- site-wide assistant widget (CC-1 directive v3, Sec 7, 8.6, 9).
//
// MOUNT: rendered once from app/layout.tsx, so it appears on every route
// automatically (Sec 8.6) -- see __tests__/wiseManLayoutMount.test.tsx for
// the enumeration test proving this, and why a future new page can't
// silently miss it.
//
// LAYOUT COLLISION (Sec 1.7 / GATE A finding): the existing per-strategy
// ChatBot occupies bottom-right (closed: bottom-6 right-6; open:
// bottom-24 right-6) on /strategy/[id] pages ONLY. CHOICE, my call per the
// GATE B kickoff decision: Wise Man defaults to BOTTOM-LEFT, site-wide,
// unconditionally -- not just on strategy pages. Reasoning: (1) it
// guarantees zero collision with ChatBot on the one route where both
// widgets coexist, with no per-route conditional positioning logic to keep
// in sync as routes change; (2) one consistent position everywhere is a
// simpler mental model for a returning visitor than "usually bottom-right,
// except here it's bottom-left"; (3) it reads as Wise Man's own distinct
// "home" on the page rather than a fallback squeezed in around ChatBot.
//
// ICON (Sec 9.1): the real navy-gold seal SVG asset has not been supplied
// (confirmed still open at GATE B kickoff). This is a CLEARLY-MARKED
// PLACEHOLDER built from the site's own existing ink/gold Tailwind tokens
// (tailwind.config.ts), with the ring and needle as separately addressable
// SVG groups (stable ids #wise-man-ring / #wise-man-needle) so the real
// asset can drop in later without changing the animation wiring -- Sec
// 9.1's own structural requirement.

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { resolvePathToPageContext } from "@/lib/wiseMan/pathToPageContext";
import {
  PERSISTENT_DISCLAIMER_EN,
  PERSISTENT_DISCLAIMER_UR,
  ESCALATED_DISCLAIMER_EN,
  ESCALATED_DISCLAIMER_UR,
} from "@/lib/wiseMan/disclaimer";

const SESSION_STORAGE_KEY = "wise-man-history-v1";
const MAX_MESSAGE_CHARS = 2000;

interface ChatTurn {
  role: "user" | "assistant";
  text: string;
  isEscalatedDisclaimer?: boolean;
}

interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: { results: { [index: number]: { [index: number]: { transcript: string } } }; }) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

function getSpeechRecognitionCtor(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

function speechSynthesisSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

export default function WiseMan() {
  const pathname = usePathname();
  const pageContext = useMemo(() => resolvePathToPageContext(pathname ?? "/"), [pathname]);

  const [isOpen, setIsOpen] = useState(false);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [voiceSupported, setVoiceSupported] = useState(false);
  const [ttsSupported, setTtsSupported] = useState(false);
  const [ttsEnabled, setTtsEnabled] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");

  const inputRef = useRef<HTMLTextAreaElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const liveRegionId = useId();
  const dialogTitleId = useId();

  useEffect(() => {
    setVoiceSupported(getSpeechRecognitionCtor() !== null);
    setTtsSupported(speechSynthesisSupported());
    setReducedMotion(prefersReducedMotion());
    try {
      const saved = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
      if (saved) setTurns(JSON.parse(saved));
    } catch {
      // sessionStorage unavailable (private mode, quota, etc.) -- history just won't persist.
    }
  }, []);

  useEffect(() => {
    try {
      window.sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(turns));
    } catch {
      // Non-fatal -- see above.
    }
  }, [turns]);

  useEffect(() => {
    if (isOpen) inputRef.current?.focus();
  }, [isOpen]);

  const closeOnEscape = useCallback((e: KeyboardEvent) => {
    if (e.key === "Escape") setIsOpen(false);
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [isOpen, closeOnEscape]);

  const speak = useCallback(
    (text: string) => {
      if (!ttsEnabled || !ttsSupported) return;
      try {
        const utterance = new SpeechSynthesisUtterance(text);
        window.speechSynthesis.speak(utterance);
      } catch {
        // Non-fatal -- speech synthesis failing should never block the text reply.
      }
    },
    [ttsEnabled, ttsSupported],
  );

  const sendMessage = useCallback(
    async (rawText: string) => {
      const text = rawText.trim();
      if (!text || text.length > MAX_MESSAGE_CHARS || isSending) return;

      const userTurn: ChatTurn = { role: "user", text };
      const nextTurns = [...turns, userTurn];
      setTurns(nextTurns);
      setInput("");
      setIsSending(true);
      setStatusMessage("Wise Man is thinking...");

      try {
        const response = await fetch("/api/wise-man", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({
            message: text,
            pageContext,
            history: turns.map((t) => ({ role: t.role, text: t.text })),
          }),
        });
        const payload = await response.json();
        if (payload.error) {
          const isBlocked = response.status === 200; // guardrail refusals return 200 with an error body
          const replyText: string = payload.error.en;
          setTurns((prev) => [...prev, { role: "assistant", text: replyText, isEscalatedDisclaimer: isBlocked }]);
          setStatusMessage(replyText);
          speak(replyText);
        } else {
          setTurns((prev) => [...prev, { role: "assistant", text: payload.reply }]);
          setStatusMessage(payload.reply);
          speak(payload.reply);
        }
      } catch {
        const fallback = "Something went wrong. Please try again.";
        setTurns((prev) => [...prev, { role: "assistant", text: fallback }]);
        setStatusMessage(fallback);
      } finally {
        setIsSending(false);
      }
    },
    [turns, pageContext, isSending, speak],
  );

  const toggleListening = useCallback(() => {
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) return;
    if (isListening) {
      recognitionRef.current?.stop();
      setIsListening(false);
      return;
    }
    const recognition = new Ctor();
    recognition.lang = "en-US";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onresult = (event) => {
      // Transcribed text enters the SAME sendMessage() function typed text
      // uses -- no separate code path (Sec 4.1.2 / Sec 7's own requirement).
      const transcript = event.results[0]?.[0]?.transcript;
      if (transcript) void sendMessage(transcript);
    };
    recognition.onerror = () => setIsListening(false);
    recognition.onend = () => setIsListening(false);
    recognitionRef.current = recognition;
    recognition.start();
    setIsListening(true);
  }, [isListening, sendMessage]);

  const disclaimer = useMemo(
    () => ({ en: PERSISTENT_DISCLAIMER_EN, ur: PERSISTENT_DISCLAIMER_UR }),
    [],
  );
  const showEscalatedDisclaimer = turns.length > 0 && turns[turns.length - 1].isEscalatedDisclaimer === true;

  return (
    <div className="fixed bottom-6 left-6 z-40" data-testid="wise-man-widget">
      {!isOpen && (
        <button
          type="button"
          aria-label="Open Wise Man, the site assistant"
          onClick={() => setIsOpen(true)}
          className="h-14 w-14 rounded-full bg-ink border border-gold/60 shadow-lg flex items-center justify-center focus:outline-none focus-visible:ring-2 focus-visible:ring-gold"
        >
          <WiseManIcon reducedMotion={reducedMotion} size={36} />
        </button>
      )}

      {isOpen && (
        <div
          ref={panelRef}
          role="dialog"
          aria-modal="false"
          aria-labelledby={dialogTitleId}
          className="w-96 h-[36rem] rounded-lg border border-gold/40 bg-ink flex flex-col shadow-2xl"
        >
          <div className="flex items-center justify-between px-4 py-3 border-b border-gold/20">
            <div className="flex items-center gap-2">
              <WiseManIcon reducedMotion={reducedMotion} size={24} />
              <span id={dialogTitleId} className="font-serif text-parchment text-sm tracking-wide">
                Wise Man
              </span>
            </div>
            <div className="flex items-center gap-2">
              {ttsSupported && (
                <button
                  type="button"
                  aria-label={ttsEnabled ? "Disable spoken replies" : "Enable spoken replies"}
                  aria-pressed={ttsEnabled}
                  onClick={() => setTtsEnabled((v) => !v)}
                  className="text-xs text-muted hover:text-parchment focus-visible:ring-2 focus-visible:ring-gold rounded"
                >
                  {ttsEnabled ? "🔊" : "🔈"}
                </button>
              )}
              <button
                type="button"
                aria-label="Close Wise Man"
                onClick={() => setIsOpen(false)}
                className="text-muted hover:text-parchment focus-visible:ring-2 focus-visible:ring-gold rounded"
              >
                ✕
              </button>
            </div>
          </div>

          <div className="px-4 py-2 text-[11px] text-muted border-b border-gold/10">
            <div>{disclaimer.en}</div>
            <div dir="auto">{disclaimer.ur}</div>
          </div>

          {showEscalatedDisclaimer && (
            <div
              role="alert"
              className="mx-4 mt-2 rounded border border-loss/50 bg-loss/10 px-3 py-2 text-xs text-parchment"
            >
              <div>{ESCALATED_DISCLAIMER_EN}</div>
              <div dir="auto">{ESCALATED_DISCLAIMER_UR}</div>
            </div>
          )}

          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3" aria-live="off">
            {turns.length === 0 && (
              <p className="text-sm text-muted">
                Ask about methodology, definitions, or what a page&apos;s numbers mean.
              </p>
            )}
            {turns.map((turn, i) => (
              <div key={i} className={turn.role === "user" ? "text-right" : "text-left"}>
                <div
                  className={
                    "inline-block rounded-lg px-3 py-2 text-sm max-w-[85%] " +
                    (turn.role === "user"
                      ? "bg-gold/20 text-parchment"
                      : turn.isEscalatedDisclaimer
                        ? "bg-loss/20 text-parchment border border-loss/40"
                        : "bg-white/5 text-parchment")
                  }
                >
                  {turn.text}
                </div>
              </div>
            ))}
          </div>

          {/* ARIA live region: announces the latest reply to screen readers.
              /api/wise-man responds as one complete JSON payload, not a
              token stream (the outbound guardrail check must see the FULL
              response before it can decide to release it, per Sec 4.1.1 --
              true token streaming would conflict with that), so this
              announces the complete reply once, not incrementally. */}
          <div id={liveRegionId} aria-live="polite" className="sr-only">
            {statusMessage}
          </div>

          <form
            className="flex items-end gap-2 px-4 py-3 border-t border-gold/20"
            onSubmit={(e) => {
              e.preventDefault();
              void sendMessage(input);
            }}
          >
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void sendMessage(input);
                }
              }}
              maxLength={MAX_MESSAGE_CHARS}
              rows={2}
              aria-label="Message Wise Man"
              placeholder="Ask a question..."
              className="flex-1 resize-none rounded bg-white/5 text-parchment text-sm px-2 py-1.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-gold"
            />
            {voiceSupported && (
              <button
                type="button"
                aria-label={isListening ? "Stop voice input" : "Start voice input"}
                aria-pressed={isListening}
                onClick={toggleListening}
                className={
                  "h-8 w-8 rounded-full flex items-center justify-center focus-visible:ring-2 focus-visible:ring-gold " +
                  (isListening ? "bg-gold text-ink" : "bg-white/10 text-parchment")
                }
              >
                🎤
              </button>
            )}
            <button
              type="submit"
              disabled={isSending || input.trim().length === 0}
              className="rounded bg-gold text-ink text-sm px-3 py-1.5 disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-gold"
            >
              Send
            </button>
          </form>
        </div>
      )}
    </div>
  );
}

function WiseManIcon({ reducedMotion, size }: { reducedMotion: boolean; size: number }) {
  // PLACEHOLDER (Sec 9.1): real navy-gold seal asset not yet supplied.
  // Ring and needle are separately addressable groups (stable ids) so a
  // real SVG drop-in only needs to preserve those two ids to keep the
  // animation wiring below. Both animate continuously, not on hover (Sec
  // 9.2); both are CSS keyframe transforms (GPU-composited, no
  // layout/paint per frame) and both are skipped entirely under
  // prefers-reduced-motion (Sec 9.4).
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" role="img" aria-hidden="true">
      <circle cx="20" cy="20" r="19" fill="#0a0e27" stroke="#d4af37" strokeWidth="1" />
      <g id="wise-man-ring" className={reducedMotion ? "" : "wise-man-spin"} style={{ transformOrigin: "20px 20px" }}>
        <circle cx="20" cy="20" r="14" fill="none" stroke="#d4af37" strokeWidth="1.5" strokeDasharray="3 4" strokeLinecap="round" />
      </g>
      <g id="wise-man-needle" className={reducedMotion ? "" : "wise-man-tilt"} style={{ transformOrigin: "20px 20px" }}>
        <polygon points="20,6 24,20 20,34 16,20" fill="#d4af37" />
        <circle cx="20" cy="20" r="2" fill="#0a0e27" />
      </g>
      <style>{`
        /* Ring: continuous anti-clockwise spin (Sec 9.2) -- rotate(0) to
           rotate(-360) is counter-clockwise (SVG's positive-angle direction
           is clockwise). 8s + bolder rounded dashes so the spin actually
           reads at icon size (36px closed / 24px open), not just at full
           scale. */
        .wise-man-spin { animation: wise-man-ring-spin 8s linear infinite; }
        /* Needle: independent from the ring (own timing, own motion shape) --
           a wide "seek and settle" sweep rather than a small wobble, closer
           to how a compass needle actually behaves (swings past center,
           settles, swings back) than a flat sine tilt. */
        .wise-man-tilt { animation: wise-man-needle-tilt 3s cubic-bezier(0.45, 0, 0.55, 1) infinite; }
        @keyframes wise-man-ring-spin { from { transform: rotate(0deg); } to { transform: rotate(-360deg); } }
        @keyframes wise-man-needle-tilt {
          0% { transform: rotate(-26deg); }
          30% { transform: rotate(20deg); }
          50% { transform: rotate(30deg); }
          80% { transform: rotate(-18deg); }
          100% { transform: rotate(-26deg); }
        }
      `}</style>
    </svg>
  );
}
