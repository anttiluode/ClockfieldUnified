#!/usr/bin/env python3
"""Gate 2: local eligibility + one global scalar consequence.

This gate removes the centralized parameter-update interpretation from Gate 0.

Each edge and node:
  1. measures its own local traffic,
  2. probabilistically becomes eligible,
  3. generates and stores its own +/- perturbation sign,
  4. receives the same scalar global loss difference,
  5. updates only its own parameter using eligibility * global pulse.

A fixed-budget homeostat renormalizes total edge coupling and total clock mass.

This is mathematically close to distributed simultaneous perturbation /
three-factor learning. It is not claimed as new optimization mathematics.

Traffic observables:
  edge e=(i,j): mean |x_i-x_j|^2 over the four training tones
  node i:        mean omega^2 |x_i|^2

Arms:
  TRAFFIC_GATED      local traffic gates eligibility
  UNGATED_LOCAL      every local parameter is eligible every update
  SHUFFLED_TRAFFIC   same traffic values assigned to wrong addresses
  SHUFFLED_PULSE     half of +/- global consequences are reversed

All learned bodies are also frozen and evaluated on Gate 1's 512 finite
packet mixtures.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from experiment import (
    E,
    EDGES,
    N,
    TRAIN_FREQS,
    TRAIN_TARGETS,
    TEST_FREQS,
    TEST_TARGETS,
    decode,
    measure,
    response,
    task_loss,
)
from gate1_packets import evaluate_body, make_mixtures


TRAFFIC_FLOOR = 0.40
TRAFFIC_REFRESH = 10
DEFAULT_STEPS = 1600
DEFAULT_SEEDS = 12


def summarize(values):
    x = np.asarray(values, dtype=float)
    return {
        "mean": float(np.mean(x)),
        "min": float(np.min(x)),
        "max": float(np.max(x)),
        "std": float(np.std(x)),
    }


def pack(z_edge: np.ndarray, z_mass: np.ndarray) -> np.ndarray:
    return np.concatenate([z_edge, z_mass])


def body_from_logits(
    z_edge: np.ndarray,
    z_mass: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    return decode(pack(z_edge, z_mass), "both")


def local_traffic(
    z_edge: np.ndarray,
    z_mass: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Traffic each structural element can measure locally."""
    g, mass = body_from_logits(z_edge, z_mass)
    edge_score = np.zeros(E, dtype=float)
    node_score = np.zeros(N, dtype=float)

    for omega in TRAIN_FREQS:
        x = response(g, mass, float(omega))
        for ei, (i, j) in enumerate(EDGES):
            edge_score[ei] += (
                float(abs(x[i] - x[j]) ** 2) / len(TRAIN_FREQS)
            )
        node_score += (
            float(omega * omega)
            * np.abs(x) ** 2
            / len(TRAIN_FREQS)
        )

    edge_score /= float(np.max(edge_score) + 1e-12)
    node_score /= float(np.max(node_score) + 1e-12)
    return edge_score, node_score


def train_local(
    seed: int,
    *,
    steps: int,
    traffic_gating: bool,
    shuffle_traffic: bool = False,
    shuffle_pulse: bool = False,
) -> dict:
    rng = np.random.default_rng(int(seed))

    z_edge = np.zeros(E, dtype=float)
    z_mass = np.zeros(N, dtype=float)

    edge_m1 = np.zeros(E, dtype=float)
    edge_m2 = np.zeros(E, dtype=float)
    mass_m1 = np.zeros(N, dtype=float)
    mass_m2 = np.zeros(N, dtype=float)

    best_edge = z_edge.copy()
    best_mass = z_mass.copy()
    best_loss = task_loss(pack(z_edge, z_mass), "both")

    edge_traffic = np.ones(E, dtype=float)
    node_traffic = np.ones(N, dtype=float)

    active = 0
    possible = 0

    for step_index in range(1, int(steps) + 1):
        if (
            step_index == 1
            or step_index % TRAFFIC_REFRESH == 0
        ):
            edge_traffic, node_traffic = local_traffic(
                z_edge, z_mass
            )
            if shuffle_traffic:
                edge_traffic = edge_traffic[
                    rng.permutation(E)
                ]
                node_traffic = node_traffic[
                    rng.permutation(N)
                ]

        if traffic_gating:
            edge_probability = (
                TRAFFIC_FLOOR
                + (1.0 - TRAFFIC_FLOOR) * edge_traffic
            )
            node_probability = (
                TRAFFIC_FLOOR
                + (1.0 - TRAFFIC_FLOOR) * node_traffic
            )
        else:
            edge_probability = np.ones(E, dtype=float)
            node_probability = np.ones(N, dtype=float)

        # Each local element first chooses its private perturbation sign,
        # then its traffic-gated eligibility.  This ordering is fixed for
        # deterministic receipts.
        edge_sign = rng.choice(
            np.asarray([-1.0, 1.0]), size=E
        )
        edge_sign *= (
            rng.random(E) < edge_probability
        ).astype(float)

        node_sign = rng.choice(
            np.asarray([-1.0, 1.0]), size=N
        )
        node_sign *= (
            rng.random(N) < node_probability
        ).astype(float)

        active += int(np.count_nonzero(edge_sign))
        active += int(np.count_nonzero(node_sign))
        possible += E + N

        probe_size = 0.1 / (step_index ** 0.101)

        plus = pack(
            np.clip(
                z_edge + probe_size * edge_sign,
                -3.0,
                3.0,
            ),
            np.clip(
                z_mass + probe_size * node_sign,
                -3.0,
                3.0,
            ),
        )
        minus = pack(
            np.clip(
                z_edge - probe_size * edge_sign,
                -3.0,
                3.0,
            ),
            np.clip(
                z_mass - probe_size * node_sign,
                -3.0,
                3.0,
            ),
        )

        plus_loss = task_loss(plus, "both")
        minus_loss = task_loss(minus, "both")

        if shuffle_pulse and rng.random() < 0.5:
            plus_loss, minus_loss = minus_loss, plus_loss

        global_pulse = (
            (plus_loss - minus_loss) / (2.0 * probe_size)
        )

        # Three-factor form:
        #   local update = global consequence * stored local eligibility.
        edge_gradient = global_pulse * edge_sign
        mass_gradient = global_pulse * node_sign

        edge_m1 = 0.9 * edge_m1 + 0.1 * edge_gradient
        edge_m2 = (
            0.999 * edge_m2
            + 0.001 * edge_gradient * edge_gradient
        )
        mass_m1 = 0.9 * mass_m1 + 0.1 * mass_gradient
        mass_m2 = (
            0.999 * mass_m2
            + 0.001 * mass_gradient * mass_gradient
        )

        learning_rate = 0.02 / (
            1.0 + 0.0005 * step_index
        )

        z_edge -= (
            learning_rate
            * edge_m1
            / (np.sqrt(edge_m2) + 1e-8)
        )
        z_mass -= (
            learning_rate
            * mass_m1
            / (np.sqrt(mass_m2) + 1e-8)
        )

        # One global resource homeostat per structural field.
        z_edge -= float(np.mean(z_edge))
        z_mass -= float(np.mean(z_mass))
        z_edge = np.clip(z_edge, -3.0, 3.0)
        z_mass = np.clip(z_mass, -3.0, 3.0)

        current_loss = task_loss(
            pack(z_edge, z_mass), "both"
        )
        if current_loss < best_loss:
            best_loss = current_loss
            best_edge = z_edge.copy()
            best_mass = z_mass.copy()

    g, mass = body_from_logits(best_edge, best_mass)
    return {
        "seed": int(seed),
        "loss": float(best_loss),
        "active_fraction": float(active / possible),
        "couplings": g,
        "clock_mass": mass,
    }


def evaluate_arm(rows, mixtures):
    steady = []
    packet = []

    for row in rows:
        z = np.concatenate(
            [
                np.log(row["couplings"]),
                np.log(row["clock_mass"]),
            ]
        )
        steady.append(
            measure(
                z, "both", TEST_FREQS, TEST_TARGETS
            )
        )
        packet.append(
            evaluate_body(
                row["couplings"],
                row["clock_mass"],
                mixtures,
            )
        )

    return {
        "heldout_accuracy": summarize(
            [r["accuracy"] for r in steady]
        ),
        "heldout_mean_margin_db": summarize(
            [r["mean_margin_db"] for r in steady]
        ),
        "heldout_min_margin_db": summarize(
            [r["min_margin_db"] for r in steady]
        ),
        "active_fraction": summarize(
            [row["active_fraction"] for row in rows]
        ),
        "packet_component_accuracy": summarize(
            [r["component_accuracy"] for r in packet]
        ),
        "packet_mean_margin_db": summarize(
            [r["mean_margin_db"] for r in packet]
        ),
        "packet_min_margin_db": summarize(
            [r["min_component_margin_db"] for r in packet]
        ),
        "packet_p05_margin_db": summarize(
            [r["p05_margin_db"] for r in packet]
        ),
        "per_seed": [
            {
                "seed": int(row["seed"]),
                "active_fraction": float(
                    row["active_fraction"]
                ),
                "steady": steady_metric,
                "packets": packet_metric,
            }
            for row, steady_metric, packet_metric
            in zip(rows, steady, packet)
        ],
    }


def run(
    *,
    seeds: int,
    steps: int,
    mixtures_count: int,
    mixture_seed: int,
):
    mixtures = make_mixtures(
        mixtures_count, mixture_seed
    )

    configs = {
        "TRAFFIC_GATED": dict(
            traffic_gating=True,
            shuffle_traffic=False,
            shuffle_pulse=False,
        ),
        "UNGATED_LOCAL": dict(
            traffic_gating=False,
            shuffle_traffic=False,
            shuffle_pulse=False,
        ),
        "SHUFFLED_TRAFFIC": dict(
            traffic_gating=True,
            shuffle_traffic=True,
            shuffle_pulse=False,
        ),
        "SHUFFLED_PULSE": dict(
            traffic_gating=True,
            shuffle_traffic=False,
            shuffle_pulse=True,
        ),
    }

    aggregate = {}
    trained = {}

    for label, kwargs in configs.items():
        rows = [
            train_local(
                seed,
                steps=steps,
                **kwargs,
            )
            for seed in range(int(seeds))
        ]
        trained[label] = rows
        aggregate[label] = evaluate_arm(
            rows, mixtures
        )

    gated = aggregate["TRAFFIC_GATED"]
    ungated = aggregate["UNGATED_LOCAL"]
    shuffled_traffic = aggregate["SHUFFLED_TRAFFIC"]
    shuffled_pulse = aggregate["SHUFFLED_PULSE"]

    requirements = {
        "traffic_gated_steady_accuracy_ge_0p95": (
            gated["heldout_accuracy"]["mean"] >= 0.95
        ),
        "traffic_gated_packet_accuracy_ge_0p99": (
            gated["packet_component_accuracy"]["mean"]
            >= 0.99
        ),
        "traffic_gated_uses_le_0p72_parameters_per_update": (
            gated["active_fraction"]["mean"] <= 0.72
        ),
        "traffic_gating_beats_shuffled_traffic_packets_by_0p04": (
            gated["packet_component_accuracy"]["mean"]
            >= shuffled_traffic[
                "packet_component_accuracy"
            ]["mean"] + 0.04
        ),
        "causal_pulse_beats_shuffled_pulse_packets_by_0p25": (
            gated["packet_component_accuracy"]["mean"]
            >= shuffled_pulse[
                "packet_component_accuracy"
            ]["mean"] + 0.25
        ),
        "causal_pulse_has_positive_packet_p05_margin": (
            gated["packet_p05_margin_db"]["mean"] > 1.0
        ),
        "shuffled_pulse_has_negative_packet_p05_margin": (
            shuffled_pulse[
                "packet_p05_margin_db"
            ]["mean"] < 0.0
        ),
        "traffic_gated_not_worse_than_ungated_by_more_than_0p01": (
            gated["packet_component_accuracy"]["mean"]
            >= ungated["packet_component_accuracy"]["mean"] - 0.01
        ),
    }
    passed = all(requirements.values())

    best_gated = max(
        aggregate["TRAFFIC_GATED"]["per_seed"],
        key=lambda row: (
            row["packets"]["component_accuracy"],
            row["packets"]["min_component_margin_db"],
        ),
    )

    return {
        "gate": 2,
        "classification": (
            "LOCAL_ELIGIBILITY_PLUS_GLOBAL_PULSE_TRAINS_ROUTING_BODY"
            if passed
            else "LOCAL_PLASTICITY_GATE_FAILED"
        ),
        "passed": passed,
        "learning_rule": {
            "edge_local_trace": (
                "mean |x_i-x_j|^2 across calibration tones"
            ),
            "node_local_trace": (
                "mean omega^2 |x_i|^2 across calibration tones"
            ),
            "eligibility_probability": (
                "0.4 + 0.6 * normalized_local_traffic"
            ),
            "stored_local_eligibility": (
                "independent local +/- perturbation sign"
            ),
            "global_signal": (
                "one scalar paired consequence difference "
                "(L_plus-L_minus)/(2*epsilon)"
            ),
            "local_update": (
                "parameter_i <- parameter_i - eta * "
                "global_signal * eligibility_i "
                "(with local Adam-like moments)"
            ),
            "global_homeostasis": (
                "fixed total edge-coupling budget and "
                "fixed total clock-mass budget"
            ),
            "important_boundary": (
                "This is a distributed implementation of simultaneous "
                "perturbation / three-factor learning, not a novel "
                "credit-assignment theorem."
            ),
        },
        "training": {
            "seeds": int(seeds),
            "updates_per_seed": int(steps),
            "scalar_consequence_evaluations_per_update": 2,
            "autograd": False,
            "central_parameter_gradient": False,
        },
        "packet_evaluation": {
            "gate2_retraining": False,
            "mixtures": int(mixtures_count),
            "components_per_body": int(
                2 * mixtures_count
            ),
            "mixture_seed": int(mixture_seed),
        },
        "aggregate": aggregate,
        "best_traffic_gated_seed": best_gated,
        "requirements": requirements,
        "scope": (
            "Locality here means parameter-specific eligibility and "
            "traffic are local; a scalar consequence and resource "
            "homeostat remain global. The implementation is digital "
            "and synchronized. This is not a biological-plasticity "
            "claim."
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--seeds", type=int, default=DEFAULT_SEEDS
    )
    parser.add_argument(
        "--steps", type=int, default=DEFAULT_STEPS
    )
    parser.add_argument(
        "--mixtures", type=int, default=512
    )
    parser.add_argument(
        "--mixture-seed", type=int, default=20260903
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(
            "physics_router/results/GATE2.json"
        ),
    )
    args = parser.parse_args()

    result = run(
        seeds=args.seeds,
        steps=args.steps,
        mixtures_count=args.mixtures,
        mixture_seed=args.mixture_seed,
    )
    args.out.parent.mkdir(
        parents=True, exist_ok=True
    )
    args.out.write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
