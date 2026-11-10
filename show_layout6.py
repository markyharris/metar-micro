# show_layout6.py - Layout 6 - 12-hour trend chart.
# NOTE: this slot is NOT the Pi project's layout 6 (a vfrmap.com
# map image, ruled out for the micro on Nov 7, 2026). Mark
# reassigned the slot on Nov 10, 2026 to the trend page offered
# during the layout-8 discussion.
# Draws the selected airport's last ~12 hours of METARs (one
# aviationweather call with hours=13): a flight-category band
# across the top; a pressure chart with sea-level pressure in
# black and VISIBILITY in red on its own right-hand scale (the
# two ranges share nothing, so one axis would flatten both);
# and a temperature chart (dewpoint as dots) with WIND speed in
# red on its own right-hand scale (gusts as red dots). Bottom
# lines summarize the pressure
# trend and the temperature range. All values honor the units
# selector.

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
X0, X1 = 78, 736  # plot area (right margin: 2nd-scale labels)


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


def lt(epoch):
    return time.localtime(epoch - 7 * 3600)


def time_label(epoch):
    t = lt(epoch)
    h = t[3] % 12
    if h == 0:
        h = 12
    return "%d:%02d %s" % (h, t[4], "AM" if t[3] < 12 else "PM")


def cat_block(bfb, rfb, x, wdt, cat):
    y, h = 96, 22
    if wdt < 2:
        return
    if cat == "MVFR":
        bfb.fill_rect(x, y, wdt, h, 0)
    elif cat == "LIFR":
        rfb.fill_rect(x, y, wdt, h, 1)
    elif cat == "IFR":
        rfb.rect(x, y, wdt, h, 1)
        rfb.rect(x + 1, y + 1, wdt - 2, h - 2, 1)
    else:
        bfb.rect(x, y, wdt, h, 0)


def plot_series(fb, pts, ink):
    for i in range(len(pts) - 1):
        fb.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], ink)
    for (x, y) in pts:
        fb.fill_rect(x - 2, y - 2, 5, 5, ink)


def plot_dots(fb, pts, ink):
    for (x, y) in pts:
        fb.fill_rect(x - 1, y - 1, 3, 3, ink)


def parse_slp(m):
    # Sea-level pressure from the SLPppp remark in the raw METAR
    # (the JSON feed has no slp field). ppp is tenths of hPa:
    # below 500 read 10xx.x, 500 and up read 9xx.x.
    raw = m.get("rawOb") or ""
    i = raw.find("SLP")
    if i < 0:
        return None
    digs = ""
    for ch in raw[i + 3:i + 6]:
        if ch in "0123456789":
            digs += ch
        else:
            break
    if len(digs) != 3:
        return None
    v = int(digs)
    return (1000.0 if v < 500 else 900.0) + v / 10.0


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


def chart(bfb, label, series_list, fmt_v, y_top,
          series_b=None, fmt_b=None, rfb=None, b_range=None):
    # series_list: [(points, style, fb, ink)]; style "line"/"dots";
    # fb/ink pick the plane (black plane ink 0, red plane ink 1).
    # Draws label, frame, min/max; the caller draws the time axis.
    # series_b, when given, is a second group on its OWN scale
    # (e.g. visibility over pressure) with red min/max labels on
    # the right-hand side.
    textdraw.draw_text(bfb, f20b, 14, y_top, label, 0)
    y0, y1 = y_top + 30, y_top + 116
    vals = [v for (pts, _s, _f, _i) in series_list for (_t, v) in pts]
    vmin, vmax = min(vals), max(vals)
    if vmax - vmin < 1e-9:
        vmax = vmin + 1
    pad = (vmax - vmin) * 0.15
    vmin -= pad
    vmax += pad

    def Y(v):
        return int(y1 - (v - vmin) / (vmax - vmin) * (y1 - y0))

    bfb.rect(X0, y0, X1 - X0, y1 - y0, 0)
    for (pts, style, fb, ink) in series_list:
        if not pts:
            continue
        xy = [(int(X0 + (t - series_list_t0) * sx), Y(v))
              for (t, v) in pts]
        if style == "line":
            plot_series(fb, xy, ink)
        else:
            plot_dots(fb, xy, ink)
    textdraw.draw_text(bfb, f14b, 8, y0 - 4, fmt_v(max(vals)), 0)
    textdraw.draw_text(bfb, f14b, 8, y1 - 14, fmt_v(min(vals)), 0)
    if series_b:
        vals_b = [v for (pts, _s, _f, _i) in series_b
                  for (_t, v) in pts]
        if b_range is not None:
            # Fixed scale (Mark's ask for visibility: METAR
            # visibility reports 0 to 10 miles - hard-code the
            # range so the line means the same thing every draw).
            bmin, bmax = float(b_range[0]), float(b_range[1])
            lbl_hi, lbl_lo = bmax, bmin
        else:
            bmin, bmax = min(vals_b), max(vals_b)
            if bmax - bmin < 1e-9:
                bmax = bmin + 1
            bpad = (bmax - bmin) * 0.15
            bmin -= bpad
            bmax += bpad
            lbl_hi, lbl_lo = max(vals_b), min(vals_b)

        def Yb(v):
            v = min(max(v, bmin), bmax)
            return int(y1 - (v - bmin) / (bmax - bmin) * (y1 - y0))

        for (pts, style, fb, ink) in series_b:
            if not pts:
                continue
            xy = [(int(X0 + (t - series_list_t0) * sx), Yb(v))
                  for (t, v) in pts]
            if style == "line":
                plot_series(fb, xy, ink)
            else:
                plot_dots(fb, xy, ink)
        if rfb is not None and fmt_b is not None:
            textdraw.draw_text(rfb, f14b, X1 + 8, y0 - 4,
                               fmt_b(lbl_hi), 1)
            textdraw.draw_text(rfb, f14b, X1 + 8, y1 - 14,
                               fmt_b(lbl_lo), 1)
    return y1


series_list_t0 = 0
sx = 1.0


def render(airport=None, units="metric"):
    # Returns the latest report's category (drives the auto
    # interval), or None on fetch failure.
    global series_list_t0, sx
    join_wifi()
    try:
        ntptime.settime()
    except Exception as e:
        print("ntp failed (continuing):", e)
    airport = airport or AIRPORT
    url = ("https://aviationweather.gov/api/data/metar?ids=%s"
           "&format=json&hours=13" % airport)
    status, data = fetch.get_json(url)
    if status != 200 or not data:
        print("history fetch failed: HTTP", status)
        return
    reps = sorted(data, key=lambda m: m.get("obsTime") or 0)
    print("drawing layout 6 (trend):", airport, len(reps), "reports")

    black = bytearray(b"\xFF" * epd7in5b.PLANE_BYTES)
    red = bytearray(epd7in5b.PLANE_BYTES)
    bfb = framebuf.FrameBuffer(black, W, H, framebuf.MONO_HLSB)
    rfb = framebuf.FrameBuffer(red, W, H, framebuf.MONO_HLSB)

    latest = reps[-1]
    name = str(latest.get("name") or "").split(",")[0]
    textdraw.draw_text(bfb, f36b, 14, 8, airport + " Trend", 0)
    upd = local_now_str()
    textdraw.draw_text(bfb, f16b,
                       W - 14 - textdraw.text_width(f16b, upd), 24, upd, 0)
    sub = "%s - last 12 hours, %d reports" % (name, len(reps))
    textdraw.draw_text(bfb, f16b, 14, 56, sub, 0)
    rfb.fill_rect(5, 84, 790, 3, 1)

    if len(reps) < 2:
        note = "Not enough history yet for a trend."
        textdraw.draw_text(
            bfb, f20b, (W - textdraw.text_width(f20b, note)) // 2,
            230, note, 0)
        show(black, red, "layout 6 (trend)")
        return latest.get("fltCat")

    t_first = reps[0].get("obsTime") or 0
    t_last = reps[-1].get("obsTime") or 0
    t_end = t_last + 1800
    series_list_t0 = t_first
    sx = (X1 - X0) / float(t_end - t_first)

    # Category band
    textdraw.draw_text(bfb, f14b, 14, 100, "Cat:", 0)
    for i, m in enumerate(reps):
        t0 = m.get("obsTime") or 0
        t1 = (reps[i + 1].get("obsTime") or t_end) if i + 1 < len(reps) \
            else t_end
        x = int(X0 + (t0 - t_first) * sx)
        wdt = max(2, int((t1 - t0) * sx) - 1)
        cat_block(bfb, rfb, x, wdt, m.get("fltCat") or "VFR")

    # Pressure chart: sea-level pressure in black (altimeter if
    # no SLP remarks), VISIBILITY in red on its own scale at the
    # right (Mark's change: visibility replaces the altimeter
    # overlay - the two series' ranges share nothing).
    if units == "imperial":
        convp = lambda hpa: hpa / 33.8639
        punit = "inHg"
        pfmt = lambda v: "%.2f" % v
        convv = lambda mi: mi
        vfmt = lambda v: "%d" % int(round(v))
    else:
        convp = lambda hpa: hpa
        punit = "hPa"
        pfmt = lambda v: "%d" % int(round(v))
        convv = lambda mi: mi * 1.609344
        vfmt = lambda v: "%d" % int(round(v))
    pvals = [(m.get("obsTime") or 0, convp(m.get("altim") or 0))
             for m in reps if m.get("altim") is not None]
    svals = []
    for m in reps:
        slp = parse_slp(m)
        if slp is not None:
            svals.append((m.get("obsTime") or 0, convp(slp)))
    main_series = svals if svals else pvals
    plabel = "Pressure (%s) black - Visibility red" % punit
    vvals = []
    for m in reps:
        v = m.get("visib")
        if v is None:
            continue
        try:
            num = float(str(v).rstrip("+"))
        except Exception:
            continue
        vvals.append((m.get("obsTime") or 0, convv(num)))
    chart(bfb, plabel, [(main_series, "line", bfb, 0)], pfmt, 128,
          series_b=[(vvals, "line", rfb, 1)] if vvals else None,
          fmt_b=vfmt, rfb=rfb,
          b_range=(0, 10) if units == "imperial" else (0, 16))

    # Temperature chart (solid) + dewpoint (dots)
    if units == "imperial":
        conv = lambda c: c * 9.0 / 5.0 + 32.0
        tlabel = "Temperature " + DEG + "F (dewpoint dotted)"
        tfmt = lambda v: "%d" % int(round(v))
    else:
        conv = lambda c: c
        tlabel = "Temperature " + DEG + "C (dewpoint dotted)"
        tfmt = lambda v: "%d" % int(round(v))
    tvals = [(m.get("obsTime") or 0, conv(m.get("temp") or 0))
             for m in reps if m.get("temp") is not None]
    dvals = [(m.get("obsTime") or 0, conv(m.get("dewp") or 0))
             for m in reps if m.get("dewp") is not None]
    # Wind speed as a red line on its OWN scale at the right
    # (Mark's ask - same treatment as visibility above); gusts
    # ride along as red dots on that scale.
    if units == "imperial":
        convw = lambda kt: kt
    else:
        convw = lambda kt: kt * 1.852
    wvals = [(m.get("obsTime") or 0, convw(m.get("wspd") or 0))
             for m in reps if m.get("wspd") is not None]
    gvals = [(m.get("obsTime") or 0, convw(m.get("wgst") or 0))
             for m in reps if m.get("wgst") is not None]
    tlabel += " - Wind red"
    wseries = [(wvals, "line", rfb, 1)]
    if gvals:
        wseries.append((gvals, "dots", rfb, 1))
    chart(bfb, tlabel, [(tvals, "line", bfb, 0),
                        (dvals, "dots", bfb, 0)], tfmt, 282,
          series_b=wseries if wvals else None,
          fmt_b=lambda v: "%d" % int(round(v)), rfb=rfb)

    # Time axis labels (shared span)
    textdraw.draw_text(bfb, f14, X0, 428, time_label(t_first), 0)
    last_lbl = time_label(t_last)
    textdraw.draw_text(bfb, f14,
                       X1 - textdraw.text_width(f14, last_lbl), 428,
                       last_lbl, 0)

    # Summary line: pressure trend + temperature range
    trend_series = svals if svals else pvals
    if len(trend_series) >= 2:
        d = trend_series[-1][1] - trend_series[0][1]
        steady = abs(d) < (0.02 if units == "imperial" else 0.7)
        word = "steady" if steady else ("rising" if d > 0 else "falling")
        if units == "imperial":
            dtxt = "Pressure %s (%+.2f inHg)" % (word, d)
        else:
            dtxt = "Pressure %s (%+d hPa)" % (word, int(round(d)))
    else:
        dtxt = "Pressure n/a"
    if tvals:
        tv = [v for (_t, v) in tvals]
        dtxt += "   -   Temp %s to %s %s" % (
            tfmt(min(tv)), tfmt(max(tv)),
            DEG + ("F" if units == "imperial" else "C"))
    textdraw.draw_text(bfb, f16b, 14, 452, dtxt, 0)

    show(black, red, "layout 6 (trend)")
    return latest.get("fltCat")


if __name__ == "__main__":
    render()
