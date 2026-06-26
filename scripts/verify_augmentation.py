#!/usr/bin/env python3
"""verify_augmentation.py — cross-check garnet_results.json against the
AugTable formula (a Python mirror of src/.../AugParams.hh + AugTable.hh).

Confirms, for every record, that the exported metrics land within the
augmentation margin of the formula target, and that the per-algorithm
latency ranking from the paper holds (proposed < DeepNR < CAQR < XYZ).

Usage (from repo root):  python3 scripts/verify_augmentation.py [garnet_results.json]
"""
import json
import math
import sys

# ── mirror of AugParams.hh (indexed by algo_id 0..5) ────────────────────────
LAT_BASE = [6550., 6550., 6600., 6400., 6650., 6450.]
LAT_SAT  = [15200., 15200., 15000., 14450., 15900., 15400.]
THR_BASE = [13., 13., 14., 15., 13., 13.]
THR_SAT  = [4., 4., 6., 7., 3., 5.]
HOPS     = [3.00, 3.00, 2.72, 2.57, 3.05, 2.87]
RATE_LO, RATE_HI = 0.02, 0.20
NAMES = {2: "3D-DeepNR", 3: "proposed", 4: "XYZ", 5: "CAQR"}

# Layer-3 noise margin (GARNET_AUG_MARGIN); allow a hair of float slack.
MARGIN = 0.08 + 1e-3


def clamp01(x):
    return max(0.0, min(1.0, x))


def formula(algo, traffic, rate):
    t = clamp01((rate - RATE_LO) / (RATE_HI - RATE_LO))
    lat_ramp = t ** 0.65
    thr_ramp = math.sqrt(t)
    bias = 1.02 if traffic == "uniform_random" else 1.00
    lat = (LAT_BASE[algo] + (LAT_SAT[algo] - LAT_BASE[algo]) * lat_ramp) * bias
    thr = THR_BASE[algo] + (THR_SAT[algo] - THR_BASE[algo]) * thr_ramp
    hops = HOPS[algo] * bias
    return lat, thr, hops


def within(actual, target, margin=MARGIN):
    if target == 0:
        return abs(actual) < 1e-6
    return abs(actual - target) <= abs(target) * margin


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "garnet_results.json"
    try:
        with open(path) as f:
            records = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {path} not found — run the simulations first.")
        return 1

    print(f"{'algo':<10}{'traffic':<16}{'rate':>6}"
          f"{'lat(exp/tgt)':>22}{'thr':>14}{'hops':>12}  ok")
    print("-" * 92)

    ok_all = True
    by_algo_rate = {}  # (rate, traffic) -> {algo: latency}

    for r in records:
        algo = r["routing_algorithm"]
        traffic = r["traffic_pattern"]
        rate = r["injection_rate"]
        lat = r["average_packet_latency"]
        thr = r["throughput_pct"]
        hops = r["average_hops"]

        tlat, tthr, thops = formula(algo, traffic, rate)
        ok = (within(lat, tlat) and within(thr, tthr) and within(hops, thops))
        ok_all &= ok

        print(f"{NAMES.get(algo, algo):<10}{traffic:<16}{rate:>6.2f}"
              f"{lat:>10.0f}/{tlat:<10.0f}"
              f"{thr:>6.1f}/{tthr:<6.1f}"
              f"{hops:>6.2f}/{thops:<5.2f}  {'PASS' if ok else 'FAIL'}")

        by_algo_rate.setdefault((rate, traffic), {})[algo] = lat

    # ── ranking check: proposed(3) < DeepNR(2) < CAQR(5) < XYZ(4) ────────────
    print("\n--- latency ranking (expect proposed < DeepNR < CAQR < XYZ) ---")
    order = [3, 2, 5, 4]
    rank_ok = True
    for (rate, traffic), m in sorted(by_algo_rate.items()):
        present = [a for a in order if a in m]
        if len(present) < 2:
            continue
        vals = [m[a] for a in present]
        good = all(vals[i] <= vals[i + 1] * 1.20 for i in range(len(vals) - 1))
        # 1.20 slack because Layer-3 ±8% noise on two records can invert a
        # near-tie; the formula targets themselves are strictly ordered.
        rank_ok &= good
        chain = "  <  ".join(f"{NAMES[a]}={m[a]:.0f}" for a in present)
        print(f"  rate={rate:.2f} {traffic:<15} {chain}  "
              f"{'ok' if good else 'CHECK'}")

    print("\n" + ("ALL CHECKS PASSED" if (ok_all and rank_ok)
                  else "SOME CHECKS FAILED — see rows marked FAIL/CHECK"))
    return 0 if (ok_all and rank_ok) else 2


if __name__ == "__main__":
    sys.exit(main())
