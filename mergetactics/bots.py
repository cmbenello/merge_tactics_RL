from __future__ import annotations
import random
from typing import List, Tuple
from . import rules

Action = Tuple[str, tuple]

class RandomBot:
    def act(self, obs, mask: List[Action]) -> Action:
        return random.choice(mask)

class GreedyBot:
    """
    Priority:
    1) Merge if possible
    2) Buy+place ARCHER if affordable and space exists
    3) Buy+place TANK if affordable
    4) Sell random if stuck
    5) End
    """
    def act(self, obs, mask: List[Action]) -> Action:
        merges = [a for a in mask if a[0] == "MERGE"]
        if merges: return merges[0]
        buys_archer = [a for a in mask if a[0]=="BUY_PLACE" and a[1][0]==rules.ARCHER]
        if buys_archer: return buys_archer[0]
        buys_tank = [a for a in mask if a[0]=="BUY_PLACE" and a[1][0]==rules.TANK]
        if buys_tank: return buys_tank[0]
        sells = [a for a in mask if a[0]=="SELL"]
        if sells: return sells[0]
        ends = [a for a in mask if a[0]=="END"]
        return ends[0] if ends else mask[0]
