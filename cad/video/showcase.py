"""Join the intro and every group's outro into one film, dissolving between segments.

clip 0 = intro + robotic arm (already one continuous take, rover_robotic-arm.mp4); then each group's outro_<slug>.mp4
in GROUPS order. Each clip's closing hold is trimmed to TAIL seconds' worth less, and neighbours cross-dissolve for XFADE s.

Usage: python3 -I showcase.py WORKDIR VIDEOS_DIR OUT.mp4
"""
import os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from groups import GROUPS

WORK, VIDEOS, OUT = sys.argv[1:4]
TRIM, XFADE = 1.3, 0.4


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


clips = [os.path.join(VIDEOS, "rover_robotic-arm.mp4")] + [os.path.join(WORK, f"outro_{g['slug']}.mp4") for g in GROUPS]
durs = [duration(c) - TRIM for c in clips]
cmd = ["ffmpeg", "-y", "-loglevel", "error"]
for c, d in zip(clips, durs):
    cmd += ["-t", f"{d:.3f}", "-i", c]
chain, label, elapsed = [], "[0:v]", durs[0]
for i in range(1, len(clips)):
    out = f"[v{i}]"
    chain.append(f"{label}[{i}:v]xfade=transition=fade:duration={XFADE}:offset={elapsed - XFADE:.3f}{out}")
    label, elapsed = out, elapsed + durs[i] - XFADE
cmd += ["-filter_complex", ";".join(chain), "-map", label, "-c:v", "libx264", "-preset", "medium", "-crf", "17",
        "-pix_fmt", "yuv420p", "-r", "30", "-movflags", "+faststart", OUT]
subprocess.run(cmd, check=True)
print(f"{len(clips)} clips, {elapsed:.1f} s -> {OUT}")
