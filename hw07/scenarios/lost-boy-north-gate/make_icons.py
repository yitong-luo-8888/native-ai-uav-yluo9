#!/usr/bin/env python3
"""make_icons.py -- draw this scenario's clue icons (transparent PNGs).

Drawn with lab/lesson7/icon_kit.py at the people icons' scale (~1150 px per
real metre on the 1024 canvas): place each at the same width_m as the boy
(8 m) and it is the right size next to him.

    python make_icons.py     # writes images/navy-cap-grey-front.png,
                             #        images/orange-dino-backpack.png,
                             #        images/navy-knit-beanie.png  (the near miss)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "lab", "lesson7"))

from icon_kit import OUTLINE, SS, blob, canvas, finish, rotated_ellipse, s, shade, texture  # noqa: E402
from PIL import ImageDraw  # noqa: E402

NAVY, NAVY_DARK = (30, 42, 96, 255), (20, 28, 66, 255)
GREY, GREY_DARK = (160, 162, 168, 255), (122, 124, 130, 255)


def cap():
    """Child's navy baseball cap (~18 cm crown, ~7 cm bill), grey front panels, crown up, bill to the south."""
    img = canvas()
    blob(img, "ellipse", s(396, 520, 628, 668), NAVY)                     # bill, under the crown
    ImageDraw.Draw(img).arc(s(410, 532, 614, 656), 25, 155, fill=NAVY_DARK, width=4 * SS)  # bill stitching
    blob(img, "ellipse", s(408, 396, 616, 604), NAVY)                     # crown
    d = ImageDraw.Draw(img)
    d.pieslice(s(408, 396, 616, 604), 30, 150, fill=GREY)                 # two grey front panels
    d.line(s(512, 500, 512, 604), fill=GREY_DARK, width=4 * SS)           # seam between the front panels
    for x0, y0, x1, y1 in ((512, 500, 602, 552), (512, 500, 422, 552), (512, 500, 602, 448),
                           (512, 500, 422, 448), (512, 500, 512, 396)):
        d.line(s(x0, y0, x1, y1), fill=NAVY_DARK if y1 < 500 else GREY_DARK, width=4 * SS)  # panel seams
    for x, y in ((470, 440), (554, 440), (440, 500), (584, 500)):         # eyelets
        d.ellipse(s(x - 5, y - 5, x + 5, y + 5), fill=NAVY_DARK)
    d.ellipse(s(500, 488, 524, 512), fill=OUTLINE)                        # top button
    d.ellipse(s(503, 491, 521, 509), fill=NAVY)
    texture(img, 14, 0.06, seed=11, mark=2)
    shade(img, strength=45)
    finish(img, os.path.join(HERE, "images", "navy-cap-grey-front.png"))


def dinosaur(img, cx, cy, k, green=(56, 150, 62, 255), dark=(30, 96, 40, 255)):
    """A small side-view dinosaur patch centred at (cx, cy), k = scale (1 = ~130 px wide)."""
    def p(*xy):
        return s(*[(cx if i % 2 == 0 else cy) + v * k for i, v in enumerate(xy)])

    d = ImageDraw.Draw(img)
    d.ellipse(p(-62, -40, 66, 40), fill=(238, 226, 190, 255), outline=dark, width=3 * SS)   # patch background
    blob(img, "polygon", p(-46, 8, -10, -6, 26, -2, 34, 14, 10, 22, -24, 20), green, width=3 * SS)  # body + tail
    blob(img, "polygon", p(20, -2, 34, -24, 50, -26, 54, -18, 40, -14, 32, 6), green, width=3 * SS)  # neck + head
    for x in (-24, -10, 4, 18):                                                              # back spikes
        blob(img, "polygon", p(x - 6, -4, x, -16, x + 6, -4), dark, width=2 * SS)
    for x in (-14, 14):                                                                      # legs
        blob(img, "polygon", p(x - 5, 18, x - 5, 32, x + 5, 32, x + 5, 18), green, width=3 * SS)
    d.ellipse(p(43, -23, 47, -19), fill=OUTLINE)                                             # eye


def backpack():
    """Small child's orange backpack (~30 x 24 cm) lying face up, front pocket with a green dinosaur patch."""
    img = canvas()
    orange, orange_dark, strap = (236, 122, 28, 255), (196, 90, 16, 255), (40, 36, 34, 255)
    d = ImageDraw.Draw(img)
    d.arc(s(470, 300, 554, 380), 180, 360, fill=OUTLINE, width=12 * SS)                     # top grab handle
    blob(img, "polygon", s(392, 352, 632, 352, 650, 380, 662, 640, 640, 668, 384, 668, 362, 640, 374, 380),
         orange)                                                                             # main body
    d = ImageDraw.Draw(img)
    d.arc(s(392, 336, 632, 420), 180, 360, fill=orange_dark, width=6 * SS)                  # top zip
    blob(img, "polygon", s(414, 500, 610, 500, 626, 516, 626, 640, 610, 652, 414, 652, 398, 640, 398, 516),
         orange_dark)                                                                        # front pocket
    d = ImageDraw.Draw(img)
    d.line(s(414, 514, 610, 514), fill=OUTLINE, width=3 * SS)                               # pocket zip
    d.rectangle(s(596, 508, 606, 534), fill=(220, 220, 220, 255))                           # zip pull
    for x in (376, 648):                                                                     # strap ends at the sides
        d.rectangle(s(x - 12, 400, x + 12, 470), fill=strap)
    texture(img, 16, 0.05, seed=12, mark=2)
    dinosaur(img, 512, 586, 1.15)
    shade(img, strength=40)
    finish(img, os.path.join(HERE, "images", "orange-dino-backpack.png"))


def beanie():
    """Near miss: adult navy knit beanie with a pompom (~24 cm wide), lying flat. Navy like Ethan's cap, but not a cap."""
    img = canvas()
    blob(img, "ellipse", s(468, 316, 556, 400), NAVY)                     # pompom
    blob(img, "polygon", s(374, 600, 384, 470, 420, 400, 512, 370, 604, 400, 640, 470, 650, 600), NAVY)  # dome
    blob(img, "polygon", s(362, 590, 662, 590, 662, 668, 362, 668), NAVY_DARK)  # folded cuff
    d = ImageDraw.Draw(img)
    for x in range(376, 660, 16):                                         # cuff ribs
        d.line(s(x, 598, x, 660), fill=NAVY, width=4 * SS)
    for x in range(410, 620, 26):                                         # knit columns on the dome
        d.line(s(x, 420 + abs(x - 512) // 4, x, 586), fill=NAVY_DARK, width=3 * SS)
    texture(img, 22, 0.12, seed=13, mark=3)
    shade(img, strength=45)
    finish(img, os.path.join(HERE, "images", "navy-knit-beanie.png"))


if __name__ == "__main__":
    cap()
    backpack()
    beanie()
