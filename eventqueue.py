#IRQ-safe fixed-size event ring buffer. Sensor/pushbutton IRQ handlers push
#(event_type, team, pin) tuples here instead of setting shared flags/globals, so closely-spaced
#events (including PB3 menu presses) are each preserved individually. Slots are preallocated and
#reused in place; head/tail/count updates are wrapped with IRQs disabled so they can't race the
#main loop's popEvent(). Split out of main.py (v3.01) as its own small compile unit.
import machine

EVENT_GOAL = "GOAL"
EVENT_TIMEOUT = "PB"
EVENT_ACTION = "ACTION"
EVENT_BUFFER_SIZE = 16

_eventBuffer = [[None, None, None] for _ in range(EVENT_BUFFER_SIZE)]
_eventHead = 0
_eventTail = 0
_eventCount = 0
eventDropped = 0

def pushEvent(evtType, team, pin):
    global _eventHead, _eventCount, eventDropped
    state = machine.disable_irq()
    try:
        if _eventCount >= EVENT_BUFFER_SIZE:
            eventDropped += 1
        else:
            slot = _eventBuffer[_eventHead]
            slot[0] = evtType
            slot[1] = team
            slot[2] = pin
            _eventHead = (_eventHead + 1) % EVENT_BUFFER_SIZE
            _eventCount += 1
    finally:
        machine.enable_irq(state)

def popEvent():
    global _eventTail, _eventCount
    state = machine.disable_irq()
    try:
        if _eventCount == 0:
            return None
        slot = _eventBuffer[_eventTail]
        evtType, team, pin = slot[0], slot[1], slot[2]
        _eventTail = (_eventTail + 1) % EVENT_BUFFER_SIZE
        _eventCount -= 1
    finally:
        machine.enable_irq(state)
    return (evtType, team, pin)

def takeDropped():
    #Atomically reads and resets the dropped-event counter so the main loop's report can't
    #race a pushEvent() call incrementing it mid-read.
    global eventDropped
    state = machine.disable_irq()
    try:
        n = eventDropped
        eventDropped = 0
    finally:
        machine.enable_irq(state)
    return n
