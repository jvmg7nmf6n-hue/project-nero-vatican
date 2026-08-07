"""Bellwether Engine — multi-agent macro intelligence core for Gold and Bitcoin.

The engine ingests global macro/geo/market signals and produces *explainable*
directional bias (never guaranteed outcomes), with a strict separation of
facts, expectations, and AI predictions, plus a learning loop that scores its
own past calls.
"""

__version__ = "0.1.0"

from .schemas import (
    Asset,
    Region,
    Category,
    Bias,
    Signal,
    MacroEvent,
    AnalysisOutput,
)
from .orchestrator import Orchestrator

__all__ = [
    "Asset",
    "Region",
    "Category",
    "Bias",
    "Signal",
    "MacroEvent",
    "AnalysisOutput",
    "Orchestrator",
    "__version__",
]
