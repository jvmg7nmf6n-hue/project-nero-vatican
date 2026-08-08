import {
  createInMemoryCounterStore,
  loadBudgetConfig,
  checkAndReserveBudget,
  AtomicCounterStore,
} from "@/lib/wiseMan/budget";

describe("loadBudgetConfig (Sec 8.2 configurable daily/monthly caps)", () => {
  it("defaults to $3/day and $20/month when unset", () => {
    const cfg = loadBudgetConfig({});
    expect(cfg.dailyCapCents).toBe(300);
    expect(cfg.monthlyCapCents).toBe(2000);
  });

  it("reads WISE_MAN_DAILY_CAP_USD / WISE_MAN_MONTHLY_CAP_USD", () => {
    const cfg = loadBudgetConfig({ WISE_MAN_DAILY_CAP_USD: "5.50", WISE_MAN_MONTHLY_CAP_USD: "50" });
    expect(cfg.dailyCapCents).toBe(550);
    expect(cfg.monthlyCapCents).toBe(5000);
  });
});

describe("checkAndReserveBudget (Sec 8.2 fail-closed on breach, Sec 11.1 atomicity)", () => {
  it("allows spend under both caps", async () => {
    const store = createInMemoryCounterStore();
    const config = { dailyCapCents: 1000, monthlyCapCents: 5000 };
    const result = await checkAndReserveBudget({ store, config, costCents: 100 });
    expect(result.allowed).toBe(true);
  });

  it("blocks and releases the reservation when the daily cap is breached", async () => {
    const store = createInMemoryCounterStore();
    const config = { dailyCapCents: 100, monthlyCapCents: 5000 };
    const first = await checkAndReserveBudget({ store, config, costCents: 100 });
    expect(first.allowed).toBe(true);
    const second = await checkAndReserveBudget({ store, config, costCents: 1 });
    expect(second.allowed).toBe(false);
    expect(second.reason).toBe("daily_cap_reached");
    // The rejected reservation was released -- a subsequent request that fits should still be allowed.
    const monthlyOnlyStore = createInMemoryCounterStore();
    const config2 = { dailyCapCents: 100, monthlyCapCents: 100 };
    await checkAndReserveBudget({ store: monthlyOnlyStore, config: config2, costCents: 100 });
    const blocked = await checkAndReserveBudget({ store: monthlyOnlyStore, config: config2, costCents: 1 });
    expect(blocked.allowed).toBe(false);
    // Confirm release happened: total should be back at 100, not 101, on the monthly key.
    const afterRelease = await monthlyOnlyStore.incrementAndGet(
      `wise-man:budget:monthly:${new Date().toISOString().slice(0, 7)}`,
      0,
    );
    expect(afterRelease).toBe(100);
  });

  it("blocks when the monthly cap is breached even if daily has room", async () => {
    const store = createInMemoryCounterStore();
    const config = { dailyCapCents: 10000, monthlyCapCents: 50 };
    const result = await checkAndReserveBudget({ store, config, costCents: 100 });
    expect(result.allowed).toBe(false);
    expect(result.reason).toBe("monthly_cap_reached");
  });

  it(
    "CONCURRENCY (Sec 11.1): N genuinely concurrent reservations never exceed the cap and never lose an update -- " +
      "this is the actual failure mode a read-then-compare-then-write implementation (like Eve's own budget_ledger.py, " +
      "per GATE A finding 1.4) has and this atomic-increment-first design does not",
    async () => {
      const store = createInMemoryCounterStore();
      const config = { dailyCapCents: 100_000, monthlyCapCents: 100_000 };
      const N = 200;
      const costEach = 10;

      const results = await Promise.all(
        Array.from({ length: N }, () => checkAndReserveBudget({ store, config, costCents: costEach })),
      );

      // Every one of the 200 concurrent $0.10 reservations must be allowed
      // (well under the $1000 cap) -- if the increment were not atomic,
      // some updates would be lost and the final total would undercount.
      expect(results.every((r) => r.allowed)).toBe(true);
      const total = await store.incrementAndGet(
        `wise-man:budget:daily:${new Date().toISOString().slice(0, 10)}`,
        0,
      );
      expect(total).toBe(N * costEach);
    },
  );

  it("CONCURRENCY at the cap boundary: exactly the requests that fit are allowed, no overshoot", async () => {
    const store = createInMemoryCounterStore();
    // Cap fits exactly 50 reservations of 10 cents each.
    const config = { dailyCapCents: 500, monthlyCapCents: 100_000 };
    const N = 80;
    const costEach = 10;

    const results = await Promise.all(
      Array.from({ length: N }, () => checkAndReserveBudget({ store, config, costCents: costEach })),
    );

    const allowedCount = results.filter((r) => r.allowed).length;
    expect(allowedCount).toBe(50);
    const total = await store.incrementAndGet(`wise-man:budget:daily:${new Date().toISOString().slice(0, 10)}`, 0);
    expect(total).toBe(500); // never exceeds the cap, never undercounts
  });

  it("fails closed with a custom store that throws (propagates rather than silently allowing)", async () => {
    const throwingStore: AtomicCounterStore = {
      incrementAndGet: async () => {
        throw new Error("store unavailable");
      },
    };
    const config = { dailyCapCents: 1000, monthlyCapCents: 5000 };
    await expect(checkAndReserveBudget({ store: throwingStore, config, costCents: 10 })).rejects.toThrow(
      "store unavailable",
    );
  });
});
