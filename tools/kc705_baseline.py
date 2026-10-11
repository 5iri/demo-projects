#!/usr/bin/env python3
"""Run the upstream KC705 BIOS memory test, preserving exact hardware evidence.

Uses volatile FPGA SRAM programming and the board's 115200-baud UART.
Requires pyserial (for example: uv run --with pyserial python ...).
Reported build timing and observed memory-test results are separate evidence.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

import serial


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bit", type=Path, required=True)
    parser.add_argument("--expect-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--uart", default="/dev/cu.usbserial-0001")
    parser.add_argument("--jtag-serial", default="210203A3CFBC")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--idle-timeout", type=float, default=30)
    parser.add_argument("--full-memory-test", action="store_true")
    args = parser.parse_args()
    bit = args.bit.resolve()
    digest = sha256(bit)
    if digest != args.expect_sha256:
        parser.error("bitstream SHA256 does not match the specified artifact")
    if b"xc7k325tffg900-2" not in bit.read_bytes()[:256]:
        parser.error("bitstream header does not identify the KC705 part")
    args.out.mkdir(parents=True, exist_ok=False)
    detect_cmd = ["openFPGALoader", "--board", "kc705", "--ftdi-serial",
                  args.jtag_serial, "--detect"]
    detect = subprocess.run(detect_cmd, capture_output=True, text=True, timeout=20)
    (args.out / "detect.log").write_text(detect.stdout + detect.stderr)
    if detect.returncode or "0x3651093" not in detect.stdout + detect.stderr:
        parser.error("expected XC7K325T was not detected; see detect.log")

    started = time.monotonic()
    started_utc = datetime.now(timezone.utc).isoformat()
    data = bytearray()
    events = []
    process = None
    result = dict(bitstream=str(bit), bitstream_sha256=digest,
                  started_utc=started_utc,
                  programming="volatile FPGA configuration SRAM",
                  uart=args.uart, jtag_serial=args.jtag_serial,
                  full_memory_test_requested=args.full_memory_test,
                  hardware_memory_pass=False, boot_memory_pass=False,
                  full_memory_pass=False, timing_closure_claimed=False)
    try:
        with serial.Serial(args.uart, 115200, timeout=0.1,
                           rtscts=False, dsrdtr=False) as uart:
            uart.reset_input_buffer()
            command = ["openFPGALoader", "--board", "kc705", "--ftdi-serial",
                       args.jtag_serial, "--write-sram", str(bit)]
            result["program_command"] = command
            with (args.out / "program.log").open("w") as log:
                process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
                escaped = False
                full_start = None
                last_output = time.monotonic()
                deadline = time.monotonic() + args.timeout
                while time.monotonic() < deadline:
                    chunk = uart.read(4096)
                    if chunk:
                        last_output = time.monotonic()
                        events.append(dict(seconds=round(time.monotonic()-started, 3),
                                           offset=len(data), size=len(chunk)))
                        data.extend(chunk)
                        print(chunk.decode("ascii", errors="backslashreplace"), end="", flush=True)
                    rc = process.poll()
                    if rc is not None:
                        result["program_exit"] = rc
                        if rc:
                            result["failure"] = "programming failed"
                            break
                    elif time.monotonic() - started > 45:
                        process.terminate()
                        process.wait(timeout=10)
                        result["failure"] = "programming timed out"
                        break

                    if full_start is not None and time.monotonic() - last_output > args.idle_timeout:
                        result["failure"] = "full-memory test UART stalled"
                        break

                    # Ignore output from the old FPGA image before this BIOS starts.
                    bios_start = data.find(b"BIOS built on")
                    if bios_start < 0 or rc is None:
                        continue
                    boot = re.sub(rb"\x1b\[[0-?]*[ -/]*[@-~]", b"", bytes(data[bios_start:]))
                    if b"Booting from serial" in boot and not escaped:
                        uart.write(b"\x1b")
                        uart.flush()
                        escaped = True
                    if b"litex>" not in boot:
                        continue
                    if full_start is None:
                        result["boot_memory_pass"] = (b"Memtest OK" in boot
                                                      and b"Memory initialization failed" not in boot)
                        if not result["boot_memory_pass"]:
                            result["failure"] = "BIOS calibration/boot memory test failed"
                            break
                        if not args.full_memory_test:
                            result["hardware_memory_pass"] = True
                            break
                        full_start = len(data)
                        result["memory_command"] = "mem_test 0x40000000 0x40000000"
                        uart.write((result["memory_command"] + "\n").encode())
                        uart.flush()
                        deadline = time.monotonic() + args.timeout
                        continue
                    test = re.sub(rb"\x1b\[[0-?]*[ -/]*[@-~]", b"", bytes(data[full_start:]))
                    if b"litex>" in test:
                        result["full_memory_pass"] = (b"(1.0GiB)" in test
                                                     and b"Memtest OK" in test
                                                     and b"failed" not in test.lower())
                        result["hardware_memory_pass"] = result["full_memory_pass"]
                        if not result["full_memory_pass"]:
                            result["failure"] = "full-memory command did not pass"
                        break
                else:
                    result["failure"] = "UART/test timeout"
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
                result["program_exit"] = process.returncode
    except KeyboardInterrupt:
        result["failure"] = "capture interrupted"
    except Exception as exc:
        result["failure"] = f"{type(exc).__name__}: {exc}"
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if process is not None:
            result["program_exit"] = process.returncode
        result["finished_utc"] = datetime.now(timezone.utc).isoformat()
        result["elapsed_seconds"] = round(time.monotonic()-started, 3)
        result["uart_bytes"] = len(data)
        (args.out / "uart.bin").write_bytes(data)
        (args.out / "uart.log").write_text(data.decode("ascii", errors="backslashreplace"))
        (args.out / "events.json").write_text(json.dumps(events, indent=2) + "\n")
        (args.out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print("\n" + json.dumps(result, indent=2), flush=True)
    return 0 if result["hardware_memory_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
