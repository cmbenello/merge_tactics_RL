from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, List, Dict
from .env import MTEnv
from .bots import GreedyBot, RandomBot

@dataclass
class Snapshot:
    name: str
    kind: str  # "greedy" or "random" or "rl"

@dataclass
class ArenaManager:
    env_ctor: Callable[[], MTEnv]
    snapshots: List[Snapshot] = field(default_factory=list)

    def __post_init__(self):
        if not self.snapshots:
            self.snapshots = [
                Snapshot("greedy_v1", "greedy"),
                Snapshot("random_v1", "random")
            ]

    def make_bot(self, snap: Snapshot):
        if snap.kind == "greedy": return GreedyBot()
        if snap.kind == "random": return RandomBot()
        raise ValueError(f"Unknown bot kind: {snap.kind}")

    def play_match(self, bot0, bot1, seed=0) -> Dict:
        env = self.env_ctor()
        obs, mask = env.reset(seed=seed)
        while True:
            bot = bot0 if env.turn == 0 else bot1
            action = bot.act(obs, mask)
            obs, reward, done, info = env.step(action)
            if done:
                winner = 0 if env.p1.base_hp<=0 else (1 if env.p0.base_hp<=0 else -1)
                return {"winner": winner, "info": env.last_info, "p0_hp": env.p0.base_hp, "p1_hp": env.p1.base_hp, "round": env.round}

    def mini_tournament(self, n_games=50, seed=123):
        results = {}
        for i, s0 in enumerate(self.snapshots):
            for j, s1 in enumerate(self.snapshots):
                if i == j: continue
                w = 0
                for g in range(n_games):
                    bot0 = self.make_bot(s0)
                    bot1 = self.make_bot(s1)
                    r = self.play_match(bot0, bot1, seed=seed+g)
                    w += 1 if r["winner"] == 0 else 0
                results[(s0.name, s1.name)] = w / n_games
        return results
