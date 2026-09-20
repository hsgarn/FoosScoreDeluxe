#Config-file read/validate/write logic. Split out of netmsg.py (v3.16) to match
#FoosScorePlus's configHelper.py, which this file corresponds to 1:1 - netmsg.py keeps
#only genuine TCP-messaging concerns (sendMessage/sendScore/sendTimeOut/sendConfigFile).
#Shared by main.py's boot-time validation, the TCP "save" command (parseSave), and
#configweb.py's on-device config editor, so all three paths agree on what's valid and how
#a value round-trips to/from config.py's text.
CONFIGFILE = "config.py"

#Base networking/sensor fields (FoosScorePlus) + integrated-board display/LED-strip/Action-button
#fields (Deluxe).
REQUIREDCONFIGNAMES = ["PORT","DPORT","SENSOR1","SENSOR2","SENSOR1_TYPE","SENSOR2_TYPE","LED1","LED2",
                        "DELAY_SENSOR","DELAY_PB","DELAY_ACTION_PB","PB1","PB2","PB3","TABLE","TEAMS",
                        "SDA","SCL","I2C","LEDSTRIP","NUMBER_PIXELS","STATE_MACHINE","TEAM1LEDS","TEAM2LEDS"]
REQUIREDCONFIGTESTS = ["PORT","PORT","PIN","PIN","TYPE","TYPE","PIN","PIN",
                        "TIME","TIME","TIME","PIN","PIN","PIN","INT","TEAMLIST",
                        "PIN","PIN","INT","PIN","INT","INT","LEDRANGE","LEDRANGE"]

#Optional - the SPI color TFT is a second, nice-to-have display. A board with only the I2C LCD
#wired up can omit all seven of these from config.py entirely; main.py falls back to running
#with the I2C LCD alone (see tftEnabled). If any is present they're all still validated normally.
OPTIONALCONFIGNAMES = ["SPIBLOCK","SPI_SCK_CLK_SCK","SPI_TX_DIN_MOSI","SPI_RX_DC_ADC",
                        "SPI_RX_RST_ARESET","SPI_CSN_CS_ACS","TFT_ROTATION"]
OPTIONALCONFIGTESTS = ["INT","PIN","PIN","PIN","PIN","PIN","INT"]

VALIDPINS = [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,26,27,28]
VALIDTYPES = ["IR","LASER"]

def readConfigFile():
    config = ""
    with open(CONFIGFILE,"r") as file:
        config = file.readlines()
    return config

def writeConfigFile(config,filename):
    with open(filename,"w") as file:
        for line in config:
            file.write(line)
    print("Config written to " + filename + ".")

def linesToText(lines):
    #Canonical "\r\n"-joined text form used by validateConfig, regardless of the line
    #endings on disk (main.py used to build this inline before every boot; configweb.py
    #reuses it to re-validate a proposed edit before writing it).
    return "\r\n".join(line.rstrip("\r\n") for line in lines) + "\r\n"

def validateValue(raw,kind):
    #Single-field type/range check, factored out of validateConfig's old inline dispatch so
    #it can also validate one submitted web-form field at a time (configweb.py) instead of
    #only a whole config.py text blob. Returns (ok,typed) - typed is a best-effort Python
    #value (int for numeric kinds, a list of ints for TEAMLIST, the string itself
    #otherwise); callers that only care about validity can ignore it.
    if kind == "PORT":
        if raw.isdigit():
            n = int(raw)
            return (0 <= n <= 65535,n)
        return (False,None)
    elif kind == "PIN":
        if raw.isdigit():
            n = int(raw)
            return (n in VALIDPINS,n)
        return (False,None)
    elif kind == "TIME":
        if raw.isdigit():
            n = int(raw)
            return (1 <= n <= 60000,n)
        return (False,None)
    elif kind == "TYPE":
        return (raw in VALIDTYPES,raw)
    elif kind == "INT":
        if raw.isdigit():
            n = int(raw)
            return (n >= 0,n)
        return (False,None)
    elif kind == "TEAMLIST":
        if raw.startswith("[") and raw.endswith("]"):
            teamValues = raw[1:-1].split(",")
            if all(v.isdigit() and int(v) in (1,2) for v in teamValues):
                return (True,[int(v) for v in teamValues])
        return (False,None)
    elif kind == "LEDRANGE":
        groups = raw.split(";")
        rangeOk = len(groups) > 0
        for group in groups:
            parts = group.split("-")
            if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                rangeOk = False
                break
        return (rangeOk,raw)
    elif kind == "STR":
        return (True,raw)
    return (False,None)

def formatConfigValue(raw,kind):
    #Inverse of the quote-stripping validateConfig does on read: turns a raw (already
    #unquoted) value into the literal text that belongs after "NAME = " in config.py.
    if kind in ("PORT","PIN","TIME","INT"):
        return raw
    elif kind == "TEAMLIST":
        return raw if raw.startswith("[") else "[%s]" % raw
    else:
        #STR, TYPE, LEDRANGE are all stored as a quoted string in config.py today.
        return '"%s"' % raw.replace('"','\\"')

def setConfigValues(lines,updates):
    #lines: readConfigFile()'s list of raw lines (comments/blanks/order preserved as-is).
    #updates: {NAME: formatted_value_text} to replace/add, or {NAME: None} to remove that
    #line entirely (a cleared optional field falls back to whatever getattr(config,NAME,
    #default) main.py already uses). Returns a new list of lines - does not touch disk.
    remaining = dict(updates)
    result = []
    for line in lines:
        stripped = line.strip()
        name = None
        if stripped and not stripped.startswith("#") and "=" in stripped:
            candidate = stripped.split("=",1)[0].strip()
            if candidate in remaining:
                name = candidate
        if name is not None:
            newValue = remaining.pop(name)
            if newValue is not None:
                result.append("%s = %s\n" % (name,newValue))
            #else newValue is None - drop this line (field cleared)
        else:
            result.append(line)
    for name,newValue in remaining.items():
        if newValue is not None:
            result.append("%s = %s\n" % (name,newValue))
    return result

def validateConfig(config):
    print("Validating...")
    validated = True
    lines = config.rsplit("\r\n")
    configNames = REQUIREDCONFIGNAMES.copy()
    configTests = REQUIREDCONFIGTESTS.copy()
    optionalNames = OPTIONALCONFIGNAMES.copy()
    optionalTests = OPTIONALCONFIGTESTS.copy()
    for line in lines:
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#") or "=" not in stripped:
            continue
        line = line.replace(" ","")
        name,value = line.rsplit("=",1)
        value = value.strip('"').strip("'")
        test = None
        if name in configNames:
            pos = configNames.index(name)
            test = configTests[pos]
            del configNames[pos]
            del configTests[pos]
        elif name in optionalNames:
            pos = optionalNames.index(name)
            test = optionalTests[pos]
            del optionalNames[pos]
            del optionalTests[pos]
        if test is not None:
            ok,_ = validateValue(value,test)
            if not ok:
                validated = False
    if len(configNames) != 0:
        validated = False
        print("Missing parameters: ")
        print(*configNames,sep = ", ")
    return validated

def parseSave(cmd):
    #cmd is the client's rxBuffer split on ":" (main loop's ["save", "<payload>"]), passed in
    #explicitly rather than read off a shared global - keeps this module self-contained.
    dateStamp = ""
    config = ""
    text = cmd[1].rsplit("\n")
    for t in text:
        if t != "":
            if t[0:3] == "End":
                print("Got End")
                if validateConfig(config):
                    if dateStamp != "":
                        oldConfig = readConfigFile()
                        if oldConfig == config:
                            print("New config same as old config - write aborted.")
                        else:
                            writeConfigFile(oldConfig,CONFIGFILE + dateStamp)
                            print("Old config backed up as " + CONFIGFILE + dateStamp + ".")
                            print("writing config...")
                            writeConfigFile(config,CONFIGFILE)
                    else:
                        print("No dateStamp found - write aborted.")
                else:
                    print("Invalid config - write aborted.")
            elif t[0:4] == "date":
                dateStamp = t[7:21]
            else:
                config = config + t + "\r\n"
