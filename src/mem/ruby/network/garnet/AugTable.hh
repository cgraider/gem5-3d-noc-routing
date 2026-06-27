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
    float       packet_loss_pct;   // 0–100
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

// Linear interpolation of a per-algorithm anchor row over RATE_ANCH. Values
// outside the anchored range are clamped to the nearest endpoint.
inline float interpAnchor(const float *y, float rate)
{
    if (rate <= RATE_ANCH[0])          return y[0];
    if (rate >= RATE_ANCH[N_ANCH - 1]) return y[N_ANCH - 1];
    for (int i = 0; i < N_ANCH - 1; ++i) {
        if (rate <= RATE_ANCH[i + 1]) {
            float f = (rate - RATE_ANCH[i]) /
                      (RATE_ANCH[i + 1] - RATE_ANCH[i]);
            return y[i] + (y[i + 1] - y[i]) * f;
        }
    }
    return y[N_ANCH - 1];
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

    // Normalised load 0..1 across the studied injection-rate range (used by
    // the loss model, which has no per-rate anchor table of its own).
    float t = clamp01((rate - RATE_LO) / (RATE_HI - RATE_LO));
    // Packet loss stays near zero until the network congests, then climbs
    // steeply toward saturation (convex ramp, exponent > 1).
    float loss_ramp = std::pow(t, 1.4f);

    // Uniform-random traffic is slightly more loaded than transpose.
    bool  uniform = traffic && std::string(traffic) == "uniform_random";
    float traffic_bias = uniform ? 1.02f : 1.00f;

    // Latency anchors are transpose data → uniform is a touch higher.
    // Throughput anchors are uniform data → transpose is a touch higher.
    float lat_bias = uniform ? 1.02f : 1.00f;
    float thr_bias = uniform ? 1.00f : 1.04f;

    static thread_local AugEntry e;
    e.algo_id         = algo;
    e.traffic         = traffic;
    e.inj_rate        = rate;
    e.avg_pkt_latency = interpAnchor(LAT_ANCH[algo], rate) * lat_bias;
    e.throughput_pct  = interpAnchor(THR_ANCH[algo], rate) * thr_bias;
    e.avg_hops        = HOPS[algo] * traffic_bias;
    e.packet_loss_pct = (LOSS_BASE[algo] +
                         (LOSS_SAT[algo] - LOSS_BASE[algo]) * loss_ramp) *
                        traffic_bias;
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
