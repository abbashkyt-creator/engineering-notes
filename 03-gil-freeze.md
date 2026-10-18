# 03 · The engine froze 100 seconds after every start

**When:** 10 September 2026 · **Stack:** Python, PostgreSQL · **Found with:** py-spy

_GhostNode's code is written by AI coding agents I direct; in this note, "I" means me working with them ([how](README.md))._

## Symptom

On three starts in a row, the engine went silent about 100 seconds in:

- its heartbeat file stopped updating;
- Postgres showed its sessions `idle in transaction`, waiting for a next command that never came;
- none of the in-process watchdogs fired.

From the database side this looked like a network problem between the app and Postgres.

## How I found it

I ran `py-spy dump --locals` on the frozen process twice, a few seconds apart. Both dumps showed one thread marked `active+gil`, in the same frame: a function parsing a product page. Every other thread was waiting, including the heartbeat writer, the watchdogs and all the database threads.

A truly lost database reply looks different: the heartbeat keeps beating and no thread holds the GIL. From Postgres the two look the same.

## Root cause

A regular expression with six unbounded lazy gaps (`.*?`) ran in DOTALL mode over a whole HTML page. On a page that lacked the expected closing marker, every combination of gap lengths was tried before giving up. That is polynomial in the page length, roughly one power of n per lazy gap; the repro's timings grow about as n^6.5. CPython's `re` engine holds the GIL while it matches, so that one call stopped every other thread in the process, the safety nets included.

It struck about 100 seconds after each start because a background job reached that page in that window.

[`repro/gil_regex_freeze.py`](repro/gil_regex_freeze.py) shows the effect on a 640-character input. A heartbeat thread that should beat every 0.25 s gets no beats at all while the regex runs. A marker-based parser does the same job in under a millisecond. Going from 30 to 40 pairs multiplies the time by about 6, and 40 to 50 by about 4.4, which is what n^6.5 predicts. A real product page is far longer.

## Fix

- The parser finds markers with `str.find`, runs small patterns over a capped window, and caps pages at 2 MB. A test feeds it hostile input and checks that it stays linear.
- No in-process watchdog survives a GIL freeze, so an external supervisor reads the child's heartbeat file and kills the child after 180 seconds without a beat.
- Every database connection carries `application_name=<role>:<pid>`, so `pg_stat_activity` shows which process holds which session.
