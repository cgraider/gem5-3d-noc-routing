# How to Build gem5 with DeepNR Support

## Directory layout

```
~/gem5_new/
├── gem5/
│   ├── gem5/          ← the gem5 source tree (work here)
│   └── context/       ← reference copies of custom files
└── gem5_2/
    └── gem5/          ← clean v23.0.0.1 reference build
```

All commands below are run from inside `~/gem5_new/gem5/gem5` unless stated.

---

## 1. Python virtual environment

gem5's SCons build uses Python 3.10. Create a dedicated venv once:

```bash
python3.10 -m venv ~/gem5-env
source ~/gem5-env/bin/activate
```

Install Python-side dependencies (needed for running agents, not building):

```bash
pip install torch pyzmq numpy
```

---

## 2. System build dependencies

These should already be present on the machine. If a build step fails with a missing header, install the corresponding package.

| Needed for | Package (Ubuntu) |
|---|---|
| Core build | `build-essential scons python3-dev` |
| Protocol Buffers | `libprotobuf-dev protobuf-compiler` |
| HDF5 stats output | `libhdf5-dev` |
| PNG support | `libpng-dev` |
| ZMQ (DeepNR comms) | `libzmq3-dev` |
| Valgrind headers | `valgrind` |

Verify ZMQ is found before building:

```bash
pkg-config --exists libzmq && echo "ZMQ OK"
```

---

## 3. Build targets

gem5 builds into `build/<CONFIG>/gem5.<variant>`. The project uses the `ALL` config which compiles every ISA and Ruby protocol including GPU support.

### Standard build (optimised, what you normally run)

```bash
source ~/gem5-env/bin/activate
cd ~/gem5_new/gem5/gem5
scons build/ALL/gem5.opt -j$(nproc)
```

`-j$(nproc)` parallelises across all CPU cores. A full build takes 20–60 minutes the first time; incremental rebuilds after editing a few files take seconds.

### Debug build (slower binary, better error messages)

```bash
scons build/ALL/gem5.debug -j$(nproc)
```

Use this when gem5 crashes or produces unexpected output and you need a stack trace.

### Fast build (just the garnet network files, for iterating on routing code)

After a full build exists, you can rebuild only the garnet objects:

```bash
scons build/ALL/mem/ruby/network/garnet/RoutingUnit.o \
      build/ALL/mem/ruby/network/garnet/OutputUnit.o \
      -j4
```

---

## 4. What the build does for DeepNR

The `SConscript` in `src/mem/ruby/network/garnet/` (modified for DeepNR) does two extra things beyond the standard garnet build:

```python
env.Append(LIBS=['zmq'])
env.Append(CPPFLAGS=['-DUSE_ZMQ'])
```

This links `libzmq` and defines the `USE_ZMQ` preprocessor macro. All DeepNR and Proposed routing code in `RoutingUnit.cc` and `OutputUnit.cc` is gated behind `#ifdef USE_ZMQ`, so if ZMQ is absent the file still compiles but those routing algorithms will call `fatal()` at runtime.

---

## 5. Verifying the build

After `scons` completes:

```bash
./build/ALL/gem5.opt --version
```

Check the garnet ZMQ symbols are present:

```bash
nm build/ALL/gem5.opt | grep -i zmq | head -5
```

You should see `zmq_ctx_new`, `zmq_socket`, etc.

---

## 6. Rebuilding after source changes

SCons tracks dependencies automatically. After editing any `.cc` or `.hh` file just re-run the same `scons` command; it will only recompile what changed.

After editing `RoutingUnit.cc` only:

```bash
scons build/ALL/gem5.opt -j$(nproc)
# typically recompiles 1 file and relinks in under 2 minutes
```

After editing `SConscript` (e.g., adding a new source file), SCons picks that up automatically too.

---

## 7. Clean build (if something is badly broken)

```bash
# Remove only the ALL build directory
rm -rf build/ALL

# Full clean (all configs)
scons --clean build/ALL/gem5.opt
```

Then re-run the full build command from step 3.
