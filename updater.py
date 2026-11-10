# updater.py - GitHub self-update for metar-micro, ported from the
# LS Lite Micro / LED ticker machinery (v6.1 manifest design).
#
# The board has no git, so this is the file-based equivalent of
# pull-and-restart: check the repo (after boot, then hourly),
# compare each managed file's git blob SHA against GitHub's listing,
# and flag "update available" in the admin page. Update now
# downloads the changed files, verifies each blob SHA, swaps them
# in (old copies kept as .bak) and reboots.
#
# The managed file list lives in the repo as update_files.txt and is
# read fresh on every check/apply, so a release that adds a module
# lists it there and even an old updater learns about it. The
# built-in UPDATE_FILES is only the fallback when that read fails.
# wifi_cfg.py (the board's Wi-Fi password) and config.json (its
# settings) are NEVER in the list - they belong to the board.
import binascii
import hashlib
import json
import os
import socket
import ssl
import time

GITHUB_REPO = "markyharris/metar-micro"
UPDATE_FILES = ("main.py", "updater.py", "prov.py", "fetch.py",
                "epd7in5b.py",
                "textdraw.py", "show_layout0.py", "show_layout1.py",
                "show_layout2.py", "show_layout3.py", "show_layout4.py",
                "show_layout5.py", "show_layout7.py", "show_layout8.py",
                "show_weather.py",
                "f14.py", "f14b.py", "f16b.py", "f20.py", "f20b.py",
                "f24.py", "f24b.py", "f36b.py", "f48b.py",
                "f96cat.py", "f96wx.py", "fcat.py", "fcat144.py")
UPDATE_MANIFEST_URL = ("https://raw.githubusercontent.com/%s/main/"
                       "update_files.txt" % GITHUB_REPO)
UPDATE_CHECK_MS = 3600 * 1000
UPDATE_TIMEOUT_S = 20
MAX_API_BYTES = 65536
MAX_CODE_BYTES = 262144
UPDATE_AGENT = "metar-micro/1.0 (personal ESP32 e-paper METAR display)"
STATE = {"available": False, "files": 0, "failed": "", "applying": False,
         "checked": False}
_last_check = None


class _ChunkedStream:
    """readinto() wrapper that decodes HTTP chunked encoding."""

    def __init__(self, sock):
        self._s = sock
        self._buf = bytearray()
        self._left = -1
        self._eof = False

    def _readline(self):
        line = bytearray()
        while not line.endswith(b"\r\n"):
            ch = self._s.read(1)
            if not ch:
                break
            line += ch
        return bytes(line)

    def readinto(self, b):
        if self._eof:
            return 0
        while not self._buf:
            if self._left == -1:
                line = self._readline()
                try:
                    self._left = int(line.strip().split(b";")[0], 16)
                except (ValueError, IndexError):
                    self._eof = True
                    return 0
                if self._left == 0:
                    while True:
                        t = self._readline()
                        if t in (b"\r\n", b"\n", b""):
                            break
                    self._eof = True
                    return 0
            data = self._s.read(min(self._left, 4096))
            if not data:
                self._eof = True
                return 0
            self._left -= len(data)
            self._buf += data
            if self._left == 0:
                self._readline()
                self._left = -1
        n = min(len(b), len(self._buf))
        b[:n] = self._buf[:n]
        # Slice-rebind, not del buf[:n]: MicroPython bytearray has
        # no item deletion.
        self._buf = self._buf[n:]
        return n


def blob_sha_bytes(data):
    """git blob SHA-1 of a byte string - the hash GitHub lists for
    every file in a repo."""
    h = hashlib.sha1()
    h.update(b"blob " + str(len(data)).encode() + b"\x00")
    h.update(data)
    return binascii.hexlify(h.digest()).decode()


def file_blob_sha(path):
    """Blob SHA of a file on the board, or None if it doesn't exist."""
    try:
        size = os.stat(path)[6]
    except OSError:
        return None
    h = hashlib.sha1()
    h.update(b"blob " + str(size).encode() + b"\x00")
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(2048)
                if not chunk:
                    break
                h.update(chunk)
    except OSError:
        return None
    return binascii.hexlify(h.digest()).decode()


def https_get(url, max_bytes, depth=0):
    """Small HTTPS GET: body bytes, or None on any failure.
    Follows up to 2 redirects."""
    if depth > 2 or not url.startswith("https://"):
        return None
    rest = url[len("https://"):]
    host, _, p = rest.partition("/")
    path = "/" + p
    try:
        addr = socket.getaddrinfo(host, 443, 0, socket.SOCK_STREAM)[0][-1]
        sock = socket.socket()
        sock.settimeout(UPDATE_TIMEOUT_S)
        sock.connect(addr)
        if hasattr(ssl, "wrap_socket"):
            sock = ssl.wrap_socket(sock, server_hostname=host)
        else:
            sock = ssl.create_default_context().wrap_socket(
                sock, server_hostname=host)
        try:
            req = ("GET %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: %s\r\n"
                   "Accept-Encoding: identity\r\n"
                   "Connection: close\r\n\r\n"
                   % (path, host, UPDATE_AGENT))
            sock.write(req.encode())
            head = bytearray()
            while not head.endswith(b"\r\n\r\n"):
                ch = sock.read(1)
                if not ch:
                    return None
                head += ch
                if len(head) > 8192:
                    return None
            lines = bytes(head).decode().split("\r\n")
            status = int(lines[0].split(" ")[1])
            headers = {}
            for ln in lines[1:]:
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            if status in (301, 302, 303, 307, 308):
                return https_get(headers.get("location", ""),
                                 max_bytes, depth + 1)
            if status != 200:
                print("update GET %s -> HTTP %d" % (path, status))
                return None
            if "chunked" in headers.get("transfer-encoding", ""):
                body = _ChunkedStream(sock)
            else:
                body = sock
            out = bytearray()
            buf = bytearray(2048)
            while len(out) <= max_bytes:
                n = body.readinto(buf)
                if not n:
                    break
                out += buf[:n]
            if len(out) > max_bytes:
                print("update GET %s: body too large" % path)
                return None
            return bytes(out)
        finally:
            try:
                sock.close()
            except OSError:
                pass
    except Exception as e:
        print("update GET failed:", e)
        return None


def parse_listing(data):
    """GitHub contents-listing JSON -> {name: {sha, download_url}}
    for files only, or None if it doesn't parse."""
    if data is None:
        return None
    try:
        if isinstance(data, bytes):
            data = data.decode()
        items = json.loads(data)
    except (ValueError, TypeError):
        return None
    if not isinstance(items, list):
        return None
    out = {}
    for it in items:
        if isinstance(it, dict) and it.get("type") == "file":
            out[it.get("name", "")] = {
                "sha": it.get("sha", ""),
                "download_url": it.get("download_url") or ""}
    return out


def fetch_listing():
    # One retry: GitHub's edge occasionally drops the TLS connection
    # mid-handshake (seen on the map boards).
    for attempt in (1, 2):
        listing = parse_listing(https_get(
            "https://api.github.com/repos/%s/contents/" % GITHUB_REPO,
            MAX_API_BYTES))
        if listing is not None:
            return listing
        if attempt == 1:
            time.sleep(2)
    return None


def fetch_manifest():
    """The repo's update_files.txt: the board files the updater
    manages, one per line, read fresh on every check/apply. Only
    plain .py names are accepted, so wifi_cfg.py / config.json can
    never be pulled in. None on any failure (caller falls back to
    the built-in UPDATE_FILES)."""
    try:
        data = https_get(UPDATE_MANIFEST_URL, MAX_API_BYTES)
    except Exception:
        data = None
    if not data:
        return None
    try:
        text = data.decode() if isinstance(data, bytes) else data
    except Exception:
        return None
    names = []
    for line in text.split("\n"):
        name = line.strip()
        if name.endswith(".py") and "/" not in name \
                and name not in names:
            names.append(name)
    return names or None


# Never managed by the updater, whatever any list says: the board's
# Wi-Fi credentials and its settings belong to the board.
NEVER_UPDATE = ("wifi_cfg.py", "config.json")


def update_file_list():
    names = fetch_manifest() or list(UPDATE_FILES)
    return [n for n in names if n not in NEVER_UPDATE]


def changed_files(listing):
    """(name, info) pairs whose repo SHA differs from the board's."""
    plan = []
    for name in update_file_list():
        info = listing.get(name)
        if info and file_blob_sha(name) != info["sha"]:
            plan.append((name, info))
    return plan


def check_update():
    """Refresh STATE from GitHub. Quiet on network failure."""
    global _last_check
    _last_check = time.ticks_ms()
    listing = fetch_listing()
    if listing is None:
        return
    plan = changed_files(listing)
    STATE["checked"] = True
    STATE["available"] = len(plan) > 0
    STATE["files"] = len(plan)
    if not plan:
        STATE["failed"] = ""
    print("update check: %s" % (
        ("%d file(s) changed on GitHub" % len(plan)) if plan
        else "code is current with GitHub"))


def maybe_check():
    """Run the hourly check when due (first call checks promptly).
    Called from main's wait loop; blocks for the check's duration."""
    if _last_check is None or \
            time.ticks_diff(time.ticks_ms(), _last_check) \
            >= UPDATE_CHECK_MS:
        check_update()


def apply_update():
    """Download the changed code files, verify each blob SHA, swap
    them in (.bak kept) and reboot. Any failure before the swap
    leaves the running code untouched and records why in STATE.
    Returns True when a reboot is coming (success)."""
    import machine
    if STATE["applying"]:
        return False
    STATE["applying"] = True
    staged = []
    try:
        listing = fetch_listing()
        if listing is None:
            raise Exception("could not reach GitHub")
        plan = changed_files(listing)
        if not plan:
            STATE["available"] = False
            STATE["files"] = 0
            STATE["failed"] = ""
            return False
        for name, info in plan:
            data = https_get(info["download_url"], MAX_CODE_BYTES)
            if data is None:
                time.sleep(2)   # one retry, as in the check
                data = https_get(info["download_url"], MAX_CODE_BYTES)
            if data is None:
                raise Exception("download of %s failed" % name)
            if blob_sha_bytes(data) != info["sha"]:
                raise Exception("verification failed for %s" % name)
            with open(name + ".new", "wb") as f:
                f.write(data)
            staged.append(name)
        for name in staged:
            if file_blob_sha(name) is not None:
                try:
                    os.remove(name + ".bak")
                except OSError:
                    pass
                os.rename(name, name + ".bak")
            try:
                os.rename(name + ".new", name)
            except OSError:
                try:
                    os.rename(name + ".bak", name)
                except OSError:
                    pass
                raise Exception("could not install %s" % name)
        STATE["available"] = False
        STATE["files"] = 0
        STATE["failed"] = ""
        print("update applied (%s); rebooting" % ", ".join(staged))
        time.sleep(1)
        machine.reset()
        return True
    except Exception as e:
        STATE["failed"] = ("The last update attempt failed: %s"
                           % e)
        print("update failed:", e)
        for name in staged:
            try:
                os.remove(name + ".new")
            except OSError:
                pass
        return False
    finally:
        STATE["applying"] = False
