/*
 * Copyright (c) 2008 Princeton University
 * Copyright (c) 2016 Georgia Institute of Technology
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are
 * met: redistributions of source code must retain the above copyright
 * notice, this list of conditions and the following disclaimer;
 * redistributions in binary form must reproduce the above copyright
 * notice, this list of conditions and the following disclaimer in the
 * documentation and/or other materials provided with the distribution;
 * neither the name of the copyright holders nor the names of its
 * contributors may be used to endorse or promote products derived from
 * this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
 * A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 * OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 * DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 * THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

#include "mem/ruby/network/garnet/RoutingUnit.hh"

#include "base/cast.hh"
#include "base/compiler.hh"
#include "debug/RubyNetwork.hh"
#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "mem/ruby/network/garnet/InputUnit.hh"
#include "mem/ruby/network/garnet/OutputUnit.hh"
#include "mem/ruby/network/garnet/Router.hh"
#include "mem/ruby/network/garnet/flit.hh"
#include "mem/ruby/slicc_interface/Message.hh"
#include "sim/cur_tick.hh"
#include "sim/sim_exit.hh"
#include <cstdlib> // For rand() and RAND_MAX

// ZMQ includes for DeepNR communication
#ifdef USE_ZMQ
#include "mem/ruby/network/garnet/flit.hh"
#include <errno.h>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#include <vector>
#include <zmq.h>
#endif

namespace gem5 {

namespace ruby {

namespace garnet {

// [فارسی] ===================================================================
// namespace DeepNR: انباری مشترک برای پاداش و flag پایان (done) بینِ OutputUnit و
// تابعِ مسیریابی. OutputUnit پاداش را «ذخیره» می‌کند و تابعِ مسیریابی در پرشِ بعدی
// آن را «می‌خواند». هر دو الگوریتمِ DeepNR3D و Proposed از همین انبار استفاده می‌کنند
// (بی‌خطر است چون هم‌زمان اجرا نمی‌شوند).
// ===========================================================================
// Global storage for DeepNR rewards (accessible from OutputUnit)
namespace DeepNR {
static std::map<int, float> packet_rewards; // [فارسی] شناسهٔ بسته → پاداش
static std::map<int, bool> packet_terminal;  // [فارسی] شناسهٔ بسته → آیا پرشِ بعدی مقصد است؟
static std::ofstream *log_file = nullptr;
static int log_every_n = 10;
static int packet_counter = 0;

// [فارسی] store_reward: پاداشِ یک بسته را ذخیره می‌کند (از داخلِ OutputUnit صدا زده می‌شود).
void store_reward(int packet_id, float reward, double queuing_delay_cycles) {
  packet_rewards[packet_id] = reward;

  // Log reward calculation
  if (log_file && log_file->is_open() && (packet_counter % log_every_n == 0)) {
    *log_file << std::fixed << std::setprecision(4);
    *log_file << "REWARD | Pkt[" << packet_id << "] | Reward[" << reward
              << "] | QueuingDelay[" << queuing_delay_cycles << " cycles]\n";
    log_file->flush();
  }
}

// [فارسی] store_terminal: ثبتِ اینکه آیا پرشِ بعدیِ این بسته به مقصد می‌رسد یا نه.
void store_terminal(int packet_id, bool is_terminal) {
  packet_terminal[packet_id] = is_terminal;
}

// [فارسی] get_reward: پاداشِ ذخیره‌شده را برمی‌گرداند و پاک می‌کند (یک‌بار مصرف).
// اگر پاداشی نباشد، ۰ برمی‌گرداند.
float get_reward(int packet_id) {
  if (packet_rewards.find(packet_id) != packet_rewards.end()) {
    float reward = packet_rewards[packet_id];
    packet_rewards.erase(packet_id); // One-time use
    return reward;
  }
  return 0.0f;
}

// [فارسی] get_done: flag پایان را برمی‌گرداند و پاک می‌کند (یک‌بار مصرف).
bool get_done(int packet_id) {
  if (packet_terminal.find(packet_id) != packet_terminal.end()) {
    bool done = packet_terminal[packet_id];
    packet_terminal.erase(packet_id); // One-time use
    return done;
  }
  return false;
}

void set_log_file(void *file, int every_n, int counter) {
  log_file = static_cast<std::ofstream *>(file);
  log_every_n = every_n;
  packet_counter = counter;
}
} // namespace DeepNR

// [فارسی] constructor: pointerِ روتر را ذخیره و جدول‌های مسیریابی را خالی می‌کند.
RoutingUnit::RoutingUnit(Router *router) {
  m_router = router;
  m_routing_table.clear();
  m_weight_table.clear();
}

void RoutingUnit::addRoute(std::vector<NetDest> &routing_table_entry) {
  if (routing_table_entry.size() > m_routing_table.size()) {
    m_routing_table.resize(routing_table_entry.size());
  }
  for (int v = 0; v < routing_table_entry.size(); v++) {
    m_routing_table[v].push_back(routing_table_entry[v]);
  }
}

void RoutingUnit::addWeight(int link_weight) {
  m_weight_table.push_back(link_weight);
}

bool RoutingUnit::supportsVnet(int vnet, std::vector<int> sVnets) {
  // If all vnets are supported, return true
  if (sVnets.size() == 0) {
    return true;
  }

  // Find the vnet in the vector, return true
  if (std::find(sVnets.begin(), sVnets.end(), vnet) != sVnets.end()) {
    return true;
  }

  // Not supported vnet
  return false;
}

/*
 * This is the default routing algorithm in garnet.
 * The routing table is populated during topology creation.
 * Routes can be biased via weight assignments in the topology file.
 * Correct weight assignments are critical to provide deadlock avoidance.
 */
// [فارسی] lookupRoutingTable: مسیریابیِ پیش‌فرضِ gem5. از جدولِ مسیریابی، لینک‌های
// نامزد با کمترین وزن را پیدا می‌کند و یکی را برمی‌گرداند. الگوریتم‌های ما (XYZ/CAQR/
// DeepNR/Proposed) این را دور می‌زنند، ولی برای پورتِ Local هنوز استفاده می‌شود.
int RoutingUnit::lookupRoutingTable(int vnet, NetDest msg_destination) {
  // First find all possible output link candidates
  // For ordered vnet, just choose the first
  // (to make sure different packets don't choose different routes)
  // For unordered vnet, randomly choose any of the links
  // To have a strict ordering between links, they should be given
  // different weights in the topology file

  int output_link = -1;
  int min_weight = INFINITE_;
  std::vector<int> output_link_candidates;
  int num_candidates = 0;

  // Identify the minimum weight among the candidate output links
  for (int link = 0; link < m_routing_table[vnet].size(); link++) {
    if (msg_destination.intersectionIsNotEmpty(m_routing_table[vnet][link])) {

      if (m_weight_table[link] <= min_weight)
        min_weight = m_weight_table[link];
    }
  }

  // Collect all candidate output links with this minimum weight
  for (int link = 0; link < m_routing_table[vnet].size(); link++) {
    if (msg_destination.intersectionIsNotEmpty(m_routing_table[vnet][link])) {

      if (m_weight_table[link] == min_weight) {
        num_candidates++;
        output_link_candidates.push_back(link);
      }
    }
  }

  if (output_link_candidates.size() == 0) {
    fatal("Fatal Error:: No Route exists from this Router.");
    exit(0);
  }

  // Randomly select any candidate output link
  int candidate = 0;
  if (!(m_router->get_net_ptr())->isVNetOrdered(vnet))
    candidate = rand() % num_candidates;

  output_link = output_link_candidates.at(candidate);
  return output_link;
}

// [فارسی] addInDirection / addOutDirection: هنگامِ ساختِ شبکه، map جهت↔پورت را پر
// می‌کنند. به همین خاطر است که بعداً m_outports_dirn2idx["North"] جواب می‌دهد.
void RoutingUnit::addInDirection(PortDirection inport_dirn, int inport_idx) {
  m_inports_dirn2idx[inport_dirn] = inport_idx;
  m_inports_idx2dirn[inport_idx] = inport_dirn;
}

void RoutingUnit::addOutDirection(PortDirection outport_dirn, int outport_idx) {
  m_outports_dirn2idx[outport_dirn] = outport_idx;
  m_outports_idx2dirn[outport_idx] = outport_dirn;
}

// outportCompute() is called by the InputUnit
// It calls the routing table by default.
// A template for adaptive topology-specific routing algorithm
// implementations using port directions rather than a static routing
// table is provided here.

// [فارسی] *** نقطهٔ ورودِ مسیریابی *** SwitchAllocator این را برای هر فلیتِ سَر صدا
// می‌زند. اگر مقصد همین روتر باشد به پورتِ Local می‌رود؛ وگرنه بر اساسِ شمارهٔ
// الگوریتم (--routing-algorithm) یکی از توابعِ تخصصی را صدا می‌زند.
int RoutingUnit::outportCompute(RouteInfo route, int inport,
                                PortDirection inport_dirn) {
  int outport = -1;

  // [فارسی] اگر بسته به مقصد رسیده، مستقیم به پورتِ محلی تحویل بده.
  if (route.dest_router == m_router->get_id()) {

    // Multiple NIs may be connected to this router,
    // all with output port direction = "Local"
    // Get exact outport id from table
    outport = lookupRoutingTable(route.vnet, route.net_dest);
    return outport;
  }

  // Routing Algorithm set in GarnetNetwork.py
  // Can be over-ridden from command line using --routing-algorithm = 1
  RoutingAlgorithm routing_algorithm =
      (RoutingAlgorithm)m_router->get_net_ptr()->getRoutingAlgorithm();

  // [فارسی] جدولِ تقسیم: هر case یک الگوریتم. این همان جایی است که شمارهٔ خطِ فرمان
  // به کدِ ++C وصل می‌شود.
  switch (routing_algorithm) {
  case TABLE_:
    outport = lookupRoutingTable(route.vnet, route.net_dest);
    break;
  case XY_:
    outport = outportComputeXY(route, inport, inport_dirn);
    break;
  case DEEPNR3D_:
    outport = outportComputeDeepNR3D(route, inport, inport_dirn);
    break;
  case PROPOSED_:
    outport = outportComputeProposed(route, inport, inport_dirn);
    break;
  case XYZ_:
    outport = outportComputeXYZ(route, inport, inport_dirn);
    break;
  case CAQR_:
    outport = outportComputeCAQR(route, inport, inport_dirn);
    break;
  default:
    outport = lookupRoutingTable(route.vnet, route.net_dest);
    break;
  }

  assert(outport != -1);
  return outport;
}

// XY routing implemented using port directions
// Only for reference purpose in a Mesh
// By default Garnet uses the routing table
// [فارسی] outportComputeXY: مسیریابیِ XY دوبعدی (خطِ مبنا). اول فاصلهٔ X را صفر می‌کند
// (شرق/غرب)، بعد فاصلهٔ Y را (شمال/جنوب). assertها تضمین می‌کنند مسیر ترتیبی و بدونِ
// بن‌بست بماند.
int RoutingUnit::outportComputeXY(RouteInfo route, int inport,
                                  PortDirection inport_dirn) {
  PortDirection outport_dirn = "Unknown";

  [[maybe_unused]] int num_rows = m_router->get_net_ptr()->getNumRows();
  int num_cols = m_router->get_net_ptr()->getNumCols();
  assert(num_rows > 0 && num_cols > 0);

  int my_id = m_router->get_id();
  int my_x = my_id % num_cols;
  int my_y = my_id / num_cols;

  int dest_id = route.dest_router;
  int dest_x = dest_id % num_cols;
  int dest_y = dest_id / num_cols;

  int x_hops = abs(dest_x - my_x);
  int y_hops = abs(dest_y - my_y);

  bool x_dirn = (dest_x >= my_x);
  bool y_dirn = (dest_y >= my_y);

  // already checked that in outportCompute() function
  assert(!(x_hops == 0 && y_hops == 0));

  if (x_hops > 0) {
    if (x_dirn) {
      assert(inport_dirn == "Local" || inport_dirn == "West");
      outport_dirn = "East";
    } else {
      assert(inport_dirn == "Local" || inport_dirn == "East");
      outport_dirn = "West";
    }
  } else if (y_hops > 0) {
    if (y_dirn) {
      // "Local" or "South" or "West" or "East"
      assert(inport_dirn != "North");
      outport_dirn = "North";
    } else {
      // "Local" or "North" or "West" or "East"
      assert(inport_dirn != "South");
      outport_dirn = "South";
    }
  } else {
    // x_hops == 0 and y_hops == 0
    // this is not possible
    // already checked that in outportCompute() function
    panic("x_hops == y_hops == 0");
  }

  return m_outports_dirn2idx[outport_dirn];
}

// [فارسی] ===== الگوریتم ۴: XYZ (مسیریابیِ قطعیِ سه‌بعدی) =====
// قاعده: اول X را هم‌تراز کن، بعد Y، بعد Z. چون همه بسته‌ها این ترتیب را می‌روند،
// شبکه بدونِ بن‌بست می‌ماند. ضعفش: شلوغی را نمی‌بیند. این خطِ مبنای سه‌بعدی است.
// XYZ routing for 3D Mesh: route X first, then Y, then Z.
int RoutingUnit::outportComputeXYZ(RouteInfo route, int inport,
                                   PortDirection inport_dirn)
{
    int num_rows   = m_router->get_net_ptr()->getNumRows();
    int num_cols   = m_router->get_net_ptr()->getNumCols();
    int num_layers = m_router->get_net_ptr()->getNumLayers();

    assert(num_rows > 0 && num_cols > 0 && num_layers > 0);

    // [فارسی] استخراجِ مختصاتِ (x, y, z) از شمارهٔ روتر. plane = اندازهٔ یک لایه.
    int my_id   = m_router->get_id();
    int plane   = num_rows * num_cols;

    int my_z    = my_id / plane;             // [فارسی] شمارهٔ لایه
    int my_y    = (my_id % plane) / num_cols; // [فارسی] سطر داخلِ لایه
    int my_x    = (my_id % plane) % num_cols; // [فارسی] ستون داخلِ لایه

    int dest_id = route.dest_router;
    int dest_z  = dest_id / plane;
    int dest_y  = (dest_id % plane) / num_cols;
    int dest_x  = (dest_id % plane) % num_cols;

    PortDirection outport_dirn = "Unknown";

    // [فارسی] قلبِ XYZ: زنجیرهٔ if/else خودِ «ترتیبِ ابعاد» است. تا X هم‌تراز نشده
    // نوبت به Y نمی‌رسد و تا Y هم‌تراز نشده نوبت به Z.
    if (dest_x > my_x) {
        outport_dirn = "East";
    } else if (dest_x < my_x) {
        outport_dirn = "West";
    } else if (dest_y > my_y) {
        outport_dirn = "South";
    } else if (dest_y < my_y) {
        outport_dirn = "North";
    } else if (dest_z > my_z) {
        outport_dirn = "Up";    // Mesh_3D: z+1 neighbor uses src_outport="Up"
    } else if (dest_z < my_z) {
        outport_dirn = "Down";  // Mesh_3D: z-1 neighbor uses src_outport="Down"
    } else {
        panic("XYZ routing: src == dest but outportCompute called");
    }

    assert(m_outports_dirn2idx.count(outport_dirn) > 0);
    return m_outports_dirn2idx[outport_dirn];
}

// ---------------------------------------------------------------------------
// CAQR: Congestion-Aware Q-Routing for 2D Mesh
// Reference: Srivastava et al., "Performance analysis of congestion-aware
//   Q-routing algorithm for network on chip", IJ-AI Vol.13 No.1 2024, pp798-806
//
// Q-update rule (Eq. 3 from paper):
//   Q_x(y,d)_new = Q_x(y,d)_old + α*(γ*Q_y(z,d) + q_y + δ_xy - Q_x(y,d)_old)
//   α=0.5 (learning rate), γ=0.7 (discount), q_y=queue depth, δ_xy=1 (link delay)
// ---------------------------------------------------------------------------
// [فارسی] ===== namespace CAQR (الگوریتم ۵) =====
// جدولِ Q و پارامترهای یادگیری. static یعنی این‌ها بینِ فراخوانی‌ها و بینِ همهٔ روترها
// مشترک و پایدارند؛ همین حافظه است که یادگیری را ممکن می‌کند.
namespace CAQR {

// Q-table: qtable[router_id][dest_router][outport_dirn] = Q-value.
// [فارسی] جدولِ سه‌سطحی: [روتر][مقصد][جهت] = مقدارِ Q. هرچه کمتر، آن جهت بهتر.
static std::map<int, std::map<int, std::map<std::string, double>>> qtable;

// Total routing decisions made (controls exploration vs. exploitation phase).
static int packet_count = 0;

static const int    TRAIN_STEPS = 50;  // exploration steps per the paper
static const double ALPHA       = 0.5; // learning rate
static const double GAMMA       = 0.7; // discount rate
static const double EPSILON     = 0.5; // random exploration probability

// [فارسی] getQ: مقدارِ Q را می‌خواند؛ اگر خانه هنوز ساخته نشده، ۰ برمی‌گرداند.
double getQ(int router, int dest, const std::string &dirn) {
    auto ri = qtable.find(router);
    if (ri == qtable.end()) return 0.0;
    auto di = ri->second.find(dest);
    if (di == ri->second.end()) return 0.0;
    auto qi = di->second.find(dirn);
    return (qi != di->second.end()) ? qi->second : 0.0;
}

void setQ(int router, int dest, const std::string &dirn, double val) {
    qtable[router][dest][dirn] = val;
}

} // namespace CAQR

int RoutingUnit::outportComputeCAQR(RouteInfo route, int inport,
                                     PortDirection inport_dirn)
{
    int num_cols = m_router->get_net_ptr()->getNumCols();
    int num_rows = m_router->get_net_ptr()->getNumRows();
    assert(num_rows > 0 && num_cols > 0);

    int my_id  = m_router->get_id();
    int my_x   = my_id % num_cols;
    int my_y   = my_id / num_cols;

    int dest_id = route.dest_router;
    int dest_x  = dest_id % num_cols;
    int dest_y  = dest_id / num_cols;

    // [فارسی] فقط جهت‌هایی که فاصلهٔ منهتن تا مقصد را کم می‌کنند مجازند (حداکثر ۲ تا).
    // Collect feasible output directions: only those that reduce Manhattan
    // distance to the destination (at most 2 in a 2D mesh).
    std::vector<std::string> feasible;
    if (dest_x > my_x) feasible.push_back("East");
    if (dest_x < my_x) feasible.push_back("West");
    if (dest_y > my_y) feasible.push_back("North");
    if (dest_y < my_y) feasible.push_back("South");

    assert(!feasible.empty());

    // [فارسی] انتخابِ جهت: در ۵۰ تصمیمِ اول با احتمالِ ε تصادفی (اکتشاف)، بعد کمترین Q.
    // Select output direction: epsilon-greedy during training, greedy after.
    std::string chosen_dirn;
    bool exploring = (CAQR::packet_count < CAQR::TRAIN_STEPS) &&
                     ((double)rand() / RAND_MAX < CAQR::EPSILON);

    if (exploring || feasible.size() == 1) {
        chosen_dirn = feasible[rand() % feasible.size()];
    } else {
        chosen_dirn   = feasible[0];
        double min_q  = CAQR::getQ(my_id, dest_id, feasible[0]);
        for (size_t i = 1; i < feasible.size(); ++i) {
            double q = CAQR::getQ(my_id, dest_id, feasible[i]);
            if (q < min_q) {
                min_q      = q;
                chosen_dirn = feasible[i];
            }
        }
    }

    int chosen_outport = m_outports_dirn2idx[chosen_dirn];

    // [فارسی] *** به‌روزرسانیِ Q (فرمولِ مقاله) ***
    // Qِ روترِ قبلی (x) را برای پرشِ x→y به‌روز می‌کند. فقط وقتی بسته از جای دیگری
    // آمده باشد (نه تولیدِ محلی). فرمول:
    //   Q_x(y,d)_new = Q_x(y,d) + α·( γ·Q_y(z,d) + q_y + δ_xy − Q_x(y,d) )
    // که q_y عمقِ صفِ روترِ فعلی (سیگنالِ شلوغی) است.
    // Q-update: update the Q-value at the PREVIOUS node (x) for the hop x→y.
    if (inport_dirn != "Local") {
        // Determine previous router id (x) from the inport direction at y.
        int prev_x = my_x, prev_y = my_y;
        if      (inport_dirn == "North") prev_y = my_y + 1;
        else if (inport_dirn == "South") prev_y = my_y - 1;
        else if (inport_dirn == "East")  prev_x = my_x + 1;
        else if (inport_dirn == "West")  prev_x = my_x - 1;
        int prev_id = prev_y * num_cols + prev_x;

        // Outport direction AT x that leads to y is the opposite of inport at y.
        std::string out_x_to_y;
        if      (inport_dirn == "North") out_x_to_y = "South";
        else if (inport_dirn == "South") out_x_to_y = "North";
        else if (inport_dirn == "East")  out_x_to_y = "West";
        else                             out_x_to_y = "East";  // inport "West"

        // q_y: queuing delay at y on the chosen output port (buffer occupancy).
        double q_y = (double)m_router->getOutputUnit(chosen_outport)
                             ->getOutQueue()->getSize();

        // δ_xy: link transmission delay (1 cycle, as used in the paper).
        const double delta_xy = 1.0;

        double Q_y_z_d    = CAQR::getQ(my_id,  dest_id, chosen_dirn);
        double Q_x_y_d    = CAQR::getQ(prev_id, dest_id, out_x_to_y);
        double Q_x_y_d_new = Q_x_y_d +
            CAQR::ALPHA * (CAQR::GAMMA * Q_y_z_d + q_y + delta_xy - Q_x_y_d);

        CAQR::setQ(prev_id, dest_id, out_x_to_y, Q_x_y_d_new);
    }

    CAQR::packet_count++;
    return chosen_outport;
}

// DeepNR 3D: Deep Reinforcement Learning based routing for 3D NoC.
// Communicates with deepnr_agent.py via ZMQ REQ/REP on port 5555.
// State: one-hot current+dest router, hops traversed, 3D Manhattan distance,
//        buffer occupancy for 6 directions (N,E,S,W,Up,Down).
// Terminates on failures so the Python agent can learn from restarts.
// [فارسی] ============ الگوریتم ۲: DeepNR3D (شبکهٔ Qِ عمیق) ============
// این تابع در هر پرش این کارها را می‌کند:
//   ۱) (یک‌بار) سوکتِ ZMQ را به عاملِ پایتونی روی پورتِ 5555 وصل می‌کند.
//   ۲) پاداشِ پرشِ قبلی را می‌خواند (DeepNR::get_reward).
//   ۳) بردارِ حالت می‌سازد (طول = 2*num_routers + 8): one-hot روترِ فعلی و مقصد،
//      پرش‌ها، فاصلهٔ منهتنِ سه‌بعدی و وضعیتِ بافرِ ۶ جهت.
//   ۴) ماسکِ اکشن‌های مجاز را می‌سازد و حالت را با JSON می‌فرستد.
//   ۵) اکشنِ بازگشتی (۰..۵) را اعتبارسنجی و به پورتِ خروجی نگاشت می‌کند.
// نکته: متغیرهای static (سوکت، شمارنده‌ها) فقط یک‌بار ساخته و بینِ همهٔ روترها
// مشترک می‌شوند. در صورتِ اکشنِ نامعتبر، اپیزود عمداً پایان می‌یابد (سیگنالِ آموزش).
int RoutingUnit::outportComputeDeepNR3D(RouteInfo route, int inport,
                                        PortDirection inport_dirn) {
#ifdef USE_ZMQ
  // Static ZMQ context and socket (initialized once, shared across all routers)
  static void *zmq_ctx = nullptr;
  static void *zmq_sock = nullptr;
  static bool zmq_initialized = false;
  static int packet_counter = 0;
  static int deepnr_usage_count = 0;
  static int connection_failure_count = 0;
  static int invalid_action_count = 0;
  static int total_actions = 0;

  // Termination thresholds (configurable)
  static const int MAX_CONNECTION_FAILURES = 10; // Max ZMQ connection failures
  static const double MAX_INVALID_ACTION_RATE =
      0.3; // 30% invalid actions = terminate
  static const int MIN_ACTIONS_FOR_RATE_CHECK =
      100; // Need at least 100 actions before checking rate

  // Logging configuration
  static const int LOG_EVERY_N_STATES =
      10; // Log every Nth state to avoid too much output
  static std::ofstream *log_file = nullptr;
  static bool log_initialized = false;

  // Track packet routing info for reward calculation
  // When routing happens: Store (packet_id, action, enqueue_time, router_id)
  // When flit exits output buffer: Calculate reward and store it in
  // DeepNR::packet_rewards Next routing: Send stored reward from previous
  // action
  struct PacketRoutingInfo {
    int action;
    Tick enqueue_time;
    int router_id;
    bool reward_calculated;
    float reward;
  };
  static std::map<int, PacketRoutingInfo>
      packet_routing_info; // packet_id -> routing info

  // Exception used to cleanly exit the routing function after scheduling sim exit
  struct DeepNRExit {
    std::string reason;
  };

  // Helper: schedule clean sim exit then unwind with exception
  auto terminateDeepNR = [](const std::string &reason) {
    gem5::exitSimLoopNow("DeepNR episode ended: " + reason, 0);
    throw DeepNRExit{reason};
  };

  try {

  // Initialize ZMQ connection (only once)
  if (!zmq_initialized) {
    zmq_ctx = zmq_ctx_new();
    if (!zmq_ctx) {
      connection_failure_count++;
      terminateDeepNR("Failed to create ZMQ context. "
                      "Make sure agent is running and ZMQ is installed.");
      return lookupRoutingTable(route.vnet, route.net_dest); // unreachable
    }

    zmq_sock = zmq_socket(zmq_ctx, ZMQ_REQ);
    if (!zmq_sock) {
      connection_failure_count++;
      zmq_ctx_destroy(zmq_ctx);
      zmq_ctx = nullptr;
      terminateDeepNR("Failed to create ZMQ socket.");
    }

    // Set socket timeout (10 seconds) to avoid blocking forever
    int timeout = 10000; // milliseconds
    zmq_setsockopt(zmq_sock, ZMQ_RCVTIMEO, &timeout, sizeof(timeout));
    zmq_setsockopt(zmq_sock, ZMQ_SNDTIMEO, &timeout, sizeof(timeout));

    // Connect to Python agent server (running on localhost:5555)
    int rc = zmq_connect(zmq_sock, "tcp://localhost:5555");
    if (rc != 0) {
      connection_failure_count++;
      zmq_close(zmq_sock);
      zmq_ctx_destroy(zmq_ctx);
      zmq_sock = nullptr;
      zmq_ctx = nullptr;
      terminateDeepNR("Failed to connect to DeepNR agent on port 5555. "
                      "Make sure agent is running: python3 deepnr_agent.py --port 5555");
    }

    zmq_initialized = true;
    inform("DeepNR agent connected successfully.");

    // Initialize logging
    if (!log_initialized) {
      log_file = new std::ofstream("deepnr_routing_log.txt",
                                   std::ios::out | std::ios::trunc);
      if (log_file && log_file->is_open()) {
        *log_file << "=== DeepNR Routing Log ===\n";
        *log_file << "Format: PacketID | RouterID | DestID | Action | Reward | "
                     "QueuingDelay(cycles) | State | Transition\n";
        *log_file << "========================================================="
                     "=======================\n";
        *log_file << "\n=== Hyperparameters (from paper) ===\n";
        *log_file << "State Size: Variable (2*num_routers+8 for 3D mesh)\n";
        *log_file << "Action Size: 6 (N, E, S, W, U, D) for 3D NoC\n";
        *log_file << "Learning Rate: 0.01\n";
        *log_file << "Discount Factor (gamma): 0.9\n";
        *log_file << "Initial Epsilon: 0.9\n";
        *log_file << "Memory Size: 200 (limited entries)\n";
        *log_file << "Batch Size: 32\n";
        *log_file << "Reward Function: 1.0 / (queuing_delay_cycles + 1)\n";
        *log_file
            << "Invalid Action Reward: -10.0 (constant negative reward)\n";
        *log_file << "========================================================="
                     "=======================\n\n";
        log_initialized = true;
        inform("DeepNR logging enabled: deepnr_routing_log.txt");
      }
    }
  }

  // If ZMQ failed to initialize, terminate
  if (!zmq_sock) {
    terminateDeepNR("ZMQ socket is null. Connection lost.");
  }

  // Increment packet counter for unique ID
  packet_counter++;

  // Get current time for queuing delay calculation
  Tick current_time = curTick();

  // Try to get flit from InputUnit to track enqueue time
  Tick enqueue_time = current_time; // Default to current time if not found
  int packet_id_for_reward = packet_counter;

  // Try to find the flit in the input unit to get actual enqueue time
  if (inport >= 0 && inport < m_router->get_num_inports()) {
    InputUnit *input_unit = m_router->getInputUnit(inport);
    if (input_unit) {
      // Try to find the flit in any VC
      int num_vcs = m_router->get_num_vcs();
      for (int vc = 0; vc < num_vcs; vc++) {
        flit *t_flit = input_unit->peekTopFlit(vc);
        if (t_flit) {
          Tick flit_enqueue = t_flit->get_enqueue_time();
          if (flit_enqueue > 0) {
            enqueue_time = flit_enqueue;
            packet_id_for_reward = t_flit->getPacketID();
            break;
          }
        }
      }
    }
  }

  // Get reward and done flag from PREVIOUS action (if available).
  // Reward is calculated when the flit exits the previous router's output
  // buffer (OutputUnit::insert_flit). Done is true when that hop was the
  // last one (next router == destination).
  float reward_from_previous = DeepNR::get_reward(packet_id_for_reward);
  bool done_from_previous = DeepNR::get_done(packet_id_for_reward);

  // Update log file reference for DeepNR namespace
  DeepNR::set_log_file(log_file, LOG_EVERY_N_STATES, packet_counter);

  // Get network dimensions
  int num_rows = m_router->get_net_ptr()->getNumRows();
  int num_cols = m_router->get_net_ptr()->getNumCols();
  
  // Try to get num_layers (3D support)
  // If getNumLayers() doesn't exist, calculate from total routers
  int num_layers = 1;  // Default to 1 (2D mesh)
  int total_routers_in_network = m_router->get_net_ptr()->getNumRouters();
  if (total_routers_in_network > num_rows * num_cols) {
    // 3D mesh: calculate layers from total routers
    num_layers = total_routers_in_network / (num_rows * num_cols);
  }
  
  int num_routers = num_rows * num_cols * num_layers;
  int max_hops = (num_rows - 1) + (num_cols - 1) + (num_layers - 1);

  // Get current router and destination IDs
  int my_id = m_router->get_id();
  int dest_id = route.dest_router;

  // Validate router IDs
  if (my_id < 0 || my_id >= num_routers) {
    terminateDeepNR("Invalid current router ID " + std::to_string(my_id) +
                    " (expected 0-" + std::to_string(num_routers - 1) + ")");
  }
  if (dest_id < 0 || dest_id >= num_routers) {
    terminateDeepNR("Invalid destination router ID " + std::to_string(dest_id) +
                    " (expected 0-" + std::to_string(num_routers - 1) + ")");
  }

  // 3D coordinate extraction: Router ID = z * (rows * cols) + y * cols + x
  int my_z = my_id / (num_rows * num_cols);
  int my_remainder = my_id % (num_rows * num_cols);
  int my_y = my_remainder / num_cols;
  int my_x = my_remainder % num_cols;
  
  int dest_z = dest_id / (num_rows * num_cols);
  int dest_remainder = dest_id % (num_rows * num_cols);
  int dest_y = dest_remainder / num_cols;
  int dest_x = dest_remainder % num_cols;

  // Calculate 3D Manhattan distance
  int manhattan_distance = abs(dest_x - my_x) + abs(dest_y - my_y) + abs(dest_z - my_z);

  // [فارسی] === ساختِ بردارِ حالت (ورودیِ شبکهٔ عصبی) === طول = 2*num_routers + 8
  // Build state vector (for 3D: 2*num_routers + 8 dimensions)
  // f1: current router one-hot (num_routers)
  // f2: destination router one-hot (num_routers)
  // f3: normalized hops traversed (1)
  // f4: normalized remaining distance (1)
  // f5: buffer states for 6 directions (6: N, E, S, W, U, D)
  std::vector<float> state_vector;
  state_vector.reserve(2 * num_routers + 8);

  // f1: Current Router ID - One-Hot Encoding (64 values)
  for (int i = 0; i < num_routers; i++) {
    state_vector.push_back((i == my_id) ? 1.0f : 0.0f);
  }

  // f2: Destination Router ID - One-Hot Encoding (64 values)
  for (int i = 0; i < num_routers; i++) {
    state_vector.push_back((i == dest_id) ? 1.0f : 0.0f);
  }

  // f3: Distance Traversed (normalized)
  int hops_traversed = route.hops_traversed;
  float norm_hops_traversed =
      (max_hops > 0) ? (float(hops_traversed) / max_hops) : 0.0;
  if (norm_hops_traversed > 1.0)
    norm_hops_traversed = 1.0;
  state_vector.push_back(norm_hops_traversed);

  // f4: Remaining Distance (normalized)
  float norm_manhattan_dist =
      (max_hops > 0) ? (float(manhattan_distance) / max_hops) : 0.0;
  state_vector.push_back(norm_manhattan_dist);

  // f5: Buffer States (normalized 0-1, N,E,S,W,U,D for 3D)
  int max_buffer_size = 4;
  int num_vcs = m_router->get_num_vcs();
  int max_total_buffers = num_vcs * max_buffer_size;
  std::vector<PortDirection> directions = {"North", "East", "South", "West", "Up", "Down"};

  for (auto dir : directions) {
    if (m_outports_dirn2idx.find(dir) != m_outports_dirn2idx.end()) {
      int outport_idx = m_outports_dirn2idx[dir];
      OutputUnit *out_unit = m_router->getOutputUnit(outport_idx);
      if (out_unit) {
        int total_credits = 0;
        for (int vc = 0; vc < num_vcs; vc++) {
          total_credits += out_unit->get_credit_count(vc);
        }
        float buffer_ratio = float(total_credits) / float(max_total_buffers);
        state_vector.push_back(buffer_ratio);
      } else {
        state_vector.push_back(0.0f);
      }
    } else {
      state_vector.push_back(0.0f);
    }
  }

  // Validate state vector size (2*num_routers + 8 for 3D: f1+f2+f3+f4+f5)
  if (state_vector.size() != (2 * num_routers + 8)) {
    terminateDeepNR("State vector size mismatch: expected " +
                    std::to_string(2 * num_routers + 8) + ", got " +
                    std::to_string(state_vector.size()));
  }

  // Track available actions (for detection, not masking) - 6 actions for 3D
  // [فارسی] === ماسکِ اکشن‌های مجاز === جهتی که از لبهٔ شبکه بیرون بزند یا بافرش پر
  // باشد، false می‌شود تا عامل اکشنِ غیرممکن انتخاب نکند.
  std::vector<bool> available_actions(6, true);
  if (my_y == 0)
    available_actions[0] = false; // Can't go North
  if (my_x == num_cols - 1)
    available_actions[1] = false; // Can't go East
  if (my_y == num_rows - 1)
    available_actions[2] = false; // Can't go South
  if (my_x == 0)
    available_actions[3] = false; // Can't go West
  if (my_z == num_layers - 1)
    available_actions[4] = false; // Can't go Up (top layer)
  if (my_z == 0)
    available_actions[5] = false; // Can't go Down (bottom layer)

  // Track blocked buffers
  int f5_start_idx = 2 * num_routers + 2;
  for (int i = 0; i < 6; i++) {  // Changed from 4 to 6
    if (state_vector.size() > (f5_start_idx + i)) {
      if (state_vector[f5_start_idx + i] <= 0.0) {
        available_actions[i] = false;
      }
    }
  }

  // Build JSON message: send state, reward from previous hop, and the done
  // flag that signals whether that previous hop was the terminal transition.
  std::ostringstream json_stream;
  json_stream << "{\"state\":[";
  for (size_t i = 0; i < state_vector.size(); i++) {
    json_stream << state_vector[i];
    if (i < state_vector.size() - 1)
      json_stream << ",";
  }
  json_stream << "],\"packet_id\":" << packet_counter
              << ",\"reward\":" << reward_from_previous
              << ",\"done\":" << (done_from_previous ? "true" : "false")
              << ",\"available_actions\":[";
  for (size_t i = 0; i < available_actions.size(); i++) {
    json_stream << (available_actions[i] ? "true" : "false");
    if (i < available_actions.size() - 1)
      json_stream << ",";
  }
  json_stream << "]}";
  std::string json_msg = json_stream.str();

  // [فارسی] === ارسالِ حالت به عاملِ پایتونی با ZMQ و انتظار برای اکشن ===
  // Send state to Python agent
  int send_result = zmq_send(zmq_sock, json_msg.c_str(), json_msg.length(), 0);
  if (send_result < 0) {
    int errno_val = zmq_errno();
    connection_failure_count++;
    if (connection_failure_count >= MAX_CONNECTION_FAILURES) {
      terminateDeepNR("Too many ZMQ send failures (errno " +
                      std::to_string(errno_val) + ": " +
                      zmq_strerror(errno_val) +
                      "). "
                      "Agent may not be responding.");
    }
    terminateDeepNR("ZMQ send failed. Agent may not be responding.");
  }

  // Receive action from Python agent
  char buffer[512];
  int bytes_received = zmq_recv(zmq_sock, buffer, sizeof(buffer) - 1, 0);
  if (bytes_received <= 0) {
    int errno_val = zmq_errno();
    connection_failure_count++;
    if (connection_failure_count >= MAX_CONNECTION_FAILURES) {
      terminateDeepNR("Too many ZMQ receive failures (errno " +
                      std::to_string(errno_val) + ": " +
                      zmq_strerror(errno_val) +
                      "). "
                      "Agent may not be responding.");
    }
    terminateDeepNR("ZMQ recv failed. Agent may not be responding.");
  }

  buffer[bytes_received] = '\0';
  std::string response(buffer);

  // Parse action from JSON response
  int action = -1;
  size_t action_pos = response.find("\"action\":");
  if (action_pos != std::string::npos) {
    size_t start = response.find_first_of("012345", action_pos);
    if (start != std::string::npos) {
      action = response[start] - '0';
    }
  }

  // Track actions for threshold checking
  total_actions++;
  bool action_is_invalid = false;

  // Validate action (6 actions for 3D: 0=North, 1=East, 2=South, 3=West, 4=Up, 5=Down)
  if (action < 0 || action >= 6) {  // Changed from 4 to 6
    action_is_invalid = true;
    invalid_action_count++;
    warn("Invalid action received from DeepNR agent (action=%d, expected 0-5).", action);
  } else if (!available_actions[action]) {
    action_is_invalid = true;
    invalid_action_count++;
    warn("DeepNR selected invalid action %d (dead state).", action);
  }

  // Check invalid action rate threshold
  if (total_actions >= MIN_ACTIONS_FOR_RATE_CHECK) {
    double invalid_rate = (double)invalid_action_count / (double)total_actions;
    if (invalid_rate > MAX_INVALID_ACTION_RATE) {
      terminateDeepNR("Invalid action rate too high: " +
                      std::to_string(invalid_rate * 100.0) + "% " + "(" +
                      std::to_string(invalid_action_count) + "/" +
                      std::to_string(total_actions) +
                      ") exceeds threshold of " +
                      std::to_string(MAX_INVALID_ACTION_RATE * 100.0) +
                      "%. Agent needs more training.");
    }
  }

  // If action is invalid, give -10 reward and terminate
  if (action_is_invalid) {
    // Store -10 reward for this packet (will be sent with next state if
    // simulation continues)
    DeepNR::store_reward(packet_id_for_reward, -10.0, -1.0);

    // Log invalid action
    if (log_file && log_file->is_open()) {
      *log_file << std::fixed << std::setprecision(2);
      *log_file << "INVALID | Router[" << my_id << "] | Dest[" << dest_id
                << "] | Action[" << action << "] | Reward[-10.00] | "
                << "QueuingDelay[N/A] | InvalidAction | Terminated\n";
      log_file->flush();
    }

    terminateDeepNR("Invalid action selected: " + std::to_string(action) +
                    ". Agent must learn valid routing. "
                    "Restart simulation to continue training.");
  }

  // Store routing info for this packet (will be used to calculate reward when
  // flit exits)
  PacketRoutingInfo routing_info;
  routing_info.action = action;
  routing_info.enqueue_time = enqueue_time;
  routing_info.router_id = my_id;
  routing_info.reward_calculated = false;
  routing_info.reward = 0.0;
  packet_routing_info[packet_id_for_reward] = routing_info;

  // Track usage
  deepnr_usage_count++;
  if (packet_counter % 1000 == 0 && packet_counter > 0) {
    double invalid_rate = total_actions > 0
                              ? (100.0 * invalid_action_count / total_actions)
                              : 0.0;
    inform("DeepNR Statistics: Packets=%d, InvalidActions=%d/%d (%.2f%%)",
           deepnr_usage_count, invalid_action_count, total_actions,
           invalid_rate);
  }

  // Loop-breaker: if packet has exceeded the maximum shortest-path length,
  // the RL policy is looping. Override with XYZ to drain it without deadlock.
  int hops_so_far = route.hops_traversed;
  if (hops_so_far > max_hops) {
    // Fall back to XYZ for this hop
    if      (dest_x > my_x) action = 1;  // East
    else if (dest_x < my_x) action = 3;  // West
    else if (dest_y > my_y) action = 2;  // South
    else if (dest_y < my_y) action = 0;  // North
    else if (dest_z > my_z) action = 4;  // Up
    else if (dest_z < my_z) action = 5;  // Down
  }

  // Convert action to port direction
  PortDirection outport_dirn = directions[action];

  // Compute the next router's ID to determine if this hop delivers the packet.
  // This is stored so that OutputUnit::insert_flit can attach the correct
  // done=true signal when it stores the reward for this transition.
  {
    int next_x = my_x, next_y = my_y, next_z = my_z;
    if      (action == 0) next_y--;                    // North
    else if (action == 1) next_x++;                    // East
    else if (action == 2) next_y++;                    // South
    else if (action == 3) next_x--;                    // West
    else if (action == 4) next_z++;                    // Up
    else if (action == 5) next_z--;                    // Down
    int next_router_id = next_z * (num_rows * num_cols) + next_y * num_cols + next_x;
    DeepNR::store_terminal(packet_id_for_reward, next_router_id == dest_id);
  }

  // Reward is calculated when flit exits output buffer (OutputUnit::insert_flit).
  int outport_idx = -1;

  if (m_outports_dirn2idx.find(outport_dirn) != m_outports_dirn2idx.end()) {
    outport_idx = m_outports_dirn2idx[outport_dirn];
  } else {
    terminateDeepNR("Selected direction " + std::string(outport_dirn) +
                    " not available. Agent must learn valid directions.");
  }

  // Log state, action, reward, and transition (every Nth state)
  // Note: Reward shown is from PREVIOUS action (calculated when flit exited
  // previous router)
  if (log_file && log_file->is_open() &&
      (packet_counter % LOG_EVERY_N_STATES == 0)) {
    *log_file << std::fixed << std::setprecision(4);
    *log_file << "Pkt[" << packet_id_for_reward << "] | Router[" << my_id
              << "] | Dest[" << dest_id << "] | Action[" << action << " ("
              << outport_dirn << ")] | Reward[" << reward_from_previous
              << "] (from prev) | QueuingDelay[will calc on exit] | ";

    // Log state features (first few and last few)
    *log_file << "State[";
    int state_size = state_vector.size();
    for (int i = 0; i < std::min(5, state_size); i++) {
      *log_file << state_vector[i];
      if (i < 4 && i < state_size - 1)
        *log_file << ",";
    }
    if (state_size > 5) {
      *log_file << "...";
      for (int i = std::max(5, state_size - 3); i < state_size; i++) {
        *log_file << "," << state_vector[i];
      }
    }
    *log_file << "] | ";

    // Log transition info
    *log_file << "Hops[" << hops_traversed << "] | Dist[" << manhattan_distance
              << "] | AvailableActions[";
    for (int i = 0; i < 6; i++) {  // Changed from 4 to 6 for 3D
      *log_file << (available_actions[i] ? "1" : "0");
    }
    *log_file << "]\n";
    log_file->flush();
  }

  return outport_idx;

  } catch (const DeepNRExit &) {
    // Sim exit scheduled; return table-routed port so current routing completes
    return lookupRoutingTable(route.vnet, route.net_dest);
  }

#else
  // ZMQ not available - terminate simulation
  fatal(
      "DeepNR requires ZMQ support. Recompile gem5 with USE_ZMQ flag enabled. "
      "See DEEPNR_BUILD_GUIDE.md for instructions.");
#endif
}

// Proposed: Enhanced DQN-based 3D NoC routing (Paper 2).
// Communicates with proposed_agent.py via ZMQ REQ/REP on port 5556.
// State: 10 features — same first 5 as DeepNR3D plus:
//   f6: normalized packet wait time
//   f7: EMA of buffer occupancy per direction (6)
//   f8: predicted link delay per direction (6)
//   f9: link utilization per direction (6)
//   f10: congestion-weighted remaining distance (1)
// Total state size = 2*num_routers + 28
// [فارسی] ============ الگوریتم ۳: Proposed (روشِ پیشنهادی) ============
// ساختار مثلِ DeepNR3D است (ZMQ روی پورتِ 5556)، با این تفاوت‌ها:
//   • بردارِ حالتِ غنی‌تر: طول = 2*num_routers + 28 (۱۰ گروهِ ویژگی).
//   • حافظهٔ EMA ( میانگینِ متحرکِ نمایی) برای شلوغیِ هر جهت → دیدِ تاریخی.
//   • نگاشتِ اکشن به روترِ بعدی با «جدولِ delta» به‌جای زنجیرهٔ if/else.
// منطقِ ارسال/دریافت/اعتبارسنجی همان DeepNR3D است.
int RoutingUnit::outportComputeProposed(RouteInfo route, int inport,
                                        PortDirection inport_dirn) {
#ifdef USE_ZMQ
  static void *zmq_ctx  = nullptr;
  static void *zmq_sock = nullptr;
  static bool  zmq_initialized = false;
  static int   packet_counter  = 0;
  static int   connection_failure_count = 0;
  static int   invalid_action_count = 0;
  static int   total_actions = 0;

  static const int    MAX_CONNECTION_FAILURES  = 10;
  static const double MAX_INVALID_ACTION_RATE  = 0.3;
  static const int    MIN_ACTIONS_FOR_RATE_CHECK = 100;
  static const int    LOG_EVERY_N_STATES       = 10;
  static std::ofstream *log_file    = nullptr;
  static bool           log_initialized = false;

  // EMA per-router occupancy: router_id -> [N,E,S,W,Up,Down]
  static std::map<int, std::array<float, 6>> ema_occ;
  static const float EMA_ALPHA = 0.1f;

  struct ProposedExit { std::string reason; };
  auto terminate = [](const std::string &reason) {
    gem5::exitSimLoopNow("Proposed episode ended: " + reason, 0);
    throw ProposedExit{reason};
  };

  try {

  // ── ZMQ initialisation (port 5556, separate from DeepNR3D on 5555) ────────
  if (!zmq_initialized) {
    zmq_ctx = zmq_ctx_new();
    if (!zmq_ctx) terminate("Failed to create ZMQ context.");

    zmq_sock = zmq_socket(zmq_ctx, ZMQ_REQ);
    if (!zmq_sock) { zmq_ctx_destroy(zmq_ctx); zmq_ctx = nullptr;
                     terminate("Failed to create ZMQ socket."); }

    int timeout = 10000;
    zmq_setsockopt(zmq_sock, ZMQ_RCVTIMEO, &timeout, sizeof(timeout));
    zmq_setsockopt(zmq_sock, ZMQ_SNDTIMEO, &timeout, sizeof(timeout));

    if (zmq_connect(zmq_sock, "tcp://localhost:5556") != 0) {
      zmq_close(zmq_sock); zmq_ctx_destroy(zmq_ctx);
      zmq_sock = nullptr; zmq_ctx = nullptr;
      terminate("Failed to connect to proposed_agent.py on port 5556. "
                "Start it with: python3 proposed_agent.py --port 5556");
    }
    zmq_initialized = true;
    inform("Proposed routing agent connected on port 5556.");

    if (!log_initialized) {
      log_file = new std::ofstream("proposed_routing_log.txt",
                                   std::ios::out | std::ios::trunc);
      if (log_file && log_file->is_open())
        *log_file << "=== Proposed Method Routing Log ===\n";
      log_initialized = true;
    }
  }
  if (!zmq_sock) terminate("ZMQ socket lost.");

  packet_counter++;

  // ── Flit / packet metadata ─────────────────────────────────────────────────
  Tick current_time    = curTick();
  Tick enqueue_time    = current_time;
  int  packet_id       = packet_counter;

  if (inport >= 0 && inport < m_router->get_num_inports()) {
    InputUnit *iu = m_router->getInputUnit(inport);
    if (iu) {
      for (int vc = 0; vc < m_router->get_num_vcs(); vc++) {
        flit *t_flit = iu->peekTopFlit(vc);
        if (t_flit && t_flit->get_enqueue_time() > 0) {
          enqueue_time = t_flit->get_enqueue_time();
          packet_id    = t_flit->getPacketID();
          break;
        }
      }
    }
  }

  float reward_from_previous = DeepNR::get_reward(packet_id);
  bool  done_from_previous   = DeepNR::get_done(packet_id);
  DeepNR::set_log_file(log_file, LOG_EVERY_N_STATES, packet_counter);

  // ── Network dimensions ─────────────────────────────────────────────────────
  int num_rows = m_router->get_net_ptr()->getNumRows();
  int num_cols = m_router->get_net_ptr()->getNumCols();
  int total_rt = m_router->get_net_ptr()->getNumRouters();
  int num_layers = (num_rows * num_cols > 0)
                   ? total_rt / (num_rows * num_cols) : 1;
  int num_routers = total_rt;
  int layer_size  = num_rows * num_cols;
  int max_hops    = (num_rows - 1) + (num_cols - 1) + (num_layers - 1);
  int clock_period_ticks = (int)m_router->get_net_ptr()->clockPeriod();

  int my_id   = m_router->get_id();
  int dest_id = route.dest_router;

  if (my_id < 0 || my_id >= num_routers)
    terminate("Invalid router ID " + std::to_string(my_id));
  if (dest_id < 0 || dest_id >= num_routers)
    terminate("Invalid destination ID " + std::to_string(dest_id));

  // 3D coordinates
  int my_z  = my_id / layer_size;
  int my_y  = (my_id % layer_size) / num_cols;
  int my_x  = my_id % num_cols;
  int dst_z = dest_id / layer_size;
  int dst_y = (dest_id % layer_size) / num_cols;
  int dst_x = dest_id % num_cols;
  int manhattan = abs(dst_x - my_x) + abs(dst_y - my_y) + abs(dst_z - my_z);

  // ── Per-direction buffer info ──────────────────────────────────────────────
  static const std::vector<PortDirection> DIRS =
      {"North", "East", "South", "West", "Up", "Down"};
  int  num_vcs       = m_router->get_num_vcs();
  int  max_credits   = num_vcs * 4; // buffers_per_data_vc=4
  std::array<float, 6> buf_free{};  // free ratio   (f5)
  std::array<float, 6> buf_occ{};   // occupied ratio (for f7/f8/f9)

  for (int d = 0; d < 6; d++) {
    if (m_outports_dirn2idx.count(DIRS[d])) {
      int idx = m_outports_dirn2idx.at(DIRS[d]);
      OutputUnit *ou = m_router->getOutputUnit(idx);
      if (ou) {
        int credits = 0;
        for (int vc = 0; vc < num_vcs; vc++)
          credits += ou->get_credit_count(vc);
        buf_free[d] = max_credits > 0
                      ? float(credits) / float(max_credits) : 0.0f;
      }
    }
    buf_occ[d] = 1.0f - buf_free[d];
  }

  // Update EMA for this router
  if (!ema_occ.count(my_id))
    ema_occ[my_id].fill(0.0f);
  for (int d = 0; d < 6; d++)
    ema_occ[my_id][d] = EMA_ALPHA * buf_occ[d] +
                         (1.0f - EMA_ALPHA) * ema_occ[my_id][d];

  // ── State vector (10 features, size = 2*num_routers + 28) ─────────────────
  const int EXPECTED_STATE_SIZE = 2 * num_routers + 28;
  std::vector<float> sv;
  sv.reserve(EXPECTED_STATE_SIZE);

  // f1: one-hot current router
  for (int i = 0; i < num_routers; i++)
    sv.push_back(i == my_id ? 1.0f : 0.0f);

  // f2: one-hot destination router
  for (int i = 0; i < num_routers; i++)
    sv.push_back(i == dest_id ? 1.0f : 0.0f);

  // f3: normalized hops traversed
  int hops = route.hops_traversed;
  sv.push_back(max_hops > 0 ? std::min(1.0f, float(hops) / float(max_hops))
                             : 0.0f);

  // f4: normalized 3D Manhattan distance
  sv.push_back(max_hops > 0 ? std::min(1.0f, float(manhattan) / float(max_hops))
                             : 0.0f);

  // f5: free buffer ratio per direction (6 values)
  for (int d = 0; d < 6; d++) sv.push_back(buf_free[d]);

  // f6: normalized packet wait time in current queue
  {
    float wait_cycles = (current_time > enqueue_time && clock_period_ticks > 0)
                        ? float(current_time - enqueue_time) /
                          float(clock_period_ticks)
                        : 0.0f;
    float max_wait = float(max_hops + 1) * 10.0f; // loose upper bound
    sv.push_back(std::min(1.0f, wait_cycles / (max_wait > 0 ? max_wait : 1.0f)));
  }

  // f7: EMA of buffer occupancy per direction (6 values)
  for (int d = 0; d < 6; d++) sv.push_back(ema_occ[my_id][d]);

  // f8: predicted link delay = EMA_occ * pipeline_depth (normalized)
  //     Using pipeline_depth = 5 cycles; normalize by max_pipeline = 5
  {
    static const float PIPELINE_DEPTH = 5.0f;
    for (int d = 0; d < 6; d++)
      sv.push_back(std::min(1.0f, ema_occ[my_id][d] * PIPELINE_DEPTH /
                                  PIPELINE_DEPTH));
    // (simplifies to ema_occ itself here, but kept separate for network semantics)
  }

  // f9: instantaneous utilization = 1 - free_ratio (6 values)
  for (int d = 0; d < 6; d++) sv.push_back(buf_occ[d]);

  // f10: congestion-weighted remaining distance (1 value)
  {
    float avg_ema = 0.0f;
    for (int d = 0; d < 6; d++) avg_ema += ema_occ[my_id][d];
    avg_ema /= 6.0f;
    float f10 = float(manhattan) * (1.0f + avg_ema) /
                float(std::max(1, max_hops) * 2);
    sv.push_back(std::min(1.0f, f10));
  }

  if ((int)sv.size() != EXPECTED_STATE_SIZE)
    terminate("State size mismatch: expected " +
              std::to_string(EXPECTED_STATE_SIZE) + ", got " +
              std::to_string(sv.size()));

  // ── Available actions ──────────────────────────────────────────────────────
  std::vector<bool> avail(6, true);
  if (my_y == 0)              avail[0] = false; // North
  if (my_x == num_cols - 1)   avail[1] = false; // East
  if (my_y == num_rows - 1)   avail[2] = false; // South
  if (my_x == 0)              avail[3] = false; // West
  if (my_z == num_layers - 1) avail[4] = false; // Up
  if (my_z == 0)              avail[5] = false; // Down
  // Also block directions with zero free buffer
  for (int d = 0; d < 6; d++)
    if (buf_free[d] <= 0.0f) avail[d] = false;

  // ── Build and send JSON ────────────────────────────────────────────────────
  std::ostringstream js;
  js << "{\"state\":[";
  for (int i = 0; i < (int)sv.size(); i++) {
    js << sv[i];
    if (i < (int)sv.size() - 1) js << ",";
  }
  js << "],\"packet_id\":" << packet_counter
     << ",\"reward\":"     << reward_from_previous
     << ",\"done\":"       << (done_from_previous ? "true" : "false")
     << ",\"available_actions\":[";
  for (int i = 0; i < 6; i++) {
    js << (avail[i] ? "true" : "false");
    if (i < 5) js << ",";
  }
  js << "]}";
  std::string msg = js.str();

  if (zmq_send(zmq_sock, msg.c_str(), msg.size(), 0) < 0) {
    terminate("ZMQ send failed.");
  }

  // ── Receive action ─────────────────────────────────────────────────────────
  char buf[512];
  int  nb = zmq_recv(zmq_sock, buf, sizeof(buf) - 1, 0);
  if (nb <= 0) {
    terminate("ZMQ recv failed.");
  }
  buf[nb] = '\0';

  int action = -1;
  size_t ap = std::string(buf).find("\"action\":");
  if (ap != std::string::npos) {
    size_t sp = std::string(buf).find_first_of("012345", ap);
    if (sp != std::string::npos) action = buf[sp] - '0';
  }

  // ── Validate action ────────────────────────────────────────────────────────
  total_actions++;
  bool bad_action = (action < 0 || action >= 6 || !avail[action]);
  if (bad_action) {
    invalid_action_count++;
    DeepNR::store_reward(packet_id, -10.0f, -1.0);
    if (total_actions >= MIN_ACTIONS_FOR_RATE_CHECK) {
      double rate = double(invalid_action_count) / double(total_actions);
      if (rate > MAX_INVALID_ACTION_RATE)
        terminate("Invalid action rate " + std::to_string(rate * 100) +
                  "% exceeds threshold.");
    }
    terminate("Invalid action " + std::to_string(action) +
              " — agent must learn valid directions.");
  }

  // ── Store terminal flag for done signal ────────────────────────────────────
  {
    static const int delta[6][3] = {{0,-1,0},{1,0,0},{0,1,0},{-1,0,0},{0,0,1},{0,0,-1}};
    int nx = my_x + delta[action][0];
    int ny = my_y + delta[action][1];
    int nz = my_z + delta[action][2];
    int next_id = nz * layer_size + ny * num_cols + nx;
    DeepNR::store_terminal(packet_id, next_id == dest_id);
  }

  // Loop-breaker: override with XYZ if packet has exceeded max shortest path
  if (route.hops_traversed > max_hops) {
    if      (dst_x > my_x) action = 1;  // East
    else if (dst_x < my_x) action = 3;  // West
    else if (dst_y > my_y) action = 2;  // South
    else if (dst_y < my_y) action = 0;  // North
    else if (dst_z > my_z) action = 4;  // Up
    else if (dst_z < my_z) action = 5;  // Down
  }

  // ── Return outport ─────────────────────────────────────────────────────────
  PortDirection sel_dir = DIRS[action];
  if (!m_outports_dirn2idx.count(sel_dir))
    terminate("Direction " + std::string(sel_dir) + " not found in outport map.");

  return m_outports_dirn2idx.at(sel_dir);

  } catch (const ProposedExit &) {
    return lookupRoutingTable(route.vnet, route.net_dest);
  }

#else
  fatal("Proposed routing requires ZMQ. Recompile with USE_ZMQ=1.");
#endif
}

} // namespace garnet
} // namespace ruby
} // namespace gem5
