# prov.py - Wi-Fi provisioning / rehoming for metar-micro, ported
# from the LS Lite Micro captive portal (blocking-socket version:
# this app has no asyncio loop).
#
# Setup mode starts its own open network, MetarMicro-Setup, and
# serves one page: pick the home network (or type its name), enter
# its password, save. A DNS catch-all answers every lookup with the
# board's address, which is what makes the phone pop the page up by
# itself. Saving writes ONLY wifi_cfg.py (SSID + PASSWORD) and
# reboots; the display's config.json settings are never touched.
#
# Entered from main.py when: the BOOT button is held just after
# power-up, an admin "Wi-Fi setup" reboot left its flag file, the
# saved credentials are blank/placeholder, or the saved network
# fails to join. run() serves until a save reboots the board; it
# returns only if setup itself fails to start, so the caller can
# fall through to running the display offline.
import socket
import time

import machine
import network
import uselect

AP_SSID = "MetarMicro-Setup"
AP_IP = "192.168.4.1"
PLACEHOLDER_SSID = "YOUR_WIFI_NAME"


# ------------------------------------------------------------ creds
def load_creds():
    """(ssid, password) from wifi_cfg.py, or (None, None)."""
    try:
        import wifi_cfg
        return wifi_cfg.SSID, wifi_cfg.PASSWORD
    except Exception:
        return None, None


def creds_usable(ssid):
    return bool(ssid) and ssid != PLACEHOLDER_SSID


def _py_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') \
        .replace("\n", " ").replace("\r", " ") + '"'


def save_wifi(ssid, password):
    """Write wifi_cfg.py - the board's ONLY stored Wi-Fi secret."""
    with open("wifi_cfg.py", "w") as f:
        f.write("# wifi_cfg.py - this board's Wi-Fi credentials.\n")
        f.write("# Written by the setup portal (prov.py); edit by\n")
        f.write("# hand only if you must.\n")
        f.write("SSID = %s\n" % _py_str(ssid))
        f.write("PASSWORD = %s\n" % _py_str(password))
    print("provisioning: saved Wi-Fi for", ssid)


# ------------------------------------------------------------ forms
def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def urldecode(s):
    out = ""
    i = 0
    while i < len(s):
        c = s[i]
        if c == "+":
            out += " "
            i += 1
        elif c == "%" and i + 2 < len(s) + 1 and i + 2 <= len(s) - 1 + 1:
            try:
                out += chr(int(s[i + 1:i + 3], 16))
                i += 3
            except ValueError:
                out += c
                i += 1
        else:
            out += c
            i += 1
    return out


def parse_form(body):
    form = {}
    if not body:
        return form
    if isinstance(body, bytes):
        body = body.decode()
    for pair in body.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            form[urldecode(k)] = urldecode(v)
    return form


def validate(form):
    """(ssid, password) from the setup form; ValueError with a
    user-facing message when something is off. The manual field
    wins over the scanned-list pick (hidden networks)."""
    ssid = ((form.get("ssid_manual") or "").strip()
            or (form.get("ssid") or "").strip())
    password = form.get("wifi_password") or ""
    if not ssid:
        raise ValueError("Pick a network from the list, or type its "
                         "name in the box below it.")
    if len(ssid) > 32:
        raise ValueError("That network name is too long - Wi-Fi "
                         "names are at most 32 characters.")
    if len(password) > 64:
        raise ValueError("That password is too long - Wi-Fi "
                         "passwords are at most 64 characters.")
    return ssid, password


# ------------------------------------------------------------- scan
def clean_scan(raw):
    """wlan.scan() output -> (ssid, rssi) pairs, strongest first.
    Hidden networks, duplicates and undecodable names are dropped;
    the page's manual field covers anything the scan cannot name."""
    best = {}
    for entry in raw or ():
        try:
            ssid = entry[0].decode("utf-8").strip()
            rssi = int(entry[3])
        except Exception:
            continue
        if not ssid:
            continue
        if ssid not in best or rssi > best[ssid]:
            best[ssid] = rssi
    return sorted(best.items(), key=lambda kv: -kv[1])


def scan(sta):
    """One scan, cleaned for the page. Never raises."""
    try:
        return clean_scan(sta.scan())
    except Exception as e:
        print("provisioning scan failed:", e)
        return []


# -------------------------------------------------------------- DNS
def dns_reply(query):
    """Answer one DNS query packet with AP_IP, whatever name was
    asked - in setup mode every lookup lands on the board, which is
    what makes the phone open the setup page by itself. None for a
    malformed query (drop those)."""
    try:
        if len(query) < 12:
            return None
        if ((query[4] << 8) | query[5]) < 1:
            return None
        i = 12
        while True:
            if i >= len(query):
                return None
            n = query[i]
            i += 1
            if n == 0:
                break
            if n & 0xC0:
                return None
            i += n
        if i + 4 > len(query):
            return None
        question = query[12:i + 4]
        flags = 0x8000 | (query[2] & 0x79) | 0x0080
        resp = bytearray()
        resp += query[0:2]
        resp += bytes((flags >> 8, flags & 0xFF))
        resp += b"\x00\x01"
        resp += b"\x00\x01"
        resp += b"\x00\x00\x00\x00"
        resp += question
        resp += b"\xc0\x0c"
        resp += b"\x00\x01"
        resp += b"\x00\x01"
        resp += b"\x00\x00\x00\x3c"
        resp += b"\x00\x04"
        for part in AP_IP.split("."):
            resp.append(int(part))
        return bytes(resp)
    except Exception:
        return None


# ------------------------------------------------------------- page
_PAGE = """<!DOCTYPE html><html><head><title>METAR Micro - WiFi Setup</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body { font-family: sans-serif; max-width: 34em; margin: 1em auto; padding: 0 1em; }
input, select { font-size: 1em; padding: 0.3em; width: 100%; box-sizing: border-box; }
button { font-size: 1em; padding: 0.4em 1.2em; }
</style></head><body>
<h2>METAR Micro &mdash; WiFi Setup</h2>
%%ERR%%
<p>This display is not on a Wi-Fi network. You are connected to its
own setup network, <strong>MetarMicro-Setup</strong>. Tell it which
network to join and that network's password; it saves them, restarts,
and joins &mdash; this setup network then disappears, so reconnect
your phone to your normal Wi-Fi afterwards.</p>
<form method="post" action="/save">
<p><label for="ssid">Network</label><br>
<select name="ssid" id="ssid">%%OPTIONS%%</select></p>
<p><label for="ssid_manual">... or type the name instead (hidden networks)</label><br>
<input name="ssid_manual" id="ssid_manual" autocomplete="off"></p>
<p><label for="wifi_password">Wi-Fi password (blank for an open network)</label><br>
<input name="wifi_password" id="wifi_password" type="password"></p>
<p><label><input type="checkbox" id="show_pw" style="width:auto"
onchange="document.getElementById('wifi_password').type = this.checked ? 'text' : 'password'">
Show password</label></p>
<p><button type="submit">Save and restart</button></p>
</form>
<p><a href="/rescan">Rescan for networks</a></p>
</body></html>"""

_SAVED_PAGE = """<!DOCTYPE html><html><head><title>Saved</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body { font-family: sans-serif; max-width: 34em; margin: 1em auto; padding: 0 1em; }</style>
</head><body><h2>Saved &mdash; restarting</h2>
<p>The display is restarting and will join <strong>%%SSID%%</strong>.
This setup network is about to disappear; reconnect your phone to
your normal Wi-Fi. The display's admin page address will be shown on
its boot screen.</p></body></html>"""


def page(nets, error=""):
    options = "".join(
        '<option value="%s">%s (%d dBm)</option>'
        % (_esc(ssid), _esc(ssid), rssi) for ssid, rssi in nets)
    if not options:
        options = '<option value="">(no networks found)</option>'
    err = ('<p style="color:#b00"><strong>%s</strong></p>'
           % _esc(error)) if error else ""
    return _PAGE.replace("%%ERR%%", err).replace("%%OPTIONS%%", options)


# ------------------------------------------------------------ server
def _send(conn, status, ctype, body):
    if isinstance(body, str):
        body = body.encode()
    head = ("HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
            "Connection: close\r\n\r\n" % (status, ctype, len(body)))
    conn.write(head.encode())
    if body:
        conn.write(body)


def _redirect(conn):
    conn.write(b"HTTP/1.1 302 Found\r\nLocation: http://"
               + AP_IP.encode() + b"/\r\nContent-Length: 0\r\n\r\n")


def _handle_http(conn, sta, state):
    """One setup-mode HTTP request. Returns True when a save has
    been accepted and the board should reboot."""
    conn.settimeout(5)
    try:
        req = b""
        while b"\r\n\r\n" not in req:
            chunk = conn.recv(1024)
            if not chunk:
                return False
            req += chunk
            if len(req) > 16384:
                return False
        head, _, rest = req.partition(b"\r\n\r\n")
        lines = head.decode().split("\r\n")
        parts = lines[0].split(" ")
        method = parts[0]
        path = parts[1] if len(parts) > 1 else "/"
        clen = 0
        for ln in lines[1:]:
            if ln.lower().startswith("content-length:"):
                try:
                    clen = int(ln.split(":", 1)[1].strip())
                except ValueError:
                    clen = 0
        print("prov http:", method, path)
        if method == "POST" and path == "/save":
            body = rest
            while len(body) < clen:
                chunk = conn.recv(1024)
                if not chunk:
                    break
                body += chunk
            try:
                ssid, password = validate(parse_form(body[:clen]))
            except ValueError as e:
                _send(conn, "200 OK", "text/html",
                      page(state["nets"], str(e)))
                return False
            save_wifi(ssid, password)
            _send(conn, "200 OK", "text/html",
                  _SAVED_PAGE.replace("%%SSID%%", _esc(ssid)))
            return True
        if path == "/" or path == "/rescan":
            if path == "/rescan":
                state["nets"] = scan(sta)
            _send(conn, "200 OK", "text/html", page(state["nets"]))
            return False
        _redirect(conn)
        return False
    except Exception as e:
        print("prov http error:", e)
        return False
    finally:
        try:
            conn.close()
        except OSError:
            pass


def run():
    """Serve setup mode until a save reboots the board. Returns
    only when setup itself cannot start (AP failure), letting the
    caller fall through to an offline run."""
    sta = network.WLAN(network.STA_IF)
    # Drop any pending join before scanning - a radio still retrying
    # a failed join scans empty (learned on LS Lite Micro, Nov 5).
    try:
        sta.disconnect()
    except Exception:
        pass
    sta.active(True)
    state = {"nets": []}
    for _ in range(3):
        state["nets"] = scan(sta)
        if state["nets"]:
            break
        time.sleep(1)
    ap = network.WLAN(network.AP_IF)
    try:
        ap.active(True)
        try:
            ap.config(essid=AP_SSID, authmode=0)   # open network
        except Exception:
            ap.config(essid=AP_SSID)
    except Exception as e:
        print("provisioning: AP failed to start:", e)
        return
    print("provisioning: join Wi-Fi '%s', open http://%s/"
          % (AP_SSID, AP_IP))
    dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dns.bind(("0.0.0.0", 53))
    dns.setblocking(False)
    web = socket.socket()
    web.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    web.bind(("0.0.0.0", 80))
    web.listen(4)
    web.setblocking(False)
    poller = uselect.poll()
    poller.register(dns, uselect.POLLIN)
    poller.register(web, uselect.POLLIN)
    while True:
        for obj, _ev in poller.poll(1000):
            if obj is dns:
                try:
                    data, addr = dns.recvfrom(512)
                except OSError:
                    continue
                resp = dns_reply(data)
                if resp:
                    try:
                        dns.sendto(resp, addr)
                    except OSError:
                        pass
            else:
                try:
                    conn, _addr = web.accept()
                except OSError:
                    continue
                if _handle_http(conn, sta, state):
                    print("provisioning: saved, rebooting")
                    time.sleep(1)
                    machine.reset()
                    return
