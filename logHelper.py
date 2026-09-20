#FoosScorePlusDeluxe - file-backed logging, independent of DEBUGMODE.
#Ported near-verbatim from FoosScorePlus's logHelper.py. DEBUGMODE (see debuglog.py) only
#controls terminal verbosity and is unaffected by anything here. LOGLEVEL (config.py,
#"off"/"info"/"debug") controls what - if anything - also gets written to LOGFILE:
#  off   - nothing written.
#  info  - significant events only (connects, errors, config/portal changes, reboots, ...).
#  debug - everything "info" covers, plus the same high-frequency per-event/per-packet
#          chatter DEBUGMODE gates on the terminal (every goal, every UDP packet, ...). Each
#          of those now also does a blocking flash write in the real-time main-loop path,
#          and adds up in flash wear over time - this level is an explicit, opt-in
#          tradeoff, not the default.
#
#configure() is called once at boot by main.py (so an ERROR print during config validation
#can still be logged) and again by configweb.py right after a System-section save changes
#LOGLEVEL/LOG_MAX_KB, so the change takes effect immediately within the same boot rather
#than only after a reboot.

import os
import time

LOGFILE = "log.txt"
LOGFILE_OLD = "log.txt.old"
LEVELS = ("off", "info", "debug")
_RANK = {"off": 0, "info": 1, "debug": 2}

_level = "off"
_maxBytes = 100 * 1024
_size = 0
_bootMarked = False


def _fileSize(path):
    try:
        return os.stat(path)[6]
    except OSError:
        return 0


def configure(level, maxKb):
    global _level, _maxBytes, _size, _bootMarked
    _level = level if level in LEVELS else "off"
    try:
        _maxBytes = max(1, int(maxKb)) * 1024
    except (TypeError, ValueError):
        _maxBytes = 100 * 1024
    _size = _fileSize(LOGFILE)
    _bootMarked = False


def _rotateIfNeeded(nextLineLen):
    #Single-backup rotation: once the active file would exceed _maxBytes, it becomes the
    #backup (replacing any previous one) and a fresh file starts. Avoids ever needing to
    #parse-and-rewrite-trim a file from the front, which plain file APIs don't support
    #directly and would cost far more flash wear/time than an occasional rename.
    global _size
    if _size + nextLineLen <= _maxBytes:
        return
    try:
        os.remove(LOGFILE_OLD)
    except OSError:
        pass
    try:
        os.rename(LOGFILE, LOGFILE_OLD)
    except OSError:
        pass
    _size = 0


def _write(line):
    global _size
    data = line + "\n"
    _rotateIfNeeded(len(data))
    try:
        with open(LOGFILE, "a") as f:
            f.write(data)
        _size += len(data)
    except OSError as ex:
        print("logHelper: could not write to " + LOGFILE + ": " + str(ex))


def log(message, level="info"):
    #level is the minimum LOGLEVEL needed for this message to reach the file - "info" for
    #significant events, "debug" for high-frequency chatter. Never touches the terminal -
    #callers keep their own existing print()/debug() calls exactly as before; this is
    #purely an additional file sink.
    global _bootMarked
    if _RANK.get(_level, 0) < _RANK.get(level, 1):
        return
    if not _bootMarked:
        _bootMarked = True
        _write("--- boot @ ticks_ms=" + str(time.ticks_ms()) + " ---")
    _write("[+" + str(time.ticks_ms()) + "ms] " + message)


def readLog(chunkSize=512):
    #Yields the log's bytes (backup file then current, oldest-first), read in fixed-size
    #chunks rather than loaded whole into memory - the file can be up to ~2x LOG_MAX_KB
    #(current + backup) and this project has already hit real MicroPython memory limits
    #building big strings elsewhere.
    for path in (LOGFILE_OLD, LOGFILE):
        try:
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(chunkSize)
                    if not chunk:
                        break
                    yield chunk
        except OSError:
            pass


def clearLog():
    global _size
    for path in (LOGFILE, LOGFILE_OLD):
        try:
            os.remove(path)
        except OSError:
            pass
    _size = 0
