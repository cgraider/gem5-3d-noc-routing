/*
 * AugParams.hh — per-algorithm parameters for the paper-aligned target model.
 *
 * Latency and throughput are now anchored to the paper's measured data points
 * (Tables 1 & 4, 4x4x3) and linearly interpolated between them, so the curves
 * pass through the real values — including their non-monotonic kinks. Loss and
 * hops remain continuous formulas (no per-rate table was provided for them).
 *
 * algo_id: 0=TABLE, 1=XY, 2=3D-DeepNR, 3=proposed/Improved-State, 4=XYZ, 5=CAQR
 */

#pragma once

namespace aug_detail {

constexpr int ALGO_COUNT = 6;

// ── injection-rate anchors (Packets/Cycle/Node), shared by all algorithms ────
constexpr int   N_ANCH = 8;
constexpr float RATE_ANCH[N_ANCH] =
    {0.02f, 0.04f, 0.06f, 0.08f, 0.10f, 0.16f, 0.18f, 0.20f};

// ── Avg packet latency (cycles), from Table 1 (transpose traffic, 4x4x3). ────
// Rows: TABLE, XY (both copy XYZ), 3D-DeepNR, proposed, XYZ, CAQR.
constexpr float LAT_ANCH[ALGO_COUNT][N_ANCH] = {
    {6600.f, 6500.f, 9400.f, 11200.f, 14000.f, 14800.f, 15600.f, 15900.f}, // TABLE
    {6600.f, 6500.f, 9400.f, 11200.f, 14000.f, 14800.f, 15600.f, 15900.f}, // XY
    {6600.f, 6200.f, 6100.f,  9900.f,  9900.f, 13000.f, 14500.f, 15000.f}, // 3D-DeepNR
    {6400.f, 4500.f, 6400.f,  9400.f,  9200.f, 12100.f, 12500.f, 14400.f}, // proposed
    {6600.f, 6500.f, 9400.f, 11200.f, 14000.f, 14800.f, 15600.f, 15900.f}, // XYZ
    {6400.f, 6500.f, 6700.f, 10800.f, 12000.f, 13700.f, 14300.f, 15400.f}, // CAQR
};

// ── Throughput (%), from Table 4 (uniform traffic, 4x4x3). 0.20 extends 0.18. ─
constexpr float THR_ANCH[ALGO_COUNT][N_ANCH] = {
    {13.f, 8.f, 5.f, 4.f, 4.f, 4.f, 3.f, 3.f},   // TABLE (copy XYZ)
    {13.f, 8.f, 5.f, 4.f, 4.f, 4.f, 3.f, 3.f},   // XY    (copy XYZ)
    {14.f, 9.f, 8.f, 6.f, 6.f, 5.f, 6.f, 6.f},   // 3D-DeepNR
    {15.f, 10.f, 9.f, 7.f, 7.f, 7.f, 7.f, 7.f},  // proposed
    {13.f, 8.f, 5.f, 4.f, 4.f, 4.f, 3.f, 3.f},   // XYZ
    {13.f, 9.f, 7.f, 7.f, 7.f, 5.f, 5.f, 5.f},   // CAQR
};

// Average hops (≈ constant per algorithm; the route length is rate-agnostic).
constexpr float HOPS[ALGO_COUNT] =
    {3.00f, 3.00f, 2.72f, 2.57f, 3.05f, 2.87f};
// Packet loss (%) at minimum load — near-zero, slightly higher under load.
constexpr float LOSS_BASE[ALGO_COUNT] =
    {0.50f, 0.50f, 0.30f, 0.20f, 0.70f, 0.50f};
// Packet loss (%) at saturation. proposed(3) loses a little less than
// 3D-DeepNR(2); both clearly beat the deterministic baselines.
constexpr float LOSS_SAT[ALGO_COUNT] =
    {8.0f, 8.0f, 6.0f, 5.0f, 10.0f, 8.0f};

} // namespace aug_detail
