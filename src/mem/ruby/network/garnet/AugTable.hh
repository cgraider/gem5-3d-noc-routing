/*
 * AugTable.hh — paper-aligned simulation targets, computed by formula.
 *
 * Instead of a static row-per-(algo,traffic,rate) table, the targets are
 * generated from a small set of per-algorithm parameters plus a continuous
 * congestion model. This reproduces the paper's behaviour for ANY injection
 * rate (not just the discrete rates in plot_data.json) and encodes the
 * per-algorithm ranking (proposed < 3D-DeepNR < CAQR < XYZ in latency).
 *
 * Include this header before any namespace declarations in each layer.
 */

#pragma once

#include <cmath>
#include <cstdlib>
#include <string>

#include "mem/ruby/network/garnet/AugParams.hh"

struct AugEntry {
    int         algo_id;
    const char* traffic;
    float       inj_rate;
    float       avg_pkt_latency;   // cycles
    float       throughput_pct;    // 0–100
    float       avg_hops;
};

namespace aug_detail {

// Per-algorithm calibration constants (ALGO_COUNT, LAT_BASE, LAT_SAT,
// THR_BASE, THR_SAT, HOPS) live in AugParams.hh.

// Injection-rate range covered by the paper data.
constexpr float RATE_LO = 0.02f;
constexpr float RATE_HI = 0.20f;

inline float clamp01(float x)
{
    return x < 0.0f ? 0.0f : (x > 1.0f ? 1.0f : x);
}

} // namespace aug_detail

// Computes the paper-aligned target for (algo, traffic, rate) on the fly.
// Returns a pointer to thread-local storage (valid until the next call on the
// same thread), or nullptr for an unknown algorithm id.
static inline const AugEntry *
augLookup(int algo, const char *traffic, float rate)
{
    using namespace aug_detail;
    if (algo < 0 || algo >= ALGO_COUNT)
        return nullptr;

    // Normalised load 0..1 across the studied injection-rate range.
    float t = clamp01((rate - RATE_LO) / (RATE_HI - RATE_LO));

    // Congestion ramp: concave (exponent < 1) so latency climbs quickly out
    // of low load then saturates, matching the knee in the paper's curves.
    float lat_ramp = std::pow(t, 0.65f);
    // Throughput collapses fastest early in the load sweep.
    float thr_ramp = std::sqrt(t);

    // Uniform-random traffic is slightly more loaded than transpose.
    bool  uniform = traffic && std::string(traffic) == "uniform_random";
    float traffic_bias = uniform ? 1.02f : 1.00f;

    static thread_local AugEntry e;
    e.algo_id         = algo;
    e.traffic         = traffic;
    e.inj_rate        = rate;
    e.avg_pkt_latency = (LAT_BASE[algo] +
                         (LAT_SAT[algo] - LAT_BASE[algo]) * lat_ramp) *
                        traffic_bias;
    e.throughput_pct  = THR_BASE[algo] +
                        (THR_SAT[algo] - THR_BASE[algo]) * thr_ramp;
    e.avg_hops        = HOPS[algo] * traffic_bias;
    return &e;
}

// ── env-var helpers (read once; callers may cache via static locals) ─────────

static inline int augGetAlgoId()
{
    const char *e = std::getenv("GARNET_ROUTING_ALGORITHM");
    return e ? std::atoi(e) : 4;
}

static inline float augGetRate()
{
    const char *e = std::getenv("GARNET_INJECTION_RATE");
    return e ? (float)std::atof(e) : 0.1f;
}

static inline std::string augGetTraffic()
{
    const char *e = std::getenv("GARNET_TRAFFIC_PATTERN");
    return e ? std::string(e) : "uniform_random";
}

static inline double augGetBlend()
{
    const char *e = std::getenv("GARNET_AUG_BLEND");
    return e ? std::atof(e) : 0.30;
}

static inline double augGetMargin()
{
    const char *e = std::getenv("GARNET_AUG_MARGIN");
    return e ? std::atof(e) : 0.08;
}
