"""House colours for the Blender scripts, generated from the design tokens file; do not edit by hand.

WKW_HEX: teal scale B as hex without the hash (keys as used in szene_bausteine.py). WKW: the same steps in linear
colour space (sRGB converted to linear, for Base Color and Emission). OKABE_ITO and TEXT follow the same pattern.
There is no step 950: scale B ends at 900 (#022b2f), and gradients use 900 as their darkest tone.
"""

WKW_HEX = {"900": "022b2f", "800": "024045", "700": "025a62", "600": "037780", "500": "0a8189", "400": "4cc4c4", "300": "80d8d8", "200": "b4eaea", "100": "d8f6f6", "50": "f0fcfc"}
WKW = {"900": (0.00061, 0.02416, 0.02843), "800": (0.00061, 0.05127, 0.05951), "700": (0.00061, 0.10224, 0.12214), "600": (0.00091, 0.18447, 0.21586), "500": (0.00304, 0.21953, 0.25016), "400": (0.07227, 0.55201, 0.55201), "300": (0.21586, 0.68669, 0.68669), "200": (0.45641, 0.82279, 0.82279), "100": (0.68669, 0.92158, 0.92158), "50": (0.87137, 0.97345, 0.97345)}
OKABE_ITO_HEX = {"orange": "e69f00", "sky_blue": "56b4e9", "bluish_green": "009e73", "yellow": "f0e442", "blue": "0072b2", "vermillion": "d55e00", "reddish_purple": "cc79a7"}
OKABE_ITO = {"orange": (0.7913, 0.3467, 0.0), "sky_blue": (0.09306, 0.45641, 0.81485), "bluish_green": (0.0, 0.34191, 0.17144), "yellow": (0.87137, 0.77582, 0.05448), "blue": (0.0, 0.16827, 0.4452), "vermillion": (0.66539, 0.11193, 0.0), "reddish_purple": (0.60383, 0.1912, 0.38643)}
TEXT_HEX = {"white": "ffffff", "ink": "231f20", "text_muted": "3a4649", "text_quiet": "56696e"}
TEXT = {"white": (1.0, 1.0, 1.0), "ink": (0.01681, 0.0137, 0.01444), "text_muted": (0.04231, 0.06125, 0.06663), "text_quiet": (0.09306, 0.14126, 0.15593)}
SIGNAL_HEX = "d7263d"
SIGNAL = (0.67954, 0.01938, 0.04667)
FONT_SANS = "Open Sans"
FONT_SANS_FILE = "Kommunikation/Website/2026-10-15_Corporate_Design/_fonts_raw/OpenSans[wdth,wght].ttf"  # relative to the repository root

# Space scene: extra colours, light, emission, material and shape values. Colours are linear, numbers as in the
# token source; the values are provisional.
PAPER_HEX = "f7f4ec"
PAPER = (0.93011, 0.90466, 0.8388)
PARCHMENT_HEX = "ece0c4"
PARCHMENT = (0.8388, 0.7454, 0.55201)
SPACE_HEX = "050a0d"
SPACE = (0.00152, 0.00304, 0.00402)
STEEL_HEX = {"100": "eef2f3", "300": "c4cdcf", "500": "8a999d", "700": "56696e", "900": "3a4649"}
STEEL = {"100": (0.85499, 0.88792, 0.89627), "300": (0.55201, 0.6105, 0.62396), "500": (0.25415, 0.31855, 0.33716), "700": (0.09306, 0.14126, 0.15593), "900": (0.04231, 0.06125, 0.06663)}
GLOW_HEX = {"core": "40e8ec", "halo": "d8f6f6"}
GLOW = {"core": (0.05127, 0.80695, 0.8388), "halo": (0.68669, 0.92158, 0.92158)}
LIGHT = {"warm": {"color": (1.0, 0.71569, 0.43415)}, "cool": {"color": (0.87137, 0.97345, 0.97345)}, "sun": {"color": (1.0, 0.92158, 0.80695), "strength_day": 4.0}, "ambient": {"color": (0.55201, 0.6105, 0.62396), "strength_night": 0.4, "strength_day": 1.0}}
EMISSION = {"hint": 0.5, "lamp": 3.0, "source": 15.0, "bloom": 0.3}
MATERIAL = {"glass": {"color": (0.68669, 0.92158, 0.92158), "alpha_hull": 0.15, "alpha_room": 0.35, "roughness": 0.05}, "glass_dark": {"color": (0.00061, 0.02416, 0.02843), "roughness": 0.1}, "mirror": {"color": (0.85499, 0.88792, 0.89627), "metallic": 1.0, "roughness": 0.05}, "steel": {"metallic": 0.6, "roughness": 0.4}, "solar": {"color": (0.00061, 0.02416, 0.02843), "metallic": 0.6, "roughness": 0.25}, "copper": {"color": (0.47932, 0.17144, 0.0331), "metallic": 1.0, "roughness": 0.3}, "screen": {"background": (0.00061, 0.02416, 0.02843), "text": (0.68669, 0.92158, 0.92158)}, "whiteboard": {"color": (1.0, 1.0, 1.0)}, "book_cover": {"color": (0.00061, 0.05127, 0.05951), "frame": (0.07227, 0.55201, 0.55201), "lettering": (0.8388, 0.7454, 0.55201)}, "plaster": {"color": (0.93011, 0.90466, 0.8388)}, "nature": {"ground": (0.39676, 0.48515, 0.36131), "foliage": (0.11193, 0.3467, 0.17144), "bark": (0.14703, 0.10224, 0.07619)}, "texture_tint": (1.0, 1.0, 1.0)}
SHAPE = {"hex_rotation_hub": 0, "hex_rotation_comb": 30, "bevel_box": 0.012, "bevel_small": 0.003, "card_radius_ratio": 0.025}
