"""Data providers.

Every quantitative feed sits behind a small interface so the engine never cares
whether numbers come from a mock or a live vendor. The mock providers are
*deterministic* given a seed, which makes runs reproducible for tests and
backtests. To go live, subclass the interface and register it in build_data_hub.
"""
from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..config import Settings, get_settings
from ..schemas import Category, MarketSnapshot, Region


# --------------------------------------------------------------------------- #
# Interfaces
# --------------------------------------------------------------------------- #
class MarketDataProvider(ABC):
    @abstractmethod
    def snapshot(self) -> MarketSnapshot: ...


@dataclass
class CalendarItem:
    name: str
    region: Region
    category: Category
    when: datetime
    consensus: float | None = None
    prior: float | None = None
    actual: float | None = None

    @property
    def surprise(self) -> float | None:
        """Normalised surprise in [-1, 1] when an actual print exists."""
        if self.actual is None or self.consensus is None:
            return None
        scale = abs(self.consensus) if abs(self.consensus) > 1e-9 else 1.0
        raw = (self.actual - self.consensus) / scale
        return max(-1.0, min(1.0, raw))


class CalendarProvider(ABC):
    @abstractmethod
    def upcoming(self, horizon_days: int = 10) -> list[CalendarItem]: ...

    @abstractmethod
    def recent_releases(self, lookback_days: int = 3) -> list[CalendarItem]: ...


class OnChainProvider(ABC):
    @abstractmethod
    def metrics(self) -> dict[str, float]: ...


class DerivativesProvider(ABC):
    @abstractmethod
    def metrics(self) -> dict[str, float]: ...


class EtfFlowProvider(ABC):
    @abstractmethod
    def flows(self) -> dict[str, float]: ...


# --------------------------------------------------------------------------- #
# Mock implementations
# --------------------------------------------------------------------------- #
class MockMarketData(MarketDataProvider):
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng

    def snapshot(self) -> MarketSnapshot:
        r = self.rng
        return MarketSnapshot(
            gold_price=round(2600 + r.uniform(-80, 120), 2),
            btc_price=round(64000 + r.uniform(-6000, 9000), 2),
            dxy=round(104 + r.uniform(-2.5, 2.5), 2),
            real_yield_10y=round(1.9 + r.uniform(-0.4, 0.4), 2),
            nominal_yield_10y=round(4.2 + r.uniform(-0.4, 0.4), 2),
            vix=round(15 + r.uniform(-3, 12), 2),
            fed_funds_mid=5.13,
            move_index=round(95 + r.uniform(-15, 35), 1),
        )


class MockCalendar(CalendarProvider):
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng

    def upcoming(self, horizon_days: int = 10) -> list[CalendarItem]:
        now = datetime.now(timezone.utc)
        plan = [
            ("FOMC Rate Decision", Region.USA, Category.MONETARY_POLICY, 2, 5.13, 5.13),
            ("US CPI (YoY)", Region.USA, Category.INFLATION, 4, 3.1, 3.2),
            ("US Non-Farm Payrolls", Region.USA, Category.LABOR, 6, 180.0, 175.0),
            ("ECB Rate Decision", Region.EUROZONE, Category.MONETARY_POLICY, 7, 3.4, 3.65),
            ("BOJ Policy Statement", Region.JAPAN, Category.MONETARY_POLICY, 9, 0.25, 0.1),
        ]
        out = []
        for name, region, cat, day, cons, prior in plan:
            if day <= horizon_days:
                out.append(CalendarItem(name, region, cat, now + timedelta(days=day),
                                        consensus=cons, prior=prior))
        return out

    def recent_releases(self, lookback_days: int = 3) -> list[CalendarItem]:
        now = datetime.now(timezone.utc)
        r = self.rng
        items = [
            ("US PPI (MoM)", Region.USA, Category.INFLATION, 0.2, 0.1),
            ("US Initial Jobless Claims", Region.USA, Category.LABOR, 230.0, 225.0),
        ]
        out = []
        for name, region, cat, cons, prior in items:
            actual = round(cons * (1 + r.uniform(-0.25, 0.25)), 3)
            out.append(CalendarItem(name, region, cat, now - timedelta(days=1),
                                    consensus=cons, prior=prior, actual=actual))
        return out


class MockOnChain(OnChainProvider):
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng

    def metrics(self) -> dict[str, float]:
        r = self.rng
        return {
            "exchange_netflow_btc": round(r.uniform(-9000, 6000), 0),   # negative = leaving exchanges (bullish)
            "stablecoin_supply_chg_pct": round(r.uniform(-1.5, 2.5), 2),
            "lth_supply_chg_pct": round(r.uniform(-0.5, 1.2), 2),       # long-term holder supply
            "mvrv_z": round(r.uniform(-0.5, 3.0), 2),
            "funding_rate_bps": round(r.uniform(-3, 8), 2),
        }


class MockDerivatives(DerivativesProvider):
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng

    def metrics(self) -> dict[str, float]:
        r = self.rng
        return {
            "btc_oi_chg_pct": round(r.uniform(-6, 8), 2),
            "btc_perp_funding_bps": round(r.uniform(-4, 9), 2),
            "btc_25d_skew": round(r.uniform(-6, 6), 2),       # >0 = puts bid (fear)
            "gold_futures_oi_chg_pct": round(r.uniform(-4, 5), 2),
            "gold_mgr_net_long_pct": round(r.uniform(30, 70), 1),
        }


class MockEtfFlows(EtfFlowProvider):
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng

    def flows(self) -> dict[str, float]:
        r = self.rng
        return {
            "btc_spot_etf_flow_musd": round(r.uniform(-400, 700), 1),
            "gold_etf_flow_musd": round(r.uniform(-300, 400), 1),
        }


# --------------------------------------------------------------------------- #
# Vatican integration — real providers (Stage 2, docs/bellwether_audit.md)
# --------------------------------------------------------------------------- #
class VaticanRealMarketData(MarketDataProvider):
    """Real real_yield_10y (FRED DFII10) via nero_core.data_sources.macro_data
    — the SAME module, SAME cache, SAME t+2 lag discipline MACRO_RISK_ON
    already uses in production; this class does not recompute or shortcut
    that lag, it takes the already-lagged latest usable value.

    dxy stays on the ORIGINAL mock draw deliberately, not real, even though
    Vatican's macro_data.py has a cached "dollar_proxy" series: that cache is
    UUP (an ETF price, ~$28) sourced by fetch_dollar_proxy_daily's own
    UUP-first fallback order, not an actual DXY-index-scale quote (~100-110)
    — confirmed directly against data/macro_cache/dollar_proxy.csv (values
    in the high 20s, not the 100s). Feeding that number into a formula built
    around `_DXY_NEUTRAL = 104.0` (bellwether/agents/monetary_policy.py)
    would silently produce a nonsense dxy_gap (off by a factor of ~4), not a
    real signal — worse than staying mock, since it would look confidently
    real while being wrong. Fixing this honestly needs either a genuine
    DXY-scale quote (macro_data.fetch_dollar_proxy_daily's own DXY fallback
    would work, but the CACHED series is UUP, and forcing a re-fetch isn't
    this class's call to make unilaterally) or adapting monetary_policy.py's
    own dxy_gap formula to a proxy-relative baseline instead of a fixed
    DXY-scale anchor — a decision left to a future increment, not guessed
    here. real_yield_10y has no such issue: DFII10 is already a genuine %
    real-yield level, exactly the units monetary_policy.py's own
    `_REAL_YIELD_NEUTRAL = 1.8` anchor expects.

    Every other MarketSnapshot field (gold_price, btc_price, vix,
    nominal_yield_10y, fed_funds_mid, move_index) has no real Vatican source
    yet (see docs/bellwether_audit.md's opportunity map) and stays on the
    identical mock draw MockMarketData would have produced from the same rng
    — this class wraps a MockMarketData instance rather than reimplementing
    those draws, so nothing about the non-real fields' distribution changes.

    Soft dependency on nero_core: the import happens inside snapshot(), not
    at module load time, so this subpackage stays importable (and its own
    test suite stays green) even when nero_core isn't on the path — e.g.
    when bellwether is exercised fully standalone, outside the Vatican repo.
    If the import or the live/cached fetch fails for any reason
    (nero_core not importable, no cache and no FRED_API_KEY, or a genuine
    fetch error), real_yield_10y falls back to the mock draw too and is
    labelled `synthetic`, never a guessed real-looking number — matching
    this codebase's own "never fabricate, never guess" discipline
    (nero_core.data_sources.macro_data.MacroDataUnavailableError's own
    contract)."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self._mock = MockMarketData(rng)

    def snapshot(self) -> MarketSnapshot:
        from ..schemas import DataProvenance

        base = self._mock.snapshot()
        field_provenance = {
            "gold_price": DataProvenance.SYNTHETIC,
            "btc_price": DataProvenance.SYNTHETIC,
            "dxy": DataProvenance.SYNTHETIC,
            "nominal_yield_10y": DataProvenance.SYNTHETIC,
            "vix": DataProvenance.SYNTHETIC,
            "fed_funds_mid": DataProvenance.SYNTHETIC,
            "move_index": DataProvenance.SYNTHETIC,
        }

        real_yield_10y = base.real_yield_10y
        try:
            real_yield_10y = _fetch_real_dfii10_level()
            field_provenance["real_yield_10y"] = DataProvenance.REAL
        except Exception:
            field_provenance["real_yield_10y"] = DataProvenance.SYNTHETIC

        field_provenance["dxy"] = DataProvenance.SYNTHETIC  # see class docstring

        return MarketSnapshot(
            gold_price=base.gold_price,
            btc_price=base.btc_price,
            dxy=base.dxy,
            real_yield_10y=round(real_yield_10y, 3),
            nominal_yield_10y=base.nominal_yield_10y,
            vix=base.vix,
            fed_funds_mid=base.fed_funds_mid,
            move_index=base.move_index,
            field_provenance=field_provenance,
        )


def _fetch_real_dfii10_level() -> float:
    """The most recently USABLE (already lag-shifted) DFII10 level, reusing
    nero_core.data_sources.macro_data unmodified — same cache, same
    DFII10_LAG_BUSINESS_DAYS=2 convention that module's own
    compute_lagged_change uses for its 20-day-CHANGE computation, applied
    here to the raw LEVEL instead (monetary_policy.py wants a level to
    compare against its own `_REAL_YIELD_NEUTRAL` anchor, not a change).
    Raises whatever nero_core.data_sources.macro_data.fetch_dfii10_daily
    raises (MacroDataUnavailableError, or ImportError if nero_core isn't on
    the path) — callers must catch and fall back, never guess a substitute."""
    from nero_core.data_sources.macro_data import DFII10_LAG_BUSINESS_DAYS, fetch_dfii10_daily

    series, _source_label = fetch_dfii10_daily()
    lagged = series.shift(DFII10_LAG_BUSINESS_DAYS).dropna()
    if lagged.empty:
        raise ValueError("DFII10 series has no usable observation after applying the lag buffer")
    return float(lagged.iloc[-1])


# --------------------------------------------------------------------------- #
# Hub
# --------------------------------------------------------------------------- #
@dataclass
class DataHub:
    market: MarketDataProvider
    calendar: CalendarProvider
    onchain: OnChainProvider
    derivatives: DerivativesProvider
    etf: EtfFlowProvider
    rng: random.Random = field(default_factory=random.Random)


def build_data_hub(settings: Settings | None = None) -> DataHub:
    s = settings or get_settings()
    rng = random.Random(s.seed)
    if s.data_mode == "mock":
        return DataHub(
            market=MockMarketData(rng),
            calendar=MockCalendar(rng),
            onchain=MockOnChain(rng),
            derivatives=MockDerivatives(rng),
            etf=MockEtfFlows(rng),
            rng=rng,
        )
    if s.data_mode == "live":
        # VATICAN INTEGRATION (Stage 2, docs/bellwether_audit.md): only
        # `market` (specifically real_yield_10y) has a real provider so
        # far — calendar/onchain/derivatives/etf stay on the same mock
        # providers as "mock" mode until a later increment wires them,
        # per the audit's own priority order (monetary_policy -> VIX ->
        # funding rate -> everything else). This is deliberate partial
        # coverage, not an oversight: "live" means "real where real
        # exists, honestly labelled mock everywhere else" (see
        # VaticanRealMarketData's own field_provenance), never a silent
        # promise that every field is real.
        return DataHub(
            market=VaticanRealMarketData(rng),
            calendar=MockCalendar(rng),
            onchain=MockOnChain(rng),
            derivatives=MockDerivatives(rng),
            etf=MockEtfFlows(rng),
            rng=rng,
        )
    raise NotImplementedError(
        f"data_mode='{s.data_mode}' has no provider wiring yet. "
        "Implement live providers and register them here."
    )
