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

**Gate 1 — time domain.** Launch finite packets instead of solving steady sinusoids. Require successful routing under onset, offset, and mixtures.

**Gate 2 — local plasticity.** Replace external SPSA parameter updates with local traffic traces plus one global scalar consequence.

**Gate 3 — memory.** Let repeated traffic slowly change `g` and `m`; test whether yesterday's signals reshape tomorrow's routes.

**Gate 4 — useful task.** Replace frequency labels with an actual signal-processing problem where physical filtering/routing is useful.

## Run

```bash
python physics_router/experiment.py
```

**Body first. Router never. Claims last.**
