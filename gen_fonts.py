# gen_fonts.py - workstation-side generator: renders DejaVu glyphs into
# MicroPython font modules for metar-micro. Each glyph is stored as a
# full-cell MONO_HLSB bitmap (bit 1 = ink) plus its advance width, so the
# on-device renderer is just framebuf blits - no bearing math.
#
# Module API: HEIGHT (int), glyph(ch) -> (advance_px, bitmap_width_px,
# bytearray). Unknown chars fall back to '?' where present.

from PIL import Image, ImageDraw, ImageFont

BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
ASCII = "".join(chr(c) for c in range(32, 127))

SPECS = [
    ("f48b", BOLD, 48, ASCII),
    ("f24", REG, 24, ASCII),
    ("f20", REG, 20, ASCII),
    ("f16b", BOLD, 16, ASCII),
    ("fcat", BOLD, 232, "VFRMILNA/"),
    ("f36b", BOLD, 36, ASCII),
    ("f14b", BOLD, 14, ASCII),
    ("f14", REG, 14, ASCII),
    ("f24b", BOLD, 24, ASCII + "\u00b0"),
    ("f20b", BOLD, 20, ASCII + "\u00b0"),
    ("f96cat", BOLD, 96, "VFRMILNA/"),
    ("f96wx", BOLD, 96, "0123456789.\u00b0F- "),
]


def build(name, ttf, size, charset):
    font = ImageFont.truetype(ttf, size)
    ascent, descent = font.getmetrics()
    height = ascent + descent
    entries = []
    total = 0
    for ch in charset:
        adv = round(font.getlength(ch))
        ink = font.getbbox(ch)  # (x0, y0, x1, y1), anchor = left/ascender
        right = ink[2] if ink else 0
        wpx = max(adv, right)
        wpx = (wpx + 7) // 8 * 8
        img = Image.new("1", (wpx, height), 0)
        d = ImageDraw.Draw(img)
        d.text((0, 0), ch, font=font, fill=1)
        px = img.load()
        data = bytearray()
        for y in range(height):
            for bx in range(0, wpx, 8):
                byte = 0
                for bit in range(8):
                    if px[bx + bit, y]:
                        byte |= 0x80 >> bit
                data.append(byte)
        total += len(data)
        entries.append(" %r: (%d, %d, bytearray(%r))," % (ch, adv, wpx, bytes(data)))
    out = []
    out.append("# %s - generated bitmap font (DejaVu, %dpx). Do not edit." % (name, size))
    out.append("HEIGHT = %d" % height)
    out.append("_G = {")
    out.extend(entries)
    out.append("}")
    out.append("")
    out.append("def glyph(ch):")
    out.append("    g = _G.get(ch)")
    out.append("    if g is None:")
    out.append("        g = _G.get('?')")
    out.append("    return g")
    path = "/home/hatch/workspace/metar-micro/%s.py" % name
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")
    print("%s: height %d, glyph data %d bytes -> %s" % (name, height, total, path))
    return font, height


for name, ttf, size, cs in SPECS:
    build(name, ttf, size, cs)

# category word widths at jumbo size, for the fit check
font = ImageFont.truetype(BOLD, 232)
for word in ("VFR", "MVFR", "IFR", "LIFR", "N/A"):
    print("fcat width", word, "=", round(sum(font.getlength(c) for c in word)), "px")
