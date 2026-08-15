#iRefFoos Remote Command API client - HTTP/1.1 over a keep-alive ssl-wrapped raw socket, plus
#the ring-buffer queue serviced by main.py's core1Worker alongside the LED-strip queue rather
#than its own dedicated thread. Split out of main.py (v3.01) as its own small compile unit.
import socket
import time
import gc
import _thread

#ssl is frozen into current Pico W/2W MicroPython firmware; older builds name it ussl.
try:
    import ssl
except ImportError:
    try:
        import ussl as ssl
    except ImportError:
        ssl = None

from debuglog import debug

IREF_QUEUE_SIZE = 8

class IrefClient:
    def __init__(self,url,api_key,home_team,device_template,table_nbr):
        self.url = url
        self.api_key = api_key
        self.home_team = home_team
        self.device_template = device_template
        self.table_nbr = table_nbr
        self.enabled = False
        self.scheme = None
        self.host = None
        self.port = None
        self._socket = None
        self._queue = [None] * IREF_QUEUE_SIZE
        self._head = 0
        self._tail = 0
        self._count = 0
        self._lock = _thread.allocate_lock()

    def try_configure(self):
        #Parses self.url; call only after confirming ssl/APIKEY/IREF flag are all present.
        #Returns True and sets self.enabled on success; returns False (self.enabled untouched)
        #on failure so the caller can report it and leave iRefFoos reporting disabled.
        try:
            self.scheme,self.host,self.port = self._parse_url(self.url)
        except Exception:
            return False
        self.enabled = True
        return True

    def update_table(self,table_nbr):
        self.table_nbr = table_nbr

    def device_id(self):
        return self.device_template.replace("{n}",str(self.table_nbr))

    def enqueue(self,team):
        #called from the main loop only, never from an IRQ handler
        if not self.enabled:
            return
        command = "score_home_up" if team == self.home_team else "score_away_up"
        dropped = True
        self._lock.acquire()
        try:
            if self._count < IREF_QUEUE_SIZE:
                self._queue[self._head] = command
                self._head = (self._head + 1) % IREF_QUEUE_SIZE
                self._count += 1
                dropped = False
        finally:
            self._lock.release()
        if dropped:
            print("iRefFoos queue full - dropped " + command + ".")

    def queue_depth(self):
        return self._count

    def _dequeue(self):
        self._lock.acquire()
        try:
            if self._count == 0:
                return None
            command = self._queue[self._tail]
            self._queue[self._tail] = None
            self._tail = (self._tail + 1) % IREF_QUEUE_SIZE
            self._count -= 1
            return command
        finally:
            self._lock.release()

    @staticmethod
    def _parse_url(url):
        scheme,_,rest = url.partition("://")
        hostport = rest.split("/",1)[0]
        host,_,portStr = hostport.partition(":")
        port = int(portStr) if portStr else (443 if scheme == "https" else 80)
        return scheme,host,port

    def _connect_socket(self):
        addr = socket.getaddrinfo(self.host,self.port)[0][-1]
        sock = socket.socket()
        sock.settimeout(10)
        sock.connect(addr)
        if self.scheme == "https":
            sock = ssl.wrap_socket(sock,server_hostname=self.host)
        self._socket = sock

    def _close_socket(self):
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

    def _request(self,path):
        if self._socket is None:
            self._connect_socket()
        req = "GET " + path + " HTTP/1.1\r\nHost: " + self.host + "\r\nConnection: keep-alive\r\n\r\n"
        self._socket.write(req.encode())
        line = self._socket.readline()
        if not line:
            raise OSError("iRefFoos: connection closed by server")
        status = int(line.decode().split(" ",2)[1])
        contentLength = 0
        chunked = False
        while True:
            header = self._socket.readline()
            if header in (b"\r\n",b"\n",b""):
                break
            headerText = header.decode().strip().lower()
            if headerText.startswith("content-length:"):
                contentLength = int(headerText.split(":",1)[1].strip())
            elif headerText.startswith("transfer-encoding:") and "chunked" in headerText:
                chunked = True
        if chunked:
            raise OSError("iRefFoos: chunked response unsupported")
        remaining = contentLength
        while remaining > 0:
            chunk = self._socket.read(min(remaining,512))
            if not chunk:
                break
            remaining -= len(chunk)
        return status

    def service_one(self):
        #services exactly one queued iRefFoos command; no-op if the queue is empty
        command = self._dequeue()
        if command is None:
            return
        path = "/api/remote/" + command + "?apiKey=" + self.api_key + "&deviceId=" + self.device_id()
        for attempt in range(2):
            try:
                status = self._request(path)
                debug("iRefFoos: {} -> {} (HTTP {})",command,self.device_id(),status,level="DEBUG")
                break
            except Exception as ex:
                self._close_socket()
                if attempt == 0:
                    time.sleep(1)
                else:
                    print("iRefFoos: " + command + " failed - dropped: " + str(ex))
        gc.collect()
