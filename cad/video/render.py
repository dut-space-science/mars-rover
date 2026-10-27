"""Render the raw 3D frames for the rover video through the SolidCraft MCP server.

Phases rendered here (everything 2D - cursor, highlight, leader line, label - is
composited afterwards by compose.py):

  a_####.png  blown-up -> re-assembled, parts landing one after another
  b_####.png  360 degree orbit, ending on the hold view
  hold_full.png / hold_hide.png
              the hold view with and without the robotic-arm group; their
              difference is the pixel mask used for the highlight

Usage: python3 -I render.py WORKDIR [WORKERS]
"""
import json, math, os, sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mcpclient import SolidCraftMCP

WORK = sys.argv[1]
WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
W, H = 1920, 1080
FRAMES = os.path.join(WORK, "frames")

A_FRAMES, B_FRAMES = 150, 180        # 30 fps: 5 s assemble, 6 s orbit
HOLD_YAW, PITCH = 0.8, 0.45
ASSEMBLED = {"target": [150, 0, 120], "distance": 760}
EXPLODED = {"target": [235, 0, 135], "distance": 1300}
EXPLODE_K = 1.5

# Occurrence ids (component.list) in the order they should land.
ARM = [2736, 2751, 2782, 2813, 2844]
ASSEMBLY_ORDER = (
    [1930]
    + [2109, 2192, 2275, 2358, 2441, 2524]          # drive modules
    + [2162, 2245, 2328, 2411, 2494, 2577]          # wheels
    + [3287, 2630, 2607, 3020]                      # underbody LEDs, power, avionics, lab
    + [2854, 2672, 2698, 3397, 3173]                # armour, lid, payload mounts, DUT badges, lights
    + [3229, 3241, 3257, 3142, 3154, 3162, 2710]    # mast and dish
    + ARM
    + [2882, 2951]                                  # solar wings
)
ARM_SCALE = 0.7      # the arm chain explodes a long way; pull it in so it stays in frame


def smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def ease_out(x):
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


_m = None
_base = None
_shown = False


def init():
    global _m, _base
    _m = SolidCraftMCP(os.path.join(WORK, os.environ.get("ROVER_DESIGN", "rover.solidcraft")), WORK)
    _base = {x["occurrence"]: x["translate"] for x in json.load(open(os.path.join(WORK, "base_moves.json")))}
    # Sweep-path sketches (hose and wire routes) stay at the assembled position while the bodies explode,
    # so they float loose. Hide them: the hose bodies themselves travel with their arm segments.
    _m.cmd("browser.visibility", visible=False, folder="sketches")


def shot(path, camera):
    _m.tool("screenshot", camera=camera, width=W, height=H, grid=False, axes=False, path=path)


def lerp(a, b, t):
    return a + (b - a) * t


def assemble_frame(i):
    global _shown
    t = i / (A_FRAMES - 1)
    n = len(ASSEMBLY_ORDER)
    moves = []
    for k, occ in enumerate(ASSEMBLY_ORDER):
        start = k * 0.45 / (n - 1)
        p = ease_out((t - start) / 0.55)
        f = EXPLODE_K * (ARM_SCALE if occ in ARM else 1.0) * (1 - p)
        moves.append({"occurrence": occ, "translate": [c * f for c in _base[occ]]})
    z = smooth(t)
    cam = {
        "target": [lerp(EXPLODED["target"][j], ASSEMBLED["target"][j], z) for j in range(3)],
        "distance": lerp(EXPLODED["distance"], ASSEMBLED["distance"], z),
        "yaw": lerp(0.6, HOLD_YAW, z),
        "pitch": lerp(0.40, PITCH, z),
    }
    out = os.path.join(FRAMES, f"a_{i + 1:04d}.png")
    if t >= 1.0:
        _m.cmd("explode.show", view="none"); _shown = False
    else:
        name = f"f{i}"
        view = _m.cmd("explode.create", name=name, moves=moves)["view"]
        _m.cmd("explode.show", view=view); _shown = True
        shot(out, cam)
        _m.cmd("explode.show", view="none"); _m.cmd("explode.delete", view=view)
        return out
    shot(out, cam)
    return out


def orbit_frame(i):
    t = i / (B_FRAMES - 1)
    z = smooth(t)
    cam = {
        "target": ASSEMBLED["target"],
        "distance": ASSEMBLED["distance"],
        "yaw": HOLD_YAW + 2 * math.pi * z,
        "pitch": PITCH + 0.10 * math.sin(2 * math.pi * z),
    }
    out = os.path.join(FRAMES, f"b_{i + 1:04d}.png")
    shot(out, cam)
    return out


def hold_frames(_):
    cam = {"target": ASSEMBLED["target"], "distance": ASSEMBLED["distance"], "yaw": HOLD_YAW, "pitch": PITCH}
    shot(os.path.join(FRAMES, "hold_full.png"), cam)
    paths = [[o] for o in ARM]
    _m.cmd("browser.visibility", visible=False, paths=paths)
    shot(os.path.join(FRAMES, "hold_hide.png"), cam)
    _m.cmd("browser.visibility", visible=True, paths=paths)
    return "hold"


def job(j):
    kind, i = j
    return {"a": assemble_frame, "b": orbit_frame, "h": hold_frames}[kind](i)


if __name__ == "__main__":
    os.makedirs(FRAMES, exist_ok=True)
    only = os.environ.get("ONLY", "hab")      # e.g. ONLY=a re-renders just the assembly phase
    jobs = ([("h", 0)] if "h" in only else []) + [("a", i) for i in range(A_FRAMES) if "a" in only] \
        + [("b", i) for i in range(B_FRAMES) if "b" in only]
    with Pool(WORKERS, initializer=init) as pool:
        for n, r in enumerate(pool.imap_unordered(job, jobs), 1):
            if n % 10 == 0 or n == len(jobs):
                print(f"{n}/{len(jobs)}", flush=True)
