# Engineering notes

**Hardest problem so far.** On 10 Sep 2026 my engine went silent about 100 s after every start, three starts in a row. Postgres showed its sessions idle in transaction, so it looked like a lost database reply, and no in-process watchdog fired. Two py-spy dumps taken seconds apart showed one thread holding the GIL in the same frame: a regex with six lazy gaps, backtracking over a page that lacked its closing marker. I replaced it with marker-based parsing capped at 2 MB and tested for linear time on hostile input. I also moved the watchdog out of process: a supervisor now kills the engine after 180 s without a heartbeat. ([Note 03](03-gil-freeze.md), with a runnable repro.)

I build and run [GhostNode](https://ghostnode.co), a Python and PostgreSQL system on one machine. It tracks 8 auction marketplaces (1.7M+ listings so far) and places bids automatically on 4 of them.

Below are five production problems from running it. No product code is published. Where a technique is general, [`repro/`](repro/) has a small script or query you can run.

| # | Problem | Result |
|---|---|---|
| 01 | [A bid must never go above the limit or out twice](01-never-bid-twice.md) | Retries only before a connection exists; a test checks there's no replay after a reset |
| 02 | [Listing updates were 99% of the WAL, and most changed nothing](02-write-amplification.md) | WAL 3,772 → 1,509 MB/h over a 19-hour average (−60%), and why a price change still costs ~650 KB per row |
| 03 | [The engine froze 100 seconds after every start](03-gil-freeze.md) | Two py-spy dumps, seconds apart, showed one thread holding the GIL in a regex ([repro](repro/gil_regex_freeze.py)) |
| 04 | [One slow source starved all the others](04-fair-refresh-lanes.md) | Price age in a listing's final 5 minutes: about 3 days → under 1 minute |
| 05 | [Vacuum could not keep the main table clean](05-vacuum-falling-behind.md) | Dead tuples 77% → 0.1% after the fixes and a manual VACUUM |

In the GhostNode repository, 231 of 409 commits are co-authored by Claude Code. I set the design, review every change, and do the debugging and the production operations.

Abbas Bidhan · [LinkedIn](https://www.linkedin.com/in/abbas-bidhan) · [GitHub](https://github.com/abbashkyt-creator)
