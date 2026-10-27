"""SKELETON: ANDES AndesEnv template.

The RL extra (``gymnasium``) is optional and is not installed in every ANDES
environment.  Import it lazily so this file can be inspected without the extra;
``main()`` reports the missing dependency instead of crashing at import time.

Do not start training automatically.  Resolve the observation/action models,
reward function, and episode definition for the actual study first.
"""
import numpy as np

try:  # Optional dependency: ANDES raises ImportError when gymnasium is absent.
    from andes.rl import AndesEnv
    _RL_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - depends on the installed extras
    AndesEnv = None
    _RL_IMPORT_ERROR = exc

from andes.utils.paths import get_case

CASE = get_case("ieee14/ieee14_esst3a.xlsx")


def reward_fn(obs, action, env):
    """Illustrative frequency-deviation penalty; justify the real reward."""
    freq_dev = obs - 1.0
    return -float(np.sum(freq_dev ** 2) + 0.01 * np.sum(action ** 2))


def main() -> int:
    if AndesEnv is None:
        raise SystemExit(
            "SKELETON requires the optional ANDES RL extra (gymnasium). "
            f"Original import error: {type(_RL_IMPORT_ERROR).__name__}: {_RL_IMPORT_ERROR}"
        )

    env = AndesEnv(
        case=CASE,
        obs=[("GENROU", "omega")],
        acts=[("SynGen", "paux")],
        reward_fn=reward_fn,
        dt=0.1,
        tf=5.0,
        action_low=-0.1,
        action_high=0.1,
    )
    obs, info = env.reset(seed=42)
    # Run a no-control baseline before connecting a training library.
    trajectory = [obs.copy()]
    while True:
        obs, reward, terminated, truncated, info = env.step(np.zeros(env.action_space.shape))
        trajectory.append(obs.copy())
        if terminated or truncated:
            break
    print({"steps": len(trajectory) - 1, "observation_space": str(env.observation_space),
           "action_space": str(env.action_space)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
