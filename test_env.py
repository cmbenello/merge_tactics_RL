from mergetactics.env import MTEnv

def test_reset():
    env = MTEnv(seed=0)
    obs, mask = env.reset()
    assert obs["round"] == 1
    assert obs["turn"] in (0,1)
    assert obs["p0_elixir"] == 10 and obs["p1_elixir"] == 10
    assert len(mask) > 0

def test_play_two_bots():
    from mergetactics.bots import GreedyBot, RandomBot
    env = MTEnv(seed=1)
    obs, mask = env.reset()
    b0, b1 = GreedyBot(), RandomBot()
    steps = 0
    while True and steps < 1000:
        bot = b0 if env.turn == 0 else b1
        action = bot.act(obs, mask)
        obs, reward, done, info = env.step(action)
        steps += 1
        if done:
            assert env.p0.base_hp <= 0 or env.p1.base_hp <= 0 or env.round > 1
            break
