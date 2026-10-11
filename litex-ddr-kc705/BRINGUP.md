# KC705 DDR3 baseline

The unchanged upstream design has completed calibration, its boot memory test,
and one full 1 GiB memory test on our KC705. Two other full-memory attempts
stopped producing UART output. **Repeatability is unresolved and timing is not
closed.** Establish a repeatable baseline before migrating the TPU system.

## What upstream supplies

This directory contains a complete generated LiteX SoC: VexRiscv, LiteDRAM
controller/K7DDRPHY, clock/reset logic, UART, constraints, and BIOS ROM images.
It is not a standalone MIG IP core. The CPU, RTL, XDC, and memory initialization
files match the [original June 2023 contribution](https://github.com/openXC7/demo-projects/pull/5),
which includes successful calibration and a full 1 GiB memory-test transcript.

The configuration is a 125 MHz system clock, 64-bit DDR3 at 1000 MT/s, 1 GiB
mapped at `0x40000000`, and a 115200-baud UART. Preserve these settings and the
bundled BIOS while establishing the baseline.

## Evidence from 2026-10-11

All four programmed runs used the **same unmodified upstream CI bitstream** from
[run 37399939228](https://github.com/openXC7/demo-projects/actions/runs/37399939228),
source `25085a2434e13c93ec33bfd0ddf88740922821d2`.

| Run | Boot calibration and 2 MiB test | Full 1 GiB test |
| --- | --- | --- |
| [01](bringup/2026-10-11/run-01.txt) | Passed | Not issued: initial runner missed the ANSI-colored prompt |
| [02](bringup/2026-10-11/run-02.txt) | Passed | UART stopped near 976.7 MiB readback, followed by a NUL; no final pass |
| [03](bringup/2026-10-11/run-03.txt) | Passed | UART stopped near 277.7 MiB writes, followed by a NUL; silent for over four minutes |
| [04](bringup/2026-10-11/run-04.txt) | Passed | **`Memtest OK` and return to the BIOS prompt** |

The passing run reported BIOS CRC `316757a7`, LiteX revision `a1106b99`,
112.6 MiB/s writes, and 93.6 MiB/s reads in the boot benchmark. Its full-memory
command was `mem_test 0x40000000 0x40000000`; total capture time was 176.154 s.
A fifth attempt failed JTAG detection before programming and is not a memory
test result. The board is currently disconnected; the user will reconnect it
for further tests.

Host sleep is not an explanation established by the evidence: the recorded
stalls occurred around 20:17:33 and 20:19:06 IST; the full pass finished around
20:26:31. The first sleep entry in that interval is 20:27:25, after those tests.
The cause of the stalls remains unknown. Check power/reset/UART stability and
the timing failures alongside DDR calibration when repeating the experiment.

[baseline.json](bringup/2026-10-11/baseline.json) records exact hashes, toolchain
pins, original runner results, and annotations. The readable transcripts omit
repetitive progress lines; `run-*.uart.gz` preserve the complete UART bytes,
and `run-*.events.gz` preserve receive timing. The old run-01 result booleans
reflect the prompt-parser defect; its transcript shows the boot test passed.

## Build status and timing

| Build | Configuration | Status |
| --- | --- | --- |
| Upstream CI 37399939228 | Modern nextpnr `3e5c2cdd`, toolchain-nix `42323cb0` | Tested above; reported system Fmax **120.02 MHz against 125 MHz**, plus 14 hold violations |
| [Historical build 38149141580](https://github.com/5iri/demo-projects/actions/runs/38149141580) | Original source `f1b7ea4`, OpenXC7 snap 0.4.0, Yosys 0.17, nextpnr `b82028b` | Built and downloaded; **not hardware tested**; reported system Fmax 102.13 MHz |
| [Pinned modern rebuild 38172351473](https://github.com/5iri/demo-projects/actions/runs/38172351473) | Same design inputs as upstream CI, same toolchain-nix pin | Build in progress when this note was written |

The historical tool printed `PASS at 12.00 MHz`, its default timing target.
The RTL still runs the system at 125 MHz, so this is not timing closure.
These releases were recommended around the original contribution; we have
not established that they are the exact binaries its author used.

The [upstream timing excerpt](bringup/2026-10-11/upstream-timing.txt) retains
the critical system path and the reported hold violations. The modern
Makefile uses `--timing-allow-fail`. A successful build therefore
means a bitstream was produced, not that it meets setup/hold timing. Hardware
memory-test results are recorded separately. The initial fork build failed
before synthesis because `nextpnr-xilinx --version` invokes a compatibility
wrapper that requires a chip database; the workflow now queries
`nextpnr-himbaechel --version` directly.

The reproducible build entry points are
[kc705-baseline.yml](../.github/workflows/kc705-baseline.yml) and
[kc705-historical.yml](../.github/workflows/kc705-historical.yml). They retain
build logs, source/tool hashes, and bitstream/FASM/JSON artifacts for 30 days.

## Resume on the connected board

Run from the repository root. The runner checks the bitstream hash and the
XC7K325T ID before programming volatile configuration SRAM. It opens UART before
programming, captures calibration, sends the full-memory command only after a
successful boot test, and requires a final pass and prompt. It records a stall
after 30 seconds without output. Each output directory must be new.

The already-downloaded upstream bitstream:

```sh
caffeinate -i uv run --with pyserial python tools/kc705_baseline.py \
  --bit build/kc705-baseline/ci-37399939228/xilinx_kc705.bit \
  --expect-sha256 eea47c892d062210153e3534d7480e1c113f271fb59497f356dc4a562099a69b \
  --out build/kc705-baseline/ci-37399939228/run-06 \
  --full-memory-test
```

The historical artifact is downloaded and all its source/output checksums
have been verified:

```sh
caffeinate -i uv run --with pyserial python tools/kc705_baseline.py \
  --bit build/kc705-baseline/historical-38149141580/xilinx_kc705.bit \
  --expect-sha256 a570e971ce179e477ee6be3c92f3339fd5e126220dd47648b3dde977db83fa2e \
  --out build/kc705-baseline/historical-38149141580/run-01 \
  --full-memory-test
```

`caffeinate -i` is macOS-specific; omit it on Linux. Keep the host awake and
powered. Defaults are JTAG serial `210203A3CFBC` and UART
`/dev/cu.usbserial-0001`; override `--jtag-serial` and `--uart` for another host.
Raw UART, event times, programming logs, and `result.json` go in the output
directory. Future runs also record UTC start/end timestamps.
Offline replay of the saved run-02, run-03, and run-04 UART streams confirmed
that the current runner rejects both stalls and recognizes the full pass.

## Incremental migration

1. Repeat calibration and the full-memory test after fresh programming and
   cold power cycles. Require at least three consecutive complete passes,
   with no unexplained stalls, as an initial bring-up gate. This is not a
   reliability qualification or timing signoff.
2. Reproduce the unchanged design in our pinned build, compare source and
   normalized bitstream hashes, and repeat the same hardware test.
3. Introduce the CPU/interface changes while retaining the proven DDR PHY,
   controller, clocks, pin settings, and calibration firmware.
4. Introduce the registered interconnect and recheck memory traffic, byte
   enables, backpressure, timing, and reset behavior.
5. Add the TPU and verify DMA/GEMM with DDR-backed buffers.
6. Change the LiteX/LiteDRAM generation, firmware, or clock split one at a time,
   preserving a passing artifact and evidence at each stage.

Resolve any reproducible baseline stall before step 3. Every implementation
change needs its own timing report and memory test; a pass at one stage does
not qualify the next. The existing `tiny3tpu` working tree has not been modified
by this baseline effort.
