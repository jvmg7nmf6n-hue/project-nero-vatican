// Day 7 ChatBot rate limiting -- tracked in sessionStorage (not localStorage),
// so it resets naturally on tab close/reopen per the task's own rule, with no
// server-side session concept needed. This is a client-side-only cost guard:
// it prevents accidental/casual over-use from the browser UI, not a hardened
// abuse defense (a determined user could clear storage) -- exactly the scope
// the task asked for, nothing more.

import type { ChatMessage, StrategyChatContext } from "./types";

export const MAX_MESSAGES_PER_SESSION = 10;

const STORAGE_KEY = "vatican_chat_message_count";

// Narrowed to just the two methods actually used, so tests can pass a plain
// mock object instead of needing a real Storage implementation.
export type CountStorage = Pick<Storage, "getItem" | "setItem">;

export function readMessageCount(storage: CountStorage): number {
  const raw = storage.getItem(STORAGE_KEY);
  if (raw === null) {
    return 0;
  }
  const parsed = Number.parseInt(raw, 10);
  return Number.isNaN(parsed) || parsed < 0 ? 0 : parsed;
}

export function incrementMessageCount(storage: CountStorage): number {
  const next = readMessageCount(storage) + 1;
  storage.setItem(STORAGE_KEY, String(next));
  return next;
}

export function hasReachedLimit(count: number): boolean {
  return count >= MAX_MESSAGES_PER_SESSION;
}

// Conversation-history persistence (bug fix) -- keyed per (strategy, asset,
// timeframe), unlike the message COUNT above (one shared, session-wide
// budget), so a conversation about one strategy never bleeds into another
// strategy's page. Read on mount and written after every change, so the
// visible conversation survives a remount/reload within the same tab
// session instead of silently starting over.
export function buildChatHistoryStorageKey(
  context: Pick<StrategyChatContext, "strategy_name" | "asset" | "timeframe">
): string {
  return `vatican_chat_history_${context.strategy_name}_${context.asset}_${context.timeframe}`;
}

function isChatMessage(value: unknown): value is ChatMessage {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const v = value as Record<string, unknown>;
  return (v.role === "user" || v.role === "assistant") && typeof v.content === "string";
}

export function readStoredMessages(storage: CountStorage, key: string): ChatMessage[] {
  const raw = storage.getItem(key);
  if (!raw) {
    return [];
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(isChatMessage) : [];
  } catch {
    return [];
  }
}

export function writeStoredMessages(storage: CountStorage, key: string, messages: ChatMessage[]): void {
  storage.setItem(key, JSON.stringify(messages));
}
