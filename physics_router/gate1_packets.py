#!/usr/bin/env python3
"""Gate 1: frozen physics bodies route unseen finite packet mixtures.

Bodies are trained ONLY on Gate 0's four pure steady sinusoids.  Gate 1 then
freezes them and presents mixtures of two finite Gaussian-windowed packets:

  one component from the upper-destination frequency family
  one component from the lower-destination frequency family

Every mixture randomizes:
  frequency jitter (+/- 0.025 rad/s)
  amplitude
  carrier phase
  packet center time
  packet width
  relative onset (up to 20 time units apart)

The output is synthesized from the exact frequency response of the same damped
linear body and inverse FFT'd to a full time waveform.  Routing is scored per
component by narrow-band energy at the correct versus wrong output.

No Gate-1 retraining occurs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from experiment import (
    DAMPING,
    E,
    GROUND,
    N,
    SOURCE,
    UPPER,
    LOWER,
    decode,
    spsa,
    stiffness,
)

DT = 0.1
SAMPLES = 2048
TIME = np.arange(SAMPLES, dtype=float) * DT
OMEGA_FFT = 2.0 * np.pi * np.fft.rfftfreq(SAMPLES, DT)

UPPER_CENTERS = np.asarray([0.55, 1.15], dtype=float)
LOWER_CENTERS = np.asarray([0.85, 1.45], dtype=float)
FREQ_JITTER = 0.025
BAND_HALF_WIDTH = 0.11


def summary(values):
    x = np.asarray(values, dtype=float)
    return {
        "mean": float(np.mean(x)),
        "min": float(np.min(x)),
        "max": float(np.max(x)),
        "std": float(np.std(x)),
    }


def transfer(g: np.ndarray, mass: np.ndarray):
    k = stiffness(g)
    bins = len(OMEGA_FFT)
    a = np.broadcast_to(k, (bins, N, N)).astype(complex).copy()
    idx = np.arange(N)
    a[:, idx, idx] += (
        -(OMEGA_FFT[:, None] ** 2) * mass[None, :]
        + 1j * OMEGA_FFT[:, None] * DAMPING
    )
    drive = np.zeros((bins, N, 1), dtype=complex)
    drive[:, SOURCE, 0] = 1.0
    response = np.linalg.solve(a, drive)[..., 0]
    return response[:, UPPER], response[:, LOWER]


def make_mixtures(count: int, seed: int):
    rng = np.random.default_rng(int(seed))
    rows = []
    for _ in range(int(count)):
        upper_freq = float(
            rng.choice(UPPER_CENTERS)
            + rng.uniform(-FREQ_JITTER, FREQ_JITTER)
        )
        lower_freq = float(
            rng.choice(LOWER_CENTERS)
            + rng.uniform(-FREQ_JITTER, FREQ_JITTER)
        )

        upper_center = float(rng.uniform(28.0, 48.0))
        lower_center = float(
            upper_center + rng.uniform(-10.0, 10.0)
        )
        upper_sigma = float(rng.uniform(6.0, 11.0))
        lower_sigma = float(rng.uniform(6.0, 11.0))
        upper_phase = float(rng.uniform(0.0, 2.0 * np.pi))
        lower_phase = float(rng.uniform(0.0, 2.0 * np.pi))
        upper_amp = float(rng.uniform(0.6, 1.4))
        lower_amp = float(rng.uniform(0.6, 1.4))

        upper_packet = (
            upper_amp
            * np.exp(
                -0.5
                * ((TIME - upper_center) / upper_sigma) ** 2
            )
            * np.sin(upper_freq * TIME + upper_phase)
        )
        lower_packet = (
            lower_amp
            * np.exp(
                -0.5
                * ((TIME - lower_center) / lower_sigma) ** 2
            )
            * np.sin(lower_freq * TIME + lower_phase)
        )
        rows.append(
            {
                "input_fft": np.fft.rfft(
                    upper_packet + lower_packet
                ),
                "upper_freq": upper_freq,
                "lower_freq": lower_freq,
            }
        )
    return rows


def evaluate_body(
    g: np.ndarray,
    mass: np.ndarray,
    mixtures,
):
    upper_transfer, lower_transfer = transfer(g, mass)
    correct = 0.0
    margins: list[float] = []

    for row in mixtures:
        upper_spectrum = upper_transfer * row["input_fft"]
        lower_spectrum = lower_transfer * row["input_fft"]

        for omega, target in (
            (row["upper_freq"], UPPER),
            (row["lower_freq"], LOWER),
        ):
            mask = np.abs(OMEGA_FFT - omega) <= BAND_HALF_WIDTH
            power_upper = float(
                np.sum(np.abs(upper_spectrum[mask]) ** 2)
            )
            power_lower = float(
                np.sum(np.abs(lower_spectrum[mask]) ** 2)
            )

            if target == UPPER:
                desired, wrong = power_upper, power_lower
            else:
                desired, wrong = power_lower, power_upper

            if abs(desired - wrong) <= 1e-12 * max(
                1.0, desired, wrong
            ):
                correct += 0.5
            else:
                correct += float(desired > wrong)

            margins.append(
                float(
                    10.0
                    * np.log10(
                        (desired + 1e-12) / (wrong + 1e-12)
                    )
                )
            )

    return {
        "component_accuracy": float(
            correct / (2.0 * len(mixtures))
        ),
        "mean_margin_db": float(np.mean(margins)),
        "min_component_margin_db": float(np.min(margins)),
        "p05_margin_db": float(np.percentile(margins, 5.0)),
    }


def train_gate0_arm(mode: str, seeds: int, steps: int):
    rows = []
    for seed in range(int(seeds)):
        z, gate0_loss = spsa(mode, seed, steps=steps)
        g, mass = decode(z, mode)
        rows.append(
            {
                "seed": seed,
                "gate0_loss": float(gate0_loss),
                "g": g,
                "mass": mass,
            }
        )
    return rows


def train_shuffled(seeds: int, steps: int):
    rows = []
    for seed in range(int(seeds)):
        z, gate0_loss = spsa(
            "both",
            100 + seed,
            steps=steps,
            shuffle_consequence=True,
        )
        g, mass = decode(z, "both")
        rows.append(
            {
                "seed": seed,
                "gate0_loss": float(gate0_loss),
                "g": g,
                "mass": mass,
            }
        )
    return rows


def aggregate(rows, mixtures):
    metrics = [
        evaluate_body(row["g"], row["mass"], mixtures)
        for row in rows
    ]
    return {
        "component_accuracy": summary(
            [m["component_accuracy"] for m in metrics]
        ),
        "mean_margin_db": summary(
            [m["mean_margin_db"] for m in metrics]
        ),
        "min_component_margin_db": summary(
            [m["min_component_margin_db"] for m in metrics]
        ),
        "p05_margin_db": summary(
            [m["p05_margin_db"] for m in metrics]
        ),
        "per_seed": [
            {"seed": int(row["seed"]), **metric}
            for row, metric in zip(rows, metrics)
        ],
    }


def run(
    *,
    seeds: int = 12,
    steps: int = 1600,
    mixtures_count: int = 512,
    mixture_seed: int = 20260903,
):
    mixtures = make_mixtures(mixtures_count, mixture_seed)

    space = train_gate0_arm("space", seeds, steps)
    clock = train_gate0_arm("clock", seeds, steps)
    both = train_gate0_arm("both", seeds, steps)
    shuffled = train_shuffled(seeds, steps)

    aggregate_rows = {
        "SPACE_ONLY": aggregate(space, mixtures),
        "CLOCK_ONLY": aggregate(clock, mixtures),
        "SPACE_CLOCK": aggregate(both, mixtures),
        "SHUFFLED_CONSEQUENCE": aggregate(
            shuffled, mixtures
        ),
    }

    uniform = evaluate_body(
        np.ones(E, dtype=float),
        np.ones(N, dtype=float),
        mixtures,
    )

    joint = aggregate_rows["SPACE_CLOCK"]
    spatial = aggregate_rows["SPACE_ONLY"]
    clocks = aggregate_rows["CLOCK_ONLY"]
    shuffled_result = aggregate_rows["SHUFFLED_CONSEQUENCE"]

    requirements = {
        "frozen_joint_mean_component_accuracy_ge_0p90": (
            joint["component_accuracy"]["mean"] >= 0.90
        ),
        "joint_beats_space_by_0p08": (
            joint["component_accuracy"]["mean"]
            >= spatial["component_accuracy"]["mean"] + 0.08
        ),
        "joint_beats_clock_by_0p15": (
            joint["component_accuracy"]["mean"]
            >= clocks["component_accuracy"]["mean"] + 0.15
        ),
        "joint_positive_fifth_percentile_margin": (
            joint["p05_margin_db"]["mean"] > 1.0
        ),
        "joint_beats_shuffled_margin_by_5db": (
            joint["mean_margin_db"]["mean"]
            >= shuffled_result["mean_margin_db"]["mean"] + 5.0
        ),
        "uniform_body_is_tie": (
            abs(uniform["component_accuracy"] - 0.5) < 1e-12
        ),
    }
    passed = all(requirements.values())

    best_joint_seed = max(
        aggregate_rows["SPACE_CLOCK"]["per_seed"],
        key=lambda row: (
            row["component_accuracy"],
            row["min_component_margin_db"],
        ),
    )

    return {
        "gate": 1,
        "classification": (
            "FROZEN_SPACE_CLOCK_BODY_SEPARATES_UNSEEN_PACKET_MIXTURES"
            if passed
            else "FINITE_PACKET_MIXTURE_GATE_FAILED"
        ),
        "passed": passed,
        "training": {
            "gate1_retraining": False,
            "gate0_training_only": (
                "four pure steady sinusoids at "
                "0.55, 0.85, 1.15, 1.45 rad/s"
            ),
            "gate0_scalar_optimizer": "SPSA",
            "seeds": int(seeds),
            "gate0_updates_per_seed": int(steps),
        },
        "heldout_packet_world": {
            "mixtures": int(mixtures_count),
            "components_scored": int(2 * mixtures_count),
            "mixture_seed": int(mixture_seed),
            "frequency_jitter_rad_per_s": FREQ_JITTER,
            "amplitude_range": [0.6, 1.4],
            "packet_center_range": [28.0, 48.0],
            "relative_center_offset_range": [-10.0, 10.0],
            "gaussian_sigma_range": [6.0, 11.0],
            "phase_range_rad": [0.0, float(2.0 * np.pi)],
            "band_half_width_rad_per_s": BAND_HALF_WIDTH,
            "dt": DT,
            "samples": SAMPLES,
        },
        "measurement": (
            "For each finite two-packet mixture, synthesize full output "
            "waveforms through the fixed LTI body; for each component, "
            "compare narrow-band energy at its intended versus wrong output."
        ),
        "aggregate": aggregate_rows,
        "uniform_body": uniform,
        "best_joint_seed": best_joint_seed,
        "requirements": requirements,
        "scope": (
            "The mixture components are distinguished by carrier frequency. "
            "This demonstrates passive spectral separation of finite packets "
            "by a body trained only on pure tones. It does not establish "
            "semantic routing, nonlinear source separation, or computational "
            "savings on digital hardware."
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=12)
    parser.add_argument("--steps", type=int, default=1600)
    parser.add_argument("--mixtures", type=int, default=512)
    parser.add_argument("--mixture-seed", type=int, default=20260903)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("physics_router/results/GATE1.json"),
    )
    args = parser.parse_args()

    result = run(
        seeds=args.seeds,
        steps=args.steps,
        mixtures_count=args.mixtures,
        mixture_seed=args.mixture_seed,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
