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


#ifndef __MEM_RUBY_NETWORK_GARNET_0_ROUTINGUNIT_HH__
#define __MEM_RUBY_NETWORK_GARNET_0_ROUTINGUNIT_HH__

#include "mem/ruby/common/Consumer.hh"
#include "mem/ruby/common/NetDest.hh"
#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "mem/ruby/network/garnet/GarnetNetwork.hh"
#include "mem/ruby/network/garnet/flit.hh"

namespace gem5
{

namespace ruby
{

namespace garnet
{

class InputUnit;
class Router;

// [فارسی] کلاسِ RoutingUnit مغزِ مسیریابیِ هر روتر است. هر روتر یک نمونه از این
// کلاس دارد. توابعِ outportCompute* وظیفه دارند «پورتِ خروجی» را برای یک فلیت تعیین
// کنند. map های پایینِ کلاس، نامِ جهت (string، مثلِ "North") را به شمارهٔ پورت ترجمه می‌کنند.
class RoutingUnit
{
  public:
    RoutingUnit(Router *router);

    // [فارسی] نقطهٔ ورودِ مسیریابی: بسته به --routing-algorithm یکی از توابعِ زیر را
    // صدا می‌زند و شمارهٔ پورتِ خروجی را برمی‌گرداند.
    int outportCompute(RouteInfo route,
                      int inport,
                      PortDirection inport_dirn);

    // Topology-agnostic Routing Table based routing (default)
    // [فارسی] افزودن یک ردیف به جدولِ مسیریابیِ پیش‌فرض و وزنِ لینک.
    void addRoute(std::vector<NetDest>& routing_table_entry);
    void addWeight(int link_weight);

    // get output port from routing table
    // [فارسی] یافتنِ پورتِ خروجی از روی جدولِ مسیریابیِ پیش‌فرض.
    int  lookupRoutingTable(int vnet, NetDest net_dest);

    // Topology-specific direction based routing
    // [فارسی] ثبتِ نگاشتِ جهت↔پورت هنگامِ ساختِ شبکه (توپولوژی این‌ها را پر می‌کند).
    void addInDirection(PortDirection inport_dirn, int inport);
    void addOutDirection(PortDirection outport_dirn, int outport);

    // Routing for Mesh
    // [فارسی] الگوریتمِ XY دوبعدی (خطِ مبنا): اول در راستای X، بعد Y.
    int outportComputeXY(RouteInfo route,
                         int inport,
                         PortDirection inport_dirn);

    // XYZ routing for 3D Mesh (X first, then Y, then Z)
    // [فارسی] الگوریتمِ XYZ سه‌بعدی (شمارهٔ ۴): ترتیبِ ثابتِ X سپس Y سپس Z.
    int outportComputeXYZ(RouteInfo route,
                          int inport,
                          PortDirection inport_dirn);

    // DeepNR 3D: DQN-based adaptive routing for 3D NoC (ZMQ port 5555)
    // [فارسی] DeepNR3D (شمارهٔ ۲): از عاملِ پایتونیِ DQN روی پورتِ 5555 جهت می‌پرسد.
    int outportComputeDeepNR3D(RouteInfo route,
                               int inport,
                               PortDirection inport_dirn);

    // Proposed: DQN-based 3D NoC routing with 10-feature state (via ZMQ port 5556)
    // [فارسی] روشِ پیشنهادی (شمارهٔ ۳): مثلِ DeepNR3D ولی حالتِ غنی‌تر، پورتِ 5556.
    int outportComputeProposed(RouteInfo route,
                               int inport,
                               PortDirection inport_dirn);

    // CAQR: Congestion-Aware Q-Routing for 2D Mesh (Srivastava et al., IJ-AI 2024)
    // [فارسی] CAQR (شمارهٔ ۵): یادگیریِ Qِ جدولیِ آگاه از شلوغی، کاملاً داخلِ ++C.
    int outportComputeCAQR(RouteInfo route,
                           int inport,
                           PortDirection inport_dirn);

    // Returns true if vnet is present in the vector
    // of vnets or if the vector supports all vnets.
    bool supportsVnet(int vnet, std::vector<int> sVnets);


  private:
    Router *m_router;  // [فارسی] pointer به روترِ صاحبِ این RoutingUnit

    // Routing Table
    std::vector<std::vector<NetDest>> m_routing_table;
    std::vector<int> m_weight_table;

    // Inport and Outport direction to idx maps
    // [فارسی] چهار map برای ترجمهٔ جهت↔شمارهٔ پورت. توابعِ مسیریابی با
    // m_outports_dirn2idx["North"] شمارهٔ پورتِ نهایی را می‌گیرند.
    std::map<PortDirection, int> m_inports_dirn2idx;   // جهتِ ورودی → شمارهٔ پورت
    std::map<int, PortDirection> m_inports_idx2dirn;   // شمارهٔ پورت → جهتِ ورودی
    std::map<int, PortDirection> m_outports_idx2dirn;  // شمارهٔ پورت → جهتِ خروجی
    std::map<PortDirection, int> m_outports_dirn2idx;  // جهتِ خروجی → شمارهٔ پورت
};

} // namespace garnet
} // namespace ruby
} // namespace gem5

#endif // __MEM_RUBY_NETWORK_GARNET_0_ROUTINGUNIT_HH__
