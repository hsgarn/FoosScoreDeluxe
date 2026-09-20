#FoosScorePlusDeluxe - Wi-Fi setup captive portal.
#Ported from FoosScorePlus. Entered from the on-screen menu's "Wi-Fi Setup"
#item (Deluxe has a display and a working standalone mode, so unlike the base
#project this does NOT run automatically on a failed connection - that stays
#in standalone mode as before). Brings up an open access point, spoofs DNS so
#any phone/laptop that joins it gets the "sign in to network" captive-portal
#popup, and serves a form that writes the chosen SSID/password (and an
#optional admin password - see below) into secrets.py before rebooting into
#normal station mode.
#The AP/DNS/HTTP primitives and form helpers below are intentionally not
#private (no leading underscore): configweb.py (the full config editor,
#entered via the menu's "Start Config Web" item) reuses them rather than
#duplicating socket/DNS/HTTP plumbing, the same relationship FoosScorePlus's
#wifi_setup.py has with its configPortal.py.
#The optional admin password set here (or left blank - it's not required to
#connect to Wi-Fi) is what later gates access to that full config editor;
#save_network() always rewrites both NETWORKS and ADMINPASSWORD together so a
#plain Wi-Fi-only save here never silently drops a password set earlier from
#within the config editor.
#Takes already-constructed Pin objects for the two team LEDs (rather than pin
#numbers) so a caller with other uses for those GPIOs can hand over Pin
#instances it already owns instead of this module creating its own. An
#optional on_ready(ssid, ip) callback lets the caller show the setup AP's
#name/address on its own display once the AP is up. An optional wdt (a
#machine.WDT, or None if the caller runs without one) is fed once per loop
#iteration - this function blocks in its own loop until a network is
#submitted, easily past a watchdog's timeout otherwise.
#An optional action_pressed() (a zero-arg callable returning True while the menu's Action
#button, PB3, is physically held down) lets that button cancel back out to the caller without
#submitting anything. This polls the raw pin instead of going through main.py's usual
#IRQ/event-queue path deliberately: that path's own debounce only gets cleared by
#serviceDebounce(), which runs once per main-loop iteration - and the main loop is exactly
#what's paused while this function blocks in its own loop, so the debounce flag set by the
#very first press (the one that selected "Wi-Fi Setup") would otherwise never clear, silently
#swallowing every later press at the IRQ handler itself before it could reach the queue.
#Returning this way (rather than machine.reset(), used on a successful save) leaves both
#radios in a disrupted state - see the caller's comment for how it recovers.
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


def dns_reply(data, ip_bytes):
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


def urldecode(s):
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


def parse_form(body):
    fields = {}
    for pair in body.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            fields[urldecode(k)] = urldecode(v)
    return fields


def _write_secrets(networks, admin_password):
    #Full-file rewrite of secrets.py, always including both NETWORKS and ADMINPASSWORD -
    #shared by save_network/remove_network/save_admin_password below so a save from any of
    #them never silently clobbers the other field.
    with open(SECRETSFILE, "w") as f:
        f.write("#WiFi networks to try, in order, until one connects.\n")
        f.write("NETWORKS = [\n")
        for s, p in networks:
            f.write("    (%r, %r),\n" % (s, p))
        f.write("]\n")
        f.write("ADMINPASSWORD = %r\n" % admin_password)


def save_network(ssid, password, existing, admin_password=""):
    nets = [(s, p) for s, p in existing if s != ssid]
    nets.append((ssid, password))
    _write_secrets(nets, admin_password)


def remove_network(ssid, existing, admin_password=""):
    nets = [(s, p) for s, p in existing if s != ssid]
    _write_secrets(nets, admin_password)


def save_admin_password(existing_networks, admin_password):
    #Changes only the admin password, leaving NETWORKS untouched - used by configweb.py's
    #create-password/login-gate/change-password flows, which don't touch Wi-Fi credentials.
    _write_secrets(existing_networks, admin_password)


def _page(scanned_ssids, message="", existing_admin_password=""):
    options = "".join('<option value="%s">' % s for s in scanned_ssids)
    admin_note = ("An admin password is already set." if existing_admin_password
                   else "Protects the full config editor you can later reach from the on-device "
                        "Settings menu's \"Start Config Web\" item. Leave blank to set one later.")
    return """<!DOCTYPE html><html><head><title>FoosScore Wi-Fi Setup</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{font-family:sans-serif;max-width:400px;margin:2em auto;padding:0 1em}
label{display:block;margin-top:.6em}
input{width:100%%;padding:.5em;margin:.3em 0 1em;box-sizing:border-box}
button{width:100%%;padding:.7em;font-size:1em}
.note{font-size:.85em;color:#555;margin:-.8em 0 1em}</style></head><body>
<h2>Connect FoosScore to Wi-Fi</h2>
<p>%s</p>
<form method="POST" action="/save">
<label>Network name (SSID)</label>
<input list="ssids" name="ssid" autocomplete="off" required>
<datalist id="ssids">%s</datalist>
<label>Password</label>
<input type="password" name="password">
<label>Admin password (optional)</label>
<input type="password" name="admin_password" autocomplete="new-password">
<p class="note">%s</p>
<button type="submit">Save &amp; Connect</button>
</form></body></html>""" % (message, options, admin_note)


def _success_page(ssid):
    return """<!DOCTYPE html><html><head><title>FoosScore Wi-Fi Setup</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="font-family:sans-serif;text-align:center;margin-top:3em">
<h2>Saved</h2><p>Restarting and connecting to "%s"&hellip;</p>
<p>You can close this page and reconnect your phone to your normal Wi-Fi.</p>
</body></html>""" % ssid


def http_response(body):
    body_bytes = body.encode()
    header = ("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: %d\r\nConnection: close\r\n\r\n"
              % len(body_bytes))
    return header.encode() + body_bytes


def _handle_http(cl, scanned, existing, existing_admin_password=""):
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

        fields = parse_form(body.decode())
        ssid = fields.get("ssid", "").strip()
        password = fields.get("password", "")
        admin_password = fields.get("admin_password", "").strip() or existing_admin_password
        if ssid:
            save_network(ssid, password, existing, admin_password)
            cl.send(http_response(_success_page(ssid)))
            cl.close()
            time.sleep(1)  #let the response reach the phone before the reset drops the AP
            machine.reset()
        else:
            cl.send(http_response(_page(scanned, "SSID is required - please try again.", existing_admin_password)))
        return

    #Any other path - including the captive-portal probe URLs phones request
    #on their own (/generate_204, /hotspot-detect.html, etc.) - gets the setup
    #form. Returning content other than what those probes expect is what
    #makes the OS pop up the captive-portal browser automatically.
    cl.send(http_response(_page(scanned, "", existing_admin_password)))


def start_ap(wlan_sta, wdt=None):
    #Brings up the open setup AP (SSID scheme, static IP, open security) - shared by
    #run_captive_portal() below and configweb.py's full config editor so both portals bring
    #up the AP identically instead of duplicating this. Feeds wdt between each step rather
    #than just once: the STA->AP radio mode switch is itself slow enough on the cyw43 chip
    #to eat a meaningful chunk of one WDT window on its own (see the wdt comment near the
    #top of main.py).
    try:
        mac_suffix = "".join("%02x" % b for b in wlan_sta.config("mac"))[-6:]
    except OSError:
        mac_suffix = "000000"
    if wdt: wdt.feed()
    wlan_sta.active(False)
    if wdt: wdt.feed()
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    if wdt: wdt.feed()
    ap.ifconfig((AP_IP, "255.255.255.0", AP_IP, AP_IP))
    ssid = "FoosScoreSetup-%s" % mac_suffix
    try:
        ap.config(essid=ssid, security=0)  #security=0 -> open network, no password needed to join setup AP
    except (ValueError, TypeError, OSError):
        ap.config(essid=ssid)
    if wdt: wdt.feed()
    return ap, ssid


def open_dns_http():
    #Shared by run_captive_portal() and configweb.py - one UDP:53 DNS-spoofing socket, one
    #TCP:80 HTTP socket, both non-blocking via the caller's own select() loop.
    dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dns.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    dns.bind(("0.0.0.0", 53))

    http = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    http.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    http.bind(("0.0.0.0", 80))
    http.listen(4)
    return dns, http


def run_captive_portal(wlan_sta, existing_networks, led1, led2, on_ready=None, wdt=None, action_pressed=None, existing_admin_password=""):
    print("No known Wi-Fi network reachable - starting setup access point.")

    #No nearby-SSID scan here (the setup form's dropdown is just left empty - typing a name
    #by hand still works fine): wlan_sta.scan() is an unbounded blocking call that can easily
    #run past the RP2040 WDT's ~8.3s hard ceiling in an RF-dense area (many networks/BSSIDs
    #to enumerate, e.g. a mesh system's multiple nodes), same as the startup connect sequence
    #(see the wdt comment near the top of main.py) - the difference is the watchdog is already
    #armed by the time this runs from the menu, and there's no way to feed it mid-call.
    scanned = []
    ap, ssid = start_ap(wlan_sta, wdt)
    print('Setup AP "%s" is up - connect a phone to it, then browse to http://%s/ if a setup page does not open automatically.' % (ssid, AP_IP))
    if on_ready:
        on_ready(ssid, AP_IP)
    if wdt: wdt.feed()

    dns, http = open_dns_http()
    if wdt: wdt.feed()

    ip_bytes = bytes(int(x) for x in AP_IP.split("."))

    #Alternates the two team LEDs while waiting so the board visibly signals
    #"needs setup input" even though this version has no display.
    led1.value(1)
    led2.value(0)
    lastToggle = time.ticks_ms()

    #Baseline read (rather than assuming not-pressed) so a still-held button at entry - e.g.
    #the very press that selected "Wi-Fi Setup" hasn't been released yet - isn't mistaken for
    #a fresh press; only a later release-then-press edge cancels.
    wasPressed = action_pressed() if action_pressed else False

    while True:
        if wdt: wdt.feed()
        if action_pressed:
            pressed = action_pressed()
            if pressed and not wasPressed:
                break
            wasPressed = pressed
        readable, _, _ = select.select([dns, http], [], [], 0.1)
        for r in readable:
            if r is dns:
                try:
                    data, addr = dns.recvfrom(512)
                    dns.sendto(dns_reply(data, ip_bytes), addr)
                except OSError:
                    pass
            else:
                cl, _addr = http.accept()
                try:
                    _handle_http(cl, scanned, existing_networks, existing_admin_password)
                except OSError:
                    pass
                finally:
                    cl.close()

        if time.ticks_diff(time.ticks_ms(), lastToggle) >= LED_BLINK_MS:
            led1.value(not led1.value())
            led2.value(not led2.value())
            lastToggle = time.ticks_ms()

    #Cancelled via the Action button - only reached by that break above, since a successful
    #save resets the board directly from _handle_http() instead of returning here. Tear down
    #the AP/DNS/HTTP state this function created; the caller is responsible for whatever
    #station-mode reconnect makes sense for it (this module doesn't know the caller's network
    #list or connect-retry logic).
    print("Wi-Fi Setup cancelled - Action button pressed.")
    dns.close()
    http.close()
    ap.active(False)
    led1.value(0)
    led2.value(0)
    wlan_sta.active(True)
