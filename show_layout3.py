# show_layout3.py - Layout 3 - jumbo category in a rounded box
# mirroring the Pi version (metar_layouts.layout3): airport and station name over the jumbo category inside a rounded box styled by category, update line below.

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
import f24
import f16b
import fcat

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
    # Jumbo category page; no measurements, so `units` is accepted
    # only for a uniform signature. Returns the category or None.
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
    print("drawing layout 3:", m.get("icaoId"), cat)

    black = bytearray(b"\xFF" * epd7in5b.PLANE_BYTES)
    red = bytearray(epd7in5b.PLANE_BYTES)
    bfb = framebuf.FrameBuffer(black, W, H, framebuf.MONO_HLSB)
    rfb = framebuf.FrameBuffer(red, W, H, framebuf.MONO_HLSB)

    if cat == "MVFR":
        round_box(bfb, 25, 25, 750, 410, 20, 0, True)
        plane, ink = bfb, 1
    elif cat == "LIFR":
        round_box(rfb, 25, 25, 750, 410, 20, 1, True)
        plane, ink = rfb, 0
    elif cat == "IFR":
        round_box(rfb, 25, 25, 750, 410, 20, 1, False)
        plane, ink = rfb, 1
    else:
        round_box(bfb, 25, 25, 750, 410, 20, 0, False)
        plane, ink = bfb, 0

    def centered(font, y, s):
        textdraw.draw_text(
            plane, font, (W - textdraw.text_width(font, s)) // 2,
            y, s, ink)

    centered(f48b, 20, str(m.get("icaoId") or airport or AIRPORT))
    centered(f24, 65, str(m.get("name") or ""))
    centered(fcat, 100, cat_text)
    # The Pi draws the update line in the category ink below the
    # box, which makes it invisible for the filled categories;
    # here it is always black on the white margin.
    textdraw.draw_text(bfb, f16b,
                       (W - textdraw.text_width(f16b, upd)) // 2,
                       445, upd, 0)

    show(black, red, "layout 3")
    return cat


if __name__ == "__main__":
    render()
