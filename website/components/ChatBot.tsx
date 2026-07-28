"use client";

import { useEffect, useState } from "react";
import { HISTORY_LIMIT } from "@/lib/chatApi";
import {
  buildChatHistoryStorageKey,
  hasReachedLimit,
  incrementMessageCount,
  readMessageCount,
  readStoredMessages,
  writeStoredMessages,
} from "@/lib/chatSession";
import type { ChatMessage, FaqEntry, StrategyChatContext } from "@/lib/types";

const GENERIC_ERROR = "AI is temporarily unavailable. Please check the FAQ above or try later.";
// Fallback used only when we truly have no more specific reason: the server's
// error body wasn't valid JSON, or a thrown error carries no useful `name`.
// Previously this ONE string covered every failure mode -- HTTP errors,
// empty-but-successful streams, timeouts, and network failures alike -- which
// is exactly the uninformative dead end CLAUDE.md's honesty rule rules out.
// Prefer one of the more specific messages below wherever the cause is known.
const NO_RESPONSE_PLACEHOLDER = "(No response — please try again.)";
const TIMEOUT_MESSAGE = "Request timed out — please try again.";
const EMPTY_REPLY_MESSAGE = "The model didn't return any text for this question — please try rephrasing or try again.";
const LIMIT_MESSAGE = "You've reached today's limit. Come back tomorrow for more questions!";
const MAX_INPUT_LENGTH = 500;
// Must stay ABOVE route.ts's `maxDuration` (30s) -- that Vercel platform
// backstop is the real worst-case ceiling on how long a legitimate in-progress
// stream can take server-side (route.ts's own STREAM_IDLE_TIMEOUT_MS of 15s
// bounds only the gap between chunks, not total duration, so a slow-but-alive
// stream can legally run right up to maxDuration). Previously this was 10s --
// SHORTER than even the 15s idle timeout -- so the client could abort a
// stream the server was still actively and correctly serving, discarding
// whatever text had already arrived. Order: UPSTREAM_TIMEOUT_MS (10s, initial
// connection) < STREAM_IDLE_TIMEOUT_MS (15s, per-chunk) < maxDuration (30s,
// hard server cap) < CLIENT_TIMEOUT_MS (35s) -- the client is now always the
// last one to give up.
export const CLIENT_TIMEOUT_MS = 35_000;

export interface ChatBotProps {
  faqEntries: FaqEntry[];
  strategyContext: StrategyChatContext;
  hasLiveChat: boolean;
}

// Reads an upstream Response as plain text, preferring an incremental stream
// reader when the runtime provides one (real browsers, real fetch) and
// falling back to response.text() otherwise -- this lets the exact same
// production code path work against a plain mocked Response in tests (no
// ReadableStream required from the mock) while still streaming for real in
// the browser. `onChunk` fires after every increment so the caller can render
// partial replies as they arrive.
async function readResponseAsText(response: Response, onChunk: (soFar: string) => void): Promise<string> {
  const body = response.body as ReadableStream<Uint8Array> | null;
  if (body && typeof body.getReader === "function") {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let fullText = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      fullText += decoder.decode(value, { stream: true });
      onChunk(fullText);
    }
    return fullText;
  }
  const fullText = await response.text();
  onChunk(fullText);
  return fullText;
}

export default function ChatBot({ faqEntries, strategyContext, hasLiveChat }: ChatBotProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [activeFaqIndex, setActiveFaqIndex] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [messageCount, setMessageCount] = useState(0);

  const historyKey = buildChatHistoryStorageKey(strategyContext);

  // Hydrate this strategy's conversation from sessionStorage on mount, so it
  // survives a remount/reload within the same tab session instead of
  // silently starting over with an empty array. See buildChatHistoryStorageKey's
  // own doc comment for why history is keyed per strategy while the message
  // count above is one shared, session-wide budget.
  useEffect(() => {
    setMessageCount(readMessageCount(window.sessionStorage));
    setMessages(readStoredMessages(window.sessionStorage, historyKey));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist after every change. The `length > 0` guard specifically avoids a
  // real ordering hazard: on first mount this effect runs with the render's
  // OLD `messages` (still `[]`, since the hydration effect's setMessages
  // above hasn't triggered a re-render yet) -- without the guard, that
  // no-op run would immediately overwrite a just-read, non-empty
  // sessionStorage entry with `[]`.
  useEffect(() => {
    if (messages.length > 0) {
      writeStoredMessages(window.sessionStorage, historyKey, messages);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages]);

  function toggleFaq(index: number) {
    setActiveFaqIndex((prev) => (prev === index ? null : index));
  }

  // Messages are only ever appended (handleSend) or updated IN PLACE (here) --
  // never removed. A prior version called setMessages(prev => prev.slice(0, -1))
  // on error/timeout, which could delete an assistant reply that had already
  // finished streaming if the 10s client-side abort fired in a race right at
  // the tail end of a normal response -- the exact "message vanishes after
  // streaming completes" bug this file now fixes.
  function setLastAssistantMessage(content: string) {
    setMessages((prev) => {
      if (prev.length === 0) {
        return prev;
      }
      const next = [...prev];
      next[next.length - 1] = { role: "assistant", content };
      return next;
    });
  }

  async function handleSend() {
    const trimmed = inputValue.trim().slice(0, MAX_INPUT_LENGTH);
    if (!trimmed || isSending) {
      return;
    }

    const currentCount = readMessageCount(window.sessionStorage);
    if (hasReachedLimit(currentCount)) {
      setMessageCount(currentCount);
      setChatError(LIMIT_MESSAGE);
      return;
    }

    const historyToSend = messages.slice(-HISTORY_LIMIT);
    setMessages((prev) => [...prev, { role: "user", content: trimmed }, { role: "assistant", content: "" }]);
    setInputValue("");
    setChatError(null);
    setIsSending(true);
    setMessageCount(incrementMessageCount(window.sessionStorage));

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), CLIENT_TIMEOUT_MS);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: trimmed, strategyContext, history: historyToSend }),
        signal: controller.signal,
      });

      if (!response.ok) {
        // The server's error body already says WHY (invalid input, upstream
        // failure, or -- since the "(No response)" investigation -- an
        // honestly-empty model reply with its stop_reason) -- read it back
        // instead of collapsing every non-2xx status to the same placeholder.
        // The body may not be valid JSON in every mocked/edge case, so this
        // parse is its own try/catch, independent of the outer one.
        let serverMessage: string | null = null;
        try {
          const data: unknown = await response.json();
          if (data && typeof data === "object" && typeof (data as { error?: unknown }).error === "string") {
            serverMessage = (data as { error: string }).error;
          }
        } catch {
          // Not JSON (or already consumed) -- fall through to the generic placeholder.
        }
        setLastAssistantMessage(serverMessage ?? NO_RESPONSE_PLACEHOLDER);
        setChatError(GENERIC_ERROR);
        return;
      }

      const fullText = await readResponseAsText(response, setLastAssistantMessage);
      if (!fullText) {
        // route.ts now converts a genuinely empty-but-successful stream into a
        // non-2xx response with stop_reason (see above) -- this branch is a
        // defensive fallback for any other path that still yields an empty
        // 200 body, so it gets its own honest label rather than the generic
        // "no response at all" placeholder.
        setLastAssistantMessage(EMPTY_REPLY_MESSAGE);
      }
    } catch (err) {
      // Never remove the message. If the stream had already produced real
      // text before the error/abort, that text stays exactly as shown; only
      // an still-empty placeholder gets filled in, so there's always
      // something visible and nothing already-delivered ever disappears.
      const timedOut = err instanceof DOMException && err.name === "AbortError";
      setMessages((prev) => {
        if (prev.length === 0) {
          return prev;
        }
        const last = prev[prev.length - 1];
        if (last.role === "assistant" && last.content.length === 0) {
          const next = [...prev];
          next[next.length - 1] = { role: "assistant", content: timedOut ? TIMEOUT_MESSAGE : NO_RESPONSE_PLACEHOLDER };
          return next;
        }
        return prev;
      });
      setChatError(GENERIC_ERROR);
    } finally {
      clearTimeout(timeoutId);
      setIsSending(false);
    }
  }

  if (!isOpen) {
    return (
      <button
        type="button"
        data-testid="chatbot-toggle-open"
        onClick={() => setIsOpen(true)}
        aria-label="Open chat assistant"
        className="fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-gold text-2xl text-ink shadow-lg"
      >
        💬
      </button>
    );
  }

  return (
    <div
      data-testid="chatbot-panel"
      className="fixed inset-0 z-50 flex flex-col bg-ink sm:inset-auto sm:bottom-24 sm:right-6 sm:h-[36rem] sm:w-96 sm:rounded-lg sm:border sm:border-gold/30"
    >
      <div className="flex items-center justify-between border-b border-gold/20 px-4 py-3">
        <h3 className="font-serif text-parchment">Vatican Assistant</h3>
        <button
          type="button"
          data-testid="chatbot-close"
          onClick={() => setIsOpen(false)}
          aria-label="Close chat assistant"
          className="text-xl text-muted hover:text-parchment"
        >
          ×
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3">
        <div data-testid="chatbot-faq">
          <div data-testid="faq-chips" className="flex flex-wrap gap-2">
            {faqEntries.map((faq, index) => (
              <button
                key={faq.question}
                type="button"
                data-testid={`faq-chip-${index}`}
                aria-pressed={activeFaqIndex === index}
                onClick={() => toggleFaq(index)}
                className={`rounded-full border px-3 py-1 text-xs transition ${
                  activeFaqIndex === index
                    ? "border-gold/60 bg-gold/10 text-parchment"
                    : "border-muted/30 text-muted"
                }`}
              >
                {faq.question}
              </button>
            ))}
          </div>
          {activeFaqIndex !== null ? (
            <p data-testid="faq-answer" className="mt-3 text-sm text-parchment">
              {faqEntries[activeFaqIndex].answer}
            </p>
          ) : null}
        </div>

        {hasLiveChat ? (
          <div data-testid="chatbot-live-chat" className="mt-4">
            <hr className="border-muted/20" />
            <p className="mt-3 text-xs uppercase tracking-wide text-muted">
              Ask anything in any language...
            </p>

            <div data-testid="chat-messages" className="mt-2 flex flex-col gap-2">
              {messages.map((message, index) => (
                <div
                  key={`${message.role}-${index}`}
                  data-testid="chat-bubble"
                  data-role={message.role}
                  className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                    message.role === "user"
                      ? "self-end bg-gold/20 text-parchment"
                      : "self-start bg-muted/10 text-parchment"
                  }`}
                >
                  {message.content}
                </div>
              ))}
              {isSending ? (
                <div data-testid="typing-indicator" className="self-start text-xs text-muted">
                  Vatican Assistant is typing…
                </div>
              ) : null}
            </div>

            {chatError ? (
              <p data-testid="chat-error" className="mt-2 text-xs text-loss">
                {chatError}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>

      {hasLiveChat ? (
        <div className="flex gap-2 border-t border-gold/20 px-4 py-3">
          <input
            data-testid="chat-input"
            type="text"
            value={inputValue}
            maxLength={MAX_INPUT_LENGTH}
            placeholder="Ask anything in any language..."
            onChange={(event) => setInputValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                handleSend();
              }
            }}
            className="flex-1 rounded-md border border-muted/30 bg-transparent px-3 py-2 text-sm text-parchment"
          />
          <button
            type="button"
            data-testid="chat-send"
            onClick={handleSend}
            disabled={isSending}
            className="rounded-md bg-gold px-4 py-2 text-sm font-medium text-ink disabled:opacity-50"
          >
            Send
          </button>
        </div>
      ) : null}
    </div>
  );
}
