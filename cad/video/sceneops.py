"""Visibility operations shared by survey.py and render_groups.py (all through the MCP `browser.visibility` command).

Every op is one undo step, so a caller counts the ops it applied and rewinds exactly those.
"""
import numpy as np
from PIL import Image


def prep(m, g):
    """Make the group visible from outside: un-hide design-hidden bodies, lift occluders (cutaway). Returns ops applied."""
    n = 0
    if g.get("show_bodies"):
        m.cmd("browser.visibility", visible=True, items=g["show_bodies"]); n += 1
    if g.get("exclude_bodies"):
        m.cmd("browser.visibility", visible=False, items=g["exclude_bodies"]); n += 1
    if g.get("cutaway"):
        m.cmd("browser.visibility", visible=False, paths=[[o] for o in g["cutaway"]]); n += 1
    return n


def isolate(m, g):
    """Show only the group (minus its excluded bodies). Returns the ops applied, for rewind()."""
    m.cmd("browser.visibility", visible=True, paths=[[o] for o in g["occ"]], isolate=True)
    if g.get("exclude_bodies"):
        m.cmd("browser.visibility", visible=False, items=g["exclude_bodies"])
        return 2
    return 1


def rewind(m, n):
    for _ in range(n):
        m.tool("undo")


def group_mask(full_path, iso_path, tol=48, edge_thr=8):
    """Pixels where the group is what you see: it is in the group-only render (not backdrop) and the full render matches it."""
    a = np.asarray(Image.open(full_path).convert("RGB"), np.int16)
    c = np.asarray(Image.open(iso_path).convert("RGB"), np.int16)
    edge = np.concatenate([c[:, :4], c[:, -4:]], axis=1)
    bg = np.median(edge, axis=1)[:, None, :]
    sil = np.abs(c - bg).sum(axis=2) > edge_thr
    near = np.abs(a - c).sum(axis=2) < tol
    return sil & near


def drop_specks(mask, min_px=60):
    """Remove 8-connected blobs smaller than min_px (stray fragments that would stretch the selection box)."""
    from collections import deque
    h, w = mask.shape
    seen = np.zeros_like(mask, bool)
    keep = np.zeros_like(mask, bool)
    ys, xs = np.nonzero(mask)
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if seen[y0, x0]:
            continue
        blob, q = [], deque([(y0, x0)])
        seen[y0, x0] = True
        while q:
            y, x = q.popleft()
            blob.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        q.append((ny, nx))
        if len(blob) >= min_px:
            for y, x in blob:
                keep[y, x] = True
    return keep
