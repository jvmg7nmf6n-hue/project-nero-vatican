// Wise Man's spend cap (CC-1 directive v3, Sec 8.2 + Sec 11.1 concurrency
// fix). Design Option 2.3-A from docs/investigations/wise_man_gate_a_report.md:
// an atomic counter store (Vercel KV / Redis in production), NOT Eve's own
// budget_ledger.py mechanism -- GATE A finding 1.4 established that ledger
// is read-then-compare-then-write (a real TOCTOU gap) and, more
// fundamentally, requires a live Python process this Vercel function
// doesn't have at request time.
//
// THE FIX FOR SEC 11.1: the increment-and-check is ONE atomic operation
// (AtomicCounterStore#incrementAndGet), never read-then-compare-then-write.
// checkAndReserveBudget always increments FIRST (atomically) and only
// inspects the atomic call's own return value to decide allowed/blocked --
// there is no separate read step that could race with another caller's
// write. If the atomic increment pushes the total over the cap, the
// reservation is released (an atomic decrement) and the request is
// rejected; nothing about the release step needs to be atomic WITH the
// increment for correctness, because the increment already happened
// exactly once, atomically, before any decision was made.
//
// Amounts are tracked in CENTS (integers), never floating-point dollars --
// the same reason Managed Agents' own session budgets use integer minor
// units: avoids float-rounding drift on a running total that many
// concurrent callers add to.

export interface AtomicCounterStore {
  /** Atomically adds `amountCents` to `key` and returns the NEW total. Must be a single atomic operation server-side. */
  incrementAndGet(key: string, amountCents: number): Promise<number>;
}

/**
 * In-process, single-Node-instance atomic store. Correct in a single
 * Vercel function instance because the critical section below has NO
 * `await` inside it -- under Node's single-threaded, run-to-completion
 * event loop, a synchronous block cannot be interleaved by a concurrent
 * caller, which is what makes this genuinely atomic (not just "usually
 * fine"). NOT safe across multiple serverless instances/processes -- that
 * is exactly what a real backend (Vercel KV/Redis, whose INCRBY is atomic
 * server-side) is for; see VercelKvCounterStore below. Used by default
 * only when no real store is configured, and always in tests, so the
 * gate-logic algorithm itself (not the backend) is what's under test in
 * website/__tests__/wiseManBudget.test.ts's concurrency test.
 */
export function createInMemoryCounterStore(): AtomicCounterStore {
  const counters = new Map<string, number>();
  return {
    async incrementAndGet(key: string, amountCents: number): Promise<number> {
      const next = (counters.get(key) ?? 0) + amountCents;
      counters.set(key, next);
      return next;
    },
  };
}

/**
 * Upstash Redis-backed store (production). Requires the `@upstash/redis`
 * package and UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN env vars
 * (auto-populated by linking a Redis integration in the Vercel project --
 * Vercel's own `@vercel/kv` package is deprecated as of this build, per its
 * npm install-time warning: "install a Redis integration from Vercel
 * Marketplace... Upstash Redis"). Provisioning that store is a human,
 * dashboard-side step, the same way ANTHROPIC_API_KEY itself is configured
 * per GATE A finding 1.3; this module cannot provision it.
 * `redis.incrby` maps to Redis INCRBY, which is atomic server-side.
 */
export async function createUpstashRedisCounterStore(): Promise<AtomicCounterStore> {
  const { Redis } = await import("@upstash/redis");
  const redis = Redis.fromEnv();
  return {
    async incrementAndGet(key: string, amountCents: number): Promise<number> {
      return redis.incrby(key, amountCents);
    },
  };
}

export interface BudgetConfig {
  dailyCapCents: number;
  monthlyCapCents: number;
}

/** Reads WISE_MAN_DAILY_CAP_USD / WISE_MAN_MONTHLY_CAP_USD, both configurable per Sec 8.2. */
export function loadBudgetConfig(env: Partial<Record<string, string>> = process.env): BudgetConfig {
  const dailyUsd = Number(env.WISE_MAN_DAILY_CAP_USD ?? "3");
  const monthlyUsd = Number(env.WISE_MAN_MONTHLY_CAP_USD ?? "20");
  return {
    dailyCapCents: Math.round((Number.isFinite(dailyUsd) ? dailyUsd : 3) * 100),
    monthlyCapCents: Math.round((Number.isFinite(monthlyUsd) ? monthlyUsd : 20) * 100),
  };
}

function utcDateKey(now: Date): string {
  return now.toISOString().slice(0, 10); // YYYY-MM-DD
}
function utcMonthKey(now: Date): string {
  return now.toISOString().slice(0, 7); // YYYY-MM
}

export interface BudgetReservationResult {
  allowed: boolean;
  reason?: "daily_cap_reached" | "monthly_cap_reached";
}

/**
 * Atomically reserves `costCents` against both the daily and monthly caps.
 * Checks monthly first: if it fails, daily was never touched, so there is
 * nothing to release. If monthly passes but daily fails, the monthly
 * reservation is released (an atomic decrement) before returning blocked.
 */
export async function checkAndReserveBudget(params: {
  store: AtomicCounterStore;
  config: BudgetConfig;
  costCents: number;
  now?: Date;
}): Promise<BudgetReservationResult> {
  const { store, config, costCents } = params;
  const now = params.now ?? new Date();
  const monthlyKey = `wise-man:budget:monthly:${utcMonthKey(now)}`;
  const dailyKey = `wise-man:budget:daily:${utcDateKey(now)}`;

  const monthlyTotal = await store.incrementAndGet(monthlyKey, costCents);
  if (monthlyTotal > config.monthlyCapCents) {
    await store.incrementAndGet(monthlyKey, -costCents); // release
    return { allowed: false, reason: "monthly_cap_reached" };
  }

  const dailyTotal = await store.incrementAndGet(dailyKey, costCents);
  if (dailyTotal > config.dailyCapCents) {
    await store.incrementAndGet(dailyKey, -costCents); // release
    await store.incrementAndGet(monthlyKey, -costCents); // release the monthly reservation too
    return { allowed: false, reason: "daily_cap_reached" };
  }

  return { allowed: true };
}
