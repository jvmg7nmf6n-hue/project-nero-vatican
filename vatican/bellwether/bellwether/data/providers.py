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

    dxy is now ALSO real (added after a dedicated availability check, see
    docs/bellwether_stage2_report.md): NOT sourced via Vatican's own
    macro_data.fetch_dollar_proxy_daily — that pipeline is cascaded through
    Twelve Data, where DXY is confirmed NOT a valid symbol
    (docs/macro_risk_on_report.md: "DXY is not a valid Twelve Data symbol...
    symbol or figi parameter is missing or invalid"), which is WHY
    MACRO_RISK_ON's own dollar leg fell back to UUP (an ETF price, ~$28) in
    the first place — a genuine provider limitation, not a quality
    preference, and confirmed documented rather than assumed. Feeding UUP's
    price into a formula anchored at `_DXY_NEUTRAL = 104.0`
    (bellwether/agents/monetary_policy.py) would silently produce a
    nonsense dxy_gap (off by a factor of ~4) — worse than staying mock,
    since it would look confidently real while being wrong. Instead, dxy is
    sourced directly via yfinance's `DX-Y.NYB` (ICE US Dollar Index) — a
    DIFFERENT provider than macro_data.py's own, confirmed live 2026-08-07:
    14,116 daily rows back to 1971, free, no key, current level ~99.9 —
    genuinely DXY-index-scale, no unit mismatch. monetary_policy.py's own
    formula is UNCHANGED; this was a data-sourcing fix, not a formula
    rewrite, per the availability check landing on option (a).

    real_yield_10y has no such issue: DFII10 is already a genuine %
    real-yield level, exactly the units monetary_policy.py's own
    `_REAL_YIELD_NEUTRAL = 1.8` anchor expects.

    vix is now ALSO real (audit priority-2, same session as dxy): yfinance's
    `^VIX` (CBOE Volatility Index) — confirmed live 2026-08-07, free, no
    key, 9,217 daily rows back to 1990, same t+1 execution-buffer treatment
    as dxy (market-quoted level, not a genuine-reporting-lag series). This
    is the SAME field `liquidity.py`'s risk-appetite score and
    `risk.py`'s "elevated volatility regime" check both already read —
    both become real automatically, no further code change needed in
    either, since both already gate on `ctx.market.provenance_of("vix")`
    or the equivalent per-agent provenance mechanism.

    Every other MarketSnapshot field (gold_price, btc_price,
    nominal_yield_10y, fed_funds_mid, move_index) has no real Vatican source
    yet (see docs/bellwether_audit.md's opportunity map) and stays on the
    identical mock draw MockMarketData would have produced from the same rng
    — this class wraps a MockMarketData instance rather than reimplementing
    those draws, so nothing about the non-real fields' distribution changes.

    Soft dependencies: the real_yield_10y fetch imports nero_core inside
    snapshot(), not at module load time (so this subpackage stays importable
    standalone, nero_core or not); the dxy/vix fetches import yfinance the
    same way (yfinance is not in this subpackage's own requirements.txt —
    it's a soft dependency exactly like nero_core, degrading to the mock
    draw rather than raising ImportError). If any fetch fails for any reason
    (import failure, no cache and no credentials, a genuine network/data
    error), that field falls back to the mock draw and is labelled
    `synthetic`, never a guessed real-looking number — matching this
    codebase's own "never fabricate, never guess" discipline
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

        dxy = base.dxy
        try:
            dxy = _fetch_real_dxy_level_cached()
            field_provenance["dxy"] = DataProvenance.REAL
        except Exception:
            field_provenance["dxy"] = DataProvenance.SYNTHETIC

        vix = base.vix
        try:
            vix = _fetch_real_vix_level_cached()
            field_provenance["vix"] = DataProvenance.REAL
        except Exception:
            field_provenance["vix"] = DataProvenance.SYNTHETIC

        return MarketSnapshot(
            gold_price=base.gold_price,
            btc_price=base.btc_price,
            dxy=round(dxy, 3),
            real_yield_10y=round(real_yield_10y, 3),
            nominal_yield_10y=base.nominal_yield_10y,
            vix=round(vix, 3),
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


# Process-lifetime cache: DXY doesn't move intraday between two calls in the
# same run (e.g. a sweep of many Orchestrator cycles), and yfinance/Yahoo
# rate-limits aggressively under repeated back-to-back requests (the exact
# behavior nero_core.data_sources.market_data.YFINANCE_RETRY_DELAYS_SECONDS's
# own comment documents). This is NOT a disk cache like macro_data.py's own
# CSV convention — a future scheduled-job increment should add one if this
# ever runs outside a single short-lived process; flagged, not built here,
# since nothing in this integration runs on a schedule yet.
_DXY_CACHE: dict[str, float] = {}

# Matches nero_core.data_sources.macro_data.DOLLAR_LAG_BUSINESS_DAYS's own
# convention exactly (a market-quoted price is public the moment the market
# closes; the 1-day buffer is this codebase's standard "act only on an
# already-closed candle" rule, not a genuine reporting lag the way DFII10
# has one) — reimplemented as a literal here rather than imported, since
# this fetch deliberately does NOT go through macro_data.py at all (see
# VaticanRealMarketData's own class docstring on why).
_DXY_LAG_BUSINESS_DAYS = 1


def _fetch_real_dxy_level_cached() -> float:
    if "value" not in _DXY_CACHE:
        _DXY_CACHE["value"] = _fetch_real_dxy_level()
    return _DXY_CACHE["value"]


def _fetch_real_dxy_level() -> float:
    """Real, DXY-index-scale (~90-110) dollar strength level via yfinance's
    `DX-Y.NYB` (ICE US Dollar Index) — confirmed live 2026-08-07, free, no
    key, 14,116 daily rows back to 1971. See VaticanRealMarketData's own
    class docstring for why this does NOT reuse
    nero_core.data_sources.macro_data's dollar-proxy pipeline (DXY isn't a
    valid Twelve Data symbol at all, confirmed in
    docs/macro_risk_on_report.md). Raises on any failure (empty response,
    yfinance not importable, network error) — callers must catch and fall
    back, never guess a substitute."""
    import yfinance as yf

    ticker = yf.Ticker("DX-Y.NYB")
    history = ticker.history(period="30d", interval="1d")
    if history.empty:
        raise ValueError("empty yfinance response for DX-Y.NYB")
    lagged = history["Close"].shift(_DXY_LAG_BUSINESS_DAYS).dropna()
    if lagged.empty:
        raise ValueError("DX-Y.NYB series has no usable observation after applying the lag buffer")
    return float(lagged.iloc[-1])


# Same process-lifetime-cache / t+1-lag rationale as the dxy fetch above —
# VIX is also a market-quoted level (CBOE Volatility Index), same
# "public the moment the market closes, standard 1-day execution buffer"
# category as DXY, not a genuine-reporting-lag series like DFII10.
_VIX_CACHE: dict[str, float] = {}
_VIX_LAG_BUSINESS_DAYS = 1


def _fetch_real_vix_level_cached() -> float:
    if "value" not in _VIX_CACHE:
        _VIX_CACHE["value"] = _fetch_real_vix_level()
    return _VIX_CACHE["value"]


def _fetch_real_vix_level() -> float:
    """Real VIX level via yfinance's `^VIX` (CBOE Volatility Index) —
    confirmed live 2026-08-07: free, no key, 9,217 daily rows back to 1990,
    current level ~15-16 (matches MockMarketData's own calm-regime range,
    coincidentally, but this is a live fetch, not a tuned match). Raises on
    any failure — callers must catch and fall back, never guess a
    substitute."""
    import yfinance as yf

    ticker = yf.Ticker("^VIX")
    history = ticker.history(period="30d", interval="1d")
    if history.empty:
        raise ValueError("empty yfinance response for ^VIX")
    lagged = history["Close"].shift(_VIX_LAG_BUSINESS_DAYS).dropna()
    if lagged.empty:
        raise ValueError("^VIX series has no usable observation after applying the lag buffer")
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
