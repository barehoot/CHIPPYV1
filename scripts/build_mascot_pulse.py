"""Build Chippy's interval ("pulse") animations from the supplied frames. No new art: every frame comes from
streamlit/sr_ui/mascot/radar/*.webp.

The supplied animations loop forever at full frame rate, often several on one page. A pulse plays the pose, then
rests on its first frame for a few seconds (one frame with a long duration costs the browser almost nothing to show),
then loops. Mixes chain two or three poses with rests between them, so Chippy does different things over time.
Every output is padded to a square 192 x 192 canvas, bottom-centred, so no pose is stretched.

Run from the project folder:  python3 scripts/build_mascot_pulse.py
Writes streamlit/sr_ui/mascot/radar/pulse/<name>.webp and <name>.png (the still shown with reduced motion).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

SRC = Path(__file__).resolve().parents[1] / "streamlit" / "sr_ui" / "mascot" / "radar"
OUT = SRC / "pulse"
SIDE = 192

# name -> [(pose, plays, rest_ms after it)]. Rests differ, so mascots on one page do not move in step.
PULSES = {
    "welcome": [("welcome", 1, 7000)],
    "detective": [("detective", 1, 6500)],
    "success": [("success", 2, 8000)],
    "resting": [("resting", 1, 9000)],
    # mixes: a different pose each time Chippy moves
    "hero_mix": [("detective", 1, 5200), ("investigating", 1, 5800), ("welcome", 1, 6400)],
    "hello_mix": [("welcome", 1, 6000), ("success", 1, 7000)],
    "think_mix": [("investigating", 1, 5000), ("detective", 1, 6000)],
    "rest_mix": [("resting", 1, 8000), ("welcome", 1, 9000)],
}


def frames(pose: str) -> list[tuple[Image.Image, int]]:
    im = Image.open(SRC / f"{pose}.webp")
    out = []
    for i in range(im.n_frames):
        im.seek(i)
        im.load()
        canvas = Image.new("RGBA", (SIDE, SIDE), (0, 0, 0, 0))
        f = im.convert("RGBA")
        f.thumbnail((SIDE, SIDE))
        canvas.paste(f, ((SIDE - f.width) // 2, SIDE - f.height), f)
        out.append((canvas, int(im.info.get("duration") or 160)))
    return out


def build(name: str, plan: list[tuple[str, int, int]]) -> None:
    seq: list[Image.Image] = []
    durations: list[int] = []
    for pose, plays, rest in plan:
        fr = frames(pose)
        for _ in range(plays):
            for img, d in fr:
                seq.append(img)
                durations.append(d)
        seq.append(fr[0][0])               # rest on the first frame: one long frame
        durations.append(rest)
    seq[0].save(OUT / f"{name}.webp", save_all=True, append_images=seq[1:], duration=durations, loop=0,
                lossless=False, quality=88, method=6, minimize_size=True)
    seq[0].save(OUT / f"{name}.png", optimize=True)    # the first pose: what reduced motion shows


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, plan in PULSES.items():
        build(name, plan)
        print(f"{name}: {(OUT / f'{name}.webp').stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
