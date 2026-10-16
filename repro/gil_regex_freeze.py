"""Reproduce note 03: one regex freezes every thread in a Python process.

A heartbeat thread should beat every 0.25 s. While the main thread runs a
pattern with several unbounded lazy gaps over a page that does not match,
CPython's `re` engine backtracks without releasing the GIL, and the heartbeat
gets no beats in until the match gives up. That is why no in-process watchdog
could save the engine: it was frozen too.

Run:  python gil_regex_freeze.py
"""
import re
import threading
import time

beats = []
stop = threading.Event()


def heartbeat():
    while not stop.is_set():
        beats.append(time.monotonic())
        time.sleep(0.25)


def beats_between(start, end):
    return sum(1 for t in beats if start < t < end)


# Six lazy .*? gaps (three of them captured) in DOTALL mode, over a page with
# no closing marker.
BAD = re.compile(r"<dt>(.*?)</dt>.*?<dd>(.*?)</dd>.*?<dt>(.*?)</dt>.*?NEVER", re.S)

# 32 short pairs is enough for a multi-second freeze; the cost explodes as the
# page grows (on one machine: 10 pairs 0.02 s, 20 pairs 0.17 s, 30 pairs 2.8 s,
# 40 pairs 17 s, 50 pairs 77 s). A real product page is far bigger than this.
page = "<dt>k</dt><dd>v</dd>" * 32


def bounded(text):
    """The same job, done with markers instead of a backtracking pattern."""
    out, i = [], 0
    while True:
        a = text.find("<dt>", i)
        if a < 0:
            return out
        b = text.find("</dt>", a)
        c = text.find("<dd>", b)
        d = text.find("</dd>", c)
        if min(b, c, d) < 0:
            return out
        out.append((text[a + 4:b], text[c + 4:d]))
        i = d + 5


threading.Thread(target=heartbeat, daemon=True).start()
time.sleep(1)

t0 = time.monotonic()
BAD.search(page)
t1 = time.monotonic()
expected = int((t1 - t0) / 0.25)
print(f"backtracking regex: {t1 - t0:5.2f} s, heartbeats during it: "
      f"{beats_between(t0, t1)} (a free thread would have beaten ~{expected} times)")

t2 = time.monotonic()
pairs = bounded(page)
t3 = time.monotonic()
print(f"bounded parser:     {t3 - t2:7.4f} s for {len(pairs)} pairs")
stop.set()
