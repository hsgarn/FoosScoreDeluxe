# Changelog

All notable changes to FoosScorePlusDeluxe are documented here. main.py's header
comment keeps only the current version; this file has the full history.

## v3.06 08/15/2026
- Fix the real cause of unreliable menu button response, found via a Pico 2 W + MicroPython
  v1.28 test that (unlike the original Pico W) didn't freeze and so surfaced the actual
  Python traceback: `pushbuttonTimers[idx].init(...)` was arming a `machine.Timer` from
  inside the pin's IRQ handler, which MicroPython's rp2 port raises `OSError 12` (ENOMEM)
  for - hard-IRQ context can't safely allocate, since the interrupt may have landed
  mid-garbage-collection. Because that exception aborted `pushbuttonInterrupt` partway
  through, the two lines after it never ran: `pushbuttonStates[idx]` never reset and
  `pushbuttonBlocked[idx]` never cleared (only the timer's callback did that), leaving that
  pin stuck ignoring further presses - the actual "sometimes takes two presses" / unreliable
  navigation reported across both boards. `sensorInterrupt` had the identical pattern for the
  goal sensors and would have hit the same failure once real goals were being scored, not
  just during menu testing.
  Replaced the per-pin `machine.Timer` debounce with a ticks_ms() deadline (an int, set from
  the ISR - allocation-free) polled once per main-loop iteration by the new
  `serviceDebounce()`, which does the actual unblocking outside interrupt context where
  allocation is always safe. `machine.Timer` is no longer used anywhere in main.py.
  Whether this was also silently contributing to the original RP2040 board's freezes (on top
  of the suspected I2C erratum) is unconfirmed - worth retesting the original Pico W with
  this fix before assuming the I2C mitigations were the only thing needed there too.

## v3.05 08/15/2026
- Fix two menu-navigation bugs found while chasing the I2C lockup:
  - PB1/PB2 were debounced with the full gameplay `DELAY_PB` (5000ms, sized to stop one
    physical time-out press from registering as several) even while reused for menu
    up/down navigation, so a second press inside that 5s window was silently dropped -
    reported as "sometimes it takes two button presses to move the pointer." They now use
    the shorter `DELAY_ACTION_PB` (same as PB3) whenever the menu is on screen.
  - `printMenuI2CLCD` drew the cursor twice on every page-boundary redraw (once inside the
    `pageChangedI2CLCD` branch, again unconditionally at the end) - doubling I2C traffic
    exactly on the presses that cross onto a new page, which lines up with lockups being
    reported specifically at the first/last item of a page. Cursor is now drawn once.
  These don't change the v3.03/v3.04 I2C-glitch mitigations, but should reduce how often
  they're needed - less I2C traffic per redraw and correctly-registering presses.

## v3.04 08/15/2026
- Add a hardware watchdog (`machine.WDT`, 8s timeout) armed once the main loop starts, so
  a board that's still wedged after the v3.03 I2C speed reduction reboots itself in ~8s
  instead of staying frozen until someone finds the power switch. Not armed during startup
  (WiFi connect retries can legitimately run past the RP2040's ~8.3s max WDT timeout and
  aren't fed) - only from the main loop onward, which is where the reported lockups occur.
  blink()/allBlink()/blinkDigit()/blinkTableNumber()/identFlash() each feed it inside their
  loops so a legitimate multi-second LED animation (e.g. blinking a two-digit table number,
  worst case ~20+s) can't be mistaken for a hang and trigger a false reset.

## v3.03 08/15/2026
- Drop the I2C LCD bus from 400kHz to 100kHz to reduce the odds of triggering RP2040
  errata E14 (a bus noise glitch permanently wedging the I2C peripheral, hanging the
  board with no exception and no serial output) - reported as the board locking up after
  a few menu down-presses, which redraw the LCD via dozens of back-to-back I2C writes
  each. Lower clock speed loosens the bus timing margins the glitch depends on; it's a
  mitigation, not a guaranteed fix - a hardware watchdog (to auto-recover from any future
  freeze) and a wiring/pull-up check were discussed but deferred.

## v3.02 08/15/2026
- WiFi connect: repeat the full `secrets.NETWORKS` list up to `WLAN_LIST_PASSES` times
  (a connection can fail on the first pass even when the network is fine - weak signal,
  AP still booting, etc.), poll `wlan.status()` against a per-attempt timeout instead of
  a flat sleep so a definitive failure (wrong password/no AP found/connect fail) bails
  out early, and wait 2s after `wlan.active(True)` so the CYW43 radio's firmware settles
  before the first `connect()` attempt - firing `connect()` immediately after
  `active(True)` can lose that race and fail the very first attempt against an otherwise
  fine network.
- Move version history out of main.py's header comment into this file; main.py now
  keeps only the latest entry.

## v3.01 08/14/2026
Split main.py into colors.py/eventqueue.py/debuglog.py/netmsg.py/ledstrip.py/iref.py.
The merged v3.00 file was ~68KB/1750 lines as a single compile unit, which was enough
to exhaust the RP2040's heap during MicroPython's on-device parse/compile step
(MemoryError at startup) even though the resulting bytecode would have run fine - the
compiler's parse tree for one file scales with that file's size, and each import now
compiles (and frees its own parse tree) independently before the next one runs. No
behavior changes intended; see each new module's header comment for what moved where
and why.

## v3.00 08/14/2026
Merge FoosScorePlus in as the new networking/reliability base under this board's
display/LED-strip/standalone-mode feature set: multi-client TCP, the UDP
discovery/management protocol (DISCOVER_PICO/ENTER_IDENT/EXIT_IDENT/ASSIGN/FLASH/
REPORT_TABLE), an IRQ-safe event ring buffer, per-pin debounce, a single unified
select() main loop, and threaded iRefFoos reporting. The NeoPixel LED-strip worker and
the iRefFoos HTTPS worker now share one core-1 thread (core1Worker) instead of each
claiming their own - MicroPython's _thread only supports one additional thread on this
hardware, so both can't run independently the way the two source projects used to. LED
commands are serviced first each iteration (score/timeout feedback is the more latency-
sensitive of the two); a long LED animation or a slow iRef HTTP call can still delay the
other by its full duration in the worst case - accepted tradeoff, see README. The third
pushbutton (PB3, the on-device menu "Action" button) now goes through the same per-pin
debounce and event ring buffer as the goal sensors and PB1/PB2, instead of its own
shared-flag mechanism. WiFi now tries every network in secrets.NETWORKS (replacing
secretsHP.py/secretsHome.py) before falling back to standalone mode. Config validation
moved fully inline (configHelper.py/requiredConfigItems.py are gone, matching
FoosScorePlus).

### FoosScorePlusDeluxe history prior to the v3.00 merge
- v2.11 11/03/2025 Add TFT LCD display setup.
- v2.10 05/10/2025 Add Set Color menu and its submenu options.
- v2.09 04/27/2025 Reworked LED Strip handling and send_command queue. Added Test LEDs sub menu.
- v2.08 11/20/2024 LCD improvements, Show Host, force standalonemode when no network available, add team colors, debugmode.
- v2.07 12/31/2023
- v2.06 12/29/2023 Pass c around to fix errors when scoring, time out. Got config save working
- v2.05 07/31/2023 Test Inputs, Test LEDs, FoosOBS Mode, StandAlone Mode mostly working
- v2.04 07/15/2023 Reworked configuration and validation
- v2.03 06/30/2023 Add led strips
- v2.02 02/17/2023 Add lcd displays
- v2.01 02/04/2023 Add Time Out push button logic
- v2.00 01/01/2023 Compatible with FoosOBSPlus v2.00 and above

### FoosScorePlus history merged in at v3.00
- v2.20 08/14/2026 Fix "Listening for Discovery Requests" spamming the console while idle.
- v2.19 08/14/2026 Add REPORT_TABLE:<mac> UDP command (blinks current table number without changing it).
- v2.18 08/14/2026 Allow multiple simultaneous FoosOBSPlus connections to the same table.
- v2.17 08/12/2026 Handle "ping" -> "pong" on the TCP connection.
- v2.16 08/12/2026 Bind the discovery/identify UDP socket to config.DPORT instead of a hardcoded 5051.
- v2.15 08/12/2026 Loop sendMessage()'s socket send() until all bytes are written.
- v2.14 08/12/2026 Reduce hot-path logging via a DEBUGMODE flag.
- v2.13 08/12/2026 Ring-buffer iRefFoos queue; lock-as-wake-signal instead of fixed poll.
- v2.12 08/12/2026 Keep-alive HTTPS socket for iRefFoos instead of a fresh TLS handshake per goal.
- v2.11 08/12/2026 IRQ-safe event ring buffer replacing shared teamScored/sensorPinNbr globals.
- v2.10 08/12/2026 Per-pin debounce flag/Timer instead of a blanket IRQ disable/restore.
- v2.09 08/12/2026 Leaner IRQ handlers: list.index(pin) instead of string-parsing, reused Timers.
- v2.08 08/12/2026 Single blocking select() over UDP/listen/client sockets instead of fixed polling.
- v2.07 08/12/2026 2-sensor tables (SENSOR3 optional); consolidated secrets.py; inline config validation.
- v2.06 07/05/2026 Threaded direct goal reporting to iRefFoos.
- v2.05 07/02/2026 Answer discovery while a game client is connected (BUSY status).
- v2.04 07/02/2026 Remote table assignment (table.txt); ENTER_IDENT/EXIT_IDENT/ASSIGN/FLASH.
- v2.03 06/08/2026 IR break sensors or laser sensors.
- v2.02 10/24/2025 Discover Pico address logic (UDP discovery).
- v2.01 02/04/2023 Time Out push button logic.
- v2.00 01/01/2023 Compatible with FoosOBSPlus v2.00 and above.
