"""
render_commercial.py - turns the 15 second advert page (site/commercial.html) into a real video file.

WHAT THIS FILE DOES
    The advert is an animated web page whose every moment is worked out from one number, the time. This tool opens it in a real browser (1080 x 1920, the shape phones use for
    Reels, Shorts and TikTok), asks for each frame in turn (30 a second, 450 in all), takes a picture of it, and gives the pictures to ffmpeg, which makes the MP4.
    Because every frame is asked for by its exact time, the video is the same, smooth, every time, however slow this computer is.

    Sound: with --music a soft original pad is made by ffmpeg itself (a few sine tones, nothing copied from anywhere), so the video is free of music rights. Without it the
    video is silent for you to put your own voice and music on (see docs/COMMERCIAL.md).

    The 30 second version (--cut 30, site/commercial30.html) has a voice. The voice is made on this computer by Piper (free, open source) from the page's own list of lines,
    each placed at its time, with the soft pad ducked underneath it so the words stay clear. The voice used is "Alba" (British English, the University of Edinburgh's CSTR,
    CC BY 4.0: free to use in a commercial advert with the credit "Voice: Alba, CSTR, University of Edinburgh, CC BY 4.0"). It is downloaded once to a cache folder.
    If the voice reads a word wrongly (the brand name is spelt "Em-vrix" for it), change the spelling in the page's VOICE list and render again.

Usage:
    python tools/render_commercial.py                      (silent video: site/emvryx-ad-15s.mp4)
    python tools/render_commercial.py --cut 30             (the 30 second ad with the voice and the pad: site/emvryx-ad-30s.mp4)
    python tools/render_commercial.py --music              (with the soft pad)
    python tools/render_commercial.py --stills             (six pictures to look at, in the output folder)
    python tools/render_commercial.py --out some/folder
Needs: playwright with a browser (the same one the tests use; EMVRYX_BROWSER can name it) and ffmpeg on the path.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)); import emvryx_paths  # noqa: E402,F401
import argparse
import shutil
import subprocess
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
PAGES = {15: "commercial.html", 30: "commercial30.html"}
FPS = 30
SECONDS = 15
VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alba/medium/en_GB-alba-medium"     # Alba, CC BY 4.0
VOICE_CACHE = os.path.join(os.path.expanduser("~"), ".cache", "emvryx-voice")
STILLS = {15: (1.9, 4.0, 5.9, 8.9, 11.6, 14.4), 30: (2.5, 5.0, 9.4, 14.6, 19.6, 23.4, 28.5)}            # the moments worth looking at: the mark, a question, the answer, the finished build, the four reasons, the sign-off


def browser_path():
    """The browser to use: EMVRYX_BROWSER if set, otherwise the one the tests find (None lets playwright use its own)."""
    if os.environ.get("EMVRYX_BROWSER"):
        return os.environ["EMVRYX_BROWSER"]
    try:
        from tests.test_browser_check import find_browser
        return find_browser()
    except Exception:
        return None


def voice_model():
    """The path of the Alba voice model, downloaded once to the cache folder."""
    import urllib.request
    os.makedirs(VOICE_CACHE, exist_ok=True)
    for ext in (".onnx", ".onnx.json"):
        dest = os.path.join(VOICE_CACHE, "alba" + ext)
        if not os.path.exists(dest):
            print("downloading the voice (once):", VOICE_URL.rsplit("/", 1)[1] + ext, flush=True)
            urllib.request.urlretrieve(VOICE_URL + ext, dest)
    return os.path.join(VOICE_CACHE, "alba.onnx")


def make_voice(lines, folder):
    """One WAV per line of the page's VOICE list ([{"t": start seconds, "say": words}, ...]). Returns [(path, start, length)] and says plainly if a line runs into the next."""
    import wave
    try:
        from piper import PiperVoice
    except ImportError:
        raise SystemExit("the voice needs Piper: pip install piper-tts")
    voice = PiperVoice.load(voice_model())
    made = []
    for i, line in enumerate(lines):
        path = os.path.join(folder, f"voice{i}.wav")
        with wave.open(path, "wb") as w:
            voice.synthesize_wav(line["say"], w)
        with wave.open(path) as w:
            made.append((path, float(line["t"]), w.getnframes() / w.getframerate()))
    for (p1, t1, d1), (p2, t2, d2) in zip(made, made[1:]):
        if t1 + d1 > t2 - 0.1:
            print(f"WARNING: a line that starts at {t1}s ends at {t1 + d1:.2f}s but the next starts at {t2}s", flush=True)
    if made and made[-1][1] + made[-1][2] > SECONDS:
        print("WARNING: the last line runs past the end of the video", flush=True)
    print("voice lines (start, length):", [(round(t, 1), round(d, 2)) for _, t, d in made], flush=True)
    return made


def music_filter(level=0.16):
    """An original soft pad made from sine tones (an A minor chord, a slow swell), faded in and out over the 15 seconds. Nothing here is copied from any recording."""
    tones = [110.0, 164.81, 220.0, 261.63, 329.63]
    inputs = []
    for f in tones:
        inputs += ["-f", "lavfi", "-t", str(SECONDS), "-i", f"sine=frequency={f}:sample_rate=48000"]
    # input 0 is the picture sequence, so the tones are inputs 1 to 5
    mix = f"{''.join(f'[{i + 1}]' for i in range(len(tones)))}amix=inputs={len(tones)}:normalize=0,volume={level},tremolo=f=0.35:d=0.35,lowpass=f=1400,afade=t=in:st=0:d=2,afade=t=out:st={SECONDS - 2.5}:d=2.5,aformat=channel_layouts=stereo"
    return inputs, mix


def main():
    ap = argparse.ArgumentParser(description="Render the 15 second advert to an MP4")
    ap.add_argument("--out", default=os.path.join(ROOT, "site"), help="the folder for the result")
    ap.add_argument("--music", action="store_true", help="add a soft original pad made by ffmpeg (the 30 second cut always has it)")
    ap.add_argument("--cut", type=int, choices=sorted(PAGES), default=15, help="15 (silent animation) or 30 (with the voice)")
    ap.add_argument("--stills", action="store_true", help="only take six pictures to look at")
    args = ap.parse_args()
    global SECONDS
    SECONDS = args.cut
    PAGE = os.path.join(ROOT, "site", PAGES[args.cut])
    from playwright.sync_api import sync_playwright
    os.makedirs(args.out, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=browser_path())
        page = browser.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
        page.goto("file://" + os.path.abspath(PAGE).replace("\\", "/") + "?clean")
        page.wait_for_function("typeof window.__seek === 'function'")
        lines = page.evaluate("window.__voice || []")
        if args.stills:
            for t in STILLS[args.cut]:
                page.evaluate("(t) => window.__seek(t)", t)
                page.screenshot(path=os.path.join(args.out, f"ad-still-{t:04.1f}.png"))
            browser.close()
            print("stills written to", args.out)
            return
        if not shutil.which("ffmpeg"):
            raise SystemExit("ffmpeg is needed to make the video (https://ffmpeg.org)")
        frames = tempfile.mkdtemp(prefix="emvryx-ad-")
        done = False
        try:
            total = FPS * SECONDS
            for i in range(total):
                page.evaluate("(t) => window.__seek(t)", i / FPS)
                page.screenshot(path=os.path.join(frames, f"f{i:04d}.jpg"), type="jpeg", quality=96)
                if i % 60 == 0:
                    print(f"frame {i}/{total}", flush=True)
            browser.close()
            target = os.path.join(args.out, f"emvryx-ad-{args.cut}s.mp4")
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(frames, "f%04d.jpg")]
            if lines:
                made = make_voice(lines, frames)
                inputs, mix = music_filter(0.30)                                   # louder than in the silent cut: it is ducked under the voice
                n = len(made)
                vin = []
                for path, _, _ in made:
                    vin += ["-i", path]
                first = 1 + 5                                                     # input 0 is the pictures, 1 to 5 the pad's tones, then the voice lines
                delays = ";".join(f"[{first + i}]adelay={int(t * 1000)}|{int(t * 1000)},aresample=48000,aformat=channel_layouts=stereo[v{i}]" for i, (_, t, _) in enumerate(made))
                vmix = "".join(f"[v{i}]" for i in range(n)) + f"amix=inputs={n}:normalize=0,volume=1.6,asplit[vo][vkey]"
                # the pad sits under the voice: it dips while the voice speaks (sidechain), then both are mixed and kept from clipping
                graph = f"{mix}[pad];{delays};{vmix};[pad][vkey]sidechaincompress=threshold=0.015:ratio=10:attack=15:release=500[low];[low][vo]amix=inputs=2:normalize=0,apad=whole_dur={SECONDS},alimiter=limit=0.95[a]"
                cmd += inputs + vin + ["-filter_complex", graph, "-map", "0:v", "-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
            elif args.music:
                inputs, mix = music_filter()
                cmd += inputs + ["-filter_complex", mix + "[a]", "-map", "0:v", "-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
            cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-t", str(SECONDS), target]
            subprocess.run(cmd, check=True)
            done = True
        finally:
            if done:
                shutil.rmtree(frames, ignore_errors=True)
            else:
                print("the pictures are kept in", frames, "(so the video can be made again without taking them again)")
    print("wrote", target)


if __name__ == "__main__":
    main()
