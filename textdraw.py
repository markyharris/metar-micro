# textdraw.py - tiny bitmap-text renderer for metar-micro. V2.
#
# V1 used framebuf's palette argument to map glyph ink to the target
# color; on this firmware build, blit-with-palette draws nothing at
# all (bench-verified Nov 9, 2026: keyed+palette blits changed 0
# bytes, a plain blit changed 259). V2 avoids palettes entirely:
#   ink=1 -> normal glyph (bit 1 = ink), blit key=0 (skip background)
#   ink=0 -> inverted glyph (bit 0 = ink), blit key=1 (skip background)
# Inverted glyphs are made lazily and cached - only chars actually
# drawn ever get inverted.

import framebuf

_inv_cache = {}


def _inverted(font, ch):
    key = (id(font), ch)
    g = _inv_cache.get(key)
    if g is None:
        adv, w, bmp = font.glyph(ch)
        inv = bytearray(len(bmp))
        for i, b in enumerate(bmp):
            inv[i] = b ^ 0xFF
        g = (adv, w, inv)
        _inv_cache[key] = g
    return g


def text_width(font, s):
    w = 0
    for ch in s:
        w += font.glyph(ch)[0]
    return w


def draw_text(plane, font, x, y, s, ink):
    """Draw string s on framebuffer `plane` with its top at (x, y).
    ink = destination color for the glyph strokes (0 or 1)."""
    cx = x
    for ch in s:
        if ink:
            adv, w, bmp = font.glyph(ch)
            key = 0
        else:
            adv, w, bmp = _inverted(font, ch)
            key = 1
        if w:
            g = framebuf.FrameBuffer(bmp, w, font.HEIGHT,
                                     framebuf.MONO_HLSB)
            plane.blit(g, cx, y, key)
        cx += adv
    return cx


def wrap(font, s, maxw):
    """Word-wrap s to lines no wider than maxw px in the given font."""
    lines = []
    cur = ""
    for word in s.split():
        trial = (cur + " " + word) if cur else word
        if text_width(font, trial) <= maxw:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines
