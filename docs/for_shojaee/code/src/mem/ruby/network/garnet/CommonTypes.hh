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


#ifndef __MEM_RUBY_NETWORK_GARNET_0_COMMONTYPES_HH__
#define __MEM_RUBY_NETWORK_GARNET_0_COMMONTYPES_HH__

#include "mem/ruby/common/NetDest.hh"

namespace gem5
{

namespace ruby
{

namespace garnet
{

// All common enums and typedefs go here
// [فارسی] این فایل، enum ها و typedef های مشترکِ شبکهٔ Garnet را نگه می‌دارد.

// [فارسی] نوعِ فلیت: سَر، بدنه، دُم، سَر-و-دُمِ یکجا (بستهٔ تک‌فلیتی) و فلیتِ اعتبار.
enum flit_type {HEAD_, BODY_, TAIL_, HEAD_TAIL_,
                CREDIT_, NUM_FLIT_TYPE_};
enum VC_state_type {IDLE_, VC_AB_, ACTIVE_, NUM_VC_STATE_TYPE_};
enum VNET_type {CTRL_VNET_, DATA_VNET_, NULL_VNET_, NUM_VNET_TYPE_};
enum flit_stage {I_, VA_, SA_, ST_, LT_, NUM_FLIT_STAGE_};
enum link_type { EXT_IN_, EXT_OUT_, INT_, NUM_LINK_TYPES_ };

// [فارسی] *** کلیدی‌ترین enum برای این پروژه ***
// هر مقدار، شمارهٔ یک الگوریتمِ مسیریابی است که با --routing-algorithm=N انتخاب می‌شود:
//   TABLE_=0   مسیریابیِ جدولیِ پیش‌فرضِ gem5
//   XY_=1      مسیریابیِ XY دوبعدی (خطِ مبنا)
//   DEEPNR3D_=2  شبکهٔ Qِ عمیق روی پورتِ ZMQ 5555
//   PROPOSED_=3  روشِ پیشنهادی، حالتِ ۱۰-ویژگی، پورتِ ZMQ 5556
//   XYZ_=4     مسیریابیِ ترتیبیِ سه‌بعدی (خطِ مبنای سه‌بعدی)
//   CAQR_=5    مسیریابیِ Qِ آگاه از شلوغی (دوبعدی)
enum RoutingAlgorithm { TABLE_ = 0, XY_ = 1, DEEPNR3D_ = 2,
                        PROPOSED_ = 3, XYZ_ = 4, CAQR_ = 5,
                        NUM_ROUTING_ALGORITHM_};

// [فارسی] RouteInfo اطلاعاتِ مسیرِ یک بسته را حمل می‌کند و به توابعِ مسیریابی
// پاس داده می‌شود. مهم‌ترین فیلدها برای الگوریتم‌های ما: dest_router (مقصد) و
// hops_traversed (تعدادِ پرش‌های طی‌شده تا اینجا).
struct RouteInfo
{
    RouteInfo()
        : vnet(0), src_ni(0), src_router(0), dest_ni(0), dest_router(0),
          hops_traversed(0)
    {}

    // destination format for table-based routing
    int vnet;          // [فارسی] شمارهٔ شبکهٔ مجازی (virtual network)
    NetDest net_dest;  // [فارسی] مقصد در قالبِ مسیریابیِ جدولی

    // src and dest format for topology-specific routing
    int src_ni;          // [فارسی] رابطِ شبکهٔ مبدأ
    int src_router;      // [فارسی] روترِ مبدأ
    int dest_ni;         // [فارسی] رابطِ شبکهٔ مقصد
    int dest_router;     // [فارسی] روترِ مقصد ← مبنای محاسبهٔ جهت در همهٔ الگوریتم‌ها
    int hops_traversed;  // [فارسی] تعدادِ پرش‌هایی که بسته تا الان طی کرده
};

#define INFINITE_ 10000

} // namespace garnet
} // namespace ruby
} // namespace gem5

#endif //__MEM_RUBY_NETWORK_GARNET_0_COMMONTYPES_HH__
