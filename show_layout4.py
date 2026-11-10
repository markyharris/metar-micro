# show_layout4.py - Layout 4 - three-area page
# mirroring the Pi version (metar_layouts.layout4) minus its icons: black left column with white field text, red upper box with the raw METAR, big category lower right (fcat144, sized so MVFR fits the 480 px box).

import network
import time
import fetch
import ntptime
import framebuf
import gc
import math

import wifi_cfg
import epd7in5b
import textdraw
import f48b
import f24b
import f20b
import f16b
import f14b
import fcat144

AIRPORT = "KFLG"
W, H = epd7in5b.EPD_WIDTH, epd7in5b.EPD_HEIGHT
DEG = "\u00b0"


def join_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return wlan
    print("joining", wifi_cfg.SSID, "...")
    wlan.connect(wifi_cfg.SSID, wifi_cfg.PASSWORD)
    t0 = time.ticks_ms()
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), t0) > 20000:
            raise OSError("wifi join timeout")
        time.sleep_ms(250)
    print("connected:", wlan.ifconfig())
    return wlan


def local_now_str():
    t = time.localtime(time.time() - 7 * 3600)
    h = t[3] % 12
    if h == 0:
        h = 12
    ampm = "AM" if t[3] < 12 else "PM"
    return "Last Updated at %02d:%02d %s" % (h, t[4], ampm)


# ---- field formats (same as show_layout1: Pi get_* routines,
# unit-aware since Nov 10, 2026) ------------------------------------
def fmt_temp(m, units):
    if m.get("temp") is None:
        return "n/a"
    if units == "imperial":
        return "%.1f" % (m["temp"] * 9 / 5 + 32) + " " + DEG + "F"
    return "%.1f" % m["temp"] + " " + DEG + "C"


def fmt_wdir(m):
    d = m.get("wdir")
    if d is None:
        return "n/a"
    if d == "VRB":
        return "VRB"
    s = "%03d" % int(d)
    if s == "000":
        return "Calm"
    return s + DEG


def fmt_wind(v, units):
    if units == "imperial":
        return "%d kt" % int(round(v))
    return str(round(v * 1.852, 1)) + " km/h"


def fmt_wspd(m, units):
    v = m.get("wspd")
    if v is None:
        return "n/a"
    if v == 0:
        return "Calm"
    return fmt_wind(v, units)


def fmt_wgst(m, units):
    v = m.get("wgst")
    if v is None:
        return "n/a"
    return fmt_wind(v, units)


def fmt_altim(m, units):
    if m.get("altim") is None:
        return "n/a"
    if units == "imperial":
        return "%.2f inHg" % (m["altim"] * 0.02953)
    return "%.0f" % m["altim"] + " hPa"


def fmt_visib(m, units):
    v = m.get("visib")
    if v is None:
        return "n/a"
    if units == "imperial":
        s = str(v).strip()
        if s.endswith(".0"):
            s = s[:-2]
        return s + " mi"
    miles = float(str(v).strip("+"))
    return str(round(miles * 1.609344, 1)) + " km"


def fmt_clouds(m, units):
    out = []
    for c in (m.get("clouds") or [])[:3]:
        cover = c.get("cover") or ""
        base = c.get("base")
        if base is None:
            out.append(cover + " ")
        elif units == "imperial":
            out.append("%s %s ft" % (cover, str(int(round(base)))))
        else:
            out.append("%s %s m" % (cover, str(int(round(base * 0.3048)))))
    return out


def fetch_one(airport):
    url = ("https://aviationweather.gov/api/data/metar?ids=%s"
           "&format=json&hours=3" % airport)
    status, data = fetch.get_json(url)
    if status != 200:
        print("fetch failed: HTTP", status)
        return None
    if not data:
        print("no METAR available")
        return None
    return data[0]


def show(black, red, label):
    gc.collect()
    print("free RAM before refresh:", gc.mem_free())
    epd = epd7in5b.EPD()
    epd.init()
    t0 = time.ticks_ms()
    epd.display(black, red)
    print("refresh done in", time.ticks_diff(time.ticks_ms(), t0), "ms")
    epd.sleep()
    print(label, "on panel")



def round_box(fb, x, y, w, h, r, col, fill):
    if fill:
        fb.fill_rect(x + r, y, w - 2 * r, h, col)
        fb.fill_rect(x, y + r, w, h - 2 * r, col)
        for cx, cy in ((x + r, y + r), (x + w - r - 1, y + r),
                       (x + r, y + h - r - 1), (x + w - r - 1, y + h - r - 1)):
            fb.ellipse(cx, cy, r, r, col, True)
        return
    for d in (0, 1):
        fb.hline(x + r, y + d, w - 2 * r, col)
        fb.hline(x + r, y + h - 1 - d, w - 2 * r, col)
        fb.vline(x + d, y + r, h - 2 * r, col)
        fb.vline(x + w - 1 - d, y + r, h - 2 * r, col)
    for cx, cy, sx, sy in ((x + r, y + r, -1, -1), (x + w - r - 1, y + r, 1, -1),
                           (x + r, y + h - r - 1, -1, 1), (x + w - r - 1, y + h - r - 1, 1, 1)):
        for rr in (r, r - 1):
            for a in range(0, 91, 3):
                rad = math.radians(a)
                fb.pixel(cx + sx * round(rr * math.cos(rad)),
                         cy + sy * round(rr * math.sin(rad)), col)


def render(airport=None, units="metric"):
    # Returns the flight category on success, None on fetch failure.
    join_wifi()
    try:
        ntptime.settime()
    except Exception as e:
        print("ntp failed (continuing):", e)
    m = fetch_one(airport or AIRPORT)
    if m is None:
        return
    cat = m.get("fltCat") or "N/A"
    cat_text = cat if cat in ("VFR", "MVFR", "IFR", "LIFR") else "N/A"
    upd = local_now_str()
    print("drawing layout 4:", m.get("icaoId"), cat)

    black = bytearray(b"\xFF" * epd7in5b.PLANE_BYTES)
    red = bytearray(epd7in5b.PLANE_BYTES)
    bfb = framebuf.FrameBuffer(black, W, H, framebuf.MONO_HLSB)
    rfb = framebuf.FrameBuffer(red, W, H, framebuf.MONO_HLSB)

    # Left black column, white text. (The Pi's hairline separators
    # between fields are dropped: at this column width they strike
    # through the values above them. The stack is also re-spaced
    # from the Pi's: its airport header rides the rounded corner
    # and its cloud line falls off the bottom - here everything
    # sits inside the fill.)
    round_box(bfb, 25, 25, 225, 435, 20, 0, True)
    textdraw.draw_text(bfb, f48b, 34, 30,
                       str(m.get("icaoId") or airport or AIRPORT), 1)

    wx = m.get("wxString") or "n/a"
    layers = fmt_clouds(m, units)
    fields = [
        (100, "Weather:", wx, True),
        (156, "Temperature:", fmt_temp(m, units), False),
        (212, "Wind Vector:", fmt_wdir(m), False),
        (268, "Wind Speed:", fmt_wspd(m, units), False),
        (324, "Wind Gust:", fmt_wgst(m, units), False),
        (380, "Visibility:", fmt_visib(m, units), False),
    ]
    for y, label, val, small in fields:
        textdraw.draw_text(bfb, f24b, 30, y, label, 1)
        if small:
            textdraw.draw_text(bfb, f16b, 30, y + 27, val, 1)
        else:
            textdraw.draw_text(bfb, f24b, 30, y + 25, val, 1)
    # Cloud cover as one compact line, indented clear of the
    # bottom rounded corner.
    textdraw.draw_text(bfb, f16b, 34, 434,
                       "Cloud: " + (layers[0] if layers else "n/a"),
                       1)

    # Upper right red box: raw METAR in white. (The Pi measures and
    # word-splits into up to 4 lines starting above the box, which
    # clips the first line; here it is wrapped to fit inside.)
    round_box(rfb, 300, 25, 480, 115, 20, 1, True)
    raw = (m.get("metarType") or "METAR") + ": " + (m.get("rawOb") or "")
    lines = textdraw.wrap(f24b, raw, 450)
    if len(lines) > 3:
        for i, ln in enumerate(textdraw.wrap(f20b, raw, 450)[:4]):
            textdraw.draw_text(rfb, f20b, 315, 32 + i * 24, ln, 0)
    else:
        for i, ln in enumerate(lines):
            textdraw.draw_text(rfb, f24b, 315, 35 + i * 30, ln, 0)
    textdraw.draw_text(rfb, f16b,
                       540 - textdraw.text_width(f16b, upd) // 2,
                       116, upd, 0)

    # Big category, lower right
    if cat == "MVFR":
        round_box(bfb, 300, 190, 480, 270, 20, 0, True)
        plane, ink = bfb, 1
    elif cat == "LIFR":
        round_box(rfb, 300, 190, 480, 270, 20, 1, True)
        plane, ink = rfb, 0
    elif cat == "IFR":
        round_box(rfb, 300, 190, 480, 270, 20, 1, False)
        plane, ink = rfb, 1
    else:
        round_box(bfb, 300, 190, 480, 270, 20, 0, False)
        plane, ink = bfb, 0
    textdraw.draw_text(plane, fcat144,
                       540 - textdraw.text_width(fcat144, cat_text) // 2,
                       225, cat_text, ink)

    show(black, red, "layout 4")
    return cat


if __name__ == "__main__":
    render()
