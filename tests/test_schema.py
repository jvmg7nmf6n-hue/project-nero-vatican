from __future__ import annotations

import unittest

from pydantic import ValidationError

from nero_core.schema import (
    AnalysisRequest,
    AssessmentOutput,
    AssetSymbol,
    BacktestResult,
    BrainOutput,
    HistoricalMatch,
    NeroResult,
    VerdictOutput,
)


class SchemaTest(unittest.TestCase):
    def test_analysis_request_accepts_valid_payload(self) -> None:
        request = AnalysisRequest(asset=AssetSymbol.BTC, headline="Fed turns dovish today", lookback_days=45)

        self.assertEqual(request.asset, AssetSymbol.BTC)
        self.assertEqual(request.lookback_days, 45)

    def test_analysis_request_rejects_short_headline(self) -> None:
        with self.assertRaises(ValidationError):
            AnalysisRequest(asset=AssetSymbol.BTC, headline="short")

    def test_analysis_request_rejects_lookback_out_of_range(self) -> None:
        with self.assertRaises(ValidationError):
            AnalysisRequest(asset=AssetSymbol.GOLD, headline="Gold rallies on rate cut bets", lookback_days=5)

    def test_verdict_output_rejects_confidence_out_of_bounds(self) -> None:
        with self.assertRaises(ValidationError):
            VerdictOutput(direction="bullish", confidence=1.5, risk_score=0.2, summary="test", drivers=[])

    def test_historical_match_requires_similarity_between_zero_and_one(self) -> None:
        with self.assertRaises(ValidationError):
            HistoricalMatch(
                event_id="evt-1",
                event_date="2026-01-01",
                title="Test event",
                similarity=1.2,
                forward_bias=0.1,
                tags=["fed"],
            )

    def test_nero_result_composes_nested_models(self) -> None:
        request = AnalysisRequest(asset=AssetSymbol.ETH, headline="ETH breaks above resistance level")
        match = HistoricalMatch(
            event_id="evt-2",
            event_date="2026-02-01",
            title="Rate cut rally",
            similarity=0.8,
            forward_bias=0.05,
            tags=["fed", "liquidity"],
        )
        brain = BrainOutput(matches=[match], thematic_score=0.4, dominant_tags=["fed"])
        assessment = AssessmentOutput(rsi=55.0, trend_score=0.2, fair_value_gap="none", liquidity_sweep="none", momentum_score=0.1)
        verdict = VerdictOutput(direction="bullish", confidence=0.6, risk_score=0.3, summary="test summary", drivers=["fed"])

        result = NeroResult(request=request, brain=brain, assessment=assessment, verdict=verdict)

        self.assertEqual(result.verdict.direction, "bullish")
        self.assertEqual(len(result.brain.matches), 1)

    def test_backtest_result_accepts_trade_rows(self) -> None:
        result = BacktestResult(average_forward_return=0.02, win_rate=0.55, sample_count=10, trades=[{"event_id": "evt-1"}])

        self.assertEqual(result.sample_count, 10)
        self.assertEqual(result.trades[0]["event_id"], "evt-1")


if __name__ == "__main__":
    unittest.main()
