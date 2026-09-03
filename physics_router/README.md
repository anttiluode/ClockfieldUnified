# Physics Router — adaptive space + adaptive local time

This is a computational offshoot of **ClockfieldUnified** and **OutoSynapsi**.

The narrow question is:

> **Can a body route different signal content to different destinations without a per-input routing matrix, if both its spatial couplings and its local clock rates are adaptable?**

No gravity claim is required.

## The body

Seven damped oscillators form two routes from one input to two outputs, with one cross-link.

Two persistent parameter fields define the medium:

```text
g_e     edge coupling / spatial stiffness
m_i     node inertia / "clock mass"

N_i = 1 / sqrt(m_i)     local clock scale
```

Dynamics:

```text
M x_ddot + gamma x_dot + (L(g) + kappa I) x = b u(t)
```

For a sinusoidal input at angular frequency `omega`, the steady response is

```text
[-omega^2 M + i omega gamma I + L(g) + kappa I] x = b.
```

There is **no input-dependent branch selector**. The same fixed body sees every signal. Frequency-dependent resonance and impedance determine which output receives more energy.

## Gate 0 task

Four training frequencies must alternate destinations:

```text
0.55  -> upper
0.85  -> lower
1.15  -> upper
1.45  -> lower
```

Held-out evaluation contains 80 nearby frequencies, +/- 0.025 around the four training centers, excluding the centers themselves.

This is deliberately harder than "all low frequencies left, all high frequencies right": the desired routing alternates repeatedly across frequency.

## Learning is scalar

Training uses SPSA.

Each structural update asks only two questions:

```text
task score after + perturbation?
task score after - perturbation?
```

No autograd or analytic gradient is used.

The experiment compares:

```text
SPACE_ONLY        learn g, clocks fixed
CLOCK_ONLY        learn m, spatial couplings fixed
SPACE_CLOCK       learn both
SHUFFLED          learn both, but randomly reverse half the +/- consequences
```

Both edge couplings and node masses have fixed total budgets.

## Committed result

12 independent seeds, 1,600 SPSA updates each:

| arm | held-out routing accuracy | mean margin | mean worst-frequency margin |
|---|---:|---:|---:|
| SPACE_ONLY | 81.25% | 9.44 dB | -0.47 dB |
| CLOCK_ONLY | 75.00% | 11.47 dB | -1.77 dB |
| **SPACE_CLOCK** | **93.75%** | **14.07 dB** | **+3.30 dB** |
| shuffled consequence | 77.50% | 5.05 dB | -2.36 dB |

The important number is not only classification accuracy. The joint body is the only arm with a **positive mean worst-frequency routing margin**.

One representative joint seed routes all 80 held-out frequencies correctly with minimum margin **12.71 dB**.

Classification:

> `SPACE_AND_LOCAL_TIME_JOINTLY_SUPPORT_FREQUENCY_ROUTING`

Receipt: [`results/GATE0.json`](results/GATE0.json)

## Gate 1 — frozen body, finite packet mixtures

Gate 1 does **not** retrain the body.

Every arm is first trained exactly as Gate 0: four pure steady sinusoids only. Then its structure is frozen.

The held-out world contains **512 mixtures**. Every mixture contains two finite Gaussian-windowed packets:

```text
one carrier from the UPPER family: 0.55 or 1.15 +/- 0.025
one carrier from the LOWER family: 0.85 or 1.45 +/- 0.025
```

Amplitude, phase, packet width, center time, and relative onset are randomized. The two packet centers can be up to 20 time units apart.

The full output waveform is synthesized through the same fixed linear body. Each component is scored by narrow-band energy at the intended versus wrong output.

That means Gate 1 asks:

> **Did the body trained on isolated tones learn only four points, or did it become a medium that also separates unseen finite mixtures?**

### Gate 1 result

12 frozen bodies per arm, 512 mixtures = 1,024 routed components per body:

| frozen body | component accuracy | mean margin | mean 5th-percentile margin |
|---|---:|---:|---:|
| uniform | 50.00% | ~0 dB | ~0 dB |
| SPACE_ONLY | 81.18% | 6.52 dB | -0.20 dB |
| CLOCK_ONLY | 74.90% | 7.77 dB | -1.32 dB |
| **SPACE_CLOCK** | **94.24%** | **9.67 dB** | **+1.61 dB** |
| shuffled-consequence training | 77.87% | 3.45 dB | -2.19 dB |

A best joint seed routes **all 1,024 held-out packet components correctly**, with worst component margin **+4.51 dB**.

No Gate-1 optimization was allowed.

Classification:

> `FROZEN_SPACE_CLOCK_BODY_SEPARATES_UNSEEN_PACKET_MIXTURES`

Receipt: [`results/GATE1.json`](results/GATE1.json) · [experiment](gate1_packets.py) · [live packet demo](../packets.html)

This is stronger than Gate 0 in one narrow way: the useful object is no longer merely a lookup-like set of four resonances. The same passive body handles **superposed finite signals with unseen phases, amplitudes, widths, offsets, and nearby frequencies**.

The boundary remains important: linear superposition and spectral separation are doing the heavy lifting. This is not blind source separation or semantic routing.

## What this means

In this toy:

```text
space g_e
    controls coupling / routes

local time m_i
    controls inertia / resonance / dwell

g + m together
    create a frequency-selective body
```

The signal is not told which branch to take. Its spectrum interacts with the medium.

That is the precise, defensible version of **physics-routed computation** in this repo.

## What this does not mean

- `m_i` is **not gravitational mass**. It is oscillator inertia used as a local time-scale parameter.
- This does not import Einstein dynamics into Clockfield.
- Frequency is not semantics. The input "content" is only spectral content.
- A tiny explicit digital router can solve this toy problem trivially.
- The GPU still pays for the linear solves. Nothing is computationally free in this implementation.
- Training is still performed by an external scalar optimizer. The body has not yet evolved its own local plasticity law.
- This is a passive linear resonant medium after training, not a transformer replacement.

The useful question is whether the architecture buys anything when the signal itself lives naturally in a wave/analog substrate, or when adaptive dwell and routing are otherwise expensive to schedule explicitly.

## Next gates

**Gate 2 — local plasticity.** Replace external SPSA parameter updates with local traffic traces plus one global scalar consequence.

**Gate 3 — memory.** Let repeated traffic slowly change `g` and `m`; test whether yesterday's signals reshape tomorrow's routes.

**Gate 4 — useful task.** Replace frequency labels with an actual signal-processing problem where physical filtering/routing is useful.

## Run

```bash
python physics_router/experiment.py
python physics_router/gate1_packets.py
```

**Body first. Router never. Claims last.**
