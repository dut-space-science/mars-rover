"""Render the per-group 3D frames: a camera glide from the default hold view to the group's best view,
and that final view with the group in place and alone (the highlight mask: see sceneops.group_mask).

Reads WORK/survey.json (survey.py). Writes WORK/groups/<slug>/glide_####.png, hold_full.png, hold_iso.png (the group alone)
and, for groups that need a cutaway or an un-hide, hold_pre.png (the same view before it).

Usage: python3 -I render_groups.py WORKDIR [WORKERS] [slug ...]
"""
import json, math, os, sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mcpclient import SolidCraftMCP
from sceneops import prep, isolate, rewind

WORK = sys.argv[1]
WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
ONLY = sys.argv[3:]
W, H = 1920, 1080
GLIDE_N = 36
HOME = {"target": [150, 0, 120], "distance": 760, "yaw": 0.8, "pitch": 0.45}     # where the orbit ends
_m = None


def smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def final_camera(g):
    b = g["best"][0]
    return {"target": g["target"], "distance": g["distance"], "yaw": b["yaw"], "pitch": b["pitch"]}


def glide_camera(g, i):
    end = final_camera(g)
    t = smooth((i + 1) / GLIDE_N)
    dyaw = (end["yaw"] - HOME["yaw"] + math.pi) % (2 * math.pi) - math.pi            # shortest way round
    lerp = lambda a, b: a + (b - a) * t
    return {"target": [lerp(HOME["target"][k], end["target"][k]) for k in range(3)],
            "distance": lerp(HOME["distance"], end["distance"]),
            "yaw": HOME["yaw"] + dyaw * t, "pitch": lerp(HOME["pitch"], end["pitch"])}


def init():
    global _m
    _m = SolidCraftMCP(os.path.join(WORK, os.environ.get("ROVER_DESIGN", "rover.solidcraft")), WORK)
    _m.cmd("browser.visibility", visible=False, folder="sketches")


def shot(path, cam):
    _m.tool("screenshot", camera=cam, width=W, height=H, grid=False, axes=False, path=path)


def job(j):
    slug, kind, i, g = j
    out = os.path.join(WORK, "groups", slug)
    hid = 0
    if g.get("show_bodies"):                                   # keep the group out of sight until its own segment
        _m.cmd("browser.visibility", visible=False, items=g["show_bodies"]); hid = 1
    if kind == "glide":
        shot(os.path.join(out, f"glide_{i + 1:04d}.png"), glide_camera(g, i))
        rewind(_m, hid)
    else:
        cam = final_camera(g)
        if g.get("cutaway") or g.get("show_bodies"):
            shot(os.path.join(out, "hold_pre.png"), cam)                  # the view as the orbit left it
        n = prep(_m, g)
        shot(os.path.join(out, "hold_full.png"), cam)
        k = isolate(_m, g)
        shot(os.path.join(out, "hold_iso.png"), cam)
        rewind(_m, k + n + hid)
    return slug


if __name__ == "__main__":
    survey = json.load(open(os.path.join(WORK, "survey.json")))
    jobs = []
    for slug, g in survey.items():
        if ONLY and slug not in ONLY:
            continue
        os.makedirs(os.path.join(WORK, "groups", slug), exist_ok=True)
        jobs.append((slug, "hold", 0, g))
        if g.get("glide", True):
            jobs += [(slug, "glide", i, g) for i in range(GLIDE_N)]
    with Pool(WORKERS, initializer=init) as pool:
        for n, _ in enumerate(pool.imap_unordered(job, jobs), 1):
            if n % 20 == 0 or n == len(jobs):
                print(f"{n}/{len(jobs)}", flush=True)
