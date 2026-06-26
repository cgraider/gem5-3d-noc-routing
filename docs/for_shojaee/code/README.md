# 📂 کدِ کامنت‌گذاری‌شده (نسخهٔ فارسی)

این پوشه شاملِ **کپیِ فایل‌های ضروریِ پروژه** است که برای فهمیدن و کدنویسیِ چهار الگوریتمِ
مسیریابی (XYZ، CAQR، DeepNR3D، Proposed) لازم‌اند. به هر فایل **کامنت‌های فارسی** اضافه شده:
بالای هر تابع، توضیحِ کارِ آن، و گاهی روی خطوطِ پیچیده توضیحِ خطی.

> [!IMPORTANT]
> 🟣 این‌ها **کپیِ آموزشی‌اند، نه فایل‌های واقعیِ بیلد.** برای ساخت و اجرا همیشه از فایل‌های
> اصلیِ پروژه استفاده می‌شود. هر کامنتِ فارسی با برچسبِ `[فارسی]` مشخص شده تا از کامنت‌های
> اصلی جدا باشد.

## ساختار و نقشِ هر فایل

```
code/
├── src/mem/ruby/network/garnet/
│   ├── CommonTypes.hh      enum شماره‌گذاریِ الگوریتم‌ها + ساختارِ RouteInfo
│   ├── RoutingUnit.hh      اعلانِ کلاسِ RoutingUnit و توابعِ مسیریابی
│   ├── RoutingUnit.cc      *** هستهٔ مسیریابی *** هر چهار الگوریتم اینجاست
│   └── OutputUnit.cc       محاسبهٔ پاداشِ یادگیری + سیگنالِ شلوغی (اعتبار/صف)
├── configs/
│   ├── topologies/Mesh_3D.py          ساختِ شبکهٔ سه‌بعدی با لینک‌های TSV
│   └── example/garnet_deepnr_traffic.py  اسکریپتِ کانفیگِ اجرا (پل پایتون↔++C)
├── deepnr_agent.py         عاملِ پایتونیِ DeepNR3D (DQN، پورتِ ZMQ 5555)
└── proposed_agent.py       عاملِ پایتونیِ روشِ پیشنهادی (پورتِ ZMQ 5556)
```

## از کجا شروع کنم؟

۱. **CommonTypes.hh** — اول enum الگوریتم‌ها را ببین (شماره‌ها از کجا می‌آیند).
۲. **RoutingUnit.cc** — به ترتیب: `outportCompute` (تقسیم‌کننده) → `outportComputeXYZ`
   (ساده‌ترین) → `outportComputeCAQR` (یادگیریِ جدولی) → `outportComputeDeepNR3D` و
   `outportComputeProposed` (یادگیریِ عمیق).
۳. **OutputUnit.cc** — تابعِ `insert_flit` که پاداش را حساب می‌کند.
۴. **deepnr_agent.py / proposed_agent.py** — سمتِ پایتونیِ یادگیری.

برای توضیحِ مفهومی (نه خط‌به‌خط)، به پوشه‌های [`../1-fundamentals`](../1-fundamentals/) و
[`../2-algorithms`](../2-algorithms/) یا نسخهٔ HTML در [`../html/index.html`](../html/index.html) برگرد.
