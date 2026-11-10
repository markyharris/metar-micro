# show_layout7.py - Layout 7 - circles theme
# mirroring the Pi version (metar_layouts.layout7): center circle with the category, eight red data circles on a ring, four corner circles (airport, updated time, station name, coordinates), red star bursts at the sides.

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
import f16b
import f96cat

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



def circle_outline(fb, cx, cy, r, col, w=3):
    for d in range(w):
        fb.ellipse(cx, cy, r - d, r - d, col, False)


def num(s):
    return s.split(" ")[0]


def local_time_str():
    t = time.localtime(time.time() - 7 * 3600)
    h = t[3] % 12
    if h == 0:
        h = 12
    ampm = "AM" if t[3] < 12 else "PM"
    return "%02d:%02d %s" % (h, t[4], ampm)


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
    print("drawing layout 7:", m.get("icaoId"), cat)

    black = bytearray(b"\xFF" * epd7in5b.PLANE_BYTES)
    red = bytearray(epd7in5b.PLANE_BYTES)
    bfb = framebuf.FrameBuffer(black, W, H, framebuf.MONO_HLSB)
    rfb = framebuf.FrameBuffer(red, W, H, framebuf.MONO_HLSB)

    # Star bursts, left and right center (the Pi's decoration)
    for cx in (85, 705):
        for k in range(8):
            a = math.radians(45 * k)
            ex = cx + round(24 * math.cos(a))
            ey = 240 + round(24 * math.sin(a))
            rfb.line(cx, 240, ex, ey, 1)
            rfb.ellipse(ex, ey, 5, 5, 1, True)
        rfb.ellipse(cx, 240, 4, 4, 1, True)

    # Outer data circles (Pi: centers on a 186 px ring, radius 53)
    centers = []
    for k in range(8):
        a = math.radians(45 * k)
        centers.append((400 + round(186 * math.cos(a)),
                        240 + round(186 * math.sin(a))))
    for cx, cy in centers:
        circle_outline(rfb, cx, cy, 53, 1, 3)

    layers = fmt_clouds(m, units)
    if layers:
        parts = layers[0].split(" ")
        cover = parts[0]
        hgt = parts[1] if len(parts) > 1 else ""
    else:
        cover, hgt = "CLR", ""
    data = [
        ("Temp", num(fmt_temp(m, units))),
        ("Wind", fmt_wdir(m)),
        ("Speed", num(fmt_wspd(m, units))),
        ("Gust", fmt_wgst(m, units)),
        ("Baro", num(fmt_altim(m, units))),
        ("Vis", num(fmt_visib(m, units))),
        ("Type", m.get("metarType") or "n/a"),
        (cover, hgt),
    ]
    for (label, val), (cx, cy) in zip(data, centers):
        textdraw.draw_text(rfb, f24b,
                           cx - textdraw.text_width(f24b, label) // 2,
                           cy - 26, label, 1)
        textdraw.draw_text(rfb, f24b,
                           cx - textdraw.text_width(f24b, val) // 2,
                           cy + 2, val, 1)

    # Center circle + category
    if cat == "MVFR":
        bfb.ellipse(400, 240, 125, 125, 0, True)
        plane, ink = bfb, 1
    elif cat == "LIFR":
        rfb.ellipse(400, 240, 125, 125, 1, True)
        plane, ink = rfb, 0
    elif cat == "IFR":
        circle_outline(rfb, 400, 240, 125, 1, 4)
        plane, ink = rfb, 1
    else:
        circle_outline(bfb, 400, 240, 125, 0, 4)
        plane, ink = bfb, 0
    textdraw.draw_text(plane, f96cat,
                       400 - textdraw.text_width(f96cat, cat_text) // 2,
                       230 - f96cat.HEIGHT // 2, cat_text, ink)

    # Corner circles
    for cx, cy in ((85, 85), (705, 85), (85, 395), (705, 395)):
        circle_outline(bfb, cx, cy, 75, 0, 4)
    apt = str(m.get("icaoId") or airport or AIRPORT)
    textdraw.draw_text(bfb, f48b,
                       85 - textdraw.text_width(f48b, apt) // 2,
                       85 - 28, apt, 0)
    textdraw.draw_text(bfb, f24b,
                       705 - textdraw.text_width(f24b, "Updated") // 2,
                       85 - 26, "Updated", 0)
    ts = local_time_str()
    textdraw.draw_text(bfb, f24b,
                       705 - textdraw.text_width(f24b, ts) // 2,
                       85 + 2, ts, 0)
    words = (str(m.get("name") or "")).split()[:3]
    for i, wtxt in enumerate(words):
        textdraw.draw_text(bfb, f16b,
                           85 - textdraw.text_width(f16b, wtxt) // 2,
                           395 - 27 + i * 18, wtxt, 0)
    for i, ln in enumerate(("Coordinates:",
                            str(m.get("lat")), str(m.get("lon")))):
        textdraw.draw_text(bfb, f16b,
                           705 - textdraw.text_width(f16b, ln) // 2,
                           395 - 27 + i * 18, ln, 0)

    show(black, red, "layout 7")
    return cat


if __name__ == "__main__":
    render()
