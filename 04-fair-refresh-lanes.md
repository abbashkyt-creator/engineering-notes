# 04 · One slow source starved all the others

**When:** 3 October 2026 · **Stack:** Python asyncio, PostgreSQL

_GhostNode's code is written by AI coding agents I direct; in this note, "I" means me working with them ([how](README.md))._

## Symptom

- Listings in their final 5 minutes had prices about 3 days old.
- 0% of them were refreshed on schedule.
- Within the hour before close, the median price age was 47 to 209 minutes, depending on the source.

## Two causes

1. **The slowest source set the pace for all of them.** One loop ran every source together with `asyncio.gather` and waited for all of them before starting the next tick.
   - One source was far slower than the rest, so a single tick could take about 100 minutes.
   - Fast sources finished in minutes, then waited.
2. **There was a backlog no tick could clear.** About 135,000 of 156,000 listings were due on every tick, and each source took at most 1,500 per tick. Listings close to their end competed with listings days away, and most never came up.

## Fix: one lane per source, urgent work first

- **A token bucket per lane.** Each source gets a per-minute budget, with the batch size as the burst. A cadence floor means a listing is never re-sent inside its own refresh interval, even after a failed refresh.
- **Three scans, each on its own clock:**
  - listings closing within 60 minutes, every 5 seconds (an index range scan, about 1.5 ms);
  - within 6 hours, every 60 seconds;
  - everything else, every 15 minutes.
- **Urgency first, then wait time.** Inside a tier, a listing that was never sent, or was sent longest ago, goes first. Without that, one source re-priced its 31 closest listings up to 14 times in 17 minutes while 73 listings slightly further out got nothing.
- **One band for the final minutes.** As separate tiers, last-minute listings starved the 1–5-minute ones. As one band ordered by how overdue each listing is, both stay fresh.
- **A fallback.** If the lanes crash, the old loop takes over.
- **Tests.** 31 tests cover the lane rules and the real worker loop, including "a slow source never delays a fast one".

## Result

Measured the same evening, on the same metrics, for every source but one. That one refreshes by keyword search every 15 minutes and was refusing part of our searches that evening. It was not the slow source. For the searches it still answered, its listings in their final 5 minutes went from 6.8 days old to a median of 3 minutes.

| | Before | After |
|---|---|---|
| Listings in their final 5 minutes, price age | about 3 days, 0% on schedule | under 1 minute (see below) |
| Source A, closing within the hour, median age | 68 min | 1.4–5.9 min |
| Source B, closing within the hour, median age | 47 min, 0% on schedule | 0.8 min, 100% on schedule |
| Source C, closing within the hour, median age | 209 min, 0% on schedule | 0.2 min, 100% on schedule |

No source was asked for more than its budget.

Rows A–C are the refresh families I measured one by one; C groups several smaller sites that are refreshed through a browser.

My record of the evening check says only that the final-5-minutes band was "under a minute old". It does not say whether that was the median or the oldest listing, and I did not record the distribution, so there is no p95 or maximum to quote. The closest thing is one wave of 81 listings at one source: 0.3 minutes old at 1–2 minutes before close and 0.5 at 2–5 minutes, against 15.2 and 14.2 before. Next time I would record p50, p95 and the maximum.
