"""
emvryx3_preflight.py - Is this PC ready to pilot and train Flare 3, Equinox 3 and Solstice 3? (Emvryx 3 runbook, docs/EMVRYX3_RUNBOOK.md)

    python scripts/emvryx3_preflight.py                 # checks everything and prints what to fix
    python scripts/emvryx3_preflight.py --llama-cpp ..\\llama.cpp --llama-bin C:\\path\\to\\llama-server.exe

Each line is OK, WARN (probably fine, read it) or FAIL (fix it first). The exit code is 1 when anything FAILED. Nothing is changed or downloaded.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import argparse
import importlib
import json
import shutil
import socket
import subprocess

OK, WARN, FAIL = "OK", "WARN", "FAIL"
PACKAGES = (("torch", True), ("transformers", True), ("peft", True), ("bitsandbytes", True), ("accelerate", True), ("tokenizers", True), ("datasets", False))


def check_python(version):
    return (OK, f"Python {version[0]}.{version[1]}", "") if tuple(version[:2]) >= (3, 10) else (FAIL, f"Python {version[0]}.{version[1]} is too old", "Install Python 3.10 or newer.")


def check_gpu(available, name, vram_gb):
    if not available:
        return FAIL, "torch cannot see the graphics card", "Install PyTorch with CUDA: https://pytorch.org/get-started (pip install torch --index-url https://download.pytorch.org/whl/cu128; if pip finds nothing, use cu130). Uninstall the CPU one first: pip uninstall -y torch"
    if vram_gb < 11:
        return FAIL, f"{name}: only {vram_gb:.1f} GB of graphics memory", "These runs are sized for 12 GB."
    note = "" if "4070" in name or vram_gb >= 11.5 else "Not a 4070, but it has enough memory."
    return OK, f"{name}, {vram_gb:.1f} GB", note


def check_package(name, version, needed):
    if version:
        return OK, f"{name} {version}", ""
    return (FAIL if needed else WARN), f"{name} is not installed", f"pip install -U {name}"


def check_disk(free_gb):
    if free_gb < 40:
        return FAIL, f"{free_gb:.0f} GB free on this drive", "The three downloads, the training files and the exports need about 60 GB. Free some space."
    if free_gb < 60:
        return WARN, f"{free_gb:.0f} GB free on this drive", "Enough for one model at a time; delete each one's export after you have tested it."
    return OK, f"{free_gb:.0f} GB free on this drive", ""


def check_ram(total_gb):
    if total_gb is None:
        return WARN, "could not read the memory size", ""
    if total_gb < 24:
        return FAIL, f"{total_gb:.0f} GB of RAM", "Merging the 9B model needs about 20 GB of free RAM."
    return OK, f"{total_gb:.0f} GB of RAM", ""


def check_gpu_busy(used_mb, total_mb):
    if used_mb is None:
        return WARN, "could not read how much graphics memory is in use", ""
    if used_mb > 2048:
        return WARN, f"{used_mb / 1024:.1f} GB of the card is already in use", "Stop the Emvryx app and any game first: Stop-ScheduledTask \"Emvryx App\"; taskkill /F /IM llama-server.exe /T (or run the chain with --stop-app)."
    return OK, f"{used_mb / 1024:.1f} GB of the card is in use", ""


def check_file(label, path, needed, fix):
    return (OK, f"{label}: {path}", "") if path and os.path.exists(path) else ((FAIL if needed else WARN), f"{label} not found", fix)


def check_lessons(path):
    if not os.path.exists(path):
        return FAIL, f"{path} is missing", "Build it: python data_prep/make_chat_data_v3.py"
    with open(path, encoding="utf-8") as f:
        n = sum(1 for line in f if line.strip())
    return (OK, f"{path}: {n:,} lessons", "") if n >= 20000 else (WARN, f"{path} has only {n:,} lessons", "The earlier builds used about 110,000.")


# ---- reading the machine -------------------------------------------------------------------------------------------------------------
def total_ram_gb():
    try:
        import psutil
        return psutil.virtual_memory().total / 2**30
    except Exception:                                              # noqa: BLE001
        pass
    try:
        if os.name == "nt":
            import ctypes

            class MEM(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("p", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong), ("tp", ctypes.c_ulonglong),
                            ("ap", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
            m = MEM()
            m.l = ctypes.sizeof(MEM)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.total / 2**30
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except Exception:                                              # noqa: BLE001
        return None


def gpu_memory_used():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15).stdout
        used, total = (float(x) for x in out.strip().splitlines()[0].split(","))
        return used, total
    except Exception:                                              # noqa: BLE001
        return None, None


def module_version(name):
    try:
        return getattr(importlib.import_module(name), "__version__", "installed")
    except Exception:                                              # noqa: BLE001  (a broken install counts as missing)
        return None


def app_running(port=8001):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def run_checks(a):
    rows = [("Python", check_python(sys.version_info))]
    avail, name, vram = False, "", 0.0
    try:
        import torch
        avail = torch.cuda.is_available()
        if avail:
            name, vram = torch.cuda.get_device_name(0), torch.cuda.get_device_properties(0).total_memory / 2**30
    except Exception:                                              # noqa: BLE001
        pass
    rows.append(("Graphics card", check_gpu(avail, name, vram)))
    for pkg, needed in PACKAGES:
        rows.append((pkg, check_package(pkg, module_version(pkg), needed)))
    rows.append(("Disk", check_disk(shutil.disk_usage(".").free / 2**30)))
    rows.append(("RAM", check_ram(total_ram_gb())))
    used, total = gpu_memory_used()
    rows.append(("Card in use", check_gpu_busy(used, total)))
    if app_running(a.port):
        rows.append(("Emvryx app", (WARN, f"the app is running on port {a.port}", "It holds a model on the card. Stop it before training (see --stop-app in the chain).")))
    llama = a.llama_bin or shutil.which("llama-server") or os.environ.get("EMVRYX_LLAMA")
    rows.append(("llama-server", check_file("llama-server", llama, True, "Set --llama-bin to llama-server.exe (the file used in .emvryx\\start_emvryx.cmd).")))
    conv = os.path.join(a.llama_cpp, "convert_hf_to_gguf.py") if a.llama_cpp else None
    rows.append(("GGUF converter", check_file("convert_hf_to_gguf.py", conv, False, "Pass --llama-cpp <the llama.cpp source folder> (needed to turn a trained model into a .gguf).")))
    rows.append(("Lessons", check_lessons(a.lessons)))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llama-bin", default=None)
    ap.add_argument("--llama-cpp", default=None, help="the llama.cpp folder that has convert_hf_to_gguf.py")
    ap.add_argument("--lessons", default=os.path.join("data", "v3", "chat.jsonl"))
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--json", default=None, help="also write the results here")
    a = ap.parse_args(argv)
    rows = run_checks(a)
    for label, (status, detail, fix) in rows:
        print(f"{status:<5} {label:<15} {detail}" + (f"\n      -> {fix}" if fix and status != OK else ""))
    bad = [r for r in rows if r[1][0] == FAIL]
    print("\n" + ("Ready." if not bad else f"{len(bad)} thing(s) to fix before the pilot."))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump([{"check": l, "status": s, "detail": d, "fix": x} for l, (s, d, x) in rows], f, indent=2)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
