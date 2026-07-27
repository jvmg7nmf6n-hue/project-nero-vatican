import {
  buildChatHistoryStorageKey,
  hasReachedLimit,
  incrementMessageCount,
  MAX_MESSAGES_PER_SESSION,
  readMessageCount,
  readStoredMessages,
  writeStoredMessages,
  type CountStorage,
} from "@/lib/chatSession";
import type { ChatMessage, StrategyChatContext } from "@/lib/types";

function createMockStorage(): CountStorage & { store: Record<string, string> } {
  const store: Record<string, string> = {};
  return {
    store,
    getItem: (key: string) => (key in store ? store[key] : null),
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
  };
}

describe("chatSession rate limiting", () => {
  it("MAX_MESSAGES_PER_SESSION is 10, per the task's own limit", () => {
    expect(MAX_MESSAGES_PER_SESSION).toBe(10);
  });

  it("readMessageCount returns 0 for a fresh session (no stored value)", () => {
    const storage = createMockStorage();
    expect(readMessageCount(storage)).toBe(0);
  });

  it("incrementMessageCount increments from 0 to 1 on first call", () => {
    const storage = createMockStorage();
    expect(incrementMessageCount(storage)).toBe(1);
    expect(readMessageCount(storage)).toBe(1);
  });

  it("increments correctly across repeated calls, matching a real conversation", () => {
    const storage = createMockStorage();
    for (let i = 1; i <= 9; i += 1) {
      expect(incrementMessageCount(storage)).toBe(i);
    }
    expect(readMessageCount(storage)).toBe(9);
  });

  it("hasReachedLimit is false below the limit and true at/above it", () => {
    expect(hasReachedLimit(9)).toBe(false);
    expect(hasReachedLimit(10)).toBe(true);
    expect(hasReachedLimit(11)).toBe(true);
  });

  it("blocks the 11th message: count reaches 10, then hasReachedLimit gates further sends", () => {
    const storage = createMockStorage();
    for (let i = 0; i < 10; i += 1) {
      incrementMessageCount(storage);
    }
    const count = readMessageCount(storage);
    expect(count).toBe(10);
    expect(hasReachedLimit(count)).toBe(true);
  });

  it("treats a corrupted/non-numeric stored value as 0, never NaN or negative", () => {
    const storage = createMockStorage();
    storage.setItem("vatican_chat_message_count", "not-a-number");
    expect(readMessageCount(storage)).toBe(0);
  });

  it("treats a negative stored value as 0 (defensive, never a negative count)", () => {
    const storage = createMockStorage();
    storage.setItem("vatican_chat_message_count", "-5");
    expect(readMessageCount(storage)).toBe(0);
  });

  it("works against real sessionStorage (jsdom), not just the mock", () => {
    window.sessionStorage.clear();
    expect(readMessageCount(window.sessionStorage)).toBe(0);
    expect(incrementMessageCount(window.sessionStorage)).toBe(1);
    expect(readMessageCount(window.sessionStorage)).toBe(1);
    window.sessionStorage.clear();
  });
});

const CONTEXT: Pick<StrategyChatContext, "strategy_name" | "asset" | "timeframe"> = {
  strategy_name: "BREAKOUT_MOMENTUM",
  asset: "GOLD",
  timeframe: "1week",
};

describe("buildChatHistoryStorageKey", () => {
  it("derives a stable key from strategy_name, asset, and timeframe", () => {
    expect(buildChatHistoryStorageKey(CONTEXT)).toBe("vatican_chat_history_BREAKOUT_MOMENTUM_GOLD_1week");
  });

  it("gives different strategies distinct keys, so conversations never mix", () => {
    const other = { strategy_name: "TREND_PULLBACK", asset: "BNB", timeframe: "12h" };
    expect(buildChatHistoryStorageKey(CONTEXT)).not.toBe(buildChatHistoryStorageKey(other));
  });
});

describe("readStoredMessages / writeStoredMessages (conversation persistence bug fix)", () => {
  const key = buildChatHistoryStorageKey(CONTEXT);
  const MESSAGES: ChatMessage[] = [
    { role: "user", content: "hi" },
    { role: "assistant", content: "hello!" },
  ];

  it("returns an empty array when nothing is stored yet", () => {
    const storage = createMockStorage();
    expect(readStoredMessages(storage, key)).toEqual([]);
  });

  it("round-trips a written conversation exactly", () => {
    const storage = createMockStorage();
    writeStoredMessages(storage, key, MESSAGES);
    expect(readStoredMessages(storage, key)).toEqual(MESSAGES);
  });

  it("overwrites the previous value on each write (never appends duplicates)", () => {
    const storage = createMockStorage();
    writeStoredMessages(storage, key, [MESSAGES[0]]);
    writeStoredMessages(storage, key, MESSAGES);
    expect(readStoredMessages(storage, key)).toEqual(MESSAGES);
  });

  it("returns an empty array for corrupted/non-JSON stored data, never throwing", () => {
    const storage = createMockStorage();
    storage.setItem(key, "not valid json{{{");
    expect(() => readStoredMessages(storage, key)).not.toThrow();
    expect(readStoredMessages(storage, key)).toEqual([]);
  });

  it("filters out malformed entries from stored data", () => {
    const storage = createMockStorage();
    storage.setItem(key, JSON.stringify([{ role: "user", content: "ok" }, { role: "bogus", content: "x" }, { role: "assistant" }]));
    expect(readStoredMessages(storage, key)).toEqual([{ role: "user", content: "ok" }]);
  });

  it("keeps two different strategies' conversations independent under the same storage", () => {
    const storage = createMockStorage();
    const otherKey = buildChatHistoryStorageKey({ strategy_name: "TREND_PULLBACK", asset: "BNB", timeframe: "12h" });
    writeStoredMessages(storage, key, MESSAGES);
    writeStoredMessages(storage, otherKey, [{ role: "user", content: "different strategy" }]);
    expect(readStoredMessages(storage, key)).toEqual(MESSAGES);
    expect(readStoredMessages(storage, otherKey)).toEqual([{ role: "user", content: "different strategy" }]);
  });
});
