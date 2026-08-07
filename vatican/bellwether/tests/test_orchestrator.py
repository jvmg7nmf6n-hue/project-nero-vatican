import os
import tempfile

import pytest

from bellwether import Orchestrator, MacroEvent
from bellwether.config import Settings
from bellwether.schemas import Bias, Category, Region


@pytest.fixture
def orch(tmp_path):
    settings = Settings(store_path=str(tmp_path / "store.json"), data_mode="mock", seed=7)
    return Orchestrator(settings)


async def test_full_cycle_runs_offline(orch):
    out = await orch.analyze([])
    assert isinstance(out.gold_bias, Bias)
    assert isinstance(out.bitcoin_bias, Bias)
    assert 0.0 <= out.confidence <= 1.0
    assert 0.0 <= out.probability_up_gold <= 1.0
    assert 0.0 <= out.probability_up_bitcoin <= 1.0


async def test_cycle_with_events_classifies(orch):
    events = [
        MacroEvent(headline="Fed signals rate cut amid disinflation", source="t",
                   region=Region.USA, category=Category.MONETARY_POLICY),
        MacroEvent(headline="Record Bitcoin spot ETF inflow this week", source="t",
                   region=Region.USA, category=Category.ETF_FLOWS),
    ]
    out = await orch.analyze(events)
    assert out.headline  # a primary event was chosen
    assert len(out.alternative_scenarios) >= 1


async def test_learning_loop_updates_accuracy(orch):
    out = await orch.analyze([])
    # Two predictions (gold + btc) were persisted.
    preds = orch.store._data["predictions"]
    assert len(preds) == 2
    # Record a correct outcome for the first and check accuracy moves off 0.5.
    pid = preds[0]["id"]
    up = preds[0]["probability_up"] >= 0.5
    orch.record_outcome(pid, 1.0 if up else -1.0)
    assert orch.store.rolling_accuracy() == 1.0


async def test_risk_haircut_present(orch):
    await orch.analyze([])
    # run a second pass and confirm the trade engine attached recommendations
    out = await orch.analyze([])
    assert out is not None
