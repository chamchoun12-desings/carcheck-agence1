"""Cut the walk-around into photos: 1 per second, 1280 px wide (part 03)."""
import pathlib
import subprocess

from .config import FRAME_FPS


def extract(check_dir) -> list[pathlib.Path]:
    d = pathlib.Path(check_dir)
    out = d / "frames"
    out.mkdir(exist_ok=True)
    for old in out.glob("f_*.jpg"):
        old.unlink()
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-i", str(d / "walk.mp4"),
         "-vf", f"fps={FRAME_FPS},scale=1280:-2", "-q:v", "3",
         str(out / "f_%03d.jpg")],
        check=True)
    return sorted(out.glob("f_*.jpg"))
