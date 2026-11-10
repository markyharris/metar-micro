# show_layout1.py - v1 render step: layout 1, the detailed data grid,
# mirroring the Pi version (metar_layouts.layout1) minus its icons.
# Red grid, raw METAR across the top, eight labeled fields in two
# columns, flight category in a heavy-bordered center box, station
# info box bottom-center. Field formats mirror the Pi's get_*
# routines with his repo settings: temp degC, wind km/h, visibility
# km, pressure hPa, cloud heights m. One deviation, deliberate: the
# info box converts AWC's elevation (meters) to feet properly - the
# Pi prints the meter value labeled "ft".
# Units (Nov 10, 2026): render(airport, units) - "imperial" shows
# degF / knots / miles / inHg / feet, "metric" (the default, and
# this page's original baked settings) degC / km/h / km / hPa /
# meters. AWC source units: temp degC, wind kt, visib statute
# miles, altim hPa, cloud bases feet, elevation meters.

import network
import time
import fetch
import ntptime
import framebuf
import gc

import wifi_cfg
import epd7in5b
import textdraw
import f24b
import f20b
import f16b
import f14b
import f96cat

AIRPORT = "KFLG"
URL = "https://aviationweather.gov/api/data/metar?ids=%s&format=json&hours=3" % AIRPORT
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


# ---- field formats (Pi get_* routines, his settings) ----------------
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
    # AWC wind speeds arrive in knots.
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
            out.append("%s %s m" % (cover, str(round(base * 0.3048, 0))))
    return out


def box_border(fb, x, y, w, h, t, col):
    fb.fill_rect(x, y, w, t, col)
    fb.fill_rect(x, y + h - t, w, t, col)
    fb.fill_rect(x, y, t, h, col)
    fb.fill_rect(x + w - t, y, t, h, col)


def render(airport=None, units="metric"):
    # Returns the flight category on success, None on fetch failure.
    # Called by main.py's loop; also runnable standalone (see bottom).
    join_wifi()
    try:
        ntptime.settime()
    except Exception as e:
        print("ntp failed (continuing):", e)
    url = ("https://aviationweather.gov/api/data/metar?ids=%s"
           "&format=json&hours=3" % (airport or AIRPORT))
    status, data = fetch.get_json(url)
    if status != 200:
        print("fetch failed: HTTP", status)
        return
    if data is None:
        print("fetch failed: unparseable response")
        return
    if not data:
        print("no METAR available for", AIRPORT)
        return
    m = data[0]
    cat = m.get("fltCat") or "N/A"
    upd = local_now_str()
    print("drawing layout 1:", m.get("icaoId"), cat)

    black = bytearray(b"\xFF" * epd7in5b.PLANE_BYTES)
    red = bytearray(epd7in5b.PLANE_BYTES)
    bfb = framebuf.FrameBuffer(black, W, H, framebuf.MONO_HLSB)
    rfb = framebuf.FrameBuffer(red, W, H, framebuf.MONO_HLSB)

    # Red grid
    for i in range(5):
        rfb.rect(5 + i, 5 + i, 790 - 2 * i, 470 - 2 * i, 1)
    rfb.fill_rect(5, 100, 790, 5, 1)
    rfb.hline(5, 170, 790, 1)
    rfb.hline(5, 350, 790, 1)
    for yy in (230, 290):
        rfb.hline(5, yy, 271, 1)
        rfb.hline(522, yy, 273, 1)
    rfb.vline(522, 100, 250, 1)
    rfb.vline(276, 170, 305, 1)

    # Raw METAR, top strip
    raw = "METAR: " + (m.get("rawOb") or "")
    lines = textdraw.wrap(f24b, raw, 740)
    if len(lines) > 3:
        for i, ln in enumerate(textdraw.wrap(f20b, raw, 740)[:4]):
            textdraw.draw_text(bfb, f20b, 30, 8 + i * 22, ln, 0)
    else:
        for i, ln in enumerate(lines):
            textdraw.draw_text(bfb, f24b, 30, 6 + i * 30, ln, 0)

    # Center category box (276,170)-(522,350)
    cat_text = cat if cat in ("VFR", "MVFR", "IFR", "LIFR") else "N/A"
    cx = (W - textdraw.text_width(f96cat, cat_text)) // 2
    if cat == "MVFR":
        box_border(bfb, 276, 170, 246, 180, 10, 0)
        bfb.fill_rect(286, 180, 226, 160, 0)
        textdraw.draw_text(bfb, f96cat, cx, 205, cat_text, 1)
    elif cat == "IFR":
        box_border(rfb, 276, 170, 246, 180, 10, 1)
        textdraw.draw_text(rfb, f96cat, cx, 205, cat_text, 1)
    elif cat == "LIFR":
        rfb.fill_rect(276, 170, 246, 180, 1)
        textdraw.draw_text(rfb, f96cat, cx, 205, cat_text, 0)
    else:
        box_border(bfb, 276, 170, 246, 180, 10, 0)
        textdraw.draw_text(bfb, f96cat, cx, 205, cat_text, 0)

    # Fields
    fields = [
        (30, 110, "Weather:", m.get("wxString") or "n/a"),
        (545, 110, "Temperature:", fmt_temp(m, units)),
        (30, 170, "Wind Vector:", fmt_wdir(m)),
        (545, 170, "Wind Speed:", fmt_wspd(m, units)),
        (30, 230, "Wind Gust:", fmt_wgst(m, units)),
        (545, 230, "Baro Press:", fmt_altim(m, units)),
        (30, 290, "Visibility:", fmt_visib(m, units)),
        (545, 290, "Metar Type:", m.get("metarType") or "n/a"),
    ]
    for x, y, label, val in fields:
        textdraw.draw_text(bfb, f24b, x, y, label, 0)
        textdraw.draw_text(bfb, f24b, x, y + 29, val, 0)

    textdraw.draw_text(bfb, f24b, 30, 350, "Cloud Cover:", 0)
    for i, cl in enumerate(fmt_clouds(m, units)):
        textdraw.draw_text(bfb, f24b, 30, 377 + i * 27, cl, 0)

    # Info box
    textdraw.draw_text(rfb, f16b, 286, 354,
                       "%s %s" % (m.get("icaoId"), upd), 1)
    info = [
        "ICAO ID: " + str(m.get("icaoId")),
        "Obs Time: " + str(m.get("obsTime")),
        "Elevation: " + (str(int(round(m.get("elev") or 0))) + " m"
                         if units != "imperial" else
                         str(round((m.get("elev") or 0) * 3.28084)) + " ft"),
        "Coordinates: " + str(m.get("lat")) + " " + str(m.get("lon")),
        "Info: " + str(m.get("name")),
    ]
    for i, ln in enumerate(info):
        textdraw.draw_text(bfb, f14b, 286, 376 + i * 18, ln, 0)

    gc.collect()
    print("free RAM before refresh:", gc.mem_free())
    epd = epd7in5b.EPD()
    epd.init()
    t0 = time.ticks_ms()
    epd.display(black, red)
    print("refresh done in", time.ticks_diff(time.ticks_ms(), t0), "ms")
    epd.sleep()
    print("layout 1 on panel")
    return cat


if __name__ == "__main__":
    render()
