/*
 * Copyright (c) 2020 Inria
 * Copyright (c) 2016 Georgia Institute of Technology
 * Copyright (c) 2008 Princeton University
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


#include "mem/ruby/network/garnet/OutputUnit.hh"

#include "debug/RubyNetwork.hh"
#include "mem/ruby/network/garnet/Credit.hh"
#include "mem/ruby/network/garnet/CreditLink.hh"
#include "mem/ruby/network/garnet/GarnetNetwork.hh"
#include "mem/ruby/network/garnet/Router.hh"
#include "mem/ruby/network/garnet/flitBuffer.hh"

namespace gem5
{

namespace ruby
{

namespace garnet
{

// [فارسی] ----------------------------------------------------------------
// OutputUnit صفِ خروجیِ یک پورتِ روتر را مدیریت می‌کند: اعتبارها (credit) را
// می‌شمارد و فلیت‌ها را روی لینک می‌فرستد. برای الگوریتم‌های ما دو نقشِ مهم دارد:
//   ۱) اعتبار/جای خالیِ بافر = سیگنالِ شلوغی که توابعِ مسیریابی می‌خوانند.
//   ۲) محاسبهٔ پاداشِ یادگیریِ تقویتی هنگامِ خروجِ فلیت (تابعِ insert_flit).
// ------------------------------------------------------------------------

// [فارسی] اعلانِ تابعِ store_reward که پیاده‌سازی‌اش در RoutingUnit.cc (namespace
// DeepNR) است. این‌جا فقط «اعلام» می‌شود تا insert_flit بتواند صدایش بزند.
#ifdef USE_ZMQ
namespace DeepNR {
extern void store_reward(int packet_id, float reward, double queuing_delay_cycles);
} // namespace DeepNR
#endif

OutputUnit::OutputUnit(int id, PortDirection direction, Router *router,
  uint32_t consumerVcs)
  : Consumer(router), m_router(router), m_id(id), m_direction(direction),
    m_vc_per_vnet(consumerVcs)
{
    const int m_num_vcs = consumerVcs * m_router->get_num_vnets();
    outVcState.reserve(m_num_vcs);
    for (int i = 0; i < m_num_vcs; i++) {
        outVcState.emplace_back(i, m_router->get_net_ptr(), consumerVcs);
    }
}

void
OutputUnit::decrement_credit(int out_vc)
{
    DPRINTF(RubyNetwork, "Router %d OutputUnit %s decrementing credit:%d for "
            "outvc %d at time: %lld for %s\n", m_router->get_id(),
            m_router->getPortDirectionName(get_direction()),
            outVcState[out_vc].get_credit_count(),
            out_vc, m_router->curCycle(), m_credit_link->name());

    outVcState[out_vc].decrement_credit();
}

void
OutputUnit::increment_credit(int out_vc)
{
    DPRINTF(RubyNetwork, "Router %d OutputUnit %s incrementing credit:%d for "
            "outvc %d at time: %lld from:%s\n", m_router->get_id(),
            m_router->getPortDirectionName(get_direction()),
            outVcState[out_vc].get_credit_count(),
            out_vc, m_router->curCycle(), m_credit_link->name());

    outVcState[out_vc].increment_credit();
}

// [فارسی] has_credit: آیا این کانالِ مجازیِ خروجی، اعتبار (جای خالیِ بافر در روترِ
// بعدی) دارد؟ همین مقدار، خوراکِ سیگنالِ شلوغی برای DeepNR3D و Proposed است.
// Check if the output VC (i.e., input VC at next router)
// has free credits (i..e, buffer slots).
// This is tracked by OutVcState
bool
OutputUnit::has_credit(int out_vc)
{
    assert(outVcState[out_vc].isInState(ACTIVE_, curTick()));
    return outVcState[out_vc].has_credit();
}


// Check if the output port (i.e., input port at next router) has free VCs.
bool
OutputUnit::has_free_vc(int vnet)
{
    int vc_base = vnet*m_vc_per_vnet;
    for (int vc = vc_base; vc < vc_base + m_vc_per_vnet; vc++) {
        if (is_vc_idle(vc, curTick()))
            return true;
    }

    return false;
}

// Assign a free output VC to the winner of Switch Allocation
int
OutputUnit::select_free_vc(int vnet)
{
    int vc_base = vnet*m_vc_per_vnet;
    for (int vc = vc_base; vc < vc_base + m_vc_per_vnet; vc++) {
        if (is_vc_idle(vc, curTick())) {
            outVcState[vc].setState(ACTIVE_, curTick());
            return vc;
        }
    }

    return -1;
}

/*
 * The wakeup function of the OutputUnit reads the credit signal from the
 * downstream router for the output VC (i.e., input VC at downstream router).
 * It increments the credit count in the appropriate output VC state.
 * If the credit carries is_free_signal as true,
 * the output VC is marked IDLE.
 */

void
OutputUnit::wakeup()
{
    if (m_credit_link->isReady(curTick())) {
        Credit *t_credit = (Credit*) m_credit_link->consumeLink();
        increment_credit(t_credit->get_vc());

        if (t_credit->is_free_signal())
            set_vc_state(IDLE_, t_credit->get_vc(), curTick());

        delete t_credit;

        if (m_credit_link->isReady(curTick())) {
            scheduleEvent(Cycles(1));
        }
    }
}

// [فارسی] getOutQueue: صفِ خروجی را برمی‌گرداند. CAQR از getOutQueue()->getSize()
// به‌عنوانِ «عمقِ صف / تأخیرِ صفِ q_y» در فرمولِ به‌روزرسانیِ Q استفاده می‌کند.
flitBuffer*
OutputUnit::getOutQueue()
{
    return &outBuffer;
}

void
OutputUnit::set_out_link(NetworkLink *link)
{
    m_out_link = link;
}

void
OutputUnit::set_credit_link(CreditLink *credit_link)
{
    m_credit_link = credit_link;
}

// [فارسی] insert_flit: فلیت را در بافرِ خروجی می‌گذارد و ارسالش را زمان‌بندی می‌کند.
// *** این تابع محلِ محاسبهٔ پاداشِ یادگیریِ تقویتی است *** (فقط برای DeepNR3D و Proposed).
void
OutputUnit::insert_flit(flit *t_flit)
{
    outBuffer.insert(t_flit);
    m_out_link->scheduleEventAbsolute(m_router->clockEdge(Cycles(1)));

#ifdef USE_ZMQ
    // Compute reward for ZMQ-based DRL algorithms (DEEPNR3D_ and PROPOSED_).
    // Only head flits carry the enqueue time that matches the routing decision.
    // [فارسی] فقط وقتی الگوریتم DeepNR3D یا Proposed باشد پاداش حساب می‌کنیم.
    int ra = m_router->get_net_ptr()->getRoutingAlgorithm();
    if (ra == DEEPNR3D_ || ra == PROPOSED_) {
        flit_type ft = t_flit->get_type();
        // [فارسی] فقط فلیتِ سَر، زمانِ ورود (enqueue) را دارد که با تصمیمِ مسیریابی می‌خواند.
        if (ft == HEAD_ || ft == HEAD_TAIL_) {
            Tick enqueue_time = t_flit->get_enqueue_time();
            // [فارسی] مدتی که فلیت در این روتر معطل مانده (برحسبِ tick).
            Tick queuing_ticks = (curTick() > enqueue_time)
                                     ? (curTick() - enqueue_time)
                                     : 0;
            // Convert ticks to cycles for a human-readable delay value.
            // [فارسی] تبدیلِ tick به سیکل (تقسیم بر طولِ یک سیکلِ ساعت).
            double queuing_cycles =
                static_cast<double>(queuing_ticks) /
                static_cast<double>(m_router->clockPeriod());
            // [فارسی] *** فرمولِ پاداش *** تأخیرِ کم → پاداشِ نزدیک به ۱ (خوب)،
            // تأخیرِ زیاد → پاداشِ نزدیک به ۰ (بد).
            float reward = 1.0f / (static_cast<float>(queuing_cycles) + 1.0f);
            // [فارسی] پاداش را با شناسهٔ بسته ذخیره می‌کنیم تا در پرشِ بعدیِ همان
            // بسته توسطِ تابعِ مسیریابی خوانده و به عامل فرستاده شود.
            DeepNR::store_reward(t_flit->getPacketID(), reward, queuing_cycles);
        }
    }
#endif
}

bool
OutputUnit::functionalRead(Packet *pkt, WriteMask &mask)
{
    return outBuffer.functionalRead(pkt, mask);
}

uint32_t
OutputUnit::functionalWrite(Packet *pkt)
{
    return outBuffer.functionalWrite(pkt);
}

} // namespace garnet
} // namespace ruby
} // namespace gem5
