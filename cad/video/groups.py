"""The rover's other groups: occurrence ids (component.list), label text, output slug.

Occurrence ids are the placements in SolidCraft Rover.solidcraft.
Flags: "cutaway" = occurrences hidden so an internal group can be seen; "show_component" = a component whose bodies the design
keeps hidden and that must be shown for this group (resolved to body names by survey.py from the live design); "names_component" + "exclude_regex" =
body names of that component to leave out of the group's mask, box and camera;
"fixed_view" / "distance" = use this camera instead of searching for one.
"""
GROUPS = [
    {"slug": "chassis",        "title": "CHASSIS STRUCTURE", "sub": "177 PARTS // ELECTRONICS TUB + FRAME",       "occ": [1930]},
    {"slug": "wheels",         "title": "WHEELS",            "sub": "6 WHEELS // MACHINED CENTRES + TPU TYRES",   "occ": [2162, 2245, 2328, 2411, 2494, 2577]},
    {"slug": "drive-modules",  "title": "DRIVE MODULES",     "sub": "6 MODULES // MOTOR + GEARBOX + SUSPENSION",  "occ": [2109, 2192, 2275, 2358, 2441, 2524]},
    {"slug": "avionics",       "title": "AVIONICS",          "sub": "RASPBERRY PI 5 // CPU COOLER",               "occ": [2607], "cutaway": [2672, 2698]},
    {"slug": "power-bay",      "title": "POWER BAY",         "sub": "18650 CELLS // BATTERY MANAGEMENT",          "occ": [2630], "cutaway": [2672, 2698]},
    {"slug": "service-lid",    "title": "SERVICE LID",       "sub": "BOLTED LID // THERMAL PLATE + RADIATOR",     "occ": [2672]},
    {"slug": "payload-mounts", "title": "PAYLOAD MOUNTS",    "sub": "2 PAYLOAD RAILS",                            "occ": [2698]},
    {"slug": "antennas",       "title": "COMM ANTENNAS",     "sub": "2 WHIP ANTENNAS // RF CONNECTORS",           "occ": [2710]},
    {"slug": "sample-lab",     "title": "SAMPLE LABORATORY","sub": "6 GLASS VIALS // SAMPLE CASSETTE",           "occ": [3020]},
    {"slug": "dish",           "title": "PARABOLIC DISH",    "sub": "REFLECTOR // YAW MOUNT + PIVOT",             "occ": [3142, 3154, 3162]},
    {"slug": "nav-lights",     "title": "NAVIGATION LIGHTS", "sub": "4 MARKER LAMPS",                             "occ": [3173]},
    {"slug": "sensor-mast",    "title": "SENSOR MAST",       "sub": "STEREO CAMERA + SEARCHLIGHTS",               "occ": [3229, 3241, 3257]},
    {"slug": "solar-wings",    "title": "SOLAR WINGS",       "sub": "2 WINGS // 80 PHOTOVOLTAIC TILES",           "occ": [2882, 2951]},
    {"slug": "underbody-leds", "title": "UNDERBODY LEDS",    "sub": "48 LEDS // 2 LIGHT RAILS",                   "occ": [3287]},
    {"slug": "wordmark",       "title": "DUT BADGES",        "sub": "2 SIDE BADGES // RAISED GRAPHIC",             "occ": [3397], "names_component": 3396,
     "exclude_regex": r"^DUT badge (plate|mark|text) 1( |$)",      # the far-side badge: out of the mask, box and camera
     "fixed_view": {"yaw": 0.0, "pitch": 0.12}, "distance": 120},
    {"slug": "service-strips", "title": "SERVICE STRIPS",    "sub": "2 SIDE STRIPS // M3 FIXINGS",                "occ": [2854]},
]
