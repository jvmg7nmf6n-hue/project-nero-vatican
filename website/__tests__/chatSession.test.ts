import {
  hasReachedLimit,
  incrementMessageCount,
  MAX_MESSAGES_PER_SESSION,
  readMessageCount,
  type CountStorage,
} from "@/lib/chatSession";

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
