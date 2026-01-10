"""
Data sources for racing odds
"""

from .betfair import BetfairSource
from .sportsbet import SportsbetSource
from .amused import AmusedSource
from .pointsbet import PointsbetSource
from .betr import BetrSource
from .boombet import BoomBetSource
from .palmerbet import PalmerBetSource
from .tab import TABSource
from .playup import PlayUpSource

__all__ = ["BetfairSource", "SportsbetSource", "AmusedSource", "PointsbetSource", "BetrSource", "BoomBetSource", "PalmerBetSource", "TABSource", "PlayUpSource"]
