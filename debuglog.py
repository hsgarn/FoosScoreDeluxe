#Leveled console logger. Split out of main.py (v3.01) as its own small compile unit.
#main.py sets debuglog.LOG_LEVEL directly once config.DEBUGMODE is known.
#Also fans out to logHelper.py's independent file logger (v3.17) - see the module comment
#there. This only ADDS a call after the terminal-print logic below; that logic itself is
#untouched, so terminal output is unaffected by LOGLEVEL/file logging one way or the other,
#same as FoosScorePlus's own DEBUGMODE-vs-LOGLEVEL independence.
import sys
import logHelper

LOG_LEVEL = "INFO"

_LEVEL_PRIORITY = {"DEBUG": 1,"INFO": 2,"WARNING": 3,"ERROR": 4}
_LEVEL_PREFIX = {"DEBUG": "[DEBUG]","INFO": "[INFO]","WARNING": "[WARNING]","ERROR": "[ERROR]"}
#Maps debug()'s terminal levels to logHelper's coarser file levels - DEBUG is the same
#high-frequency per-event chatter logHelper's own module comment calls out as "debug";
#everything else (significant/lifecycle/error events) is "info".
_FILE_LEVEL = {"DEBUG": "debug","INFO": "info","WARNING": "info","ERROR": "info"}

def debug(message,*args,level="INFO",exc=None,multiLine=False):
    current_level_priority = _LEVEL_PRIORITY.get(level.upper(),0)
    min_level_priority = _LEVEL_PRIORITY.get(LOG_LEVEL.upper(),0)
    if current_level_priority < min_level_priority:
        return
    prefix = _LEVEL_PREFIX.get(level.upper(),"[DEBUG]")
    formatted_message = message.format(*args) if args else message
    if multiLine:
        #A partial, no-newline terminal line doesn't map to one discrete file log entry -
        #skipped for the file sink, same as this already only being a terminal nicety.
        print(f"{prefix} {formatted_message}",end="")
    else:
        print(f"{prefix} {formatted_message}")
        logHelper.log(formatted_message,_FILE_LEVEL.get(level.upper(),"info"))
    if exc is not None:
        print(f"{prefix} Exception: {exc}")
        sys.print_exception(exc)
        #Message only, not the full traceback - keeps file writes bounded/lightweight
        #rather than dumping a full traceback to flash on every exception.
        logHelper.log(f"Exception: {exc}",_FILE_LEVEL.get(level.upper(),"info"))
