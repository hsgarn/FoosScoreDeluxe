#Leveled console logger. Split out of main.py (v3.01) as its own small compile unit.
#main.py sets debuglog.LOG_LEVEL directly once config.DEBUGMODE is known.
import sys

LOG_LEVEL = "INFO"

_LEVEL_PRIORITY = {"DEBUG": 1,"INFO": 2,"WARNING": 3,"ERROR": 4}
_LEVEL_PREFIX = {"DEBUG": "[DEBUG]","INFO": "[INFO]","WARNING": "[WARNING]","ERROR": "[ERROR]"}

def debug(message,*args,level="INFO",exc=None,multiLine=False):
    current_level_priority = _LEVEL_PRIORITY.get(level.upper(),0)
    min_level_priority = _LEVEL_PRIORITY.get(LOG_LEVEL.upper(),0)
    if current_level_priority < min_level_priority:
        return
    prefix = _LEVEL_PREFIX.get(level.upper(),"[DEBUG]")
    formatted_message = message.format(*args) if args else message
    if multiLine:
        print(f"{prefix} {formatted_message}",end="")
    else:
        print(f"{prefix} {formatted_message}")
    if exc is not None:
        print(f"{prefix} Exception: {exc}")
        sys.print_exception(exc)
