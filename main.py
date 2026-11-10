# main.py - metar-micro v1 "bones": the running loop for the ESP32
# e-paper METAR display. Upload to the board AS main.py (auto-runs on
# boot; can also be run from Thonny to watch the console).
#
# What it does:
# - Joins Wi-Fi (credentials in wifi_cfg.py, as the page tests used),
#   sets the clock by NTP, starts the admin web server on port 80.
# - Boot screen on the panel showing the admin URL (Pi behavior:
#   held 60 s, with the admin page live during the hold).
# - Cycles the proven pages: layout 1 (detailed grid), layout 0
#   (jumbo category), layout 5 (12-airport grid), weather page.
#   Mode "cycle" runs the full list; mode "preferred" runs only the
#   preferred subset. Interval is a fixed number of seconds, or 0 =
#   auto by flight category (Pi table: VFR 3600, MVFR 1800, IFR 1200,
#   LIFR 600; weather page and unknown category use 1800).
# - Fetch failure: error screen, retry the same page once after 60 s,
#   then move on (Pi behavior).
# - Overnight off (admin setting): holds the last image and stops
#   refreshing during the window; the admin page stays live.
# - Display off (admin): blanks the panel and idles until turned
#   back on from the admin page.
# - Settings persist in config.json on the board; the admin Save
#   rewrites it and restarts the cycle with the new settings.
#
# Page modules are imported one at a time and purged (with their
# fonts) after each render, so only one page's fonts sit in RAM.
# Self-update and the rehoming setup portal are v2, per SPEC phasing.

import network
import socket
import time
import json
import gc
import sys
import machine
import ntptime
import framebuf

import wifi_cfg
import epd7in5b
import textdraw
import f48b
import f36b
import f24b
import f20b
import f16b

CONFIG_FILE = "config.json"
W, H = epd7in5b.EPD_WIDTH, epd7in5b.EPD_HEIGHT
TZ_OFFSET = -7 * 3600  # Phoenix: UTC-7 year-round (as the pages use)

DEFAULTS = {
    "airport": "KFLG",
    "mode": "cycle",                    # "cycle" or "preferred"
    "pages": ["layout1", "layout0", "layout5", "weather"],
    "preferred": ["layout1", "weather"],
    "interval": 0,                      # seconds; 0 = auto by category
    "overnight": False,
    "off_start": "22:00",
    "off_end": "06:00",
    "display_off": False,
}

PAGE_MODULES = {
    "layout0": "show_layout0",
    "layout1": "show_layout1",
    "layout5": "show_layout5",
    "weather": "show_weather",
}
PAGE_TITLES = {
    "layout0": "Layout 0 - jumbo category",
    "layout1": "Layout 1 - detailed grid",
    "layout5": "Layout 5 - 12-airport grid",
    "weather": "City weather page",
}
# Modules purged after each page render so its fonts leave RAM.
FONT_MODULES = ["f14", "f14b", "f16b", "f20", "f20b", "f24", "f24b",
                "f36b", "f48b", "f96cat", "f96wx", "fcat", "textdraw"]
AUTO_INTERVAL = {"VFR": 3600, "MVFR": 1800, "IFR": 1200, "LIFR": 600}

cfg = dict(DEFAULTS)
changed = False      # set by admin actions: restart the cycle
wlan = None
server = None


# ---------------------------------------------------------------- cfg
def load_cfg():
    global cfg
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_FILE) as f:
            saved = json.load(f)
        for k in saved:
            if k in cfg:
                cfg[k] = saved[k]
    except Exception:
        pass
    return cfg


def save_cfg():
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f)
    except Exception as e:
        print("config save failed:", e)


# ---------------------------------------------------------------- net
def join_wifi():
    global wlan
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return wlan
    print("joining", wifi_cfg.SSID, "...")
    wlan.connect(wifi_cfg.SSID, wifi_cfg.PASSWORD)
    t0 = time.ticks_ms()
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), t0) > 30000:
            raise OSError("wifi join timeout")
        time.sleep_ms(250)
    print("connected:", wlan.ifconfig())
    return wlan


def local_hhmm():
    t = time.localtime(time.time() + TZ_OFFSET)
    return t[3] * 60 + t[4]


def local_str():
    t = time.localtime(time.time() + TZ_OFFSET)
    h = t[3] % 12
    if h == 0:
        h = 12
    return "%02d:%02d %s" % (h, t[4], "AM" if t[3] < 12 else "PM")


def parse_hhmm(s):
    try:
        hh, mm = s.split(":")
        return int(hh) * 60 + int(mm)
    except Exception:
        return 0


def in_overnight():
    if not cfg.get("overnight"):
        return False
    start = parse_hhmm(cfg.get("off_start", "22:00"))
    end = parse_hhmm(cfg.get("off_end", "06:00"))
    now = local_hhmm()
    if start <= end:
        return start <= now < end
    return now >= start or now < end


# -------------------------------------------------------------- panel
def blank_planes():
    black = bytearray(b"\xFF" * epd7in5b.PLANE_BYTES)
    red = bytearray(epd7in5b.PLANE_BYTES)
    return (black, red,
            framebuf.FrameBuffer(black, W, H, framebuf.MONO_HLSB),
            framebuf.FrameBuffer(red, W, H, framebuf.MONO_HLSB))


def push(black, red):
    gc.collect()
    epd = epd7in5b.EPD()
    epd.init()
    epd.display(black, red)
    epd.sleep()


def draw_boot(ip):
    black, red, bfb, rfb = blank_planes()
    for i in range(5):
        rfb.rect(5 + i, 5 + i, 790 - 2 * i, 470 - 2 * i, 1)
    textdraw.draw_text(bfb, f48b, 40, 60, "METAR MICRO", 0)
    textdraw.draw_text(bfb, f24b, 40, 150,
                       "Airport: " + str(cfg.get("airport")), 0)
    textdraw.draw_text(bfb, f24b, 40, 200, "Admin page:", 0)
    textdraw.draw_text(bfb, f36b, 40, 240, "http://" + ip + "/", 0)
    textdraw.draw_text(bfb, f20b, 40, 320,
                       "Open that address to change settings.", 0)
    textdraw.draw_text(bfb, f16b, 40, 420,
                       "First weather page follows in about a minute.", 0)
    push(black, red)
    print("boot screen on panel, admin at http://" + ip + "/")


def draw_error(page, detail):
    black, red, bfb, rfb = blank_planes()
    for i in range(5):
        rfb.rect(5 + i, 5 + i, 790 - 2 * i, 470 - 2 * i, 1)
    textdraw.draw_text(rfb, f48b, 40, 60, "FETCH FAILED", 1)
    textdraw.draw_text(bfb, f24b, 40, 160,
                       "Page: " + PAGE_TITLES.get(page, page), 0)
    textdraw.draw_text(bfb, f24b, 40, 210,
                       "Airport: " + str(cfg.get("airport")), 0)
    for i, ln in enumerate(textdraw.wrap(f20b, str(detail), 700)[:3]):
        textdraw.draw_text(bfb, f20b, 40, 270 + i * 26, ln, 0)
    textdraw.draw_text(bfb, f16b, 40, 420,
                       "Retrying in 60 seconds - " + local_str(), 0)
    push(black, red)
    print("error screen on panel for", page)


def draw_blank():
    black, red, bfb, rfb = blank_planes()
    push(black, red)
    print("panel blanked (display off)")


# -------------------------------------------------------------- admin
def urldecode(s):
    out = ""
    i = 0
    while i < len(s):
        c = s[i]
        if c == "+":
            out += " "
            i += 1
        elif c == "%" and i + 2 < len(s):
            try:
                out += chr(int(s[i + 1:i + 3], 16))
            except Exception:
                out += c
            i += 3
        else:
            out += c
            i += 1
    return out


def parse_form(body):
    data = {}
    for pair in body.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            data[urldecode(k)] = urldecode(v)
    return data


def html_page():
    ip = wlan.ifconfig()[0] if wlan else "?"
    def chk(cond):
        return " checked" if cond else ""
    def sel(cond):
        return " selected" if cond else ""
    pref = cfg.get("preferred", [])
    p = []
    p.append("<!DOCTYPE html><html><head><meta charset='utf-8'>")
    p.append("<meta name='viewport' content='width=device-width,"
             "initial-scale=1'><title>metar-micro admin</title></head>"
             "<body style='font-family:sans-serif;max-width:560px;"
             "margin:20px auto;padding:0 12px'>")
    p.append("<h2>METAR Micro</h2>")
    p.append("<p>Panel airport: <b>" + str(cfg.get("airport")) +
             "</b> &middot; " + local_str() +
             (" &middot; <b>DISPLAY OFF</b>" if cfg.get("display_off")
              else "") + "</p>")
    p.append("<form method='POST' action='/save'>")
    p.append("Airport (ICAO): <input name='airport' value='" +
             str(cfg.get("airport")) +
             "' size='8' style='font-size:16px'><br><br>")
    p.append("Mode: <select name='mode'>")
    p.append("<option value='cycle'" + sel(cfg.get("mode") == "cycle") +
             ">Cycle all pages</option>")
    p.append("<option value='preferred'" +
             sel(cfg.get("mode") == "preferred") +
             ">Preferred pages only</option></select><br><br>")
    p.append("Preferred pages:<br>")
    for name in cfg.get("pages", []):
        p.append("<label><input type='checkbox' name='pref_" + name +
                 "'" + chk(name in pref) + "> " +
                 PAGE_TITLES.get(name, name) + "</label><br>")
    p.append("<br>Interval (seconds, 0 = auto by category): "
             "<input name='interval' value='" +
             str(cfg.get("interval")) +
             "' size='6' style='font-size:16px'><br><br>")
    p.append("<label><input type='checkbox' name='overnight'" +
             chk(cfg.get("overnight")) +
             "> Turn off overnight (hold last image)</label><br>")
    p.append("Off from <input name='off_start' value='" +
             str(cfg.get("off_start")) + "' size='6'> to "
             "<input name='off_end' value='" +
             str(cfg.get("off_end")) + "' size='6'> (HH:MM, 24h)"
             "<br><br>")
    p.append("<button type='submit' style='font-size:16px;"
             "padding:8px 18px'>Save</button></form>")
    p.append("<hr><p>")
    if cfg.get("display_off"):
        p.append("<a href='/on'>Turn display ON</a> &middot; ")
    else:
        p.append("<a href='/off'>Turn display OFF</a> &middot; ")
    p.append("<a href='/reboot'>Reboot board</a></p>")
    p.append("<p style='color:#666'>Admin at http://" + ip +
             "/ &middot; settings save to config.json</p>")
    p.append("</body></html>")
    return "".join(p)


def apply_save(body):
    global changed
    data = parse_form(body)
    apt = (data.get("airport") or "").strip().upper()
    if apt:
        cfg["airport"] = apt
    if data.get("mode") in ("cycle", "preferred"):
        cfg["mode"] = data["mode"]
    try:
        iv = int(data.get("interval", cfg.get("interval", 0)))
        cfg["interval"] = max(0, min(iv, 21600))
    except Exception:
        pass
    pref = []
    for name in cfg.get("pages", []):
        if "pref_" + name in data:
            pref.append(name)
    if pref:
        cfg["preferred"] = pref
    cfg["overnight"] = "overnight" in data
    if data.get("off_start"):
        cfg["off_start"] = data["off_start"]
    if data.get("off_end"):
        cfg["off_end"] = data["off_end"]
    save_cfg()
    changed = True
    print("config saved via admin:", cfg)


def send_response(cl, body, ctype="text/html"):
    try:
        cl.send("HTTP/1.0 200 OK\r\nContent-Type: " + ctype +
                "\r\nConnection: close\r\n\r\n")
        cl.send(body)
    except Exception:
        pass


def redirect_home(cl):
    try:
        cl.send("HTTP/1.0 303 See Other\r\nLocation: /\r\n"
                "Connection: close\r\n\r\n")
    except Exception:
        pass


def serve_once():
    # Handle at most one pending admin request; never blocks long.
    global changed
    try:
        cl, _ = server.accept()
    except Exception:
        return
    try:
        cl.settimeout(2)
        req = b""
        while b"\r\n\r\n" not in req and len(req) < 8192:
            chunk = cl.recv(1024)
            if not chunk:
                break
            req += chunk
        text = req.decode("utf-8", "ignore")
        line = text.split("\r\n")[0]
        parts = line.split(" ")
        method = parts[0] if len(parts) > 0 else ""
        path = parts[1] if len(parts) > 1 else "/"
        print("admin:", method, path)
        if method == "POST" and path.startswith("/save"):
            body = text.split("\r\n\r\n", 1)[1] if "\r\n\r\n" in text \
                else ""
            # Body may arrive in later packets than the headers;
            # read until Content-Length is satisfied.
            want = 0
            for hline in text.split("\r\n\r\n", 1)[0].split("\r\n"):
                if hline.lower().startswith("content-length:"):
                    try:
                        want = int(hline.split(":", 1)[1].strip())
                    except Exception:
                        want = 0
            tries = 0
            while len(body) < want and tries < 5:
                try:
                    more = cl.recv(1024)
                    if not more:
                        break
                    body += more.decode("utf-8", "ignore")
                except Exception:
                    break
                tries += 1
            apply_save(body)
            send_response(cl, "<html><body><h3>Saved.</h3>"
                          "<p><a href='/'>Back to admin</a></p>"
                          "</body></html>")
        elif path.startswith("/off"):
            cfg["display_off"] = True
            save_cfg()
            changed = True
            redirect_home(cl)
        elif path.startswith("/on"):
            cfg["display_off"] = False
            save_cfg()
            changed = True
            redirect_home(cl)
        elif path.startswith("/reboot"):
            send_response(cl, "<html><body><h3>Rebooting...</h3>"
                          "</body></html>")
            try:
                cl.close()
            except Exception:
                pass
            time.sleep(1)
            machine.reset()
        else:
            send_response(cl, html_page())
    except Exception as e:
        print("admin request failed:", e)
    try:
        cl.close()
    except Exception:
        pass


def start_server():
    global server
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("", 80))
    server.listen(2)
    server.settimeout(0.25)
    print("admin server on port 80")


def wait_with_server(seconds):
    # Sleep in short polls so the admin page stays responsive.
    # Returns "elapsed", "changed", or "overnight".
    global changed
    t0 = time.ticks_ms()
    total = int(seconds) * 1000
    while time.ticks_diff(time.ticks_ms(), t0) < total:
        serve_once()
        if changed:
            changed = False
            return "changed"
        if cfg.get("display_off"):
            return "changed"
        if in_overnight():
            return "overnight"
    return "elapsed"


# ------------------------------------------------------------ running
def run_page(name):
    # Import one page module, render it, then purge it and its fonts
    # so only one page's memory is resident at a time.
    # Returns the flight category ("weather" page: True), or None on
    # fetch failure.
    mod_name = PAGE_MODULES[name]
    result = None
    try:
        mod = __import__(mod_name)
        if name == "layout5":
            result = mod.render(cfg.get("airport"))
        else:
            result = mod.render(cfg.get("airport"))
    except Exception as e:
        print("page", name, "failed:", e)
        result = None
    for m in [mod_name] + FONT_MODULES:
        if m in sys.modules:
            del sys.modules[m]
    gc.collect()
    print("free RAM after", name, ":", gc.mem_free())
    return result


def interval_for(result):
    iv = cfg.get("interval", 0)
    if iv:
        return iv
    if isinstance(result, str):
        return AUTO_INTERVAL.get(result, 1800)
    return 1800


def run():
    load_cfg()
    # Join Wi-Fi, retrying forever with the error on the console;
    # the panel cannot show an admin URL until there is an IP.
    while True:
        try:
            join_wifi()
            break
        except Exception as e:
            print("wifi join failed, retry in 60 s:", e)
            time.sleep(60)
    try:
        ntptime.settime()
    except Exception as e:
        print("ntp failed (continuing):", e)
    start_server()
    ip = wlan.ifconfig()[0]

    draw_boot(ip)
    wait_with_server(60)

    blanked = False
    while True:
        load_cfg()
        if cfg.get("display_off"):
            if not blanked:
                draw_blank()
                blanked = True
            wait_with_server(30)
            continue
        blanked = False
        if in_overnight():
            print("overnight window - holding last image")
            wait_with_server(60)
            continue
        try:
            ntptime.settime()
        except Exception:
            pass
        pages = cfg.get("pages", [])
        if cfg.get("mode") == "preferred":
            pages = [p for p in cfg.get("preferred", [])] or pages
        for page in pages:
            if cfg.get("display_off") or in_overnight():
                break
            result = run_page(page)
            if result is None:
                draw_error(page, "No data from the weather service.")
                if wait_with_server(60) == "elapsed":
                    result = run_page(page)  # one retry, Pi behavior
                    if result is None:
                        continue
                else:
                    continue
            wait_with_server(interval_for(result))


run()
