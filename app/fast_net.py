import http.client
import json
import queue
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

DNS_CACHE_SECONDS = 600
DNS_WAIT_SECONDS = 8
CONNECT_TIMEOUT = 3
NEXT_ADDRESS_DELAY = 0.3
SLOW_DNS_SECONDS = 1.5
# On some PCs Windows takes ~20 s to find a new googlevideo.com server (the socket timeout does not cover it):
# the system lookup races with DNS over HTTPS (Google, Cloudflare) and the first answer wins.
_DOH_SERVERS = (
    ("DNS Google", "https://8.8.8.8/resolve?name={host}&type=A", {}),
    ("DNS Cloudflare", "https://1.1.1.1/dns-query?name={host}&type=A", {"Accept": "application/dns-json"}),
)

_dnsCache = {}
_dnsLock = threading.Lock()
_directOpener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_sslContext = None


def _context():
    global _sslContext
    if _sslContext is None:
        try:
            import certifi
            _sslContext = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            _sslContext = ssl.create_default_context()
    return _sslContext


def _ordered(addresses):
    unique = list(dict.fromkeys(addresses))
    return [address for address in unique if ":" not in address] + [address for address in unique if ":" in address]


def _systemLookup(host, family):
    return [info[4][0] for info in socket.getaddrinfo(host, 443, family, socket.SOCK_STREAM)]


def _dohLookup(host, template, headers):
    request = urllib.request.Request(template.format(host=urllib.parse.quote(host)), headers={"User-Agent": "Sonus", **headers})
    with _directOpener.open(request, timeout=DNS_WAIT_SECONDS) as response:
        answer = json.loads(response.read().decode("utf-8"))
    return [record["data"] for record in answer.get("Answer") or [] if record.get("type") == 1 and record.get("data")]


def resolveHost(host, timeout=DNS_WAIT_SECONDS):
    """IP addresses of host (IPv4 first): the system DNS and DNS over HTTPS race, the first answer wins."""
    with _dnsLock:
        cached = _dnsCache.get(host)
    if cached and time.time() - cached[0] < DNS_CACHE_SECONDS:
        return list(cached[1])
    try:
        socket.inet_pton(socket.AF_INET6 if ":" in host else socket.AF_INET, host)
        return [host]
    except OSError:
        pass
    startedAt = time.monotonic()
    answers = queue.Queue()

    def run(source, lookup, *args):
        try:
            addresses = lookup(host, *args)
        except Exception as error:
            answers.put((source, [], error))
            return
        elapsed = time.monotonic() - startedAt
        if source.startswith("sistema") and elapsed > SLOW_DNS_SECONDS:
            print(f"[Rete] DNS di Windows lento per {host}: {elapsed:.1f}s")
        if addresses:
            with _dnsLock:
                _dnsCache[host] = (time.time(), _ordered(addresses))
        answers.put((source, addresses, None))

    lookups = [("sistema IPv4", _systemLookup, socket.AF_INET), ("sistema", _systemLookup, socket.AF_UNSPEC)]
    lookups += [(name, _dohLookup, template, headers) for name, template, headers in _DOH_SERVERS]
    for lookup in lookups:
        threading.Thread(target=run, args=lookup, daemon=True).start()
    deadline = startedAt + timeout
    lastError = None
    for _ in lookups:
        try:
            source, addresses, error = answers.get(timeout=max(0.01, deadline - time.monotonic()))
        except queue.Empty:
            break
        if addresses:
            elapsed = time.monotonic() - startedAt
            if elapsed > SLOW_DNS_SECONDS or not source.startswith("sistema"):
                print(f"[Rete] {host} trovato in {elapsed:.1f}s ({source})")
            return _ordered(addresses)
        lastError = error
    raise OSError(f"indirizzo di {host} non trovato: {lastError or 'tempo scaduto'}")


def warmUrl(url):
    """Looks up the server of url in the background, so the first request does not wait for the DNS."""
    host = urllib.parse.urlsplit(url or "").hostname
    if not host:
        return

    def run():
        try:
            resolveHost(host)
        except Exception:
            pass

    threading.Thread(target=run, daemon=True).start()


def _connectFirst(addresses, port, timeout):
    """Tries the addresses one after another (a new one starts if the previous does not answer quickly):
    a server or an IPv6 route that does not answer costs a fraction of a second, not a whole timeout."""
    results = queue.Queue()
    lock = threading.Lock()
    state = {"done": False}
    connectTimeout = min(CONNECT_TIMEOUT, timeout)

    def attempt(address):
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(connectTimeout)
        try:
            sock.connect((address, port))
        except OSError as error:
            sock.close()
            results.put(error)
            return
        with lock:
            if state["done"]:
                sock.close()
                return
            state["done"] = True
        results.put(sock)

    candidates = list(addresses[:4])
    started = finished = 0
    lastError = None
    deadline = time.monotonic() + connectTimeout + NEXT_ADDRESS_DELAY * len(candidates)
    while finished < len(candidates):
        if started < len(candidates):
            threading.Thread(target=attempt, args=(candidates[started],), daemon=True).start()
            started += 1
        wait = NEXT_ADDRESS_DELAY if started < len(candidates) else deadline - time.monotonic()
        if wait <= 0:
            break
        try:
            item = results.get(timeout=wait)
        except queue.Empty:
            continue
        if isinstance(item, socket.socket):
            item.settimeout(timeout)
            return item
        finished += 1
        lastError = item
    with lock:
        state["done"] = True
    while not results.empty():
        item = results.get()
        if isinstance(item, socket.socket):
            item.settimeout(timeout)
            return item
    raise lastError or OSError("il server non risponde")


class _PinnedConnection(http.client.HTTPSConnection):
    def __init__(self, host, port, addresses, timeout):
        super().__init__(host, port, timeout=timeout, context=_context())
        self.addresses = addresses

    def connect(self):
        sock = _connectFirst(self.addresses, self.port, self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _Response:
    def __init__(self, connection, response):
        self.connection = connection
        self.response = response
        self.status = response.status
        self.headers = response.headers

    def read(self, size=None):
        return self.response.read(size)

    def close(self):
        try:
            self.response.close()
        finally:
            self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class _SetupError(Exception):
    """The direct way could not even reach the server (DNS, connection, certificate)."""


def _openDirect(url, headers, timeout, redirects, ipv4Only=False):
    parts = urllib.parse.urlsplit(url)
    try:
        addresses = resolveHost(parts.hostname)
        if ipv4Only:
            # A googlevideo link found over IPv4 works only from the same IPv4 address (IPv6 gives HTTP 403)
            addresses = [address for address in addresses if ":" not in address] or addresses
        connection = _PinnedConnection(parts.hostname, parts.port or 443, addresses, timeout)
        connection.connect()
    except Exception as error:
        raise _SetupError(str(error) or error.__class__.__name__) from error
    try:
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
    except Exception:
        connection.close()
        raise
    if response.status in (301, 302, 303, 307, 308) and response.getheader("Location") and redirects > 0:
        location = urllib.parse.urljoin(url, response.getheader("Location"))
        connection.close()
        return _openDirect(location, headers, timeout, redirects - 1, ipv4Only)
    if response.status >= 400:
        connection.close()
        raise urllib.error.HTTPError(url, response.status, response.reason, response.headers, None)
    return _Response(connection, response)


def openUrl(url, headers=None, timeout=15, ipv4Only=False):
    """Like urllib.request.urlopen for a GET, without waiting for a slow Windows DNS. Falls back to urllib
    (proxy, unusual networks) when the direct way does not work."""
    headers = dict(headers or {})
    headers.setdefault("User-Agent", "Mozilla/5.0")
    if urllib.parse.urlsplit(url).scheme == "https":
        try:
            return _openDirect(url, headers, timeout, 4, ipv4Only)
        except _SetupError as error:
            print(f"[Rete] collegamento diretto non riuscito ({error}), uso quello di sistema")
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout)
