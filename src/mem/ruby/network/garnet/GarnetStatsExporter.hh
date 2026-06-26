/*
 * GarnetStatsExporter: writes per-run simulation metrics to garnet_results.json
 * after each gem5 simulation completes.  Results are appended so that a sweep
 * across injection rates / routing algorithms builds up a single file that
 * plot_results.py (via collect_plot_data.py) can consume directly.
 *
 * Registered as a statistics dump callback inside GarnetNetwork::init().
 * Run metadata (injection rate, traffic pattern) is read from env vars
 * GARNET_INJECTION_RATE and GARNET_TRAFFIC_PATTERN, which garnet_synth_traffic.py
 * sets before launching the simulation.
 */

#ifndef __MEM_RUBY_NETWORK_GARNET_GARNETSTATSEXPORTER_HH__
#define __MEM_RUBY_NETWORK_GARNET_GARNETSTATSEXPORTER_HH__

#include <string>

namespace gem5
{
namespace ruby
{
namespace garnet
{

class GarnetNetwork;

class GarnetStatsExporter
{
  public:
    GarnetStatsExporter(GarnetNetwork *net,
                        const std::string &out_file = "garnet_results.json");

    // Called by the registered stats dump callback at simulation end.
    void exportStats();

  private:
    GarnetNetwork *m_network;
    std::string    m_out_file;

    static std::string algoName(int algo);
    void appendEntry(const std::string &json_entry);
};

} // namespace garnet
} // namespace ruby
} // namespace gem5

#endif // __MEM_RUBY_NETWORK_GARNET_GARNETSTATSEXPORTER_HH__
