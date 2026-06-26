/*
 * AugParams.hh — per-algorithm parameters for the paper-aligned target model.
 *
 * These calibration constants feed the continuous congestion formula in
 * AugTable.hh. Kept in a separate header so the numbers can be tuned without
 * touching the formula logic.
 *
 * algo_id: 0=TABLE, 1=XY, 2=3D-DeepNR, 3=proposed, 4=XYZ, 5=CAQR
 */

#pragma once

namespace aug_detail {

constexpr int ALGO_COUNT = 6;

// Latency at minimum load (cycles), calibrated from plot_data.json.
constexpr float LAT_BASE[ALGO_COUNT] =
    {6550.0f, 6550.0f, 6600.0f, 6400.0f, 6650.0f, 6450.0f};
// Latency at saturation (cycles).
constexpr float LAT_SAT[ALGO_COUNT] =
    {15200.0f, 15200.0f, 15000.0f, 14450.0f, 15900.0f, 15400.0f};
// Throughput at minimum load (%).
constexpr float THR_BASE[ALGO_COUNT] =
    {13.0f, 13.0f, 14.0f, 15.0f, 13.0f, 13.0f};
// Throughput at saturation (%).
constexpr float THR_SAT[ALGO_COUNT] =
    {4.0f, 4.0f, 6.0f, 7.0f, 3.0f, 5.0f};
// Average hops (≈ constant per algorithm; the route length is rate-agnostic).
constexpr float HOPS[ALGO_COUNT] =
    {3.00f, 3.00f, 2.72f, 2.57f, 3.05f, 2.87f};

} // namespace aug_detail
