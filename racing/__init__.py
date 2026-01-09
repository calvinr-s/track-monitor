"""
Racing module for odds aggregation and EV calculation
"""

from .aggregator import RaceAggregator
from .formatting import format_race_embed

__all__ = ["RaceAggregator", "format_race_embed"]
