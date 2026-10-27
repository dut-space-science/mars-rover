"""Replace the rover's SolidCraft side badges with DUT badges, through the MCP server.

The graphic is traced (by eye) from the DUT logo image: a stepped mark of six right triangles, the letters DUT,
a rule, and the two lines "DURBAN UNIVERSITY OF TECHNOLOGY" / "INYUVESI YASETHEKWINI YEZOBUCHWEPHESHE" - white,
raised, on a purple plate. It is described in the image's own pixel coordinates (IMG_*) and scaled into the plate.

Usage: python3 -I build_badge.py IN.solidcraft OUT.solidcraft WORKDIR
"""
import json, os, sys
from PIL import ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mcpclient import SolidCraftMCP

IN, OUT, WORK = sys.argv[1:4]
OLD_COMPONENT = 3352                       # "Project wordmark" (the SolidCraft badges)
WALL_Y, ZC = 63.0, 123.5                   # tub side wall, centre of the wall's height (tub z 105..142)
PLATE_W, PLATE_H, PLATE_T, RAISE = 52.0, 35.0, 3.0, 0.5
PLATE_COLOUR, WHITE = "#276848", "#f5f5fa"          # the rover's own green (service strips, arm links, PCBs)
FONT_FILE = "/usr/share/fonts/truetype/open-sans/OpenSans-CondBold.ttf"      # only used to measure widths here
FONT_FAMILY = "Open Sans Condensed"

# --- the logo, in the image's pixel space (x right, y down) ---------------------------------------------------
IMG_CX, IMG_CY, IMG_W = 176.0, 127.0, 322.0           # centre of the lockup and its width (x 15..337, y 33..221)
S = (PLATE_W - 8.0) / IMG_W                            # mm per image pixel
TRI_COLS = {0: [0, 1, 2], 1: [1, 2], 2: [2]}           # inverted staircase: row -> columns present


def px(x, y):
    return [round((x - IMG_CX) * S, 4), round((IMG_CY - y) * S, 4)]


def triangles():
    for r, cols in TRI_COLS.items():
        for c in cols:
            x0, y0 = 15 + 40 * c, 33 + 37 * r
            yield [px(x0, y0), px(x0 + 35, y0), px(x0 + 35, y0 + 33)]          # right angle at the top-right


def letters():
    def at(ox, pts):
        return [px(ox + x, 33 + y) for x, y in pts]
    D = at(153, [(0, 0), (30, 0), (55, 25), (55, 85), (30, 110), (0, 110)])
    D_hole = at(153, [(21, 22), (31, 22), (34, 26), (34, 84), (31, 88), (21, 88)])
    U = at(218, [(0, 0), (21, 0), (21, 80), (25, 88), (30, 88), (34, 80), (34, 0), (55, 0), (55, 92), (42, 110), (13, 110), (0, 92)])
    T = at(283, [(0, 0), (55, 0), (55, 21), (38, 21), (38, 110), (17, 110), (17, 21), (0, 21)])
    return [D, D_hole, U, T]


RULE = [px(15, 196), px(337, 196), px(337, 199), px(15, 199)]
LINES = [("DURBAN UNIVERSITY OF TECHNOLOGY", 190), ("INYUVESI YASETHEKWINI YEZOBUCHWEPHESHE", 221)]   # text, baseline y
CAP_PX = 12.4          # a little smaller than the image so letters never touch (touching glyphs merge into one profile)


def letter_spacing(text):
    """Extra mm between letters so the line is exactly as wide as the lockup."""
    cap_mm = CAP_PX * S
    f = ImageFont.truetype(FONT_FILE, 1000)
    em = cap_mm / 0.714                                  # Open Sans cap height is 0.714 em
    natural = f.getlength(text) / 1000 * em
    return (IMG_W * S - natural) / (len(text) - 1)


def frame(side, depth):
    """Sketch frame on the wall `depth` mm out, facing outward on that side so text reads left-to-right from outside.
    side -1: normal -Y (x_dir +X); side +1: normal +Y (x_dir -X)."""
    return {"origin": [0, side * depth, ZC], "x_dir": [-side, 0, 0], "y_dir": [0, 0, 1]}


def main():
    m = SolidCraftMCP(IN, WORK)
    print("deleted old badges:", m.cmd("component.delete", component=OLD_COMPONENT)["deleted"])
    comp = m.cmd("component.create", name="DUT badge", parent="root", activate=True)
    print("new component", comp)
    names = {"plate": [], "white": []}
    for side in (-1, 1):
        tag = "-1" if side < 0 else "1"
        # plate (sits on the tub wall, proud of the service strip)
        m.cmd("sketch.create", plane=frame(side, WALL_Y))
        m.cmd("sketch.rectangle.two_point", p0=[-PLATE_W / 2, -PLATE_H / 2], p1=[PLATE_W / 2, PLATE_H / 2])
        m.cmd("sketch.finish")
        names["plate"] += m.cmd("solid.extrude", distance=PLATE_T, operation="new", body_name=f"DUT badge plate {tag}")["created_bodies"]

        # white mark + letters + rule
        m.cmd("sketch.create", plane=frame(side, WALL_Y + PLATE_T))
        for poly in [*triangles(), *letters(), RULE]:
            m.cmd("sketch.line", points=poly, closed=True)
        m.cmd("sketch.finish")
        names["white"] += m.cmd("solid.extrude", distance=RAISE, operation="new", body_name=f"DUT badge mark {tag}")["created_bodies"]

        # the two text lines
        m.cmd("sketch.create", plane=frame(side, WALL_Y + PLATE_T))
        for text, base in LINES:
            ls = letter_spacing(text)
            u, v = px(15, base)
            m.cmd("sketch.text", text=text, at=[u, v], height=round(CAP_PX * S, 4), font=FONT_FAMILY, bold=True, align="left", letter_spacing=round(ls, 4))
            print(f"side {tag} text {text[:12]} spacing {ls:.3f}")
        m.cmd("sketch.finish")
        names["white"] += m.cmd("solid.extrude", distance=RAISE, operation="new", body_name=f"DUT badge text {tag}")["created_bodies"]

    print("bodies: plates", len(names["plate"]), "white", len(names["white"]))
    m.cmd("appearance.assign", bodies=names["plate"], color=PLATE_COLOUR)
    m.cmd("appearance.assign", bodies=names["white"], color=WHITE)
    json.dump(names, open(os.path.join(WORK, "badge_bodies.json"), "w"))
    m.tool("save", path=OUT)
    print("saved", OUT)
    m.close()


main()
