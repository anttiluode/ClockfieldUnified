#!/usr/bin/env python3
"""Gate 0: can adaptive space + adaptive local time route by signal content?

This is a computational offshoot of ClockfieldUnified + OutoSynapsi.

The body is a seven-node damped linear wave medium.  Edge couplings g define
the spatial stiffness/Laplacian.  Node masses m define local inertia and hence
a local clock scale N_i = 1/sqrt(m_i).  No per-input router chooses a branch.

For sinusoidal drive omega, steady state is

    (-omega^2 M + i omega gamma I + L(g) + kappa I) x = b.

Four input frequencies must alternate between the upper and lower outputs.
Training uses SPSA: two scalar task-loss evaluations per update, no gradients.

Arms:
  SPACE_ONLY  - learn edge couplings g, masses fixed.
  CLOCK_ONLY  - learn node masses m, couplings fixed.
  SPACE_CLOCK - learn both.
  SHUFFLED    - same SPACE_CLOCK learner, but half the +/- consequences are
                randomly swapped, destroying causal alignment.

The gate is intentionally narrow.  Frequency is "content" only in the signal-
processing sense.  This is not semantics, not free GPU computation, and not a
claim about gravitational mass.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

N = 7
EDGES = [(0, 1), (1, 2), (2, 5), (0, 3), (3, 4), (4, 6), (2, 4)]
E = len(EDGES)
SOURCE = 0
UPPER = 5
LOWER = 6

TRAIN_FREQS = np.asarray([0.55, 0.85, 1.15, 1.45], dtype=float)
TRAIN_TARGETS = np.asarray([0, 1, 0, 1], dtype=int)
GROUND = 0.25
DAMPING = 0.08

TEST_FREQS: list[float] = []
TEST_TARGETS: list[int] = []
for _center, _target in zip(TRAIN_FREQS, TRAIN_TARGETS):
    for _delta in np.linspace(-0.025, 0.025, 21):
        if abs(float(_delta)) < 1e-12:
            continue
        TEST_FREQS.append(float(_center + _delta))
        TEST_TARGETS.append(int(_target))
TEST_FREQS = np.asarray(TEST_FREQS, dtype=float)
TEST_TARGETS = np.asarray(TEST_TARGETS, dtype=int)


def normalized_exp(z: np.ndarray, total: float) -> np.ndarray:
    z = np.asarray(z, dtype=float)
    q = np.exp(z - float(np.max(z)))
    return float(total) * q / float(np.sum(q))


def decode(z: np.ndarray, mode: str) -> tuple[np.ndarray, np.ndarray]:
    cursor = 0
    if mode in ("space", "both"):
        g = normalized_exp(z[:E], E)
        cursor = E
    else:
        g = np.ones(E, dtype=float)

    if mode in ("clock", "both"):
        mass = normalized_exp(z[cursor : cursor + N], N)
    else:
        mass = np.ones(N, dtype=float)
    return g, mass


def stiffness(g: np.ndarray) -> np.ndarray:
    k = np.eye(N, dtype=float) * GROUND
    for ge, (i, j) in zip(g, EDGES):
        k[i, i] += ge
        k[j, j] += ge
        k[i, j] -= ge
        k[j, i] -= ge
    return k


def response(g: np.ndarray, mass: np.ndarray, omega: float) -> np.ndarray:
    a = (
        stiffness(g)
        - float(omega * omega) * np.diag(mass)
        + 1j * float(omega) * DAMPING * np.eye(N)
    )
    drive = np.zeros(N, dtype=complex)
    drive[SOURCE] = 1.0
    return np.linalg.solve(a, drive)


def task_loss(z: np.ndarray, mode: str) -> float:
    g, mass = decode(z, mode)
    total = 0.0
    for omega, target in zip(TRAIN_FREQS, TRAIN_TARGETS):
        x = response(g, mass, float(omega))
        upper = float(abs(x[UPPER]) ** 2)
        lower = float(abs(x[LOWER]) ** 2)
        desired, unwanted = (upper, lower) if target == 0 else (lower, upper)

        log_ratio = np.log((desired + 1e-9) / (unwanted + 1e-9))
        # Prefer roughly >= 7.8 dB routing margin and non-vanishing throughput.
        total += np.log1p(np.exp(1.8 - log_ratio))
        total += 0.02 / (desired + 1e-3)

    return float(total / len(TRAIN_FREQS))


def measure(
    z: np.ndarray,
    mode: str,
    freqs: np.ndarray,
    targets: np.ndarray,
) -> dict:
    g, mass = decode(z, mode)
    margins: list[float] = []
    desired_power: list[float] = []
    correct = 0.0

    for omega, target in zip(freqs, targets):
        x = response(g, mass, float(omega))
        upper = float(abs(x[UPPER]) ** 2)
        lower = float(abs(x[LOWER]) ** 2)

        if abs(upper - lower) <= 1e-12 * max(1.0, upper, lower):
            correct += 0.5
        else:
            predicted = 0 if upper > lower else 1
            correct += float(predicted == int(target))

        desired, unwanted = (upper, lower) if target == 0 else (lower, upper)
        margins.append(
            float(10.0 * np.log10((desired + 1e-12) / (unwanted + 1e-12)))
        )
        desired_power.append(desired)

    return {
        "accuracy": float(correct / len(freqs)),
        "mean_margin_db": float(np.mean(margins)),
        "min_margin_db": float(np.min(margins)),
        "median_desired_power": float(np.median(desired_power)),
        "couplings": g.tolist(),
        "clock_mass": mass.tolist(),
        "clock_rate": (1.0 / np.sqrt(mass)).tolist(),
    }


def spsa(
    mode: str,
    seed: int,
    *,
    steps: int,
    shuffle_consequence: bool = False,
) -> tuple[np.ndarray, float]:
    dims = {"space": E, "clock": N, "both": E + N}[mode]
    learning_rate = 0.025 if mode != "both" else 0.02
    rng = np.random.default_rng(int(seed))

    z = np.zeros(dims, dtype=float)
    first_moment = np.zeros(dims, dtype=float)
    second_moment = np.zeros(dims, dtype=float)

    best = z.copy()
    best_loss = task_loss(best, mode)

    for step_index in range(1, int(steps) + 1):
        delta = rng.choice(np.asarray([-1.0, 1.0]), size=dims)
        probe_size = 0.1 / (step_index ** 0.101)

        plus = np.clip(z + probe_size * delta, -3.0, 3.0)
        minus = np.clip(z - probe_size * delta, -3.0, 3.0)
        plus_loss = task_loss(plus, mode)
        minus_loss = task_loss(minus, mode)

        if shuffle_consequence and rng.random() < 0.5:
            plus_loss, minus_loss = minus_loss, plus_loss

        gradient = ((plus_loss - minus_loss) / (2.0 * probe_size)) * delta
        first_moment = 0.9 * first_moment + 0.1 * gradient
        second_moment = 0.999 * second_moment + 0.001 * gradient * gradient

        step_size = learning_rate / (1.0 + 0.0005 * step_index)
        z = np.clip(
            z
            - step_size
            * first_moment
            / (np.sqrt(second_moment) + 1e-8),
            -3.0,
            3.0,
        )

        current = task_loss(z, mode)
        if current < best_loss:
            best_loss = current
            best = z.copy()

    return best, float(best_loss)


def summary(values: list[float]) -> dict:
    x = np.asarray(values, dtype=float)
    return {
        "mean": float(np.mean(x)),
        "min": float(np.min(x)),
        "max": float(np.max(x)),
        "std": float(np.std(x)),
    }


def run(seeds: int, steps: int) -> dict:
    arms: dict[str, list[dict]] = {}

    for label, mode in (
        ("SPACE_ONLY", "space"),
        ("CLOCK_ONLY", "clock"),
        ("SPACE_CLOCK", "both"),
    ):
        rows = []
        for seed in range(int(seeds)):
            z, loss = spsa(mode, seed, steps=steps)
            rows.append(
                {
                    "seed": seed,
                    "loss": loss,
                    "train": measure(z, mode, TRAIN_FREQS, TRAIN_TARGETS),
                    "heldout": measure(z, mode, TEST_FREQS, TEST_TARGETS),
                }
            )
        arms[label] = rows

    shuffled = []
    for seed in range(int(seeds)):
        z, loss = spsa(
            "both",
            100 + seed,
            steps=steps,
            shuffle_consequence=True,
        )
        shuffled.append(
            {
                "seed": seed,
                "loss": loss,
                "heldout": measure(z, "both", TEST_FREQS, TEST_TARGETS),
            }
        )
    arms["SHUFFLED_CONSEQUENCE"] = shuffled

    aggregate = {}
    for label in ("SPACE_ONLY", "CLOCK_ONLY", "SPACE_CLOCK"):
        rows = arms[label]
        aggregate[label] = {
            "train_accuracy": summary(
                [row["train"]["accuracy"] for row in rows]
            ),
            "heldout_accuracy": summary(
                [row["heldout"]["accuracy"] for row in rows]
            ),
            "heldout_mean_margin_db": summary(
                [row["heldout"]["mean_margin_db"] for row in rows]
            ),
            "heldout_min_margin_db": summary(
                [row["heldout"]["min_margin_db"] for row in rows]
            ),
            "loss": summary([row["loss"] for row in rows]),
        }

    aggregate["SHUFFLED_CONSEQUENCE"] = {
        "heldout_accuracy": summary(
            [row["heldout"]["accuracy"] for row in shuffled]
        ),
        "heldout_mean_margin_db": summary(
            [row["heldout"]["mean_margin_db"] for row in shuffled]
        ),
        "heldout_min_margin_db": summary(
            [row["heldout"]["min_margin_db"] for row in shuffled]
        ),
    }

    uniform = measure(
        np.zeros(E + N, dtype=float),
        "both",
        TEST_FREQS,
        TEST_TARGETS,
    )

    both = aggregate["SPACE_CLOCK"]
    space = aggregate["SPACE_ONLY"]
    clock = aggregate["CLOCK_ONLY"]
    shuffled_summary = aggregate["SHUFFLED_CONSEQUENCE"]

    requirements = {
        "space_plus_clock_mean_accuracy_ge_0p90": (
            both["heldout_accuracy"]["mean"] >= 0.90
        ),
        "space_plus_clock_beats_space_by_0p08": (
            both["heldout_accuracy"]["mean"]
            >= space["heldout_accuracy"]["mean"] + 0.08
        ),
        "space_plus_clock_beats_clock_by_0p12": (
            both["heldout_accuracy"]["mean"]
            >= clock["heldout_accuracy"]["mean"] + 0.12
        ),
        "space_plus_clock_positive_mean_worst_case_margin": (
            both["heldout_min_margin_db"]["mean"] > 2.0
        ),
        "causal_consequence_beats_shuffled_margin_by_5db": (
            both["heldout_mean_margin_db"]["mean"]
            >= shuffled_summary["heldout_mean_margin_db"]["mean"] + 5.0
        ),
    }
    passed = all(requirements.values())

    return {
        "gate": 0,
        "classification": (
            "SPACE_AND_LOCAL_TIME_JOINTLY_SUPPORT_FREQUENCY_ROUTING"
            if passed
            else "PHYSICS_ROUTING_GATE_FAILED"
        ),
        "passed": passed,
        "body": {
            "nodes": N,
            "edges": EDGES,
            "equation": "M x_ddot + gamma x_dot + (L(g)+kappa I)x = b u",
            "ground_stiffness": GROUND,
            "damping": DAMPING,
            "edge_budget": E,
            "mass_budget": N,
            "clock_definition": "N_i = 1/sqrt(m_i)",
        },
        "task": {
            "train_frequencies": TRAIN_FREQS.tolist(),
            "train_destinations": ["upper", "lower", "upper", "lower"],
            "heldout_frequencies": int(len(TEST_FREQS)),
            "heldout_rule": "+/- 0.025 neighborhoods excluding train centers",
        },
        "learning": {
            "algorithm": "SPSA with Adam-like moment smoothing",
            "seeds": int(seeds),
            "updates_per_seed": int(steps),
            "plus_minus_scalar_consequence_pairs_per_seed": int(steps),
            "gradient_access": False,
            "per_input_router": False,
        },
        "aggregate": aggregate,
        "uniform_body": uniform,
        "requirements": requirements,
        "scope": (
            "Content means input frequency. Clock mass is a local inertia/time-scale "
            "parameter, not gravitational mass. The medium is simulated digitally, "
            "so routing is not computationally free on a GPU. An explicit digital "
            "frequency router solves this toy task trivially."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=12)
    parser.add_argument("--steps", type=int, default=1600)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("physics_router/results/GATE0.json"),
    )
    args = parser.parse_args()

    result = run(args.seeds, args.steps)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
