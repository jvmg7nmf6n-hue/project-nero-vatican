from bellwether.schemas import Bias, Signal, Asset, Category, AnalysisOutput, Region


def test_bias_score_roundtrip():
    assert Bias.STRONG_BEARISH.score == -2
    assert Bias.NEUTRAL.score == 0
    assert Bias.STRONG_BULLISH.score == 2
    assert Bias.from_score(-2.0) == Bias.STRONG_BEARISH
    assert Bias.from_score(0.0) == Bias.NEUTRAL
    assert Bias.from_score(1.9) == Bias.STRONG_BULLISH


def test_signal_weighted_score():
    s = Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=0.5)
    assert s.weighted_score == 0.5  # 1 * 0.5


def test_output_serialization_has_spec_fields():
    out = AnalysisOutput(
        headline="x", category=Category.INFLATION, country=Region.USA,
        importance_score=0.5, surprise_score=0.3,
        gold_bias=Bias.BULLISH, bitcoin_bias=Bias.NEUTRAL,
        confidence=0.6, probability_up_gold=0.6, probability_up_bitcoin=0.5,
    )
    d = out.headline_json()
    for field in ("timestamp", "headline", "category", "country", "importance_score",
                  "surprise_score", "gold_bias", "bitcoin_bias", "confidence",
                  "probability_up_gold", "probability_up_bitcoin", "historical_matches",
                  "assumptions", "risks", "alternative_scenarios", "reasoning"):
        assert field in d
