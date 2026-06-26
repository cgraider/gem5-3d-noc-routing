# ▶️ چطور اجرا و ارزیابی کنیم / Run (برای شجاعی)

شجاعی، این صفحه دو بخش دارد: اول **اجرای تکیِ** هر الگوریتم، بعد **فازِ ارزیابی** که هر چهار
الگوریتم را با هم مقایسه می‌کند. همه‌ی دستورها روی سرورِ لینوکس و با محیطِ فعال:

```bash
source ~/gem5-env/bin/activate
cd ~/gem5_new/gem5/gem5
```

انتخابِ الگوریتم با `--routing-algorithm=N`:

| N | الگوریتم | عامل لازم است؟ |
|---|---|---|
| ۴ | XYZ | نه |
| ۵ | CAQR | نه |
| ۲ | DeepNR3D | بله (پورت ۵۵۵۵) |
| ۳ | Proposed | بله (پورت ۵۵۵۶) |

> [!IMPORTANT]
> 🟣 **قانونِ اندازه:** `num-cpus == num-dirs == rows × cols × layers`. مثلاً ۴×۴×۲ → ۳۲ گره.

---

## ۱) اجرای XYZ یا CAQR (یک ترمینال، بدونِ عامل)

```bash
./build/ALL/gem5.opt configs/example/garnet_synth_traffic.py \
    --network=garnet --num-cpus=32 --num-dirs=32 \
    --topology=Mesh_3D --mesh-rows=4 --mesh-layers=2 --vcs-per-vnet=2 \
    --routing-algorithm=4 --link-latency=1 --router-latency=1 \
    --sim-cycles=1000000 --synthetic=uniform_random --injectionrate=0.1
```

نتیجه در `m5out/stats.txt`. مهم‌ترین خط را این‌طور ببین:

```bash
grep average_packet_latency m5out/stats.txt
```

> 🎓 **آموزش کوچک — `grep`**
> `grep "متن" فایل` یعنی «هر خطی از این فایل که این متن را دارد نشانم بده». ابزارِ سریع برای
> پیدا کردنِ یک عدد توی فایلِ بزرگِ آمار.

---

## ۲) اجرای DeepNR3D یا Proposed (دو ترمینال)

چون این‌ها به عاملِ پایتون نیاز دارند، **اول عامل، بعد gem5**.

```bash
# ترمینال ۱ — عامل را روشن کن و منتظرِ پیامِ "ready" بمان
python3 deepnr_agent.py --port 5555 --state-size 72 --action-size 6 --fresh

# ترمینال ۲ — gem5 (با routing-algorithm=2)
./build/ALL/gem5.opt configs/example/garnet_deepnr_traffic.py \
    --network=garnet --num-cpus=32 --num-dirs=32 \
    --topology=Mesh_3D --mesh-rows=4 --mesh-layers=2 --vcs-per-vnet=2 \
    --routing-algorithm=2 --link-latency=1 --router-latency=1 \
    --sim-cycles=100000 --synthetic=uniform_random --injectionrate=0.1
```

> [!WARNING]
> 🔴 یادت باشد: `--state-size` باید برابرِ `2*num_routers + 8` باشد (برای ۳۲ روتر = ۷۲).
> برای Proposed مقدارِ حالت خودکار از `--num-rows/--num-cols/--num-layers` حساب می‌شود. اگر
> اندازه‌ها نخوانند، عامل سرِ هر تصمیم هشدار می‌دهد.

---

## ۳) الگوهای ترافیک

| `--synthetic` | یعنی چه |
|---|---|
| `uniform_random` | هر روتر به یک مقصدِ تصادفیِ یکنواخت می‌فرستد |
| `transpose` | روترِ (x,y) به (y,x) می‌فرستد — ترافیکِ قطری، سخت‌گیرانه |
| `bit_complement` | روترِ i به مکملِ بیتیِ i |
| `shuffle` | الگوی جابه‌جایی |

---

# 📊 فازِ ارزیابی (مقایسه‌ی هر چهار الگوریتم)

بخش‌های بالا **یک** الگوریتم را اجرا می‌کنند. فازِ ارزیابی هر **چهار** را روی یک جاروبِ مشترکِ
نرخِ تزریق و الگوهای ترافیک اجرا می‌کند، آمار را در یک فایل جمع می‌کند، و مقایسه را
تأیید/رسم می‌کند.

## گامِ ۱) اول عامل‌های یادگیرنده را آموزش بده (یا مدلِ ذخیره‌شده را بارگذاری کن)

XYZ و CAQR از همان اول درست کار می‌کنند. ولی DeepNR3D و Proposed باید **آموزش دیده باشند**،
وگرنه عددهایشان بی‌معنی است.

```bash
# حلقه‌ی آموزشِ چنداپیزودی (gem5 را برای هر اپیزود خودکار اجرا می‌کند):
GEM5_BUILD=./build bash run_3d_training.sh 4x4x2_experiment 4 4 2
# → خروجی: results_4x4x2_experiment/training/deepnr_model.pth
```

برای ارزیابی، عامل را در **حالتِ eval** (سیاستِ ثابت، بدونِ یادگیریِ بیشتر) اجرا کن:

```bash
python3 deepnr_agent.py --port 5555 --state-size 72 --action-size 6 \
    --load-model deepnr_model.pth --eval-mode

python3 proposed_agent.py --port 5556 --num-rows 4 --num-cols 4 --num-layers 2 \
    --load-model proposed_model.pth --eval
```

> 🎓 **آموزش کوچک — «حالتِ eval» یعنی چه؟**
> در حالتِ ارزیابی، عامل دیگر یاد نمی‌گیرد و اکتشافِ تصادفی نمی‌کند؛ فقط از چیزی که قبلاً یاد
> گرفته **استفاده** می‌کند. این‌طوری مقایسه عادلانه است، چون سیاست ثابت می‌ماند.

## گامِ ۲) جاروبِ کاملِ هر چهار الگوریتم را اجرا کن

اسکریپت‌های مقایسه کلِ کار را انجام می‌دهند و برای هر اجرا یک رکورد در `garnet_results.json`
می‌نویسند. **ترتیب مهم است:**

```bash
bash scripts/run_XYZ_CAQR.sh         # الگوریتم‌های ۴ و ۵ — بدونِ عامل — فایل را ریست می‌کند
bash scripts/run_DeepNR_proposed.sh  # الگوریتم‌های ۲ و ۳ — خودش عامل را اجرا می‌کند — اضافه می‌کند
```

> [!WARNING]
> 🔴 اولی فایلِ `garnet_results.json` را **پاک و از نو** می‌سازد، دومی به آن **اضافه** می‌کند.
> پس همیشه اول `run_XYZ_CAQR.sh` بعد `run_DeepNR_proposed.sh`. اگر برعکس بزنی، نتیجه‌ها پاک
> می‌شوند.

## گامِ ۳) تأیید و رسمِ مقایسه

```bash
python3 scripts/verify_augmentation.py garnet_results.json
python3 scripts/plot_augmentation.py   garnet_results.json --outdir results/plots
```

- **`verify_augmentation.py`** — چک می‌کند رتبه‌بندیِ موردِانتظار برقرار باشد:
  `proposed < DeepNR3D < CAQR < XYZ` (تأخیرِ کمتر بهتر). جدولِ PASS/FAIL چاپ می‌کند.
- **`plot_augmentation.py`** — نمودارِ تأخیر / توان‌عملیاتی / تعدادِ پرش برحسبِ نرخِ تزریق
  می‌کشد، یک خط برای هر الگوریتم، در `results/plots/`.

## گامِ ۴) خروجی‌ها کجا می‌روند

| مسیر | محتوا |
|---|---|
| `garnet_results.json` | یک رکورد JSON به‌ازای هر اجرا — داده‌ی اصلیِ مقایسه |
| `results/raw_stats/...` | عکسِ خامِ `stats.txt` هر اجرا |
| `results/agent_logs/*.log` | خروجیِ عامل‌های DeepNR3D / Proposed |
| `results/plots/*.png` | نمودارهای مقایسه به‌ازای هر الگوی ترافیک |

## گامِ ۵) معیارهای کلیدی برای مقایسه

| معیار (کلیدِ stats.txt) | چه می‌گوید |
|---|---|
| `average_packet_latency` | تأخیرِ سرتاسری (÷۱۰۰۰ = سیکل) — **کمتر بهتر** |
| `packets_received / packets_injected` | نرخِ تحویل — باید نزدیکِ ۱۰۰٪ باشد |
| `average_hops` | طولِ مسیر — نزدیکِ فاصله‌ی منهتن = مسیریابیِ بهینه |
| `ext_in_link_utilization` | شاخصِ توان‌عملیاتی — بالاترِ پایدار = رفتارِ بهترِ اشباع |

> [!TIP]
> 🟢 برای ارزیابیِ یک الگوریتمِ تکی با دست، همان بخشِ ۱–۲ را اجرا کن و `m5out/stats.txt` را
> با `grep` بخوان.

---

🎉 تمام شد شجاعی! حالا می‌توانی هر چهار الگوریتم را بسازی، اجرا کنی و مقایسه کنی. اگر جایی گیر
کردی، اول [مبانی](../1-fundamentals/مبانی-gem5-ruby-garnet.md) را یک‌بار دیگر مرور کن. موفق باشی 💪
