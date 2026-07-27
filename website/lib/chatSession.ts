// Day 7 ChatBot rate limiting -- tracked in sessionStorage (not localStorage),
// so it resets naturally on tab close/reopen per the task's own rule, with no
// server-side session concept needed. This is a client-side-only cost guard:
// it prevents accidental/casual over-use from the browser UI, not a hardened
// abuse defense (a determined user could clear storage) -- exactly the scope
// the task asked for, nothing more.

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
