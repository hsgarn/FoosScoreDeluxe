#TCP message sending + config-file transfer/validation. Split out of main.py (v3.01) as its own
#small compile unit. Config validation stays inline (here) rather than an external
#configHelper.py/requiredConfigItems.py - those files exist in neither this repo nor
#FoosScorePlus's today. main.py sets netmsg.DEBUG directly once config.DEBUGMODE is known.
FORMAT = 'utf-8'
CONFIGFILE = "config.py"
DEBUG = False

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

def sendMessage(c,message):
    #returns True/False so callers tracking a set of clients (broadcast) can drop just the
    #one that failed, not everyone
    try:
        if DEBUG:
            displayMessage = message.replace("\r","\\r")
            displayMessage = displayMessage.replace("\n","\\n")
            print("Sending: [" + displayMessage + "]")
        data = message.encode(FORMAT)
        totalSent = 0
        while totalSent < len(data):
            sent = c.send(data[totalSent:])
            if sent == 0:
                raise OSError("Socket connection broken")
            totalSent += sent
        return True
    except Exception as ex:
        print(type(ex).__name__,"exception in [sendMessage] function: ",ex.args)
        print("Closing socket.")
        try:
            c.close()
        except OSError:
            pass
        return False

def sendScore(c,teamAndPin):
    return sendMessage(c,f"Team:{teamAndPin}\r\n")

def sendTimeOut(c,teamAndPin):
    return sendMessage(c,f"TO:{teamAndPin}\r\n")

def readConfigFile():
    config = ""
    with open(CONFIGFILE,"r") as file:
        config = file.readlines()
    return config

def sendConfigFile(c):
    config = readConfigFile()
    sendMessage(c,"Read:\r\n")
    for line in config:
        line = f"Line:{line.rstrip()}"
        if line != "Line:":
            line = f"{line}\r\n"
            sendMessage(c,line)

def writeConfigFile(config,filename):
    with open(filename,"w") as file:
        for line in config:
            file.write(line)
    print("Config written to " + filename + ".")

def validateConfig(config):
    print("Validating...")
    validated = True
    lines = config.rsplit("\r\n")
    configNames = REQUIREDCONFIGNAMES.copy()
    configTests = REQUIREDCONFIGTESTS.copy()
    optionalNames = OPTIONALCONFIGNAMES.copy()
    optionalTests = OPTIONALCONFIGTESTS.copy()
    for line in lines:
        if line != "":
            line = line.replace(" ","")
            name,value = line.rsplit("=")
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
                if test == "PORT":
                    if value.isdigit():
                        value = int(value)
                        if value < 0 or value > 65535:
                            validated = False
                    else:
                        validated = False
                elif test == "PIN":
                    if value.isdigit():
                        value = int(value)
                        if value not in VALIDPINS:
                            validated = False
                    else:
                        validated = False
                elif test == "TIME":
                    if value.isdigit():
                        value = int(value)
                        if value < 1 or value > 60000:
                            validated = False
                    else:
                        validated = False
                elif test == "TYPE":
                    if value not in VALIDTYPES:
                        validated = False
                elif test == "INT":
                    if value.isdigit():
                        value = int(value)
                        if value < 0:
                            validated = False
                    else:
                        validated = False
                elif test == "TEAMLIST":
                    if value.startswith("[") and value.endswith("]"):
                        teamValues = value[1:-1].split(",")
                        if not all(v.isdigit() and int(v) in (1,2) for v in teamValues):
                            validated = False
                    else:
                        validated = False
                elif test == "LEDRANGE":
                    groups = value.split(";")
                    rangeOk = len(groups) > 0
                    for group in groups:
                        parts = group.split("-")
                        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                            rangeOk = False
                            break
                    if not rangeOk:
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
