# Project Documentation

Docs for the 3D NoC routing research in this gem5 fork (algorithms: XYZ, CAQR, DeepNR3D,
Proposed). Organised as a learning path — read the folders in order.

## 1. [Fundamentals](1-fundamentals/) — learn this first

What you need to understand about gem5 / Ruby / Garnet **before** reading or writing the
routing algorithms.

- [gem5-ruby-garnet-primer.md](1-fundamentals/gem5-ruby-garnet-primer.md) — layers, flits/VCs,
  the router pipeline, the router-ID formula, how RoutingUnit plugs in, the RL loop.
- [simulation-sequence.md](1-fundamentals/simulation-sequence.md) — every file and function in
  execution order for one simulation run.

## 2. [Algorithms](2-algorithms/) — code & algorithm walkthroughs

One document per routing algorithm, in increasing complexity.

- [xyz.md](2-algorithms/xyz.md) — deterministic dimension-ordered 3D baseline (ID 4).
- [caqr.md](2-algorithms/caqr.md) — tabular Congestion-Aware Q-Routing, 2D (ID 5).
- [deepnr3d.md](2-algorithms/deepnr3d.md) — DQN agent, 3D, 5-feature state (ID 2).
- [proposed.md](2-algorithms/proposed.md) — enhanced DQN, 10-feature state, Huber loss (ID 3).

## 3. [How-to](3-howto/) — build, run, evaluate

- [build.md](3-howto/build.md) — environment, dependencies, `scons` targets, ZMQ.
- [run.md](3-howto/run.md) — run each algorithm, **plus the evaluation phase** (§7) that runs
  all four, collects metrics, verifies the ranking, and plots the comparison.

## [notimportant/](notimportant/) — archived / redundant

Older or superseded notes kept for reference, not part of the main learning path:

- `AUGMENTATION_PLAN.md` — design of the paper-alignment augmentation layer.
- `README-augmentation.md` — the augmentation run/verify/plot workflow (previous docs index).
- `stats-flow.md` — how gem5 accumulates stats (overlaps with the simulation sequence).
- `results_comparison.md` — early comparison numbers (flagged as misleading / pre-convergence).

## 🇮🇷 [for_shojaee/](for_shojaee/) — Persian teaching edition

A **Farsi**, beginner-friendly retelling of the fundamentals, algorithms, and how-to material,
written as a tutorial for a junior student (with small inline C++/Python teaching notes and
colored callouts). See [for_shojaee/README.md](for_shojaee/README.md).

---

Top-level [../CLAUDE.md](../CLAUDE.md) is the quick orientation for the whole repository.
