# show_layout8.py - Layout 8 - TAF forecast page (replaced the
# Pi's worst-weather grid Nov 10, 2026 at Mark's direction: the
# grid duplicated layout 5; this page shows what is COMING).
# The home airport's TAF from aviationweather.gov, decoded into
# one row per forecast period: category chip (derived from the
# period's ceiling and visibility with the standard thresholds -
# the TAF feed carries no category of its own), local time
# window, wind / visibility / weather / clouds. The raw TAF runs
# along the bottom. Airports that do not publish a TAF get a
# plain "No TAF issued" page instead of an error.

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
import f36b
import f20b
import f16b
import f14b
import f14

AIRPORT = "KFLG"
W, H = epd7in5b.EPD_WIDTH, epd7in5b.EPD_HEIGHT
DEG = "°"
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MAX_ROWS = 6


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


def fmt_wdir(f):
    d = f.get("wdir")
    if d is None:
        return "n/a"
    if d == "VRB":
        return "VRB"
    s = "%03d" % int(d)
    if s == "000":
        return "Calm"
    return s + DEG


def fmt_clouds(f, units):
    out = []
    for c in (f.get("clouds") or [])[:3]:
        cover = c.get("cover") or ""
        base = c.get("base")
        if base is None:
            out.append(cover + " ")
        elif units == "imperial":
            out.append("%s %s ft" % (cover, str(int(round(base)))))
        else:
            out.append("%s %s m" % (cover, str(int(round(base * 0.3048)))))
    return out


def wind_str(f, units):
    v = f.get("wspd")
    if v is None or v == 0:
        return "Calm"
    if units == "imperial":
        spd = "%d" % int(round(v))
        unit = " kt"
    else:
        spd = str(round(v * 1.852, 1))
        unit = " km/h"
    g = f.get("wgst")
    if g:
        spd += "G" + ("%d" % int(round(g)) if units == "imperial"
                      else str(round(g * 1.852, 1)))
    return fmt_wdir(f) + " " + spd + unit


def vis_str(f, units):
    v = f.get("visib")
    if v is None:
        return ""
    s = str(v)
    plus = s.endswith("+")
    try:
        num = float(s.rstrip("+"))
    except Exception:
        return "Vis " + s
    if units == "imperial":
        n = "%d" % num if num == int(num) else str(num)
        return "Vis " + n + ("+" if plus else "") + " mi"
    return "Vis " + str(round(num * 1.609344, 1)) + \
        ("+" if plus else "") + " km"


def cat_for(f):
    # Standard flight-category thresholds applied to the period's
    # ceiling (lowest BKN/OVC/VV base, or vertical visibility) and
    # visibility - the same definitions behind the METAR fltCat.
    v = f.get("visib")
    if v is None:
        visv = 99.0
    else:
        try:
            visv = float(str(v).rstrip("+"))
        except Exception:
            visv = 99.0
    ceil = None
    for c in f.get("clouds") or []:
        if c.get("cover") in ("BKN", "OVC", "VV") and \
                c.get("base") is not None:
            b = c["base"]
            if ceil is None or b < ceil:
                ceil = b
    if f.get("vertVis") is not None:
        vv = f["vertVis"]
        if ceil is None or vv < ceil:
            ceil = vv
    if (ceil is not None and ceil < 500) or visv < 1:
        return "LIFR"
    if (ceil is not None and ceil < 1000) or visv < 3:
        return "IFR"
    if (ceil is not None and ceil <= 3000) or visv <= 5:
        return "MVFR"
    return "VFR"


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


def draw_chip(bfb, rfb, x, y, cat):
    if cat == "MVFR":
        round_box(bfb, x, y, 100, 40, 8, 0, True)
        plane, ink = bfb, 1
    elif cat == "LIFR":
        round_box(rfb, x, y, 100, 40, 8, 1, True)
        plane, ink = rfb, 0
    elif cat == "IFR":
        round_box(rfb, x, y, 100, 40, 8, 1, False)
        plane, ink = rfb, 1
    else:
        round_box(bfb, x, y, 100, 40, 8, 0, False)
        plane, ink = bfb, 0
    textdraw.draw_text(plane, f20b,
                       x + (100 - textdraw.text_width(f20b, cat)) // 2,
                       y + 8, cat, ink)


def lt(epoch):
    return time.localtime(epoch - 7 * 3600)


def h12(t):
    h = t[3] % 12
    if h == 0:
        h = 12
    return h, ("AM" if t[3] < 12 else "PM")


def window_str(f):
    a = lt(f.get("timeFrom") or 0)
    b = lt(f.get("timeTo") or 0)
    ha, aa = h12(a)
    hb, ab = h12(b)
    end = "%d %s" % (hb, ab)
    if b[6] != a[6]:
        end = DAYS[b[6]] + " " + end
    return "%s %d %s - %s" % (DAYS[a[6]], ha, aa, end)


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


def render(airport=None, units="metric"):
    # Returns the current period's derived category (drives the
    # auto interval), "TAF" when no TAF is published, or None on
    # fetch failure.
    join_wifi()
    try:
        ntptime.settime()
    except Exception as e:
        print("ntp failed (continuing):", e)
    airport = airport or AIRPORT
    url = ("https://aviationweather.gov/api/data/taf?ids=%s"
           "&format=json" % airport)
    status, data = fetch.get_json(url)
    if status != 200:
        print("fetch failed: HTTP", status)
        return
    rec = data[0] if data else None
    fcsts = (rec or {}).get("fcsts") or []

    black = bytearray(b"\xFF" * epd7in5b.PLANE_BYTES)
    red = bytearray(epd7in5b.PLANE_BYTES)
    bfb = framebuf.FrameBuffer(black, W, H, framebuf.MONO_HLSB)
    rfb = framebuf.FrameBuffer(red, W, H, framebuf.MONO_HLSB)

    # Header
    textdraw.draw_text(bfb, f36b, 14, 8, airport + " TAF", 0)
    issued = ""
    if rec and rec.get("issueTime"):
        issued = "Issued " + str(rec["issueTime"])[11:16] + "Z"
    textdraw.draw_text(bfb, f16b,
                       W - 14 - textdraw.text_width(f16b, issued),
                       24, issued, 0)
    if rec:
        va = lt(rec.get("validTimeFrom") or 0)
        vb = lt(rec.get("validTimeTo") or 0)
        ha, aa = h12(va)
        hb, ab = h12(vb)
        sub = "%s - Valid %s %d %s to %s %d %s (%s)" % (
            str(rec.get("name") or ""), DAYS[va[6]], ha, aa,
            DAYS[vb[6]], hb, ab, local_now_str())
    else:
        sub = local_now_str()
    textdraw.draw_text(bfb, f16b, 14, 54, sub, 0)
    rfb.fill_rect(5, 84, 790, 3, 1)

    if not fcsts:
        textdraw.draw_text(
            bfb, f36b,
            (W - textdraw.text_width(f36b, "No TAF issued")) // 2,
            190, "No TAF issued", 0)
        note = "This airport does not publish a terminal forecast."
        textdraw.draw_text(
            bfb, f16b,
            (W - textdraw.text_width(f16b, note)) // 2, 250, note, 0)
        show(black, red, "layout 8 (no TAF)")
        return "TAF"

    print("drawing layout 8 (TAF):", airport, len(fcsts), "periods")
    now = time.time()
    current_cat = None
    for i, f in enumerate(fcsts[:MAX_ROWS]):
        y = 96 + i * 54
        cat = cat_for(f)
        if current_cat is None and \
                (f.get("timeFrom") or 0) <= now < (f.get("timeTo") or 0):
            current_cat = cat
        draw_chip(bfb, rfb, 14, y + 5, cat)
        tag = f.get("fcstChange") or ""
        if f.get("probability"):
            tag = ("PROB" + str(f["probability"]) +
                   (" " + tag if tag else ""))
        title = window_str(f) + ("  " + tag if tag else "")
        textdraw.draw_text(bfb, f20b, 128, y, title, 0)
        parts = [wind_str(f, units), vis_str(f, units)]
        if f.get("wxString"):
            parts.append(str(f["wxString"]))
        clouds = fmt_clouds(f, units)
        line = "  ".join(p for p in parts if p)
        # Fit one line: shed cloud layers, then the wx string,
        # before anything gets cut mid-word.
        cand = clouds[:]
        while True:
            trial = line + ("  " + " ".join(cand) if cand else "")
            if textdraw.text_width(f20b, trial) <= 655 or not cand:
                line = trial
                break
            cand = cand[:-1]
        if textdraw.text_width(f20b, line) > 655 and len(parts) > 2:
            line = "  ".join(parts[:2])
            if clouds:
                line += "  " + clouds[0]
        textdraw.draw_text(bfb, f20b, 128, y + 27, line, 0)
    if len(fcsts) > MAX_ROWS:
        textdraw.draw_text(bfb, f14b, 128, 96 + MAX_ROWS * 54 - 16,
                           "+ %d more period(s) in the raw TAF below"
                           % (len(fcsts) - MAX_ROWS), 0)

    # Raw TAF along the bottom
    raw = (rec.get("rawTAF") or "").replace("\n", " ")
    for i, ln in enumerate(textdraw.wrap(f14, raw, 780)[:2]):
        textdraw.draw_text(bfb, f14, 10, 428 + i * 17, ln, 0)

    show(black, red, "layout 8 (TAF)")
    return current_cat or cat_for(fcsts[0])


if __name__ == "__main__":
    render()
