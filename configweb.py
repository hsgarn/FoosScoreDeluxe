#FoosScorePlusDeluxe - full config-editing captive portal ("Config Web").
#Ported from FoosScorePlus's configPortal.py. Entered by rebooting with a "configweb.flag"
#marker file present (see main.py's boot-time check, right before it validates config.py) -
#the on-device Settings menu's "Start Web Config" item writes that flag and calls
#machine.reset() to get there, rather than a dedicated GPIO reset button like FoosScorePlus.
#Built on top of wifi_setup.py's AP/DNS/HTTP primitives (start_ap/open_dns_http/dns_reply/
#parse_form/http_response/save_network/remove_network/save_admin_password) instead of
#duplicating that plumbing - same relationship as FoosScorePlus's wifi_setup.py <->
#configPortal.py.
#run() is called before main.py's own normal locals/display-init sequence even happens (see
#the boot-time check) - it builds its own Pin/I2C objects directly from config.<NAME>
#(getattr with a fallback, best-effort) so a broken config.py can still be reached and fixed
#here rather than only crashing normal boot. It never returns - it only exits via
#machine.reset(), either from an idle timeout or the "Finish & Restart" button.
import select
import time
import machine
from machine import Pin, I2C

import config
import configHelper
import wifi_setup
import logHelper

try:
    import secrets
except ImportError:
    class secrets:
        NETWORKS = []
        ADMINPASSWORD = ""

try:
    import secretsIref
except ImportError:
    secretsIref = None

SECRETSIREFFILE = "secretsIref.py"
IDLE_TIMEOUT_MS = 5 * 60 * 1000  #no input for 5 minutes - restart rather than block forever

#Field specs: (name, label, kind, optional, options). options=None -> free-text <input>;
#a list -> <select>, either plain strings or (value,label) pairs when the stored value
#isn't human-friendly on its own. kind matches configHelper.validateValue's kinds.
GPIO_FIELDS = [
    ("SENSOR1","Sensor 1 pin","PIN",False,None),
    ("SENSOR2","Sensor 2 pin","PIN",False,None),
    ("SENSOR3","Sensor 3 pin (optional)","PIN",True,None),
    ("SENSOR1_TYPE","Sensor 1 type","TYPE",False,configHelper.VALIDTYPES),
    ("SENSOR2_TYPE","Sensor 2 type","TYPE",False,configHelper.VALIDTYPES),
    ("SENSOR3_TYPE","Sensor 3 type (optional)","TYPE",True,configHelper.VALIDTYPES),
    ("LED1","Team 1 LED pin","PIN",False,None),
    ("LED2","Team 2 LED pin","PIN",False,None),
    ("PB1","Team 1 pushbutton pin","PIN",False,None),
    ("PB2","Team 2 pushbutton pin","PIN",False,None),
    ("PB3","Action pushbutton pin","PIN",False,None),
]

GAME_FIELDS = [
    ("TABLE","Table number","INT",False,None),
    ("TEAMS","Teams, comma separated (e.g. 1,1,2)","TEAMLIST",False,None),
    ("DELAY_SENSOR","Sensor debounce (ms)","TIME",False,None),
    ("DELAY_PB","Pushbutton hold time (ms)","TIME",False,None),
    ("DELAY_ACTION_PB","Action pushbutton delay (ms)","TIME",False,None),
]

NETWORK_CONFIG_FIELDS = [
    ("PORT","Game TCP port","PORT",False,None),
    ("DPORT","Discovery UDP port","PORT",False,None),
]

DISPLAY_FIELDS = [
    ("SDA","I2C SDA pin","PIN",False,None),
    ("SCL","I2C SCL pin","PIN",False,None),
    ("I2C","I2C bus number","INT",False,None),
    ("LEDSTRIP","LED strip data pin","PIN",False,None),
    ("NUMBER_PIXELS","Number of LED strip pixels","INT",False,None),
    ("STATE_MACHINE","PIO state machine number","INT",False,None),
    ("TEAM1LEDS","Team 1 pixel range (e.g. 0-14)","LEDRANGE",False,None),
    ("TEAM2LEDS","Team 2 pixel range (e.g. 15-29)","LEDRANGE",False,None),
] + NETWORK_CONFIG_FIELDS

TFT_FIELDS = [
    ("SPIBLOCK","SPI block number (optional)","INT",True,None),
    ("SPI_SCK_CLK_SCK","SPI SCK pin (optional)","PIN",True,None),
    ("SPI_TX_DIN_MOSI","SPI MOSI pin (optional)","PIN",True,None),
    ("SPI_RX_DC_ADC","SPI DC pin (optional)","PIN",True,None),
    ("SPI_RX_RST_ARESET","SPI Reset pin (optional)","PIN",True,None),
    ("SPI_CSN_CS_ACS","SPI CS pin (optional)","PIN",True,None),
    ("TFT_ROTATION","TFT rotation 0-3 (optional)","INT",True,None),
]

IREF_FIELDS = [
    ("IREF","Enable iRefFoos reporting","INT",False,[("0","Disabled"),("1","Enabled")]),
    ("IREF_DEVICE","Device name template","STR",False,None),
    ("IREF_HOME_TEAM","Home team","INT",False,[("1","Team 1"),("2","Team 2")]),
    ("IREF_URL","iRefFoos URL","STR",False,None),
]

SYSTEM_FIELDS = [
    ("DEBUGMODE","Debug logging","INT",False,[("0","Disabled"),("1","Enabled")]),
    ("WDT_ENABLED","Watchdog timer","INT",False,[("0","Disabled"),("1","Enabled")]),
    ("LOGLEVEL","File logging level","LOGLEVEL",False,[("off","Off"),("info","Info"),("debug","Debug")]),
    ("LOG_MAX_KB","Max log file size (KB)","INT",False,None),
]

#"/system" is handled separately below (_page_system/_handle_system) rather than through
#this generic table - it needs the flash-wear note and the View Log/Clear Log buttons a
#plain field-spec form doesn't have.
SECTIONS = {
    "/gpio": ("GPIO / Pins",GPIO_FIELDS),
    "/game": ("Game",GAME_FIELDS),
    "/display": ("Display / LED Strip / Network",DISPLAY_FIELDS),
    "/tft": ("SPI TFT (optional)",TFT_FIELDS),
}

_admin_password = ""
_iref_api_key = ""
_authenticated_ips = set()


def _html_escape(s):
    return (str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            .replace('"',"&quot;"))


def _networks():
    return getattr(secrets,"NETWORKS",[])


def _field_value(name,kind,form=None):
    if form is not None:
        return form.get(name,"")
    value = getattr(config,name,None)
    if value is None:
        return ""
    if kind == "TEAMLIST":
        return ",".join(str(v) for v in value)
    return str(value)


def _render_field(name,label,options,value):
    if options:
        opts_html = ""
        for opt in options:
            if isinstance(opt,tuple):
                optValue,optLabel = opt
            else:
                optValue = optLabel = opt
            selected = " selected" if str(optValue) == str(value) else ""
            opts_html += '<option value="%s"%s>%s</option>' % (_html_escape(optValue),selected,_html_escape(optLabel))
        return '<label>%s</label><select name="%s">%s</select>' % (_html_escape(label),name,opts_html)
    return '<label>%s</label><input name="%s" value="%s">' % (_html_escape(label),name,_html_escape(value))


def _render_fields(fields_spec,form=None):
    html = ""
    for name,label,kind,optional,options in fields_spec:
        html += _render_field(name,label,options,_field_value(name,kind,form))
    return html


#Not %-formatted anywhere (unlike wifi_setup.py's page templates, which are) - a literal
#"%" is written single here, not doubled, since there's no %-substitution to survive. A
#doubled "%%" here would render as the literal, invalid CSS "100%%" in the browser (the
#bug this fixed): the whole width rule gets dropped, so every label/input/select/button
#falls back to its natural inline size instead of stacking as its own full-width row.
PAGE_HEAD = """<!DOCTYPE html><html><head><title>FoosScore Config</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{font-family:sans-serif;max-width:480px;margin:2em auto;padding:0 1em}
label{display:block;margin-top:.6em}
input,select{width:100%;padding:.5em;margin:.3em 0 1em;box-sizing:border-box}
button{width:100%;padding:.7em;font-size:1em;margin:.3em 0}
a.back{display:block;margin-top:1em;text-align:center}
.err{color:#b00020}
.menu a{display:block;padding:.6em;margin:.4em 0;background:#eee;text-decoration:none;color:#000;border-radius:4px}
</style></head><body>"""
PAGE_TAIL = "</body></html>"


def _wrap(title,body,message=""):
    msg_html = ('<p class="err">%s</p>' % _html_escape(message)) if message else ""
    return PAGE_HEAD + ("<h2>%s</h2>" % _html_escape(title)) + msg_html + body + PAGE_TAIL


def _page_menu(message=""):
    items = [("/gpio","GPIO / Pins"),("/game","Game"),("/network","Wi-Fi Networks"),
             ("/display","Display / LED Strip / Network Ports"),("/tft","SPI TFT (optional)"),
             ("/iref","iRefFoos"),("/system","System")]
    body = '<div class="menu">' + "".join('<a href="%s">%s</a>' % (h,_html_escape(t)) for h,t in items) + "</div>"
    body += '<form method="POST" action="/finish"><button type="submit">Finish &amp; Restart Table</button></form>'
    return _wrap("FoosScore Config",body,message)


def _page_section_form(action,title,fields_spec,message="",form=None):
    body = ('<form method="POST" action="%s">' % action
            + _render_fields(fields_spec,form)
            + '<button type="submit">Save</button></form>'
            + '<a class="back" href="/">Back to menu</a>')
    return _wrap(title,body,message)


def _page_create_password(message=""):
    body = ('<p>Set an admin password to protect this config editor. It is not required to '
            'connect to Wi-Fi - see the on-device menu\'s "Wi-Fi Setup" item for that.</p>'
            '<form method="POST" action="/createpassword">'
            '<label>New password (4+ characters)</label><input type="password" name="password">'
            '<label>Confirm</label><input type="password" name="confirm">'
            '<button type="submit">Set Password</button></form>')
    return _wrap("Create Admin Password",body,message)


def _page_login(message=""):
    body = ('<form method="POST" action="/login">'
            '<label>Admin password</label><input type="password" name="password" autofocus>'
            '<button type="submit">Log In</button></form>')
    return _wrap("Config Web Login",body,message)


def _page_network(message=""):
    rows = ""
    for ssid,_pw in _networks():
        rows += ('<form method="POST" action="/network/remove" style="display:flex;gap:.5em;align-items:center">'
                 '<span style="flex:1">%s</span><input type="hidden" name="ssid" value="%s">'
                 '<button type="submit" style="width:auto">Remove</button></form>'
                 % (_html_escape(ssid),_html_escape(ssid)))
    body = "<h3>Known networks</h3>" + (rows or "<p>None saved.</p>")
    body += ('<h3>Add network</h3><form method="POST" action="/network/add">'
             '<label>SSID</label><input name="ssid" required>'
             '<label>Password</label><input type="password" name="password">'
             '<button type="submit">Add</button></form>')
    body += ('<h3>Change admin password</h3><form method="POST" action="/network/password">'
             '<label>New password (4+ characters)</label><input type="password" name="password">'
             '<label>Confirm</label><input type="password" name="confirm">'
             '<button type="submit">Change</button></form>')
    body += '<a class="back" href="/">Back to menu</a>'
    return _wrap("Wi-Fi Networks",body,message)


def _page_iref(message="",form=None):
    apiKeyValue = form.get("APIKEY","") if form is not None else _iref_api_key
    body = ('<form method="POST" action="/iref">'
            + _render_fields(IREF_FIELDS,form)
            + _render_field("APIKEY","iRefFoos API key",None,apiKeyValue)
            + '<button type="submit">Save</button></form>'
            + '<a class="back" href="/">Back to menu</a>')
    return _wrap("iRefFoos",body,message)


def _page_system(message="",form=None):
    body = ('<form method="POST" action="/system">'
            + _render_fields(SYSTEM_FIELDS,form)
            + '<p style="font-size:.85em;color:#555">Writing to a log file uses the same '
              'flash the table\'s program runs from, which has a limited number of write '
              'cycles - leaving file logging on Debug for long stretches may shorten the '
              'flash\'s usable life. Off/Info are far lower volume and fine to leave on.</p>'
            + '<button type="submit">Save</button></form>'
            + '<h3>Log file</h3>'
              '<a class="back" href="/system/log">View Log</a>'
              '<form method="POST" action="/system/log/clear"><button type="submit">Clear Log</button></form>'
            + '<a class="back" href="/">Back to menu</a>')
    return _wrap("System",body,message)


def _finish_page():
    return """<!DOCTYPE html><html><head><title>FoosScore Config</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="font-family:sans-serif;text-align:center;margin-top:3em">
<h2>Restarting</h2><p>The table is restarting with the new configuration.</p>
<p>You can close this page and reconnect your phone to your normal Wi-Fi.</p>
</body></html>"""


def _normalize_raw(raw,kind):
    #TEAMLIST is shown/typed as a bare comma list ("1,1,2") - wrap it into the bracketed
    #list-literal form configHelper.validateValue/formatConfigValue and config.py itself
    #use before either sees it.
    if kind == "TEAMLIST":
        raw = raw.strip()
        if not (raw.startswith("[") and raw.endswith("]")):
            raw = "[%s]" % raw
    return raw


def _apply_config_updates(fields_spec,form):
    #Validates every field first and writes nothing if any of them fail, so a bad edit in
    #one field never leaves config.py partially updated. Returns a list of problem strings
    #(empty = success). On success, writes a backup, then the new config.py, then reflects
    #the change in the already-imported config module in-memory so re-rendering the same
    #form within this session shows the just-saved value without needing a reboot.
    problems = []
    updates = {}
    typedUpdates = {}
    for name,label,kind,optional,options in fields_spec:
        raw = form.get(name,"").strip()
        if raw == "":
            if optional:
                updates[name] = None
                typedUpdates[name] = None
                continue
            problems.append("%s is required." % label)
            continue
        normalized = _normalize_raw(raw,kind)
        ok,typed = configHelper.validateValue(normalized,kind)
        if not ok:
            problems.append("%s is not valid." % label)
            continue
        updates[name] = configHelper.formatConfigValue(normalized,kind)
        typedUpdates[name] = typed
    if problems:
        return problems

    oldLines = configHelper.readConfigFile()
    newLines = configHelper.setConfigValues(oldLines,updates)
    if newLines == oldLines:
        return []
    if not configHelper.validateConfig(configHelper.linesToText(newLines)):
        return ["Internal error - resulting config failed validation, nothing was written."]

    backupName = configHelper.CONFIGFILE + str(time.ticks_ms())
    configHelper.writeConfigFile(oldLines,backupName)
    print("Old config backed up as " + backupName + ".")
    configHelper.writeConfigFile(newLines,configHelper.CONFIGFILE)

    for name,typed in typedUpdates.items():
        if typed is None:
            if hasattr(config,name):
                delattr(config,name)
        else:
            setattr(config,name,typed)
    return []


def _handle_create_password(method,path,form,client_ip):
    global _admin_password
    if method == "POST" and path == "/createpassword":
        pw = form.get("password","")
        confirm = form.get("confirm","")
        if len(pw) < 4:
            return _page_create_password("Password must be at least 4 characters.")
        if pw != confirm:
            return _page_create_password("Passwords do not match.")
        _admin_password = pw
        wifi_setup.save_admin_password(_networks(),pw)
        _authenticated_ips.add(client_ip)
        logHelper.log("Config Web: admin password created (" + client_ip + ").")
        return _page_menu("Admin password created.")
    return _page_create_password()


def _handle_login(method,path,form,client_ip):
    if method == "POST" and path == "/login":
        pw = form.get("password","")
        if pw == _admin_password:
            _authenticated_ips.add(client_ip)
            logHelper.log("Config Web: admin logged in (" + client_ip + ").")
            return _page_menu()
        logHelper.log("Config Web: incorrect password attempt (" + client_ip + ").")
        return _page_login("Incorrect password.")
    return _page_login()


def _handle_iref(method,form):
    global _iref_api_key
    if method != "POST":
        return _page_iref()
    problems = _apply_config_updates(IREF_FIELDS,form)
    if problems:
        return _page_iref(" ".join(problems),form)
    apiKey = form.get("APIKEY","").strip()
    try:
        with open(SECRETSIREFFILE,"w") as f:
            f.write("#iRefFoos Remote Command API key (keys are created and managed by Eric).\n")
            f.write("#Leave empty to disable iRefFoos reporting even when IREF = 1 in config.py.\n")
            f.write("APIKEY = %r\n" % apiKey)
        _iref_api_key = apiKey
        logHelper.log("iRefFoos API key changed via Config Web.")
    except OSError as ex:
        return _page_iref("Config saved, but could not write secretsIref.py: %s" % ex,form)
    return _page_iref("Saved.")


def _handle_system(method,form):
    if method != "POST":
        return _page_system()
    problems = _apply_config_updates(SYSTEM_FIELDS,form)
    if problems:
        return _page_system(" ".join(problems),form)
    logHelper.log("Config section 'System' saved via Config Web.")
    #Apply a LOGLEVEL/LOG_MAX_KB change immediately within this same session instead of
    #only after the next reboot - matches FoosScorePlus's configPortal.py.
    logHelper.configure(getattr(config,"LOGLEVEL","off"),getattr(config,"LOG_MAX_KB",100))
    return _page_system("Saved.")


def _route(method,path,form):
    global _admin_password
    if path in ("/",""):
        return _page_menu()
    if path in SECTIONS:
        title,fields_spec = SECTIONS[path]
        if method == "POST":
            problems = _apply_config_updates(fields_spec,form)
            if problems:
                return _page_section_form(path,title,fields_spec," ".join(problems),form)
            logHelper.log("Config section '" + title + "' saved via Config Web.")
            return _page_section_form(path,title,fields_spec,"Saved.")
        return _page_section_form(path,title,fields_spec)
    if path == "/network":
        return _page_network()
    if path == "/network/add" and method == "POST":
        ssid = form.get("ssid","").strip()
        password = form.get("password","")
        if not ssid:
            return _page_network("SSID is required.")
        wifi_setup.save_network(ssid,password,_networks(),_admin_password)
        logHelper.log("Wi-Fi network '" + ssid + "' saved via Config Web.")
        return _page_network("Network added.")
    if path == "/network/remove" and method == "POST":
        ssid = form.get("ssid","").strip()
        wifi_setup.remove_network(ssid,_networks(),_admin_password)
        logHelper.log("Wi-Fi network '" + ssid + "' removed via Config Web.")
        return _page_network("Network removed.")
    if path == "/network/password" and method == "POST":
        pw = form.get("password","")
        confirm = form.get("confirm","")
        if len(pw) < 4:
            return _page_network("Password must be at least 4 characters.")
        if pw != confirm:
            return _page_network("Passwords do not match.")
        _admin_password = pw
        wifi_setup.save_admin_password(_networks(),pw)
        logHelper.log("Config Web: admin password changed.")
        return _page_network("Admin password changed.")
    if path == "/iref":
        return _handle_iref(method,form)
    if path == "/system":
        return _handle_system(method,form)
    if path == "/system/log/clear" and method == "POST":
        logHelper.clearLog()
        return _page_system("Log cleared.")
    #Unknown path (including captive-portal probe URLs like /generate_204) - fall back to
    #the menu, same "return something other than what the probe expects" idea wifi_setup.py
    #uses to make the OS pop up the captive browser.
    return _page_menu()


def _handle_http(cl,client_ip):
    global _admin_password
    cl.settimeout(3)
    request = b""
    try:
        while b"\r\n\r\n" not in request:
            chunk = cl.recv(512)
            if not chunk:
                break
            request += chunk
    except OSError:
        return False
    if not request:
        return False

    header_part,_,body = request.partition(b"\r\n\r\n")
    lines = header_part.split(b"\r\n")
    try:
        method,path,_ = lines[0].decode().split(" ",2)
    except ValueError:
        return False

    content_length = 0
    for line in lines[1:]:
        if line.lower().startswith(b"content-length:"):
            content_length = int(line.split(b":",1)[1].strip())
    if content_length:
        try:
            while len(body) < content_length:
                more = cl.recv(content_length - len(body))
                if not more:
                    break
                body += more
        except OSError:
            pass
    form = wifi_setup.parse_form(body.decode()) if method == "POST" else {}

    if method == "POST" and path == "/finish":
        logHelper.log("Config Web: Finish & Restart requested.")
        cl.send(wifi_setup.http_response(_finish_page()))
        cl.close()
        time.sleep(1)  #let the response reach the phone before the reset drops the AP
        machine.reset()
        return True  #unreachable - machine.reset() doesn't return

    if _admin_password == "":
        html = _handle_create_password(method,path,form,client_ip)
    elif client_ip not in _authenticated_ips:
        html = _handle_login(method,path,form,client_ip)
    elif method == "GET" and path == "/system/log":
        #Streamed directly to the socket rather than through the normal "build one html
        #string, then http_response()" path below - log.txt can be up to ~2x LOG_MAX_KB
        #(current + backup file), and this project has already hit real MemoryError from
        #big single strings/files on this same RP2040 (see README).
        _send_log(cl)
        return True
    else:
        html = _route(method,path,form)
    cl.send(wifi_setup.http_response(html))
    return True


_LOG_PAGE_HEAD = ('<!DOCTYPE html><html><head><title>FoosScore Log</title>'
                   '<meta name="viewport" content="width=device-width, initial-scale=1">'
                   '<style>body{font-family:sans-serif;margin:1em}'
                   'a.btn{display:block;text-align:center;padding:.7em;background:#eee;'
                   'border-radius:.3em;text-decoration:none;color:#000;margin:.3em 0}'
                   'pre{white-space:pre-wrap;word-break:break-all;font-size:.85em}'
                   '</style></head><body><a class="btn" href="/system">Back to System</a><pre>').encode()
_LOG_PAGE_TAIL = '</pre><a class="btn" href="/system">Back to System</a></body></html>'.encode()


def _send_log(cl):
    #Sends its own header and streams logHelper.readLog()'s chunks straight to the socket -
    #see the comment at this function's call site for why. No Content-Length; "Connection:
    #close" (used by every response here) tells the browser to read until the socket
    #closes, same as FoosScorePlus's configPortal._send_log.
    header = ("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n"
              "Cache-Control: no-store, no-cache, must-revalidate\r\nPragma: no-cache\r\n\r\n")
    cl.send(header.encode())
    cl.send(_LOG_PAGE_HEAD)
    empty = True
    for chunk in logHelper.readLog():
        empty = False
        cl.send(chunk)
    if empty:
        cl.send(b"(log is empty)")
    cl.send(_LOG_PAGE_TAIL)


def _init_display():
    #Best-effort - a broken SDA/SCL/I2C in config.py must not block reaching this editor,
    #since fixing exactly that is what this editor is for. Falls back to LED-only feedback
    #(always attempted below regardless) if this fails for any reason.
    try:
        from pico_i2c_lcd import I2cLcd
        i2c = I2C(id=getattr(config,"I2C",0),scl=Pin(getattr(config,"SCL",5)),sda=Pin(getattr(config,"SDA",4)),freq=400000)
        return I2cLcd(i2c,0x27,4,20)
    except Exception:
        return None


def _show(lcd,lines):
    if not lcd:
        return
    try:
        for i,line in enumerate(lines[:4]):
            lcd.move_to(0,i)
            lcd.putstr("%-20s" % line[:20])
    except Exception:
        pass


def run(wlan_sta,led1,led2,wdt=None):
    global _admin_password,_iref_api_key,_authenticated_ips
    print("configweb.flag present - starting Config Web access point.")
    logHelper.log("Config Web: starting access point.")
    _admin_password = getattr(secrets,"ADMINPASSWORD","") or ""
    _iref_api_key = getattr(secretsIref,"APIKEY","") if secretsIref else ""
    _authenticated_ips = set()

    lcd = _init_display()
    ap,ssid = wifi_setup.start_ap(wlan_sta,wdt)
    dns,http = wifi_setup.open_dns_http()
    if wdt: wdt.feed()
    ip_bytes = bytes(int(x) for x in wifi_setup.AP_IP.split("."))
    print('Config Web AP "%s" is up - connect a phone to it, then browse to http://%s/' % (ssid,wifi_setup.AP_IP))
    _show(lcd,["Config Web Mode",ssid[:20],ssid[20:40],"http://%s/" % wifi_setup.AP_IP])

    led1.value(1)
    led2.value(0)
    lastToggle = time.ticks_ms()
    lastActivity = time.ticks_ms()

    while True:
        if wdt: wdt.feed()
        readable,_,_ = select.select([dns,http],[],[],0.1)
        for r in readable:
            if r is dns:
                try:
                    data,addr = dns.recvfrom(512)
                    dns.sendto(wifi_setup.dns_reply(data,ip_bytes),addr)
                except OSError:
                    pass
            else:
                cl,addr = http.accept()
                try:
                    if _handle_http(cl,addr[0]):
                        lastActivity = time.ticks_ms()
                except OSError as ex:
                    logHelper.log("Config Web: request error: " + str(ex))
                finally:
                    try:
                        cl.close()
                    except OSError:
                        pass

        if time.ticks_diff(time.ticks_ms(),lastToggle) >= wifi_setup.LED_BLINK_MS:
            led1.value(not led1.value())
            led2.value(not led2.value())
            lastToggle = time.ticks_ms()

        if time.ticks_diff(time.ticks_ms(),lastActivity) >= IDLE_TIMEOUT_MS:
            print("Config Web idle timeout - restarting.")
            logHelper.log("Config Web: idle timeout - restarting.")
            _show(lcd,["Config Web","Idle timeout -","restarting...",""])
            time.sleep(1)
            machine.reset()
