"""
render_commercial.py - turns the 15 second advert page (site/commercial.html) into a real video file.

WHAT THIS FILE DOES
    The advert is an animated web page whose every moment is worked out from one number, the time. This tool opens it in a real browser (1080 x 1920, the shape phones use for
    Reels, Shorts and TikTok), asks for each frame in turn (30 a second, 450 in all), takes a picture of it, and gives the pictures to ffmpeg, which makes the MP4.
    Because every frame is asked for by its exact time, the video is the same, smooth, every time, however slow this computer is.

    Sound: with --music a soft original pad is made by ffmpeg itself (a few sine tones, nothing copied from anywhere), so the video is free of music rights. Without it the
    video is silent for you to put your own voice and music on (see docs/COMMERCIAL.md).

Usage:
    python tools/render_commercial.py                      (silent video: site/emvryx-ad-15s.mp4)
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
PAGE = os.path.join(ROOT, "site", "commercial.html")
FPS = 30
SECONDS = 15
STILLS = (1.9, 4.0, 5.9, 8.9, 11.6, 14.4)            # the moments worth looking at: the mark, a question, the answer, the finished build, the four reasons, the sign-off


def browser_path():
    """The browser to use: EMVRYX_BROWSER if set, otherwise the one the tests find (None lets playwright use its own)."""
    if os.environ.get("EMVRYX_BROWSER"):
        return os.environ["EMVRYX_BROWSER"]
    try:
        from tests.test_browser_check import find_browser
        return find_browser()
    except Exception:
        return None


def music_filter():
    """An original soft pad made from sine tones (an A minor chord, a slow swell), faded in and out over the 15 seconds. Nothing here is copied from any recording."""
    tones = [110.0, 164.81, 220.0, 261.63, 329.63]
    inputs = []
    for f in tones:
        inputs += ["-f", "lavfi", "-t", str(SECONDS), "-i", f"sine=frequency={f}:sample_rate=48000"]
    # input 0 is the picture sequence, so the tones are inputs 1 to 5
    mix = f"{''.join(f'[{i + 1}]' for i in range(len(tones)))}amix=inputs={len(tones)}:normalize=0,volume=0.16,tremolo=f=0.35:d=0.35,lowpass=f=1400,afade=t=in:st=0:d=2,afade=t=out:st={SECONDS - 2.5}:d=2.5,aformat=channel_layouts=stereo"
    return inputs, mix


def main():
    ap = argparse.ArgumentParser(description="Render the 15 second advert to an MP4")
    ap.add_argument("--out", default=os.path.join(ROOT, "site"), help="the folder for the result")
    ap.add_argument("--music", action="store_true", help="add a soft original pad made by ffmpeg")
    ap.add_argument("--stills", action="store_true", help="only take six pictures to look at")
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright
    os.makedirs(args.out, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=browser_path())
        page = browser.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
        page.goto("file://" + os.path.abspath(PAGE).replace("\\", "/") + "?clean")
        page.wait_for_function("typeof window.__seek === 'function'")
        if args.stills:
            for t in STILLS:
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
            target = os.path.join(args.out, "emvryx-ad-15s.mp4")
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(frames, "f%04d.jpg")]
            if args.music:
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
