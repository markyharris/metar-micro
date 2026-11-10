# fetch.py - small robust HTTPS GET + JSON for the page scripts.
#
# Why not urequests: aviationweather.gov sits behind an Azure
# gateway that intermittently hands back an empty response status
# line (Nov 10, 2026: "HTTP error: BadStatusLine:" on random pages,
# always fine on the next try minutes later). urequests raises on
# that and never retries, so a one-off gateway hiccup became a full
# FETCH FAILED screen. This module does a raw-socket HTTP/1.1 GET,
# validates the status line, and retries the whole request on a
# fresh connection before giving up. Same machinery as updater.py,
# shared here for the data pages.
import json
import socket
import ssl
import time

TIMEOUT_S = 20
MAX_BYTES = 262144
AGENT = "metar-micro/1.0 (personal ESP32 e-paper METAR display)"


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
        self._buf = self._buf[n:]
        return n


def _once(url):
    """One attempt: (status, body bytes). Raises on any transport
    problem, including an empty or garbled status line."""
    if not url.startswith("https://"):
        raise ValueError("https only")
    rest = url[len("https://"):]
    host, _, p = rest.partition("/")
    path = "/" + p
    addr = socket.getaddrinfo(host, 443, 0, socket.SOCK_STREAM)[0][-1]
    sock = socket.socket()
    sock.settimeout(TIMEOUT_S)
    sock.connect(addr)
    if hasattr(ssl, "wrap_socket"):
        sock = ssl.wrap_socket(sock, server_hostname=host)
    else:
        sock = ssl.create_default_context().wrap_socket(
            sock, server_hostname=host)
    try:
        req = ("GET %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: %s\r\n"
               "Accept-Encoding: identity\r\n"
               "Connection: close\r\n\r\n" % (path, host, AGENT))
        sock.write(req.encode())
        head = bytearray()
        while not head.endswith(b"\r\n\r\n"):
            ch = sock.read(1)
            if not ch:
                raise OSError("empty response (no status line)")
            head += ch
            if len(head) > 8192:
                raise OSError("response head too large")
        lines = bytes(head).decode().split("\r\n")
        if not lines[0].startswith("HTTP/"):
            raise OSError("bad status line: %r" % lines[0][:40])
        status = int(lines[0].split(" ")[1])
        headers = {}
        for ln in lines[1:]:
            if ":" in ln:
                k, v = ln.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        if "chunked" in headers.get("transfer-encoding", ""):
            body = _ChunkedStream(sock)
        else:
            body = sock
        out = bytearray()
        buf = bytearray(2048)
        while len(out) <= MAX_BYTES:
            n = body.readinto(buf)
            if not n:
                break
            out += buf[:n]
        if len(out) > MAX_BYTES:
            raise OSError("body too large")
        return status, bytes(out)
    finally:
        try:
            sock.close()
        except OSError:
            pass


def get(url, retries=2):
    """(status, body) with fresh-connection retries on transport
    failure (2 retries = 3 attempts, 2 s apart). HTTP error
    statuses are returned, not retried - the caller decides."""
    last = None
    for attempt in range(retries + 1):
        try:
            return _once(url)
        except Exception as e:
            last = e
            print("fetch attempt %d failed: %s" % (attempt + 1, e))
            if attempt < retries:
                time.sleep(2)
    raise last


def get_json(url):
    """(status, parsed) - parsed is None unless the status is 200
    and the body parses as JSON."""
    status, body = get(url)
    if status != 200:
        return status, None
    try:
        return status, json.loads(body.decode())
    except Exception as e:
        print("json parse failed:", e)
        return status, None
