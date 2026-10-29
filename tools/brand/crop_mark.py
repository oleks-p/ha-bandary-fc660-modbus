"""Crop the sun-and-B mark out of the Bandary wordmark into square brand icons.

The source is the wordmark (734 x 232 PNG) in the header of
https://www.bandaryhome.com/en/heat-pump-thermostat, the largest one the site
serves; the 32 px favicon is the whole wordmark and unreadable as an icon.

    curl -sLo logo.png <the header logo's URL>
    python3 tools/brand/crop_mark.py logo.png custom_components/bandary_fc660_modbus/brand

The sun's rays reach over the gap between "B" and "a", so the cut is made on
the letters' rows only, and to the right of it the blue (letter) pixels are
dropped while the warm (sun) pixels stay.
"""
import sys

from PIL import Image

src, out_dir = sys.argv[1], sys.argv[2]
img = Image.open(src).convert("RGBA")
w, h = img.size
px = img.load()

def is_blue(p):
    r, g, b, a = p
    return a > 40 and b > r + 40

# Letter rows: where the letters are, below the sun.
letter_rows = [y for y in range(h) if sum(is_blue(px[x, y]) for x in range(w)) > 20]
top = min(letter_rows) + (max(letter_rows) - min(letter_rows)) // 2
rows = range(top, max(letter_rows) + 1)
blue_cols = [any(is_blue(px[x, y]) for y in rows) for x in range(w)]
start_b = blue_cols.index(True)
end_b = next(x for x in range(start_b, w) if not blue_cols[x])     # first column after "B"
print("B spans", start_b, "..", end_b - 1)
for x in range(end_b, w):
    for y in range(h):
        if is_blue(px[x, y]) or (px[x, y][3] > 0 and not (px[x, y][0] > 150)):
            px[x, y] = (0, 0, 0, 0)
mark = img.crop(img.getbbox())
print("mark size", mark.size)
side = max(mark.size)
pad = round(side * 0.06)
canvas = Image.new("RGBA", (side + 2 * pad, side + 2 * pad), (0, 0, 0, 0))
canvas.paste(mark, (pad + (side - mark.width) // 2, pad + (side - mark.height) // 2), mark)
for size, name in ((256, "icon.png"), (512, "icon@2x.png")):
    canvas.resize((size, size), Image.LANCZOS).save(f"{out_dir}/{name}", optimize=True)
    print("wrote", name)
