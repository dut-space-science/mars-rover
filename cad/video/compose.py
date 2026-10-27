"""Composite the 2D storytelling onto the raw MCP renders and encode the videos.

Every video is   intro  +  outro:
  intro   assemble (a_####.png) then a 360 degree orbit (b_####.png)      - shared, encoded once
  outro   glide to the group's view -> hold -> a thin box draws round the group -> the group is highlighted
          -> a leader line leaves one corner of the box -> the label card expands out of the end of the line

Style: green accent, sharp corners, monospace type, thin lines.

Usage:
  python3 -I compose.py WORKDIR intro
  python3 -I compose.py WORKDIR build OUTDIR [slug ...]     (slug "arm" = the robotic arm; none = all groups + arm)
"""
import json, math, os, subprocess, sys
from multiprocessing import Pool
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sceneops import group_mask, drop_specks
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

FPS = 30
A_N, B_N = 150, 180
HOLD_N_ARM, HOLD_N = 60, 45
BOX_N, FADE_N, PAUSE_N, LINE_N, CARD_N, END_N = 20, 20, 6, 24, 22, 80
GLIDE_N = 36
XFADE_N = 14

ARM = {"title": "ROBOTIC ARM", "sub": "5 COMPONENTS // HYDRAULICS + CABLING"}
TAG = "> GROUP SELECTED"
GREEN = (0, 230, 118)
DARK = (7, 12, 10)
MUTED = (150, 190, 170)
SS = 2
FONT_DIR = "/usr/share/fonts/truetype/liberation/"


def font(size, bold=False):
    return ImageFont.truetype(FONT_DIR + ("LiberationMono-Bold.ttf" if bold else "LiberationMono-Regular.ttf"), size)


def smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def ffmpeg_png_to_mp4(patterns, out):
    """Encode one or more numbered PNG sequences (in order) into an H.264 file."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for p in patterns:
        cmd += ["-framerate", str(FPS), "-i", p]
    if len(patterns) > 1:
        cmd += ["-filter_complex", f"concat=n={len(patterns)}:v=1:a=0"]
    cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS), out]
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------- the highlighted scene
class Scene:
    """The hold view of one group: its pixel mask and the highlight / ghost compositing."""

    def __init__(self, full_path, iso_path):
        full = Image.open(full_path).convert("RGB")
        self.W, self.H = full.size
        diff = group_mask(full_path, iso_path)
        m = Image.fromarray((diff * 255).astype(np.uint8))
        m = m.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))          # close pinholes
        m = m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))          # drop specks
        self.mask = drop_specks(np.asarray(m) > 127)
        m = Image.fromarray((self.mask * 255).astype(np.uint8))
        if not self.mask.any():
            raise SystemExit(f"{full_path}: the group is not visible in this view")
        self.pre = Image.open(os.path.join(os.path.dirname(full_path), "hold_pre.png")).convert("RGB") if os.path.exists(os.path.join(os.path.dirname(full_path), "hold_pre.png")) else None
        ys, xs = np.nonzero(self.mask)
        self.bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
        self.soft = np.asarray(m.filter(ImageFilter.GaussianBlur(1.0)), np.float32)[..., None] / 255
        ring = np.asarray(m.filter(ImageFilter.MaxFilter(9)), np.float32) - np.asarray(m.filter(ImageFilter.MinFilter(3)), np.float32)
        ring = Image.fromarray(np.clip(ring, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))
        self.ring = np.asarray(ring, np.float32)[..., None] / 255
        glow = np.asarray(m.filter(ImageFilter.GaussianBlur(16)), np.float32)[..., None] / 255
        self.glow = np.clip(glow * 1.6, 0, 1) * (1 - self.soft)
        self.full_img = full
        self.full = np.asarray(full, np.float32)
        gray = self.full.mean(axis=2, keepdims=True).repeat(3, axis=2)
        self.ghost = (0.55 * self.full + 0.45 * gray) * 0.45 + 236 * 0.55
        self.acc = np.array(GREEN, np.float32)
        # where the rover is (not backdrop): the label should avoid covering it
        a = np.asarray(full, np.int16)
        edge = np.concatenate([a[:, :4], a[:, -4:]], axis=1)
        bg = np.median(edge, axis=1)[:, None, :]
        self.busy = np.abs(a - bg).sum(axis=2) > 24

    def highlight(self, h, pulse=0.0):
        a = smooth(h)
        img = self.full * (1 - a * (1 - self.soft)) + self.ghost * (a * (1 - self.soft))       # ghost the rest
        img = img * (1 - 0.12 * a * self.soft) + self.acc * (0.12 * a * self.soft)               # tint the group
        g = 0.65 + 0.2 * pulse
        img = img * (1 - self.glow * g * a) + self.acc * (self.glow * g * a)
        img = img * (1 - self.ring * a) + self.acc * (self.ring * a)
        return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


# ---------------------------------------------------------------- overlay drawing (2x, then reduced)
class Overlay:
    def __init__(self, scene, title, sub):
        self.s = scene
        self.W, self.H = scene.W, scene.H
        self.f_t, self.f_s, self.f_tag = font(44 * SS, True), font(24 * SS), font(22 * SS, True)
        d = ImageDraw.Draw(self.new())
        self.bw = int(max(d.textlength(title, font=self.f_t), d.textlength(sub, font=self.f_s)) / SS + 76)
        self.bh = 118
        self.title, self.sub = title, sub
        x0, y0, x1, y1 = scene.bbox
        pad = 26
        self.R = (max(10, x0 - pad), max(10, y0 - pad), min(self.W - 10, x1 + pad), min(self.H - 10, y1 + pad))
        self.layout = self.solve_layout()

    def new(self):
        return Image.new("RGBA", (self.W * SS, self.H * SS), (0, 0, 0, 0))

    # -- where the label goes -------------------------------------------------------------
    def solve_layout(self):
        W, H, bw, bh = self.W, self.H, self.bw, self.bh
        x0, y0, x1, y1 = self.R
        cands = []
        for side in (1, -1):                      # leader leaves a corner diagonally, then runs level into the card
            for vert in (1, -1):
                cx, cy = (x1 if side == 1 else x0), (y1 if vert == 1 else y0)
                elbow = (cx + side * 55, cy + vert * 55)
                end = (elbow[0] + side * 36, elbow[1])
                cx0 = end[0] if side == 1 else end[0] - bw
                cands.append(dict(pts=[(cx, cy), elbow, end], card=(cx0, end[1] - bh / 2), attach=end,
                                  frac=(0.0 if side == 1 else 1.0, 0.5), corner=(side, vert), kind="side"))
        for vert in (1, -1):                      # leader drops straight from a corner onto the card's edge
            for side in (1, -1):
                cx, cy = (x1 if side == 1 else x0), (y1 if vert == 1 else y0)
                end = (cx, cy + vert * 70)
                cx0 = min(max(cx - (0.8 if side == 1 else 0.2) * bw, 40), W - 40 - bw)
                cy0 = end[1] if vert == 1 else end[1] - bh
                cands.append(dict(pts=[(cx, cy), end], card=(cx0, cy0), attach=end,
                                  frac=((cx - cx0) / bw, 0.0 if vert == 1 else 1.0), corner=(side, vert), kind="drop"))
        best, best_cost = None, None
        for k, c in enumerate(cands):
            cx0, cy0 = c["card"]
            if cx0 < 40 or cy0 < 40 or cx0 + bw > W - 40 or cy0 + bh > H - 40:
                continue
            if not (cx0 + bw < x0 - 12 or cx0 > x1 + 12 or cy0 + bh < y0 - 12 or cy0 > y1 + 12):
                continue                           # would sit on the selection box
            cost = int(self.s.busy[int(cy0):int(cy0 + bh), int(cx0):int(cx0 + bw)].sum()) + 40 * k
            if best_cost is None or cost < best_cost:
                best, best_cost = c, cost
        if best is None:
            raise SystemExit("no room for the label")
        return best

    # -- primitives -----------------------------------------------------------------------
    def line(self, d, pts, width, alpha=255):
        flat = [(x * SS, y * SS) for x, y in pts]
        d.line(flat, fill=DARK + (int(alpha * 0.75),), width=int((width + 3) * SS), joint="curve")
        d.line(flat, fill=GREEN + (alpha,), width=int(width * SS), joint="curve")

    def box(self, d, p):
        """Thin selection rectangle, drawn clockwise from its top-left corner up to fraction p."""
        x0, y0, x1, y1 = self.R
        loop = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        lens = [math.dist(loop[i], loop[i + 1]) for i in range(4)]
        left, path = p * sum(lens), [loop[0]]
        for i in range(4):
            if left <= 0: break
            f = min(1.0, left / lens[i])
            path.append((loop[i][0] + (loop[i + 1][0] - loop[i][0]) * f, loop[i][1] + (loop[i + 1][1] - loop[i][1]) * f))
            left -= lens[i]
        if len(path) > 1:
            self.line(d, path, 2)

    def tag(self, d, alpha):
        if alpha <= 0: return
        x0, y0, x1, y1 = self.R
        side, vert = self.layout["corner"]
        tw = d.textlength(TAG, font=self.f_tag) / SS + 24
        on_top = not (vert == -1 and self.layout["kind"] == "drop")             # keep clear of an upward leader
        tx = x0 if side == 1 else x1 - tw                                         # opposite end to the leader
        ty = (y0 - 34) if on_top else y1
        ty = max(6, min(self.H - 40, ty))
        a = int(255 * alpha)
        d.rectangle([tx * SS, ty * SS, (tx + tw) * SS, (ty + 34) * SS], fill=DARK + (int(225 * alpha),))
        d.text(((tx + 12) * SS, (ty + 5) * SS), TAG, font=self.f_tag, fill=GREEN + (a,))

    def leader(self, d, p):
        pts = self.layout["pts"]
        lens = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        left, path = p * sum(lens), [pts[0]]
        for i, L in enumerate(lens):
            if left <= 0: break
            f = min(1.0, left / L)
            path.append((pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f))
            left -= L
        self.line(d, path, 2.5)
        cx, cy = pts[0]
        r = 5                                                                   # small square where the line leaves the box
        d.rectangle([(cx - r - 2) * SS, (cy - r - 2) * SS, (cx + r + 2) * SS, (cy + r + 2) * SS], fill=DARK + (230,))
        d.rectangle([(cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS], fill=GREEN + (255,))

    def card(self, lay, q):
        """The label card grows out of the end of the leader: wide bar first, then it opens downward."""
        s1, s2 = smooth(q / 0.55), smooth((q - 0.4) / 0.6)
        w, h = self.bw * s1, 3 + (self.bh - 3) * s2
        ax, ay = self.layout["attach"]
        fx, fy = self.layout["frac"]
        x0, y0 = ax - fx * w, ay - fy * h
        x1, y1 = x0 + w, y0 + h
        d = ImageDraw.Draw(lay)
        d.rectangle([x0 * SS, y0 * SS, x1 * SS, y1 * SS], fill=DARK + (int(240 * min(1.0, s2 * 1.5)),), outline=GREEN + (255,), width=2 * SS)
        if s2 > 0.45:                                                           # text, clipped to the growing card
            cx0, cy0 = self.layout["card"]
            txt = self.new()
            td = ImageDraw.Draw(txt)
            a = int(255 * smooth((s2 - 0.45) / 0.55))
            td.text(((cx0 + 34) * SS, (cy0 + 14) * SS), self.title, font=self.f_t, fill=GREEN + (a,))
            td.text(((cx0 + 34) * SS, (cy0 + 76) * SS), self.sub, font=self.f_s, fill=MUTED + (a,))
            clip = Image.new("L", txt.size, 0)
            ImageDraw.Draw(clip).rectangle([(x0 + 2) * SS, (y0 + 2) * SS, (x1 - 2) * SS, (y1 - 2) * SS], fill=255)
            txt.putalpha(ImageChops.multiply(txt.getchannel("A"), clip))
            lay.alpha_composite(txt)

    def flatten(self, base, lay):
        lay = lay.resize((self.W, self.H), Image.LANCZOS)
        return Image.alpha_composite(base.convert("RGBA"), lay).convert("RGB")


# ---------------------------------------------------------------- one video's outro
def build(task):
    work, outdir, slug = task
    survey = json.load(open(os.path.join(work, "survey.json")))
    info = survey[slug]
    src = os.path.join(work, "groups", slug)
    glide = GLIDE_N if info.get("glide", True) else 0
    hold_n = HOLD_N if glide else HOLD_N_ARM
    out_name = "rover_robotic-arm.mp4" if slug == "arm" else f"rover_{slug}.mp4"
    scene = Scene(os.path.join(src, "hold_full.png"), os.path.join(src, "hold_iso.png"))
    ov = Overlay(scene, info["title"], info["sub"])
    fdir = os.path.join(work, "final", slug)
    os.makedirs(fdir, exist_ok=True)
    for f in os.listdir(fdir):
        os.remove(os.path.join(fdir, f))

    seq = [("img", os.path.join(src, f"glide_{i + 1:04d}.png")) for i in range(glide)]
    if scene.pre is not None:                                                      # cutaway / un-hide: dissolve into it
        seq += [("xfade", (i + 1) / XFADE_N) for i in range(XFADE_N)]
    seq += [("hold",)] * hold_n
    seq += [("box", (i + 1) / BOX_N) for i in range(BOX_N)]
    seq += [("fade", (i + 1) / FADE_N) for i in range(FADE_N)]
    seq += [("pause", i) for i in range(PAUSE_N)]
    seq += [("line", smooth((i + 1) / LINE_N), i) for i in range(LINE_N)]
    seq += [("card", (i + 1) / CARD_N, i) for i in range(CARD_N)]
    seq += [("end", i) for i in range(END_N)]
    t0 = glide + (XFADE_N if scene.pre is not None else 0) + hold_n + BOX_N + FADE_N                                          # frame index where the highlight is full

    for n, it in enumerate(seq):
        k = it[0]
        lay = ov.new(); d = ImageDraw.Draw(lay)
        breathe = lambda j: math.sin(2 * math.pi * j / 40)
        if k == "img":
            base = Image.open(it[1]).convert("RGB")
        elif k == "xfade":
            base = Image.blend(scene.pre, scene.full_img, smooth(it[1]))
        elif k == "hold":
            base = scene.full_img
        elif k == "box":
            base = scene.full_img
            ov.box(d, smooth(it[1])); ov.tag(d, smooth((it[1] - 0.6) / 0.4))
        elif k == "fade":
            base = scene.highlight(it[1]); ov.box(d, 1.0); ov.tag(d, 1.0)
        elif k == "pause":
            base = scene.highlight(1.0, breathe(it[1])); ov.box(d, 1.0); ov.tag(d, 1.0)
        elif k == "line":
            base = scene.highlight(1.0, breathe(n - t0)); ov.box(d, 1.0); ov.tag(d, 1.0); ov.leader(d, it[1])
        elif k == "card":
            base = scene.highlight(1.0, breathe(n - t0)); ov.box(d, 1.0); ov.tag(d, 1.0); ov.leader(d, 1.0); ov.card(lay, it[1])
        else:
            base = scene.highlight(1.0, breathe(n - t0)); ov.box(d, 1.0); ov.tag(d, 1.0); ov.leader(d, 1.0); ov.card(lay, 1.0)
        ov.flatten(base, lay).save(os.path.join(fdir, f"{n + 1:04d}.png"))

    outro = os.path.join(work, f"outro_{slug}.mp4")
    ffmpeg_png_to_mp4([os.path.join(fdir, "%04d.png")], outro)
    listing = os.path.join(work, f"concat_{slug}.txt")
    open(listing, "w").write(f"file '{os.path.join(work, 'intro.mp4')}'\nfile '{outro}'\n")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, out_name)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy",
                    "-movflags", "+faststart", out], check=True)
    for f in os.listdir(fdir):
        os.remove(os.path.join(fdir, f))
    print(f"{slug}: {out}  card {ov.layout['kind']} {ov.layout['corner']}", flush=True)
    return out


if __name__ == "__main__":
    work, mode = sys.argv[1], sys.argv[2]
    if mode == "intro":
        fr = os.path.join(work, "frames")
        ffmpeg_png_to_mp4([os.path.join(fr, "a_%04d.png"), os.path.join(fr, "b_%04d.png")], os.path.join(work, "intro.mp4"))
        print("intro.mp4")
    else:
        outdir, slugs = sys.argv[3], sys.argv[4:]
        if not slugs:
            slugs = ["arm"] + [k for k in json.load(open(os.path.join(work, "survey.json"))) if k != "arm"]
        with Pool(min(6, len(slugs))) as pool:
            for _ in pool.imap_unordered(build, [(work, outdir, s) for s in slugs]):
                pass
