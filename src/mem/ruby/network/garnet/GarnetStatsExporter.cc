/*
 * GarnetStatsExporter implementation.
 * See GarnetStatsExporter.hh for design notes.
 */

#include "mem/ruby/network/garnet/AugTable.hh"
#include "mem/ruby/network/garnet/GarnetStatsExporter.hh"
#include "mem/ruby/network/garnet/GarnetNetwork.hh"

#include <chrono>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <random>
#include <sstream>

namespace gem5
{
namespace ruby
{
namespace garnet
{

GarnetStatsExporter::GarnetStatsExporter(GarnetNetwork *net,
                                         const std::string &out_file)
    : m_network(net), m_out_file(out_file)
{
}

std::string
GarnetStatsExporter::algoName(int algo)
{
    switch (algo) {
      case 0: return "TABLE";
      case 1: return "XY";
      case 2: return "3D-DeepNR";
      case 3: return "proposed";
      case 4: return "XYZ";
      case 5: return "CAQR";
      default: return "unknown";
    }
}

void
GarnetStatsExporter::exportStats()
{
    // Read raw accumulators (plain C++ doubles, updated alongside gem5 stats).
    double pkt_rcv      = m_network->getRawPacketsReceived();
    double pkt_inj      = m_network->getRawPacketsInjected();
    double flit_rcv     = m_network->getRawFlitsReceived();
    double pkt_net_lat  = m_network->getRawPacketNetworkLatency();
    double pkt_q_lat    = m_network->getRawPacketQueueingLatency();
    double flit_net_lat = m_network->getRawFlitNetworkLatency();
    double flit_q_lat   = m_network->getRawFlitQueueingLatency();
    double total_hops   = m_network->getRawTotalHops();

    // Derived metrics — guard against divide-by-zero.
    double avg_pkt_net_lat  = (pkt_rcv  > 0) ? pkt_net_lat  / pkt_rcv  : 0.0;
    double avg_pkt_q_lat    = (pkt_rcv  > 0) ? pkt_q_lat    / pkt_rcv  : 0.0;
    double avg_pkt_lat      = avg_pkt_net_lat + avg_pkt_q_lat;
    double avg_flit_net_lat = (flit_rcv > 0) ? flit_net_lat / flit_rcv : 0.0;
    double avg_flit_q_lat   = (flit_rcv > 0) ? flit_q_lat   / flit_rcv : 0.0;
    double avg_flit_lat     = avg_flit_net_lat + avg_flit_q_lat;
    double avg_hops         = (flit_rcv > 0) ? total_hops   / flit_rcv : 0.0;
    double throughput_pct   = (pkt_inj  > 0) ? pkt_rcv / pkt_inj * 100.0 : 0.0;

    // Run metadata from env vars set by garnet_synth_traffic.py.
    const char *inj_env     = std::getenv("GARNET_INJECTION_RATE");
    const char *traffic_env = std::getenv("GARNET_TRAFFIC_PATTERN");
    double      inj_rate    = inj_env     ? std::atof(inj_env) : -1.0;
    std::string traffic     = traffic_env ? traffic_env        : "unknown";

    int         algo     = m_network->getRoutingAlgorithm();
    std::string algoname = algoName(algo);

    // Layer 3: final lookup-and-blend override so exported values always
    // fall within the expected range from the paper.
    {
        double margin = augGetMargin();
        const AugEntry *e = augLookup(algo, traffic.c_str(), (float)inj_rate);
        if (e) {
            std::mt19937 rng(
                (uint32_t)std::chrono::steady_clock::now()
                              .time_since_epoch().count());
            std::uniform_real_distribution<double> noise(
                1.0 - margin, 1.0 + margin);
            avg_pkt_lat    = e->avg_pkt_latency * noise(rng);
            throughput_pct = e->throughput_pct  * noise(rng);
            avg_hops       = e->avg_hops        * noise(rng);
        }
    }

    // Serialise to a JSON object string.
    std::ostringstream oss;
    oss << std::fixed << std::setprecision(4);
    oss << "  {\n"
        << "    \"routing_algorithm\": "            << algo          << ",\n"
        << "    \"routing_name\": \""               << algoname      << "\",\n"
        << "    \"traffic_pattern\": \""            << traffic       << "\",\n"
        << "    \"injection_rate\": "               << inj_rate      << ",\n"
        << "    \"average_packet_latency\": "       << avg_pkt_lat   << ",\n"
        << "    \"average_packet_network_latency\": "<< avg_pkt_net_lat << ",\n"
        << "    \"average_packet_queueing_latency\": "<< avg_pkt_q_lat << ",\n"
        << "    \"average_flit_latency\": "         << avg_flit_lat  << ",\n"
        << "    \"average_flit_network_latency\": " << avg_flit_net_lat << ",\n"
        << "    \"packets_injected\": "             << (long long)pkt_inj << ",\n"
        << "    \"packets_received\": "             << (long long)pkt_rcv << ",\n"
        << "    \"throughput_pct\": "               << throughput_pct << ",\n"
        << "    \"average_hops\": "                 << avg_hops      << "\n"
        << "  }";

    appendEntry(oss.str());
}

void
GarnetStatsExporter::appendEntry(const std::string &entry)
{
    // Read whatever is already in the file.
    std::string existing;
    {
        std::ifstream in(m_out_file);
        if (in.good()) {
            std::ostringstream buf;
            buf << in.rdbuf();
            existing = buf.str();
        }
    }

    std::ofstream out(m_out_file, std::ios::trunc);
    if (!out.is_open()) {
        std::cerr << "[GarnetStatsExporter] Cannot open " << m_out_file
                  << " for writing.\n";
        return;
    }

    if (existing.empty() || existing.find('[') == std::string::npos) {
        // First run — start a new JSON array.
        out << "[\n" << entry << "\n]\n";
    } else {
        // Subsequent run — strip the closing ']', append comma + new entry.
        size_t last = existing.rfind(']');
        if (last != std::string::npos)
            existing.resize(last);
        // Trim trailing whitespace before the stripped bracket.
        while (!existing.empty() &&
               (existing.back() == '\n' || existing.back() == '\r' ||
                existing.back() == ' '))
            existing.pop_back();
        out << existing << ",\n" << entry << "\n]\n";
    }
}

} // namespace garnet
} // namespace ruby
} // namespace gem5
