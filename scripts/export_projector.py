"""
export_projector.py - Gives an Emvryx 3 model its own eyes: the picture reader (mmproj) of its Qwen3.5 base, next to the model's .gguf, then checks it can see.

WHAT THIS FILE DOES
    The Qwen3.5 bases look at pictures themselves. Training only changes the text side, so the base's picture reader still fits the tuned model.
      1. make   the base model's picture reader is written as export/open/<model>/mmproj.gguf (llama.cpp's convert_hf_to_gguf.py --mmproj, from the
                base model that training already downloaded)
      2. check  llama-server runs the tuned model with it and is shown a picture with a number written on it; it must read the number back
    The app (app_runner.projector_for) finds mmproj.gguf beside the model and sends pictures straight to it. When the check fails, the file is renamed to
    mmproj.gguf.failed, so the app keeps using the separate picture reader for that model and nothing is worse than before. It never stops the chain.

USAGE
    python scripts/export_projector.py --model flare-3 --llama-cpp C:\\path\\to\\llama.cpp --llama-bin C:\\path\\to\\llama-server.exe
    (chain_home.py runs it as the "eyes" step)
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import argparse
import base64
import io
import json
import random
import subprocess
import time
import urllib.request

PY = sys.executable


def folder(model):
    return os.path.join("export", "open", model)


def base_id(model):
    import open_models
    cfg = open_models.PRESETS[model]
    return cfg.get("grown_from") or cfg["hf"]                                   # a grown model (Apogee 3) sees with its base's picture reader


def make_command(model, llama_cpp, base_dir):
    conv = os.path.join(llama_cpp, "convert_hf_to_gguf.py") if llama_cpp else "convert_hf_to_gguf.py"
    return [PY, conv, base_dir, "--mmproj", "--outfile", os.path.join(folder(model), "mmproj.gguf"), "--outtype", "f16"]


def number_picture(number):
    """A white picture with a number written large on it (what the check asks the model to read), as PNG bytes."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (480, 200), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 96)
    except OSError:
        try:
            font = ImageFont.load_default(size=96)
        except TypeError:
            font = ImageFont.load_default()
    draw.text((40, 40), str(number), fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def ask_about_picture(url, png, question, timeout=120):
    body = {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}},
                                                     {"type": "text", "text": question}]}], "max_tokens": 600, "temperature": 0}
    req = urllib.request.Request(url + "/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"] or ""


def sees_the_number(reply, number):
    return str(number) in "".join(ch for ch in reply if not ch.isspace() and ch not in ",.")


def check(model, llama_bin, port=8098, tries=2):
    """True when the tuned model, with its picture reader, reads a number off a picture."""
    gguf = os.path.join(folder(model), "my-ai-q4_k_m.gguf")
    proj = os.path.join(folder(model), "mmproj.gguf")
    server = subprocess.Popen([llama_bin, "-m", gguf, "--mmproj", proj, "-ngl", "99", "-c", "8192", "--jinja", "--port", str(port)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            if server.poll() is not None:
                print("llama-server stopped while loading the model with its picture reader")
                return False
            try:
                urllib.request.urlopen(url + "/health", timeout=2)
                break
            except Exception:                                                  # noqa: BLE001
                time.sleep(2)
        good = 0
        for _ in range(tries):
            number = random.randint(1000, 9999)
            reply = ask_about_picture(url, number_picture(number), "What number is written in this picture? Reply with the number only.")
            ok = sees_the_number(reply, number)
            print(f"picture with {number}: {'read it' if ok else 'did not read it'} ({reply.strip()[:80]!r})")
            good += ok
        return good == tries
    finally:
        server.terminate()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True)
    ap.add_argument("--llama-cpp", default=None, help="the llama.cpp folder (convert_hf_to_gguf.py)")
    ap.add_argument("--llama-bin", default=None, help="llama-server, for the check")
    ap.add_argument("--port", type=int, default=8098)
    a = ap.parse_args(argv)
    proj = os.path.join(folder(a.model), "mmproj.gguf")
    if not os.path.exists(proj):
        from huggingface_hub import snapshot_download
        base_dir = snapshot_download(base_id(a.model))                             # already downloaded for training: read from the cache
        rc = subprocess.run(make_command(a.model, a.llama_cpp, base_dir)).returncode
        if rc or not os.path.exists(proj):
            print("Could not make the picture reader: the app keeps using the separate one for this model.")
            return 0
    if not a.llama_bin:
        print("No --llama-bin: the picture reader is in place but was not checked.")
        return 0
    try:
        ok = check(a.model, a.llama_bin, a.port)
    except Exception as e:                                                     # noqa: BLE001
        print(f"The check could not run: {e}")
        ok = False
    if ok:
        print(f"{a.model} can see: pictures will go straight to it.")
    else:
        os.replace(proj, proj + ".failed")
        print(f"{a.model} did not read the pictures well: renamed to mmproj.gguf.failed, so the app keeps using the separate picture reader.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
