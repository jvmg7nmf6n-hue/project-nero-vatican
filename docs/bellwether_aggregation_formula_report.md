# Bellwether Aggregation Formula — Mass vs. Agreement

Report only, per explicit instruction — no code change. `_synthesis.aggregate()`
(`vatican/bellwether/bellwether/agents/_synthesis.py`) is unmodified.

## The question

`aggregate()`'s confidence formula:

```
agreement = |net_score| / 2.0                          # 0 (split) .. 1 (unanimous strong)
mass       = min(1.0, total_strength / 4.0)             # sum of contributing signals' own strength
confidence = 0.3 + 0.45 * agreement + 0.25 * mass
```

Your read: confidence partly measures "how many agents contributed" rather
than "how sure we are." **Confirmed correct**, and worth being precise about
why, since the honest answer is more nuanced than either "bug" or "fine."

## Is the reading correct?

Yes, mechanically. `total_strength` is a sum across every non-neutral
contributing signal's own `strength` (each individually in roughly
[0.15, 1.0]). One maximally-confident signal alone (`strength=1.0`) yields
`mass = 0.25` — a quarter of the cap. Reaching `mass = 1.0` needs several
signals near full strength, or more signals at moderate strength. Measured
directly this session: `monetary_policy` alone gave live-mode mean
confidence **0.281**; adding `liquidity` (MIXED, via real VIX) as a second
contributing agent raised it to **0.392** — a 0.111 jump from one additional
agent, nothing to do with either signal getting more *certain*, purely from
`mass` recovering. That's not a hypothetical — it's the actual measured
effect.

## Does this distort only during partial wiring, or at full wiring too?

**It would still distort at full wiring, and the reason is worth stating
precisely: the formula has no independence discount.** It treats N
contributing signals as N independent pieces of evidence. `mass` rising with
signal count is not inherently wrong — genuine independent corroboration
*should* raise confidence beyond what any single source justifies, that's
ordinary Bayesian reasoning, not a design flaw by itself.

The problem is that Bellwether's own 15 agents are **not** independent, and
the codebase already knows this: `correlation.py`'s own hardcoded
coefficients state gold moves with real yields at ~-0.7 (structural) and BTC
tracks risk appetite. `monetary_policy` and `liquidity` both partly reflect
the *same* underlying macro regime (a "risk-on, easy policy" world moves real
yields down, DXY down, AND VIX down together) — three signals from one
regime, not three independent confirmations of it. At full 15-agent wiring,
several agents will very plausibly co-move for the same reason, and `mass`
has no mechanism to discount that: 15 correlated-but-nominally-independent
signals inflate `mass` (and therefore confidence) exactly as much as 15
genuinely orthogonal ones would.

**Concretely: a fully-real 15-agent read and a fully-real 5-agent read are
not directly comparable on confidence alone**, if the 15-agent set includes
several agents that are substantially redundant with each other (as the
codebase's own correlation coefficients suggest several will be) while the
5-agent set happens to be more orthogonal. The larger, more redundant set
would score higher on `mass` despite not actually carrying more independent
information. This isn't a "wiring in progress" artifact that resolves
itself — it's a property of the formula that a redundancy-blind `mass` term
will keep producing at any wiring level.

## A formulation that separates the two

Worth proposing concretely, since the question asked for one:

**Report `agreement` and a `coverage` metric separately, rather than
blending them into one scalar.** Keep `agreement` as-is (it already answers
"how aligned is the available evidence," which is the right question for a
FIXED evidence set). Rename/expose `mass` as `signal_coverage` — "how much
of the intended evidence base was actually available and non-neutral this
cycle" — and surface it as its own field (e.g. `meta["signal_coverage"]`)
rather than folding it into `confidence` at nearly equal weight (0.25 vs.
0.45 today).

This mirrors a discipline already established elsewhere in this codebase's
Adam/Eve system: informational checks are measured and reported, never
silently blended into a binding number (the "measure, never gate"
convention). A consumer currently can't distinguish "high confidence built
on strong, broad agreement" from "high confidence built on one very
confident but narrow signal" — both currently collapse to the same number.
Separating them would let a future macro-conditioned hypothesis pipeline (or
a human operator) see BOTH: is the read consistent, and is it built on
enough independent-ish evidence to trust that consistency.

**A more rigorous but harder fix**, worth naming even though it's a bigger
lift: discount `mass` by known correlation clusters (e.g., count
`monetary_policy` + `liquidity` as something less than 2 full independent
units, using `correlation.py`'s own coefficients or a measured correlation
matrix once more real feeds exist) rather than a flat per-signal sum. This
is the textbook-correct answer, but it requires asserting a correlation
structure — and getting that assertion wrong (or hand-tuning it to produce
better-looking numbers) is exactly the "tuning Bellwether's heuristic
constants... fitting a system before it's earned it" trap the ground rules
warn against. Recommend the separate-reporting fix first (transparent, no
new assumptions), and revisit a correlation-aware discount only once real
correlations between real agents are actually measured, not asserted.

## Bottom line

- Your reading is correct, not a misunderstanding of the formula's intent.
- Not a transient partial-wiring artifact — a structural property that
  persists at full wiring, because the formula has no independence
  discount and several of Bellwether's 15 agents are acknowledged
  (by the codebase's own correlation coefficients) to be correlated.
- A confidence number from a smaller, more orthogonal signal set and one
  from a larger, more redundant set are not safely comparable today.
- The lowest-risk fix is separating `agreement` from a renamed `coverage`
  metric, reported alongside rather than blended — informational, not
  binding, matching this project's own existing discipline elsewhere.

---

## 2026-08-07 update — A1 shipped, A2 proposal (not implemented)

**A1 (implemented, `vatican/bellwether/bellwether/agents/_synthesis.py`)**:
`AssetRead` now carries `agreement` and `coverage` as their own fields
(`coverage` is the exact same `mass` term, renamed and exposed — not a new
computation). `confidence` is byte-identical to before
(`0.3 + 0.45*agreement + 0.25*coverage`) — every existing consumer
(`trade_recommendation`'s actionability threshold, `risk`'s haircut math)
is unaffected. The split is propagated to `gold_analysis`/
`bitcoin_analysis`'s own `meta` and to four new fields on the top-level
`AnalysisOutput` (`gold_agreement`, `gold_coverage`, `bitcoin_agreement`,
`bitcoin_coverage`) — see `docs/bellwether_stage2_report.md` for the
re-measured sweep using these new fields. 6 new tests in
`tests/test_vatican_aggregation.py`; full suite still green.

**A2 — correlation discount, proposed, per explicit instruction NOT
implemented.** The question: should `agreement` (or `coverage`) apply a
discount when contributing agents are known-correlated, using
`correlation.py`'s own coefficients?

**What `correlation.py` actually encodes, precisely** (so the proposal
below isn't hand-waved): `gold_realyield_corr = -0.7` (structural, always),
`btc_risk_corr = 0.55 if vix < 20 else 0.35`, `gold_btc_corr = 0.4 if dxy >
105 else 0.2`. These are all *cross-asset-to-driver* correlations (how gold
moves with real yields, how BTC moves with risk appetite) — none of them is
directly "agent X's signal correlates with agent Y's signal at coefficient
r." Turning them into a per-signal discount requires an extra assumption
this codebase hasn't made yet: which *agents* count as reading the "same"
regime. Concretely, for GOLD today: `monetary_policy` derives its GOLD
signal from `real_yield_10y` + `dxy`; `liquidity` derives its GOLD signal
from `vix` (safe-haven proxy). These are different literal variables, but
`correlation.py`'s own narrative treats them as expressions of one
"risk-on / easy-policy" regime — the qualitative claim the aggregation
report above is built on. There is no coefficient in the codebase today for
"real_yield_10y vs vix," only the two asset-level correlations listed.

**Two concrete implementations, in order of how much they assume:**

1. **Cluster-and-discount using `correlation.py`'s existing coefficients
   directly**, treating agents that read a shared underlying driver as one
   cluster and applying the standard "effective independent signals"
   shrinkage for `n` equally-correlated contributors:
   `n_eff = n / (1 + (n-1) * rho)`. E.g. if `monetary_policy` and
   `liquidity` both contribute to GOLD in a `vix < 20` regime, treat them as
   one 2-signal cluster with `rho` borrowed from `btc_risk_corr` (0.55) as
   the working regime-correlation proxy, giving `n_eff = 2 / (1 + 1*0.55) =
   1.29` instead of 2 — `coverage` would use `n_eff`-weighted strength
   instead of raw summed strength. **Risk, stated plainly**: this borrows a
   BTC-vs-risk-appetite coefficient to discount a GOLD cluster, because no
   GOLD-specific agent-pair coefficient exists. That's an assumption being
   asserted, not measured — exactly the "fitting constants before the
   system earns it" trap the ground rules warn against.
2. **Don't borrow across assets — discount only where a coefficient
   literally applies to the pair.** Since no two currently-real-eligible
   GOLD or BTC agents share a coefficient `correlation.py` actually
   computes (the three coefficients are asset-driver relationships, not
   agent-agent ones), this option discounts nothing today and only
   activates once `correlation.py` itself is rewritten to output genuine
   agent-pair or driver-pair correlations from real rolling data (already
   flagged in `correlation.py`'s own docstring as a future addition, not a
   wiring gap). Structurally honest, but a no-op until that rewrite ships.

**Recommendation: option 2.** Option 1 would ship a discount today by
repurposing a coefficient that was never computed for the pair it would be
applied to — the same failure mode as hand-tuning constants to make output
look more sophisticated, just one layer removed. The honest sequencing is:
(a) A1's split ships now (done), (b) `correlation.py` gets rewritten to
compute real rolling correlations between agents' actual signal histories
once there's enough real signal history to compute them from (a genuine
future increment, not started), (c) only then does a correlation-aware
discount get implemented, using coefficients that were actually measured
for the pairs they discount. Implementing a discount now would require
inventing the missing coefficients, which is worse than not discounting at
all — a consumer can reason about un-discounted `coverage` knowing its
limitation (documented in `README_VATICAN.md`); a consumer of a
discounted-by-guess `coverage` would trust a number that looks
more-rigorous while being less honest.
