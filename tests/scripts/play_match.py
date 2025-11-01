from mergetactics.env import MTEnv
from mergetactics.bots import GreedyBot, RandomBot

def render_board(board):
    H, W = board.shape
    for r in range(H):
        row = []
        for c in range(W):
            v = int(board[r,c])
            if v == 0:
                row.append(" . ")
            else:
                owner = v // 10
                rem = v % 10
                troop = rem // 3
                star  = rem % 3
                row.append(f"{owner}{troop}{star}")
        print(" ".join(row))

env = MTEnv(seed=42)
obs, mask = env.reset()
b0, b1 = GreedyBot(), RandomBot()

step_cap = 200
for step in range(step_cap):
    bot = b0 if obs["turn"] == 0 else b1
    action = bot.act(obs, mask)

    # Take action
    obs, reward, done, info = env.step(action)

    # IMPORTANT: refresh the mask for the *new* state
    _, mask = env.observe()

    print(f"turn= {obs['turn']} round= {obs['round']} actions_left: {obs['p0_actions_left']} {obs['p1_actions_left']}")
    render_board(obs["board"])
    print("mask[:6] =", mask[:6])
    print(info)

    if done:
        print("GAME OVER")
        print(f"p0_hp={env.p0.base_hp} p1_hp={env.p1.base_hp} rounds={env.round}")
        print("last_info:", env.last_info)
        break