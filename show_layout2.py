# show_layout2.py - Layout 2 - two-column data page
# mirroring the Pi version (metar_layouts.layout2) minus its icons: shadowed airport/category header, raw METAR, labeled fields in two columns, cloud layers, station info box.

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
import f14b

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


def box_border(fb, x, y, w, h, t, col):
    fb.fill_rect(x, y, w, t, col)
    fb.fill_rect(x, y + h - t, w, t, col)
    fb.fill_rect(x, y, t, h, col)
    fb.fill_rect(x + w - t, y, t, h, col)


def info_stamp():
    t = time.localtime(time.time() - 7 * 3600)
    h = t[3] % 12
    if h == 0:
        h = 12
    ampm = "AM" if t[3] < 12 else "PM"
    return "INFO: Updated %02d:%02d %s, %02d/%02d/%04d" % (
        h, t[4], ampm, t[1], t[2], t[0])


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
    print("drawing layout 2:", m.get("icaoId"), cat)

    black = bytearray(b"\xFF" * epd7in5b.PLANE_BYTES)
    red = bytearray(epd7in5b.PLANE_BYTES)
    bfb = framebuf.FrameBuffer(black, W, H, framebuf.MONO_HLSB)
    rfb = framebuf.FrameBuffer(red, W, H, framebuf.MONO_HLSB)

    # Grid: black border, red rule under the header, black row rules
    box_border(bfb, 5, 5, 790, 470, 2, 0)
    rfb.fill_rect(5, 65, 790, 3, 1)
    for yy in (110, 170, 230, 290, 350):
        bfb.fill_rect(5, yy, 790, 1, 0)
    bfb.fill_rect(400, 110, 1, 365, 0)

    # Header: airport - category, red with a black drop shadow
    hdr = "%s - %s" % (m.get("icaoId"), cat)
    textdraw.draw_text(bfb, f48b, 43, 13, hdr, 0)
    textdraw.draw_text(rfb, f48b, 40, 10, hdr, 1)

    # Raw METAR under the header
    raw = (m.get("metarType") or "METAR") + ": " + (m.get("rawOb") or "")
    if textdraw.text_width(f16b, raw) > 700:
        words = raw.split()
        textdraw.draw_text(bfb, f16b, 40, 70, " ".join(words[:10]), 0)
        textdraw.draw_text(bfb, f16b, 40, 90, " ".join(words[10:]), 0)
    else:
        textdraw.draw_text(bfb, f16b, 40, 80, raw, 0)

    # Weather description (smaller font when it runs long)
    wx = m.get("wxString") or "n/a"
    textdraw.draw_text(bfb, f24b, 40, 110, "Weather:", 0)
    if textdraw.text_width(f24b, wx) > 330:
        textdraw.draw_text(bfb, f16b, 40, 139, wx, 0)
    else:
        textdraw.draw_text(bfb, f24b, 40, 137, wx, 0)

    fields = [
        (410, 110, "Temperature:", fmt_temp(m, units)),
        (40, 170, "Wind Direction:", fmt_wdir(m)),
        (410, 170, "Wind Speed:", fmt_wspd(m, units)),
        (40, 230, "Wind Gust:", fmt_wgst(m, units)),
        (410, 230, "Baro Pressure:", fmt_altim(m, units)),
        (40, 290, "Visibility:", fmt_visib(m, units)),
        (410, 290, "Metar Type:", m.get("metarType") or "n/a"),
    ]
    for x, y, label, val in fields:
        textdraw.draw_text(bfb, f24b, x, y, label, 0)
        textdraw.draw_text(bfb, f24b, x, y + 27, val, 0)

    textdraw.draw_text(bfb, f24b, 40, 350, "Cloud Cover:", 0)
    for i, cl in enumerate(fmt_clouds(m, units)):
        textdraw.draw_text(bfb, f24b, 40, 377 + i * 27, cl, 0)

    # Info box, bottom right (the Pi's remarks variant is not
    # plumbed on the micro build; the station-info variant is used)
    textdraw.draw_text(rfb, f14b, 410, 354, info_stamp(), 1)
    info = [
        "ICAO ID: " + str(m.get("icaoId")),
        "Obs Time: " + str(m.get("obsTime")),
        "Elevation: " + (str(round((m.get("elev") or 0) * 3.28084)) + " ft"
                         if units == "imperial" else
                         str(int(round(m.get("elev") or 0))) + " m"),
        "Coordinates: " + str(m.get("lat")) + " " + str(m.get("lon")),
        "Info: " + str(m.get("name")),
    ]
    for i, ln in enumerate(info):
        textdraw.draw_text(bfb, f14b, 410, 376 + i * 18, ln, 0)

    show(black, red, "layout 2")
    return cat


if __name__ == "__main__":
    render()
