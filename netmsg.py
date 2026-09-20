#TCP message sending. Split out of main.py (v3.01) as its own small compile unit.
#Config file read/validate/write logic lives in configHelper.py (split out here in v3.16 to
#match FoosScorePlus's file of the same name) - sendConfigFile below is the one function
#here that still needs it, for the TCP "read" command.
import configHelper
FORMAT = 'utf-8'
DEBUG = False

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

def sendConfigFile(c):
    config = configHelper.readConfigFile()
    sendMessage(c,"Read:\r\n")
    for line in config:
        line = f"Line:{line.rstrip()}"
        if line != "Line:":
            line = f"{line}\r\n"
            sendMessage(c,line)
