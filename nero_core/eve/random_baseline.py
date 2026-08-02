"""Phase 3.4 -- pure-code random-hypothesis baseline generator.

ZERO LLM CALLS (spec's own binding requirement, restated here): every one of
the K sampled hypotheses is produced with Python's stdlib `random` module
only, seeded for reproducibility. Only the resulting hypotheses' BACKTEST
costs compute (via nero_core.eve.scoring, which calls the real harness) --
generating them costs nothing, and this module never touches
nero_core.eve.budget_ledger at all, confirmed directly by
test_eve_random_baseline.py (no ledger entries appear from a baseline run).

WHY PURE CODE, NOT AN LLM (spec 3.4's own reasoning, restated): an
LLM-generated "random" hypothesis would be drawn from the same model prior
Eve draws from, measuring Eve against a slightly-dumber Eve rather than a
true chance floor -- a code sampler is the only thing that yields a genuine
chance-survival baseline.

ISOLATION: this module reinlines (does not import) nero_core.research_agent.
rule_dsl.ALLOWED_FIELDS as a literal copy (ALLOWED_FIELDS_COPY below) rather
than importing it -- there is no other reason for this module to depend on
nero_core.research_agent at all, so it stays fully isolated like every other
Eve module except nero_core.eve.scoring (which has a documented, narrower
exception -- see that module's own docstring). A test asserts this copy
stays byte-identical to Adam's own tuple.

SAMPLING SPACE (flagged design decision -- see this branch's closing
report): field-specific value ranges (zscore20 in [-4,4], rsi14 in [0,100],
etc. -- see _VALUE_RANGES), because a single global numeric range would make
some fields' conditions trivially always/never fire. Price-scale fields
(close, ma20/50/200, atr14, bb_lower/upper) are only ever compared
field-vs-field (a fixed constant threshold against a raw price is
meaningless without knowing which asset), never against a fabricated fixed
value. 1-3 ANDed conditions per hypothesis, matching Adam's own
"single-trigger mechanism" DSL design.

LIMITATION, STATED EXPLICITLY (not hidden): this sampler only covers the
SAME DSL region Adam's (and Eve's own DSL-expressible) hypotheses already
live in. If real proposals cluster in that same region, this baseline may be
an easy floor to beat -- flagged for human confirmation in the closing
report, not asserted as sufficient.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone

DEFAULT_K = 200
DEFAULT_SEED = 20260718  # same seed VALUE tools.backtest_statistics uses -- coincidental consistency, not a shared constant

# Reinlined copy of nero_core.research_agent.rule_dsl.ALLOWED_FIELDS -- see
# module docstring. Kept in the SAME declared order as Adam's own tuple so a
# byte-identity test is meaningful (a set-equality check would hide a
# harmless-looking reorder that nonetheless means this copy silently
# diverged from a hand-edit rather than a deliberate change).
ALLOWED_FIELDS_COPY = (
    "close", "ma20", "ma50", "ma200", "zscore20", "atr14", "rsi14", "adx14",
    "bb_lower", "bb_upper", "ret_1", "volume",
)

_VALUE_OPS = ("gt", "gte", "lt", "lte")
_CROSS_OPS = ("cross_above", "cross_below")

# Fields with no fixed universal scale -- sampled ONLY field-vs-field (see
# module docstring), never against a fabricated constant `value`.
_FIELD_VS_FIELD_ONLY = frozenset({"close", "ma20", "ma50", "ma200", "atr14", "bb_lower", "bb_upper"})

# Plausible per-field ranges for the fields that ARE sampled against a fixed
# value -- see module docstring on why these are field-specific.
_VALUE_RANGES = {
    "zscore20": (-4.0, 4.0),
    "rsi14": (0.0, 100.0),
    "adx14": (0.0, 60.0),
    "ret_1": (-0.05, 0.05),
    "volume": (0.0, 1.0),
}


def _sample_condition(rng: random.Random) -> dict:
    field = rng.choice(ALLOWED_FIELDS_COPY)
    if field in _FIELD_VS_FIELD_ONLY or rng.random() < 0.3:
        compare_to_field = rng.choice([f for f in ALLOWED_FIELDS_COPY if f != field])
        op = rng.choice(_VALUE_OPS + _CROSS_OPS)
        return {"field": field, "op": op, "compare_to_field": compare_to_field}
    low, high = _VALUE_RANGES.get(field, (-1.0, 1.0))
    op = rng.choice(_VALUE_OPS)
    return {"field": field, "op": op, "value": round(rng.uniform(low, high), 4)}


def _sample_entry_rule(rng: random.Random) -> dict:
    # Weighted toward simpler rules -- matches Adam's own "single-trigger
    # mechanism" DSL design (rule_dsl.py's own module docstring), which real
    # Eve/Adam hypotheses also tend toward, so the baseline's rule
    # COMPLEXITY distribution is at least roughly comparable, not just its
    # field/op/value space.
    n_conditions = rng.choice([1, 1, 2, 3])
    return {"conditions": [_sample_condition(rng) for _ in range(n_conditions)]}


def _sample_exit_plan(rng: random.Random) -> dict:
    plan = {
        "stop_atr_multiple": round(rng.uniform(0.5, 4.0), 2),
        "target_r_multiple": round(rng.uniform(0.5, 5.0), 2),
    }
    if rng.random() < 0.8:
        plan["max_holding_hours"] = round(rng.uniform(4.0, 240.0), 1)
    return plan


def generate_random_hypothesis(rng: random.Random, index: int, asset: str, timeframe: str, now: datetime) -> dict:
    """One hypothesis, in the exact JSON shape
    nero_core.research_agent.auto_tester.test_hypothesis already expects
    (structured_entry_rule/structured_exit_plan) -- see nero_core.eve.scoring,
    which is the only place these get run through that harness.
    `generated_at`=`now` (the moment of GENERATION, not some fabricated
    earlier date) is correct here, not a lookahead shortcut: it means "only
    real historical data up to right now is eligible," which is simply true
    for a freshly-generated baseline hypothesis, exactly as it would be for
    a freshly-generated Eve or Adam hypothesis."""
    return {
        "hypothesis_name": f"RANDOM_BASELINE_{index:04d}",
        "mechanism": (
            "Pure-code random baseline hypothesis, sampled uniformly over rule_dsl's own "
            "field/op/value-range space (nero_core.eve.random_baseline). Not a real research "
            "claim -- exists only to establish a chance-survival floor."
        ),
        "asset": asset,
        "timeframe": timeframe,
        "generated_at": now.isoformat(),
        "structured_entry_rule": _sample_entry_rule(rng),
        "structured_exit_plan": _sample_exit_plan(rng),
        "source": "random_baseline_generator",
    }


def generate_random_baseline(
    asset: str, timeframe: str, now: datetime | None = None, k: int = DEFAULT_K, seed: int = DEFAULT_SEED
) -> list[dict]:
    """K (spec's own K>=200 minimum, default DEFAULT_K=200) pure-code-sampled
    hypotheses for one (asset, timeframe) pair. Deterministic for a given
    (asset, timeframe, now, k, seed) -- cache the result and regenerate only
    when the data window changes, per spec 3.4's own caching note."""
    now = now or datetime.now(timezone.utc)
    rng = random.Random(seed)
    return [generate_random_hypothesis(rng, i, asset, timeframe, now) for i in range(k)]
