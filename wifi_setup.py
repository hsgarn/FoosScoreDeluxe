#FoosScorePlusDeluxe - Wi-Fi setup captive portal.
#Ported from FoosScorePlus. Entered from the on-screen menu's "Wi-Fi Setup"
#item (Deluxe has a display and a working standalone mode, so unlike the base
#project this does NOT run automatically on a failed connection - that stays
#in standalone mode as before). Brings up an open access point, spoofs DNS so
#any phone/laptop that joins it gets the "sign in to network" captive-portal
#popup, and serves a one-field form that writes the chosen SSID/password into
#secrets.py before rebooting into normal station mode.
#Takes already-constructed Pin objects for the two team LEDs (rather than pin
#numbers) so a caller with other uses for those GPIOs can hand over Pin
#instances it already owns instead of this module creating its own. An
#optional on_ready(ssid, ip) callback lets the caller show the setup AP's
#name/address on its own display once the AP is up.
#
#NOTE: ap.config()'s keyword names (essid vs ssid, security vs authmode) have
#shifted across MicroPython releases - this targets the v1.28.0 rp2 firmware
#shipped alongside this file (RPI_PICO_W-20260406-v1.28.0.uf2 /
#RPI_PICO2_W-20260406-v1.28.0.uf2) but should be re-checked against the actual
#device before relying on it, since it has not been run on hardware.

import network
import socket
import select
import time
import machine

AP_IP = "192.168.4.1"
SECRETSFILE = "secrets.py"
LED_BLINK_MS = 500  #alternating team-LED interval while the portal waits for input


def _dns_reply(data, ip_bytes):
    #Answers every question with ip_bytes, regardless of the name asked for -
    #that's what makes every domain the client tries resolve to this device.
    transaction_id = data[0:2]
    flags = b"\x81\x80"
    qd_count = data[4:6]
    an_count = b"\x00\x01"
    ns_count = b"\x00\x00"
    ar_count = b"\x00\x00"
    header = transaction_id + flags + qd_count + an_count + ns_count + ar_count
    question = data[12:]
    answer = b"\xc0\x0c" + b"\x00\x01" + b"\x00\x01" + b"\x00\x00\x00\x3c" + b"\x00\x04" + ip_bytes
    return header + question + answer


def _urldecode(s):
    s = s.replace("+", " ")
    out = ""
    i = 0
    while i < len(s):
        if s[i] == "%" and i + 2 < len(s):
            try:
                out += chr(int(s[i + 1:i + 3], 16))
                i += 3
                continue
            except ValueError:
                pass
        out += s[i]
        i += 1
    return out


def _parse_form(body):
    fields = {}
    for pair in body.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            fields[_urldecode(k)] = _urldecode(v)
    return fields


def _save_network(ssid, password, existing):
    nets = [(s, p) for s, p in existing if s != ssid]
    nets.append((ssid, password))
    with open(SECRETSFILE, "w") as f:
        f.write("#WiFi networks to try, in order, until one connects.\n")
        f.write("NETWORKS = [\n")
        for s, p in nets:
            f.write("    (%r, %r),\n" % (s, p))
        f.write("]\n")


def _page(scanned_ssids, message=""):
    options = "".join('<option value="%s">' % s for s in scanned_ssids)
    return """<!DOCTYPE html><html><head><title>FoosScore Wi-Fi Setup</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{font-family:sans-serif;max-width:400px;margin:2em auto;padding:0 1em}
input{width:100%%;padding:.5em;margin:.3em 0 1em;box-sizing:border-box}
button{width:100%%;padding:.7em;font-size:1em}</style></head><body>
<h2>Connect FoosScore to Wi-Fi</h2>
<p>%s</p>
<form method="POST" action="/save">
<label>Network name (SSID)</label>
<input list="ssids" name="ssid" autocomplete="off" required>
<datalist id="ssids">%s</datalist>
<label>Password</label>
<input type="password" name="password">
<button type="submit">Save &amp; Connect</button>
</form></body></html>""" % (message, options)


def _success_page(ssid):
    return """<!DOCTYPE html><html><head><title>FoosScore Wi-Fi Setup</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="font-family:sans-serif;text-align:center;margin-top:3em">
<h2>Saved</h2><p>Restarting and connecting to "%s"&hellip;</p>
<p>You can close this page and reconnect your phone to your normal Wi-Fi.</p>
</body></html>""" % ssid


def _http_response(body):
    body_bytes = body.encode()
    header = ("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: %d\r\nConnection: close\r\n\r\n"
              % len(body_bytes))
    return header.encode() + body_bytes


def _handle_http(cl, scanned, existing):
    cl.settimeout(3)
    request = b""
    try:
        while b"\r\n\r\n" not in request:
            chunk = cl.recv(512)
            if not chunk:
                break
            request += chunk
    except OSError:
        return
    if not request:
        return

    header_part, _, body = request.partition(b"\r\n\r\n")
    lines = header_part.split(b"\r\n")
    try:
        method, path, _ = lines[0].decode().split(" ", 2)
    except ValueError:
        return

    if method == "POST" and path == "/save":
        content_length = 0
        for line in lines[1:]:
            if line.lower().startswith(b"content-length:"):
                content_length = int(line.split(b":", 1)[1].strip())
        try:
            while len(body) < content_length:
                more = cl.recv(content_length - len(body))
                if not more:
                    break
                body += more
        except OSError:
            pass

        fields = _parse_form(body.decode())
        ssid = fields.get("ssid", "").strip()
        password = fields.get("password", "")
        if ssid:
            _save_network(ssid, password, existing)
            cl.send(_http_response(_success_page(ssid)))
            cl.close()
            time.sleep(1)  #let the response reach the phone before the reset drops the AP
            machine.reset()
        else:
            cl.send(_http_response(_page(scanned, "SSID is required - please try again.")))
        return

    #Any other path - including the captive-portal probe URLs phones request
    #on their own (/generate_204, /hotspot-detect.html, etc.) - gets the setup
    #form. Returning content other than what those probes expect is what
    #makes the OS pop up the captive-portal browser automatically.
    cl.send(_http_response(_page(scanned)))


def run_captive_portal(wlan_sta, existing_networks, led1, led2, on_ready=None):
    print("No known Wi-Fi network reachable - starting setup access point.")

    scanned = []
    try:
        for net in wlan_sta.scan():
            ssid = net[0].decode("utf-8", "ignore")
            if ssid and ssid not in scanned:
                scanned.append(ssid)
    except OSError:
        pass
    try:
        mac_suffix = "".join("%02x" % b for b in wlan_sta.config("mac"))[-6:]
    except OSError:
        mac_suffix = "000000"
    wlan_sta.active(False)

    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.ifconfig((AP_IP, "255.255.255.0", AP_IP, AP_IP))
    ssid = "FoosScoreSetup-%s" % mac_suffix
    try:
        ap.config(essid=ssid, security=0)  #security=0 -> open network, no password needed to join setup AP
    except (ValueError, TypeError, OSError):
        ap.config(essid=ssid)
    print('Setup AP "%s" is up - connect a phone to it, then browse to http://%s/ if a setup page does not open automatically.' % (ssid, AP_IP))
    if on_ready:
        on_ready(ssid, AP_IP)

    dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dns.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    dns.bind(("0.0.0.0", 53))

    http = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    http.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    http.bind(("0.0.0.0", 80))
    http.listen(4)

    ip_bytes = bytes(int(x) for x in AP_IP.split("."))

    #Alternates the two team LEDs while waiting so the board visibly signals
    #"needs setup input" even though this version has no display.
    led1.value(1)
    led2.value(0)
    lastToggle = time.ticks_ms()

    while True:
        readable, _, _ = select.select([dns, http], [], [], 0.1)
        for r in readable:
            if r is dns:
                try:
                    data, addr = dns.recvfrom(512)
                    dns.sendto(_dns_reply(data, ip_bytes), addr)
                except OSError:
                    pass
            else:
                cl, _addr = http.accept()
                try:
                    _handle_http(cl, scanned, existing_networks)
                except OSError:
                    pass
                finally:
                    cl.close()

        if time.ticks_diff(time.ticks_ms(), lastToggle) >= LED_BLINK_MS:
            led1.value(not led1.value())
            led2.value(not led2.value())
            lastToggle = time.ticks_ms()
