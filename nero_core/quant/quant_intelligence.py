from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class GarchVolatilityReport:
    asset: str
    model: str
    conditional_vol: float
    realized_vol_30d: float
    realized_vol_90d: float
    vol_ratio: float
    regime: str
    shock_score: float
    rows: list[dict[str, str]]
    notes: list[str]

@dataclass(frozen=True)
class QuantConsensusReport:
    asset: str
    score: float
    label: str
    bias: str
    rows: list[dict[str, str]]
    notes: list[str]

@dataclass(frozen=True)
class QuantSnapshot:
    asset: str
    source: str
    latest_close: float
    observation_count: int
    zscore_20: float
    realized_vol_30d: float
    realized_vol_90d: float
    sharpe_90d: float
    sortino_90d: float
    max_drawdown_90d: float
    trend_20d: float
    trend_60d: float
    regime: str
    pressure: str
    notes: list[str]


def log_returns(prices: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    cleaned = prices.replace(0, np.nan).astype(float)
    return np.log(cleaned / cleaned.shift(1)).replace([np.inf, -np.inf], np.nan).dropna(how="all")


def rolling_correlation(returns: pd.DataFrame, asset_x: str, asset_y: str, window: int = 60) -> pd.Series:
    return returns[asset_x].rolling(window).corr(returns[asset_y])


def rolling_beta(returns: pd.DataFrame, asset: str, benchmark: str, window: int = 60) -> pd.Series:
    cov = returns[asset].rolling(window).cov(returns[benchmark])
    var = returns[benchmark].rolling(window).var()
    return cov / var.replace(0, np.nan)


def zscore(prices: pd.Series, window: int = 20) -> pd.Series:
    price = pd.to_numeric(prices, errors="coerce")
    mean = price.rolling(window).mean()
    std = price.rolling(window).std()
    return (price - mean) / std.replace(0, np.nan)


def realized_volatility(returns: pd.Series, window: int = 30, annualize: bool = True) -> pd.Series:
    vol = pd.to_numeric(returns, errors="coerce").rolling(window).std()
    return vol * np.sqrt(252) if annualize else vol

def build_garch_volatility_report(price_history: pd.DataFrame, asset: str) -> GarchVolatilityReport:
    prices = _clean_price_history(price_history)
    if prices.empty or len(prices) < 60:
        return GarchVolatilityReport(asset, "none", 0.0, 0.0, 0.0, 0.0, "NO_DATA", 0.0, [], ["Not enough price history for volatility clustering analysis."])

    returns = pd.to_numeric(log_returns(prices["close"]), errors="coerce").dropna()
    if len(returns) < 60:
        return GarchVolatilityReport(asset, "none", 0.0, 0.0, 0.0, 0.0, "NO_DATA", 0.0, [], ["Not enough returns for volatility clustering analysis."])

    vol30 = _latest(realized_volatility(returns, 30))
    vol90 = _latest(realized_volatility(returns, 90))
    conditional_vol, model, model_note = _estimate_garch_conditional_vol(returns)
    baseline = vol90 if vol90 > 0 else vol30
    vol_ratio = conditional_vol / baseline if baseline > 0 else 0.0
    shock_score = min(100.0, max(0.0, vol_ratio * 50.0))
    regime = _classify_garch_regime(vol_ratio, conditional_vol)
    rows = [
        {"Signal": "Model", "Reading": model, "Meaning": "GARCH(1,1) when arch is installed; EWMA fallback otherwise."},
        {"Signal": "Conditional Vol", "Reading": f"{conditional_vol:.1%}", "Meaning": "Forward-looking volatility estimate from recent clustering."},
        {"Signal": "30D Realized Vol", "Reading": f"{vol30:.1%}", "Meaning": "Recent actual volatility baseline."},
        {"Signal": "90D Realized Vol", "Reading": f"{vol90:.1%}", "Meaning": "Medium-term actual volatility baseline."},
        {"Signal": "Vol Ratio", "Reading": f"{vol_ratio:.2f}x", "Meaning": "Conditional volatility versus medium-term baseline."},
        {"Signal": "Shock Score", "Reading": f"{shock_score:.0f}/100", "Meaning": "Higher score means volatility clustering risk is elevated."},
        {"Signal": "Volatility Regime", "Reading": regime, "Meaning": "NERO risk filter for trade quality and position caution."},
    ]
    notes = _garch_notes(regime, vol_ratio, model_note)
    return GarchVolatilityReport(asset, model, conditional_vol, vol30, vol90, vol_ratio, regime, shock_score, rows, notes)

def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    excess = clean - risk_free_rate / periods_per_year
    std = excess.std()
    if pd.isna(std) or std == 0:
        return 0.0
    return float(np.sqrt(periods_per_year) * excess.mean() / std)


def sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    excess = clean - risk_free_rate / periods_per_year
    downside = excess[excess < 0]
    downside_std = downside.std()
    if pd.isna(downside_std) or downside_std == 0:
        return 0.0
    return float(np.sqrt(periods_per_year) * excess.mean() / downside_std)


def max_drawdown(cumulative_returns: pd.Series) -> float:
    clean = pd.to_numeric(cumulative_returns, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    running_max = clean.cummax()
    drawdown = (clean - running_max) / running_max.replace(0, np.nan)
    return float(drawdown.min()) if not drawdown.dropna().empty else 0.0


def information_coefficient(predicted_returns: pd.Series, actual_returns: pd.Series) -> float:
    frame = pd.concat([predicted_returns, actual_returns], axis=1).dropna()
    if len(frame) < 3:
        return 0.0
    value = frame.iloc[:, 0].rank().corr(frame.iloc[:, 1].rank())
    return 0.0 if pd.isna(value) else float(value)


def build_quant_snapshot(price_history: pd.DataFrame, asset: str, source: str = "local prices") -> QuantSnapshot:
    prices = _clean_price_history(price_history)
    if prices.empty:
        return QuantSnapshot(asset, source, 0.0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, "NO_DATA", "unknown", ["No usable price history."])

    close = prices["close"]
    returns = log_returns(close)
    z20 = _latest(zscore(close, 20))
    vol30 = _latest(realized_volatility(returns, 30))
    vol90 = _latest(realized_volatility(returns, 90))
    ret90 = returns.tail(90)
    cumulative_90 = (1 + ret90).cumprod()
    trend20 = _window_return(close, 20)
    trend60 = _window_return(close, 60)
    snapshot = QuantSnapshot(
        asset=asset,
        source=source,
        latest_close=float(close.iloc[-1]),
        observation_count=len(prices),
        zscore_20=z20,
        realized_vol_30d=vol30,
        realized_vol_90d=vol90,
        sharpe_90d=sharpe_ratio(ret90),
        sortino_90d=sortino_ratio(ret90),
        max_drawdown_90d=max_drawdown(cumulative_90),
        trend_20d=trend20,
        trend_60d=trend60,
        regime=_classify_regime(trend20, trend60, vol30),
        pressure=_classify_pressure(z20, trend20, trend60),
        notes=[],
    )
    return _with_notes(snapshot)


def build_quant_consensus_report(
    snapshot: QuantSnapshot,
    garch_report: GarchVolatilityReport | None = None,
    driver_report: CrossAssetDriverReport | None = None,
    kalman_report: KalmanBetaReport | None = None,
    granger_report: GrangerCausalityReport | None = None,
) -> QuantConsensusReport:
    score = 50.0
    rows: list[dict[str, str]] = []

    trend_score = 0.0
    if snapshot.trend_20d > 0 and snapshot.trend_60d > 0:
        trend_score = 12.0
    elif snapshot.trend_20d < 0 and snapshot.trend_60d < 0:
        trend_score = -12.0
    elif snapshot.trend_20d > 0:
        trend_score = 5.0
    elif snapshot.trend_20d < 0:
        trend_score = -5.0
    score += trend_score
    rows.append({"Component": "Trend", "Impact": f"{trend_score:+.0f}", "Reading": f"20D {snapshot.trend_20d:.1%}, 60D {snapshot.trend_60d:.1%}", "Meaning": "Aligned trend improves quant environment; aligned downside weakens it."})

    risk_quality_score = 0.0
    if snapshot.sharpe_90d > 0.75:
        risk_quality_score = 10.0
    elif snapshot.sharpe_90d > 0.25:
        risk_quality_score = 5.0
    elif snapshot.sharpe_90d < -0.75:
        risk_quality_score = -10.0
    elif snapshot.sharpe_90d < 0:
        risk_quality_score = -5.0
    score += risk_quality_score
    rows.append({"Component": "Risk-adjusted Return", "Impact": f"{risk_quality_score:+.0f}", "Reading": f"90D Sharpe {snapshot.sharpe_90d:.2f}", "Meaning": "Positive Sharpe means recent returns paid for volatility."})

    stretch_score = 0.0
    if abs(snapshot.zscore_20) >= 2.5:
        stretch_score = -8.0
    elif abs(snapshot.zscore_20) >= 2.0:
        stretch_score = -5.0
    elif abs(snapshot.zscore_20) <= 1.0:
        stretch_score = 3.0
    score += stretch_score
    rows.append({"Component": "Stretch", "Impact": f"{stretch_score:+.0f}", "Reading": f"20D Z {snapshot.zscore_20:.2f}", "Meaning": "Extreme stretch reduces signal quality unless confirmed by other modules."})

    vol_score = 0.0
    if garch_report is not None:
        if garch_report.regime == "VOL_STRESS":
            vol_score = -15.0
        elif garch_report.regime == "VOL_ELEVATED":
            vol_score = -8.0
        elif garch_report.regime == "VOL_NORMAL":
            vol_score = 5.0
        elif garch_report.regime == "VOL_COMPRESSED":
            vol_score = 2.0
        score += vol_score
        rows.append({"Component": "Volatility", "Impact": f"{vol_score:+.0f}", "Reading": f"{garch_report.regime}, shock {garch_report.shock_score:.0f}/100", "Meaning": "Normal volatility supports cleaner signals; stress volatility penalizes them."})

    driver_score = 0.0
    if driver_report is not None and driver_report.rows:
        corr = driver_report.strongest_correlation
        if abs(corr) >= 0.65:
            driver_score = 8.0
        elif abs(corr) >= 0.35:
            driver_score = 4.0
        score += driver_score
        rows.append({"Component": "Cross-asset Driver", "Impact": f"{driver_score:+.0f}", "Reading": f"{driver_report.strongest_driver} corr {corr:.2f}", "Meaning": "A clear dominant driver makes the regime easier to interpret."})

    kalman_score = 0.0
    if kalman_report is not None and kalman_report.rows:
        if abs(kalman_report.beta_change) >= 0.25:
            kalman_score = -4.0
        elif abs(kalman_report.latest_beta) >= 0.35:
            kalman_score = 5.0
        score += kalman_score
        rows.append({"Component": "Dynamic Beta", "Impact": f"{kalman_score:+.0f}", "Reading": f"{kalman_report.strongest_dynamic_driver} beta {kalman_report.latest_beta:.2f}, change {kalman_report.beta_change:+.2f}", "Meaning": "Stable dynamic beta improves trust in driver readings; abrupt beta shifts reduce clarity."})

    granger_score = 0.0
    if granger_report is not None and granger_report.rows and granger_report.strongest_pvalue is not None:
        if granger_report.strongest_pvalue < 0.05:
            granger_score = 8.0
        elif granger_report.strongest_pvalue < 0.15:
            granger_score = 3.0
        score += granger_score
        rows.append({"Component": "Predictive Evidence", "Impact": f"{granger_score:+.0f}", "Reading": f"{granger_report.strongest_predictor} p={granger_report.strongest_pvalue:.4f}", "Meaning": "Formal predictive evidence upgrades confidence; weak/no evidence keeps confidence modest."})

    score = min(100.0, max(0.0, score))
    label = _quant_consensus_label(score)
    bias = _quant_consensus_bias(snapshot, score)
    notes = _quant_consensus_notes(score, label, rows)
    return QuantConsensusReport(snapshot.asset, score, label, bias, rows, notes)

def _quant_consensus_label(score: float) -> str:
    if score >= 70:
        return "QUANT_SUPPORTIVE"
    if score >= 55:
        return "QUANT_MILD_SUPPORT"
    if score >= 45:
        return "QUANT_NEUTRAL"
    if score >= 30:
        return "QUANT_WEAK"
    return "QUANT_HOSTILE"


def _quant_consensus_bias(snapshot: QuantSnapshot, score: float) -> str:
    if score < 45:
        return "NO_TRADE_FILTER"
    if snapshot.trend_20d > 0 and snapshot.trend_60d > 0:
        return "LONG_BIAS_IF_CONFIRMED"
    if snapshot.trend_20d < 0 and snapshot.trend_60d < 0:
        return "SHORT_RISK_OR_AVOID_LONGS"
    return "WAIT_FOR_CONFIRMATION"


def _quant_consensus_notes(score: float, label: str, rows: list[dict[str, str]]) -> list[str]:
    notes = [f"Final quant environment: {label} at {score:.0f}/100."]
    if score >= 70:
        notes.append("Quant evidence is broadly supportive, but NERO still needs news, regime, and trade-trigger confirmation.")
    elif score < 45:
        notes.append("Quant evidence is weak; NERO should avoid forcing trades unless other modules provide exceptional confirmation.")
    else:
        notes.append("Quant evidence is mixed; use it as a filter, not as a standalone trade signal.")
    if not rows:
        notes.append("Consensus has limited inputs; refresh cross-asset drivers for a fuller score.")
    return notes

def quant_driver_rows(snapshot: QuantSnapshot) -> list[dict[str, str]]:
    return [
        {"Signal": "20D Z-Score", "Reading": f"{snapshot.zscore_20:.2f}", "Meaning": "Positive = stretched above mean, negative = below mean."},
        {"Signal": "30D Realized Vol", "Reading": f"{snapshot.realized_vol_30d:.1%}", "Meaning": "Annualized volatility; higher vol demands stricter trade quality."},
        {"Signal": "90D Realized Vol", "Reading": f"{snapshot.realized_vol_90d:.1%}", "Meaning": "Medium-term volatility baseline."},
        {"Signal": "20D Return", "Reading": f"{snapshot.trend_20d:.1%}", "Meaning": "Short-term trend pressure."},
        {"Signal": "60D Return", "Reading": f"{snapshot.trend_60d:.1%}", "Meaning": "Broader trend direction."},
        {"Signal": "90D Sharpe", "Reading": f"{snapshot.sharpe_90d:.2f}", "Meaning": "Recent return quality adjusted for volatility."},
        {"Signal": "90D Sortino", "Reading": f"{snapshot.sortino_90d:.2f}", "Meaning": "Recent return quality adjusted for downside volatility."},
        {"Signal": "90D Max Drawdown", "Reading": f"{snapshot.max_drawdown_90d:.1%}", "Meaning": "Worst recent equity curve drop from peak."},
        {"Signal": "Quant Regime", "Reading": snapshot.regime, "Meaning": "Statistical environment from trend and volatility."},
        {"Signal": "Pressure", "Reading": snapshot.pressure, "Meaning": "Mean-reversion/trend pressure summary."},
    ]


def _clean_price_history(price_history: pd.DataFrame) -> pd.DataFrame:
    if price_history.empty or "close" not in price_history.columns:
        return pd.DataFrame(columns=["date", "close"])
    frame = price_history.copy()
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.sort_values("date")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    return frame.dropna(subset=["close"]).reset_index(drop=True)


def _window_return(close: pd.Series, window: int) -> float:
    if len(close) <= window:
        return 0.0
    start = float(close.iloc[-window - 1])
    end = float(close.iloc[-1])
    return (end / start) - 1 if start else 0.0


def _latest(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    return float(clean.iloc[-1])


def _classify_regime(trend20: float, trend60: float, vol30: float) -> str:
    if vol30 >= 0.75:
        vol = "High-Vol"
    elif vol30 <= 0.25:
        vol = "Low-Vol"
    else:
        vol = "Normal-Vol"
    if trend20 > 0.03 and trend60 > 0.05:
        trend = "Bull"
    elif trend20 < -0.03 and trend60 < -0.05:
        trend = "Bear"
    else:
        trend = "Range"
    return f"{trend} / {vol}"


def _classify_pressure(z20: float, trend20: float, trend60: float) -> str:
    if z20 <= -2 and trend60 > 0:
        return "mean-reversion long watch"
    if z20 >= 2 and trend60 < 0:
        return "mean-reversion short risk"
    if trend20 > 0 and trend60 > 0:
        return "upside trend pressure"
    if trend20 < 0 and trend60 < 0:
        return "downside trend pressure"
    return "mixed pressure"


def _with_notes(snapshot: QuantSnapshot) -> QuantSnapshot:
    notes: list[str] = []
    if snapshot.observation_count < 90:
        notes.append("Less than 90 candles; medium-term stats are weak.")
    if snapshot.realized_vol_30d > snapshot.realized_vol_90d * 1.25 and snapshot.realized_vol_90d > 0:
        notes.append("30D volatility is materially above 90D baseline.")
    if abs(snapshot.zscore_20) >= 2:
        notes.append("20D z-score is stretched; avoid chasing without confirmation.")
    if snapshot.sharpe_90d < 0:
        notes.append("90D risk-adjusted return is negative.")
    if not notes:
        notes.append("No major quant warning from local price statistics.")
    return QuantSnapshot(
        asset=snapshot.asset,
        source=snapshot.source,
        latest_close=snapshot.latest_close,
        observation_count=snapshot.observation_count,
        zscore_20=snapshot.zscore_20,
        realized_vol_30d=snapshot.realized_vol_30d,
        realized_vol_90d=snapshot.realized_vol_90d,
        sharpe_90d=snapshot.sharpe_90d,
        sortino_90d=snapshot.sortino_90d,
        max_drawdown_90d=snapshot.max_drawdown_90d,
        trend_20d=snapshot.trend_20d,
        trend_60d=snapshot.trend_60d,
        regime=snapshot.regime,
        pressure=snapshot.pressure,
        notes=notes,
    )


def _estimate_garch_conditional_vol(returns: pd.Series) -> tuple[float, str, str]:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        return 0.0, "none", "No usable returns for volatility model."
    try:
        from arch import arch_model
    except ModuleNotFoundError:
        return _ewma_conditional_vol(clean), "EWMA fallback", "arch package is not installed; using EWMA fallback instead of GARCH(1,1)."
    try:
        scaled = clean * 100.0
        model = arch_model(scaled, mean="Zero", vol="GARCH", p=1, q=1, rescale=False)
        fitted = model.fit(disp="off", show_warning=False)
        forecast = fitted.forecast(horizon=1, reindex=False)
        variance = float(forecast.variance.iloc[-1, 0])
        daily_vol = np.sqrt(max(variance, 0.0)) / 100.0
        return float(daily_vol * np.sqrt(252)), "GARCH(1,1)", "GARCH(1,1) conditional volatility estimated successfully."
    except Exception as exc:
        return _ewma_conditional_vol(clean), "EWMA fallback", f"GARCH fit failed ({exc.__class__.__name__}); using EWMA fallback."


def _ewma_conditional_vol(returns: pd.Series, decay: float = 0.94) -> float:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    variance = float(clean.var()) if not pd.isna(clean.var()) else 0.0
    for value in clean.tail(252):
        variance = decay * variance + (1 - decay) * float(value) ** 2
    return float(np.sqrt(max(variance, 0.0)) * np.sqrt(252))


def _classify_garch_regime(vol_ratio: float, conditional_vol: float) -> str:
    if conditional_vol >= 0.90 or vol_ratio >= 1.50:
        return "VOL_STRESS"
    if conditional_vol >= 0.60 or vol_ratio >= 1.20:
        return "VOL_ELEVATED"
    if conditional_vol <= 0.25 and vol_ratio <= 0.80:
        return "VOL_COMPRESSED"
    return "VOL_NORMAL"


def _garch_notes(regime: str, vol_ratio: float, model_note: str) -> list[str]:
    notes = [model_note]
    if regime == "VOL_STRESS":
        notes.append("Volatility clustering is stressed; NERO should demand stronger confirmation and smaller paper risk.")
    elif regime == "VOL_ELEVATED":
        notes.append("Volatility is elevated versus baseline; avoid low-quality signals.")
    elif regime == "VOL_COMPRESSED":
        notes.append("Volatility is compressed; breakout risk can build after quiet regimes.")
    else:
        notes.append("Volatility clustering is near normal baseline.")
    if vol_ratio >= 1.20:
        notes.append(f"Conditional volatility is {vol_ratio:.2f}x the recent baseline.")
    return notes

QUANT_DRIVER_TICKERS = {
    "BTC": {
        "btc": "BTC-USD",
        "dxy": "DX-Y.NYB",
        "spx": "^GSPC",
        "nasdaq": "^IXIC",
        "mstr": "MSTR",
        "coinbase": "COIN",
        "ibit": "IBIT",
        "gbtc": "GBTC",
        "mara": "MARA",
        "riot": "RIOT",
    },
    "GOLD": {
        "gold": "GC=F",
        "dxy": "DX-Y.NYB",
        "spx": "^GSPC",
        "us10y": "^TNX",
        "gold_etf": "GLD",
        "gold_miners": "GDX",
        "newmont": "NEM",
        "barrick": "GOLD",
    },
}


@dataclass(frozen=True)
class CrossAssetDriverReport:
    asset: str
    source: str
    rows: list[dict[str, str]]
    strongest_driver: str
    strongest_correlation: float
    notes: list[str]


@dataclass(frozen=True)
class LeadLagDriverReport:
    asset: str
    rows: list[dict[str, str]]
    strongest_leader: str
    strongest_lag_days: int
    strongest_lead_correlation: float
    notes: list[str]


@dataclass(frozen=True)
class CointegrationReport:
    asset: str
    rows: list[dict[str, str]]
    strongest_pair: str
    strongest_pvalue: float | None
    notes: list[str]


@dataclass(frozen=True)
class KalmanBetaReport:
    asset: str
    rows: list[dict[str, str]]
    strongest_dynamic_driver: str
    latest_beta: float
    beta_change: float
    notes: list[str]

@dataclass(frozen=True)
class GrangerCausalityReport:
    asset: str
    rows: list[dict[str, str]]
    strongest_predictor: str
    strongest_lag: int
    strongest_pvalue: float | None
    notes: list[str]


def fetch_cross_asset_price_data(asset: str, start: str = "2024-01-01", interval: str = "1d") -> tuple[pd.DataFrame, str]:
    """Fetch cross-asset daily prices lazily. Dashboard remains usable if yfinance is absent."""
    tickers = QUANT_DRIVER_TICKERS.get(asset.upper())
    if not tickers:
        return pd.DataFrame(), f"No cross-asset ticker map for {asset}."
    try:
        import yfinance as yf
    except ModuleNotFoundError:
        return pd.DataFrame(), "yfinance is not installed; run pip install -r requirements.txt to enable live cross-asset drivers."

    frames: dict[str, pd.Series] = {}
    warnings: list[str] = []
    for name, ticker in tickers.items():
        try:
            raw = yf.download(ticker, start=start, interval=interval, progress=False, auto_adjust=True, threads=False)
        except Exception as exc:  # pragma: no cover - external feed behavior
            warnings.append(f"{name}:{exc.__class__.__name__}")
            continue
        if raw is None or raw.empty or "Close" not in raw:
            warnings.append(f"{name}:empty")
            continue
        close = raw["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        frames[name] = pd.to_numeric(close, errors="coerce")
    if not frames:
        return pd.DataFrame(), "No cross-asset prices fetched from yfinance."
    prices = pd.DataFrame(frames).ffill().dropna(how="all")
    suffix = f"; skipped {', '.join(warnings[:5])}" if warnings else ""
    return prices, f"yfinance daily closes{suffix}"


def build_cross_asset_driver_report(asset: str, prices: pd.DataFrame, windows: tuple[int, ...] = (30, 60, 90)) -> CrossAssetDriverReport:
    if prices.empty or len(prices.columns) == 0:
        return CrossAssetDriverReport(asset, "cross-asset prices", [], "none", 0.0, ["No cross-asset price data returned by the provider."])
    asset_key = _asset_price_column(asset, prices)
    if asset_key not in prices.columns:
        return CrossAssetDriverReport(asset, "cross-asset prices", [], "none", 0.0, ["No matching asset column found for cross-asset analysis."])
    returns = log_returns(prices).dropna(how="all")
    if asset_key not in returns.columns or len(returns) < min(windows):
        return CrossAssetDriverReport(asset, "cross-asset prices", [], "none", 0.0, ["Not enough return history for rolling driver analysis."])

    rows: list[dict[str, str]] = []
    rank_window = 60 if 60 in windows else max(windows)
    strongest_driver = "none"
    strongest_correlation = 0.0
    for driver in returns.columns:
        if driver == asset_key:
            continue
        row: dict[str, str] = {"Driver": driver}
        latest_corr_for_rank = 0.0
        for window in windows:
            if len(returns[[asset_key, driver]].dropna()) < window:
                corr_value = 0.0
                beta_value = 0.0
            else:
                corr_value = _latest(rolling_correlation(returns, asset_key, driver, window))
                beta_value = _latest(rolling_beta(returns, asset_key, driver, window))
            row[f"Corr {window}D"] = f"{corr_value:.2f}"
            row[f"Beta {window}D"] = f"{beta_value:.2f}"
            if window == rank_window:
                latest_corr_for_rank = corr_value
        row["Reading"] = _driver_reading(latest_corr_for_rank)
        rows.append(row)
        if abs(latest_corr_for_rank) > abs(strongest_correlation):
            strongest_driver = driver
            strongest_correlation = latest_corr_for_rank

    rank_column = f"Corr {rank_window}D"
    rows.sort(key=lambda item: abs(float(item.get(rank_column, "0") or 0)), reverse=True)
    notes = _cross_asset_notes(strongest_driver, strongest_correlation, rows, rank_window)
    return CrossAssetDriverReport(asset, "cross-asset prices", rows, strongest_driver, strongest_correlation, notes)

def _asset_price_column(asset: str, prices: pd.DataFrame) -> str:
    if prices.empty or len(prices.columns) == 0:
        return ""
    asset_upper = asset.upper()
    if asset_upper == "BTC" and "btc" in prices.columns:
        return "btc"
    if asset_upper == "GOLD" and "gold" in prices.columns:
        return "gold"
    lowered = asset.lower()
    return lowered if lowered in prices.columns else str(prices.columns[0])

def _driver_reading(correlation: float) -> str:
    if correlation >= 0.65:
        return "strong positive linkage"
    if correlation >= 0.35:
        return "moderate positive linkage"
    if correlation <= -0.65:
        return "strong inverse linkage"
    if correlation <= -0.35:
        return "moderate inverse linkage"
    return "weak / unstable linkage"


def _cross_asset_notes(strongest_driver: str, strongest_correlation: float, rows: list[dict[str, str]], window: int = 60) -> list[str]:
    if not rows:
        return ["No driver rows available."]
    notes = [f"Strongest {window}D linkage: {strongest_driver} at {strongest_correlation:.2f} correlation."]
    if abs(strongest_correlation) < 0.35:
        notes.append("No dominant cross-asset driver; treat the regime as internally driven or noisy.")
    elif strongest_correlation > 0:
        notes.append("Positive linkage means this driver is moving with the asset in the current regime.")
    else:
        notes.append("Inverse linkage means this driver is applying opposite pressure in the current regime.")
    return notes

def kalman_dynamic_beta(asset_returns: pd.Series, driver_returns: pd.Series, process_variance: float = 1e-5, observation_variance: float = 1e-3) -> pd.Series:
    frame = pd.concat([pd.to_numeric(asset_returns, errors="coerce"), pd.to_numeric(driver_returns, errors="coerce")], axis=1).dropna()
    if len(frame) < 10:
        return pd.Series(dtype=float)
    y = frame.iloc[:, 0]
    x = frame.iloc[:, 1]
    beta = 0.0
    variance = 1.0
    values: list[float] = []
    index_values = []
    for idx, x_value, y_value in zip(frame.index, x, y):
        x_float = float(x_value)
        y_float = float(y_value)
        variance += process_variance
        innovation_variance = x_float * x_float * variance + observation_variance
        kalman_gain = variance * x_float / innovation_variance if innovation_variance else 0.0
        beta = beta + kalman_gain * (y_float - beta * x_float)
        variance = (1 - kalman_gain * x_float) * variance
        values.append(float(beta))
        index_values.append(idx)
    return pd.Series(values, index=index_values)


def build_kalman_beta_report(asset: str, prices: pd.DataFrame, min_observations: int = 90) -> KalmanBetaReport:
    if prices.empty or len(prices.columns) == 0:
        return KalmanBetaReport(asset, [], "none", 0.0, 0.0, ["No cross-asset price data available for Kalman dynamic beta analysis."])
    asset_key = _asset_price_column(asset, prices)
    if asset_key not in prices.columns:
        return KalmanBetaReport(asset, [], "none", 0.0, 0.0, ["No matching asset column found for Kalman dynamic beta analysis."])
    returns = log_returns(prices).dropna(how="all")
    if asset_key not in returns.columns or len(returns) < min_observations:
        return KalmanBetaReport(asset, [], "none", 0.0, 0.0, ["Not enough return history for Kalman dynamic beta analysis."])

    rows: list[dict[str, str]] = []
    strongest_driver = "none"
    strongest_latest_beta = 0.0
    strongest_change = 0.0
    for driver in returns.columns:
        if driver == asset_key:
            continue
        clean = returns[[asset_key, driver]].dropna()
        if len(clean) < min_observations:
            continue
        beta_series = kalman_dynamic_beta(clean[asset_key], clean[driver])
        if beta_series.empty:
            continue
        latest_beta = float(beta_series.iloc[-1])
        previous_window = beta_series.iloc[-min(30, len(beta_series))]
        beta_change = latest_beta - float(previous_window)
        stability = float(beta_series.tail(min(30, len(beta_series))).std()) if len(beta_series) > 1 else 0.0
        rows.append(
            {
                "Driver": driver,
                "Latest Beta": f"{latest_beta:.2f}",
                "30D Beta Change": f"{beta_change:+.2f}",
                "Beta Stability": f"{stability:.2f}",
                "Regime": _kalman_beta_regime(latest_beta, beta_change, stability),
                "Reading": _kalman_beta_reading(driver, latest_beta, beta_change, stability),
            }
        )
        if abs(beta_change) > abs(strongest_change) or (abs(beta_change) == abs(strongest_change) and abs(latest_beta) > abs(strongest_latest_beta)):
            strongest_driver = driver
            strongest_latest_beta = latest_beta
            strongest_change = beta_change

    rows.sort(key=lambda item: abs(float(item.get("30D Beta Change", "0").replace("+", "") or 0)), reverse=True)
    notes = _kalman_beta_notes(strongest_driver, strongest_latest_beta, strongest_change, rows)
    return KalmanBetaReport(asset, rows, strongest_driver, strongest_latest_beta, strongest_change, notes)

def build_lead_lag_driver_report(asset: str, prices: pd.DataFrame, max_lag: int = 5, min_observations: int = 60) -> LeadLagDriverReport:
    if prices.empty or len(prices.columns) == 0:
        return LeadLagDriverReport(asset, [], "none", 0, 0.0, ["No cross-asset price data available for lead/lag analysis."])
    asset_key = _asset_price_column(asset, prices)
    if asset_key not in prices.columns:
        return LeadLagDriverReport(asset, [], "none", 0, 0.0, ["No matching asset column found for lead/lag analysis."])
    returns = log_returns(prices).dropna(how="all")
    if asset_key not in returns.columns or len(returns) < min_observations:
        return LeadLagDriverReport(asset, [], "none", 0, 0.0, ["Not enough return history for lead/lag analysis."])

    rows: list[dict[str, str]] = []
    strongest_leader = "none"
    strongest_lag_days = 0
    strongest_lead_correlation = 0.0
    for driver in returns.columns:
        if driver == asset_key:
            continue
        clean = returns[[asset_key, driver]].dropna()
        if len(clean) < min_observations:
            continue
        same_day = _safe_corr(clean[asset_key], clean[driver])
        best_lag = 0
        best_corr = same_day
        for lag in range(1, max_lag + 1):
            lagged_driver = clean[driver].shift(lag)
            lag_frame = pd.concat([clean[asset_key], lagged_driver], axis=1).dropna()
            if len(lag_frame) < min_observations:
                continue
            corr = _safe_corr(lag_frame.iloc[:, 0], lag_frame.iloc[:, 1])
            if abs(corr) > abs(best_corr):
                best_corr = corr
                best_lag = lag
        row = {
            "Driver": driver,
            "Same-Day Corr": f"{same_day:.2f}",
            "Best Lead Days": str(best_lag),
            "Lead Corr": f"{best_corr:.2f}",
            "Reading": _lead_lag_reading(driver, best_lag, same_day, best_corr),
        }
        rows.append(row)
        if best_lag > 0 and abs(best_corr) > abs(strongest_lead_correlation):
            strongest_leader = driver
            strongest_lag_days = best_lag
            strongest_lead_correlation = best_corr

    rows.sort(key=lambda item: abs(float(item.get("Lead Corr", "0") or 0)), reverse=True)
    notes = _lead_lag_notes(strongest_leader, strongest_lag_days, strongest_lead_correlation, rows)
    return LeadLagDriverReport(asset, rows, strongest_leader, strongest_lag_days, strongest_lead_correlation, notes)


def _kalman_beta_regime(latest_beta: float, beta_change: float, stability: float) -> str:
    if abs(latest_beta) < 0.20:
        return "LOW_LINKAGE"
    if beta_change >= 0.25:
        return "LINKAGE_STRENGTHENING"
    if beta_change <= -0.25:
        return "LINKAGE_WEAKENING"
    if stability >= 0.25:
        return "UNSTABLE_BETA"
    return "STABLE_LINKAGE"


def _kalman_beta_reading(driver: str, latest_beta: float, beta_change: float, stability: float) -> str:
    direction = "positive" if latest_beta >= 0 else "inverse"
    if abs(latest_beta) < 0.20:
        return f"{driver} has low dynamic linkage right now"
    if beta_change >= 0.25:
        return f"{driver} {direction} influence is strengthening"
    if beta_change <= -0.25:
        return f"{driver} {direction} influence is weakening"
    if stability >= 0.25:
        return f"{driver} beta is unstable; relationship is shifting"
    return f"{driver} has stable {direction} dynamic beta"


def _kalman_beta_notes(strongest_driver: str, latest_beta: float, beta_change: float, rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return ["No Kalman dynamic beta rows available."]
    if strongest_driver == "none" or abs(beta_change) < 0.10:
        return ["No major dynamic beta shift detected; current cross-asset relationships are not changing aggressively."]
    direction = "strengthening" if beta_change > 0 else "weakening"
    sign = "positive" if latest_beta >= 0 else "inverse"
    return [f"Largest dynamic beta shift: {strongest_driver} is {direction}; latest beta {latest_beta:.2f} ({sign}), 30D change {beta_change:+.2f}."]

def _safe_corr(left: pd.Series, right: pd.Series) -> float:
    value = pd.to_numeric(left, errors="coerce").corr(pd.to_numeric(right, errors="coerce"))
    return 0.0 if pd.isna(value) else float(value)


def _lead_lag_reading(driver: str, lag_days: int, same_day_corr: float, lead_corr: float) -> str:
    improvement = abs(lead_corr) - abs(same_day_corr)
    if lag_days <= 0 or improvement < 0.05:
        return "mostly same-day / no clear lead"
    if lead_corr > 0:
        return f"{driver} tends to lead positively by {lag_days}d"
    return f"{driver} tends to lead inversely by {lag_days}d"


def _lead_lag_notes(strongest_leader: str, lag_days: int, corr: float, rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return ["No lead/lag driver rows available."]
    if strongest_leader == "none" or lag_days == 0 or abs(corr) < 0.35:
        return ["No reliable leading driver detected. Current relationships look same-day/noisy."]
    direction = "positive" if corr > 0 else "inverse"
    return [f"Strongest lead signal: {strongest_leader} leads the asset by {lag_days} day(s) with {direction} correlation {corr:.2f}."]

def engle_granger_cointegration(series_x: pd.Series, series_y: pd.Series) -> dict[str, object]:
    frame = pd.concat([pd.to_numeric(series_x, errors="coerce"), pd.to_numeric(series_y, errors="coerce")], axis=1).dropna()
    if len(frame) < 60:
        return {"status": "insufficient_data", "adf_pvalue": None, "hedge_ratio": 0.0, "cointegrated_at_5pct": False}
    try:
        import statsmodels.api as sm
        from statsmodels.tsa.stattools import adfuller
    except ModuleNotFoundError:
        return {"status": "missing_statsmodels", "adf_pvalue": None, "hedge_ratio": 0.0, "cointegrated_at_5pct": False}

    x = sm.add_constant(frame.iloc[:, 0])
    model = sm.OLS(frame.iloc[:, 1], x, missing="drop").fit()
    hedge_ratio = float(model.params.iloc[1])
    residuals = model.resid
    try:
        _adf_stat, pvalue, *_ = adfuller(residuals)
    except (ValueError, np.linalg.LinAlgError):
        return {"status": "adf_failed", "adf_pvalue": None, "hedge_ratio": hedge_ratio, "cointegrated_at_5pct": False}
    return {
        "status": "ok",
        "adf_pvalue": float(pvalue),
        "hedge_ratio": hedge_ratio,
        "cointegrated_at_5pct": bool(pvalue < 0.05),
    }


def build_cointegration_report(asset: str, prices: pd.DataFrame, min_observations: int = 120) -> CointegrationReport:
    if prices.empty or len(prices.columns) == 0:
        return CointegrationReport(asset, [], "none", None, ["No cross-asset price data available for cointegration analysis."])
    asset_key = _asset_price_column(asset, prices)
    if asset_key not in prices.columns:
        return CointegrationReport(asset, [], "none", None, ["No matching asset column found for cointegration analysis."])
    clean_prices = prices.apply(pd.to_numeric, errors="coerce").ffill().dropna(how="all")
    if len(clean_prices) < min_observations:
        return CointegrationReport(asset, [], "none", None, ["Not enough price history for cointegration analysis."])

    rows: list[dict[str, str]] = []
    strongest_pair = "none"
    strongest_pvalue: float | None = None
    missing_dependency = False
    for driver in clean_prices.columns:
        if driver == asset_key:
            continue
        pair = clean_prices[[driver, asset_key]].dropna()
        if len(pair) < min_observations:
            continue
        result = engle_granger_cointegration(pair[driver], pair[asset_key])
        status = str(result["status"])
        pvalue = result["adf_pvalue"]
        hedge_ratio = float(result["hedge_ratio"])
        cointegrated = bool(result["cointegrated_at_5pct"])
        if status == "missing_statsmodels":
            missing_dependency = True
        if isinstance(pvalue, float) and (strongest_pvalue is None or pvalue < strongest_pvalue):
            strongest_pvalue = pvalue
            strongest_pair = driver
        rows.append(
            {
                "Pair": f"{asset_key}/{driver}",
                "Driver": driver,
                "ADF p-value": "n/a" if pvalue is None else f"{pvalue:.4f}",
                "Hedge Ratio": f"{hedge_ratio:.2f}",
                "Cointegrated 5%": "yes" if cointegrated else "no",
                "Status": status,
                "Reading": _cointegration_reading(status, pvalue, cointegrated),
            }
        )

    rows.sort(key=lambda item: 999.0 if item["ADF p-value"] == "n/a" else float(item["ADF p-value"]))
    notes = _cointegration_notes(strongest_pair, strongest_pvalue, rows, missing_dependency)
    return CointegrationReport(asset, rows, strongest_pair, strongest_pvalue, notes)


def _cointegration_reading(status: str, pvalue: object, cointegrated: bool) -> str:
    if status == "missing_statsmodels":
        return "statsmodels missing; install requirements to run ADF test"
    if status != "ok":
        return "test unavailable"
    if cointegrated:
        return "possible long-run relationship"
    if isinstance(pvalue, float) and pvalue < 0.15:
        return "watchlist: near cointegration threshold"
    return "no stable long-run relationship detected"


def _cointegration_notes(strongest_pair: str, pvalue: float | None, rows: list[dict[str, str]], missing_dependency: bool) -> list[str]:
    if missing_dependency:
        return ["Cointegration requires statsmodels. Run pip install -r requirements.txt, then refresh drivers again."]
    if not rows:
        return ["No cointegration rows available."]
    if pvalue is None:
        return ["Cointegration test did not produce valid p-values."]
    if pvalue < 0.05:
        return [f"Strongest long-run relationship candidate: {strongest_pair} with ADF p-value {pvalue:.4f}."]
    return ["No statistically strong cointegration found at the 5% level. Treat correlations as regime-dependent."]

def granger_causality_pvalues(returns: pd.DataFrame, cause: str, effect: str, max_lag: int = 5) -> dict[int, float] | str:
    data = returns[[effect, cause]].dropna()
    if len(data) < max(30, max_lag * 8):
        return "insufficient_data"
    try:
        from statsmodels.tsa.stattools import grangercausalitytests
    except ModuleNotFoundError:
        return "missing_statsmodels"
    try:
        result = grangercausalitytests(data, maxlag=max_lag, verbose=False)
    except Exception as exc:
        if exc.__class__.__name__ != "InfeasibleTestError" and not isinstance(exc, (ValueError, np.linalg.LinAlgError)):
            raise
        return "test_failed"
    return {lag: float(result[lag][0]["ssr_ftest"][1]) for lag in result}


def build_granger_causality_report(asset: str, prices: pd.DataFrame, max_lag: int = 5, min_observations: int = 90) -> GrangerCausalityReport:
    if prices.empty or len(prices.columns) == 0:
        return GrangerCausalityReport(asset, [], "none", 0, None, ["No cross-asset price data available for Granger causality analysis."])
    asset_key = _asset_price_column(asset, prices)
    if asset_key not in prices.columns:
        return GrangerCausalityReport(asset, [], "none", 0, None, ["No matching asset column found for Granger causality analysis."])
    returns = log_returns(prices).dropna(how="all")
    if asset_key not in returns.columns or len(returns) < min_observations:
        return GrangerCausalityReport(asset, [], "none", 0, None, ["Not enough return history for Granger causality analysis."])

    rows: list[dict[str, str]] = []
    strongest_predictor = "none"
    strongest_lag = 0
    strongest_pvalue: float | None = None
    missing_dependency = False
    for driver in returns.columns:
        if driver == asset_key:
            continue
        clean = returns[[asset_key, driver]].dropna()
        if len(clean) < min_observations:
            continue
        result = granger_causality_pvalues(clean, cause=driver, effect=asset_key, max_lag=max_lag)
        if isinstance(result, str):
            status = result
            best_lag = 0
            best_pvalue = None
            if result == "missing_statsmodels":
                missing_dependency = True
        else:
            status = "ok"
            best_lag, best_pvalue = min(result.items(), key=lambda item: item[1])
            if strongest_pvalue is None or best_pvalue < strongest_pvalue:
                strongest_predictor = driver
                strongest_lag = int(best_lag)
                strongest_pvalue = float(best_pvalue)
        rows.append(
            {
                "Driver": driver,
                "Best Lag": str(best_lag),
                "Best p-value": "n/a" if best_pvalue is None else f"{best_pvalue:.4f}",
                "Predictive 5%": "yes" if isinstance(best_pvalue, float) and best_pvalue < 0.05 else "no",
                "Status": status,
                "Reading": _granger_reading(status, best_pvalue, best_lag),
            }
        )

    rows.sort(key=lambda item: 999.0 if item["Best p-value"] == "n/a" else float(item["Best p-value"]))
    notes = _granger_notes(strongest_predictor, strongest_lag, strongest_pvalue, rows, missing_dependency)
    return GrangerCausalityReport(asset, rows, strongest_predictor, strongest_lag, strongest_pvalue, notes)


def _granger_reading(status: str, pvalue: float | None, lag: int) -> str:
    if status == "missing_statsmodels":
        return "statsmodels missing; install requirements to run Granger test"
    if status != "ok":
        return "test unavailable"
    if pvalue is not None and pvalue < 0.05:
        return f"driver history has predictive signal at lag {lag}"
    if pvalue is not None and pvalue < 0.15:
        return f"weak watchlist predictive signal at lag {lag}"
    return "no formal predictive relationship detected"


def _granger_notes(predictor: str, lag: int, pvalue: float | None, rows: list[dict[str, str]], missing_dependency: bool) -> list[str]:
    if missing_dependency:
        return ["Granger causality requires statsmodels. Run pip install -r requirements.txt, then refresh drivers again."]
    if not rows:
        return ["No Granger causality rows available."]
    if pvalue is None:
        return ["Granger test did not produce valid p-values."]
    if pvalue < 0.05:
        return [f"Strongest formal predictor: {predictor} at lag {lag} day(s), p-value {pvalue:.4f}."]
    return ["No statistically strong Granger predictor found at the 5% level. Treat lead/lag readings as exploratory."]
