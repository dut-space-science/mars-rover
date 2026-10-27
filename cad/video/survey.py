"""Pick, for every group, the viewpoint from which most of it is visible.

For each candidate camera: render with the group shown and hidden; the pixel difference is the
part of the group that is actually visible from there. Writes WORK/survey.json.

Usage: python3 -I survey.py WORKDIR [WORKERS]
"""
import json, math, os, re, sys
from multiprocessing import Pool
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mcpclient import SolidCraftMCP
from groups import GROUPS
from sceneops import prep, isolate, rewind, group_mask

WORK = sys.argv[1]
WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
ONLY = sys.argv[3:]
DESIGN = os.path.join(WORK, os.environ.get("ROVER_DESIGN", "rover.solidcraft"))
SW, SH = 960, 540
YAWS = [0.8 + k * math.pi / 4 for k in range(8)]
PITCHES = [0.45, 0.95, -0.35]
_m = None


def init():
    global _m
    _m = SolidCraftMCP(DESIGN, WORK)
    _m.cmd("browser.visibility", visible=False, folder="sketches")


def camera_for(g):
    lo, hi = g["bbox"]
    c = [(a + b) / 2 for a, b in zip(lo, hi)]
    diag = math.dist(lo, hi)
    return c, g.get("distance") or min(900, max(330, diag * 1.9))


def survey_group(g):
    """Render every candidate camera with the group in place and alone; keep how much of it is visible."""
    n = prep(_m, g)
    target, dist = camera_for(g)
    a, b = os.path.join(WORK, f"_s_{g['slug']}_a.png"), os.path.join(WORK, f"_s_{g['slug']}_b.png")
    rows = []
    views = [(g["fixed_view"]["pitch"], g["fixed_view"]["yaw"])] if g.get("fixed_view") else [(p, y) for p in PITCHES for y in YAWS]
    for pitch, yaw in views:
        if True:
            cam = {"target": target, "distance": dist, "yaw": yaw, "pitch": pitch}
            _m.tool("screenshot", camera=cam, width=SW, height=SH, grid=False, axes=False, path=a)
            k = isolate(_m, g)
            _m.tool("screenshot", camera=cam, width=SW, height=SH, grid=False, axes=False, path=b)
            rewind(_m, k)
            d = group_mask(a, b)
            ys, xs = np.nonzero(d)
            rows.append({"yaw": yaw, "pitch": pitch, "area": int(d.sum()),
                         "bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if len(xs) else None})
    rewind(_m, n)
    return g["slug"], rows


if __name__ == "__main__":
    m = SolidCraftMCP(DESIGN, WORK)
    groups = []
    for g in GROUPS:
        if ONLY and g["slug"] not in ONLY:
            continue
        lo, hi = [1e9] * 3, [-1e9] * 3
        for o in g["occ"]:
            props = m.cmd("occurrence.properties", occurrence=o)
            if g.get("exclude_regex"):                                   # bounding box of the bodies that stay
                boxes = [b["bbox"] for b in props["bodies"] if not re.match(g["exclude_regex"], b["name"])]
                tmin = [min(b["min"][k] for b in boxes) for k in range(3)]
                tmax = [max(b["max"][k] for b in boxes) for k in range(3)]
            else:
                tmin, tmax = props["total"]["bbox"]["min"], props["total"]["bbox"]["max"]
            lo = [min(a, b) for a, b in zip(lo, tmin)]
            hi = [max(a, b) for a, b in zip(hi, tmax)]
        groups.append({**g, "bbox": [lo, hi]})
        print(g["slug"], [round(v) for v in lo], [round(v) for v in hi], flush=True)
    comps = {c["id"]: c for c in m.cmd("component.list", compact=True, bodies=True)["components"]}
    for g in groups:
        if g.get("show_component"):
            g["show_bodies"] = comps[g["show_component"]]["bodies"]
        if g.get("names_component"):
            g["exclude_bodies"] = [n for n in comps[g["names_component"]]["bodies"] if re.match(g["exclude_regex"], n)]
    m.close()
    by = {g["slug"]: g for g in groups}
    results = {}
    with Pool(WORKERS, initializer=init) as pool:
        for slug, rows in pool.imap_unordered(survey_group, groups):
            results[slug] = rows
            print("surveyed", slug, flush=True)
    out = {}
    for slug, rs in results.items():
        ok = []
        for r in rs:
            if r["bbox"] is None: continue
            x0, y0, x1, y1 = r["bbox"]
            margin = 18
            if not by[slug].get("fixed_view") and (x0 < margin or y0 < margin or x1 > SW - margin or y1 > SH - margin): continue   # cut off by the frame
            ok.append({**r, "score": r["area"] * (1.0 if r["pitch"] == 0.45 else 0.92)})
        ok.sort(key=lambda r: -r["score"])
        target, dist = camera_for(by[slug])
        out[slug] = {**{k: by[slug][k] for k in ("title", "sub", "occ", "bbox")},
                     **{k: by[slug][k] for k in ("cutaway", "show_bodies", "exclude_bodies") if k in by[slug]},
                     "target": target, "distance": dist, "best": ok[:3]}
        top = ok[0] if ok else None
        print(f"{slug:15s} dist {dist:4.0f}  best " + (f"yaw {top['yaw']:.2f} pitch {top['pitch']:.2f} area {top['area']}px" if top else "NONE VISIBLE"))
    path = os.path.join(WORK, "survey.json")
    merged = json.load(open(path)) if ONLY and os.path.exists(path) else {}
    merged.update(out)
    json.dump(merged, open(path, "w"), indent=1)
