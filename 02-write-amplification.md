# 02 · Listing updates were 99% of the WAL, and most changed nothing

**When:** 3 October 2026, re-measured 16 October · **Stack:** Python, SQLAlchemy, PostgreSQL 16

## Symptom

WAL and disk traffic grew far faster than the data, and the database logged 190 deadlocks in 28 hours.

## How I measured it

I took two snapshots of `pg_stat_statements`, `pg_stat_wal` and the table statistics a few minutes apart and diffed them. The query is in [`repro/wal_rates.sql`](repro/wal_rates.sql).

- UPDATEs to the listings table made up 99% of all WAL: 3,772 MB per hour.
- One statement, which refreshes a listing's countdown and its "last checked" time, ran 46,000–77,000 times an hour. It re-stamped listings that hadn't changed, including listings days away from closing.

Each re-stamp still produced a new row version, WAL, index work and lock traffic.

## Five changes, made the same day

1. **No-change writes are dropped at flush time.** A SQLAlchemy `before_flush` hook skips an UPDATE whose only changes are bookkeeping fields while the row is still inside its refresh cadence. The scheduler keeps "last checked" in memory instead.
2. **Countdown jitter is ignored.** Some sources only give a countdown, so "now + countdown" moves a second or two on every read. A move smaller than the countdown's resolution is not written. A real extension is written at once.
3. **An indexed column stops flip-flopping.** A listing found by two keywords had that column rewritten on every pass. Matches are now appended once.
4. **Two importers use UTC.** They stamped local time instead of UTC, so about 1,460 listings looked overdue on every scheduler tick.
5. **WAL settings:** `wal_compression = lz4` and `checkpoint_timeout = 15min`.

## Result

| | 3 Oct, before (a few-minute window) | 3 Oct, after (9-min window) | 16 Oct, 19-hour average |
|---|---|---|---|
| Listings UPDATEs / hour | 69,898 | 11,541 | 28,676 |
| WAL / hour | 3,772 MB | 707 MB | 1,509 MB (**−60%**) |
| HOT share of updates | 67% | 78% | 86.9% |
| Deadlocks | 190 in 28 h | | 0 in the same 19 h |

The 9-minute window was the best case; the 19-hour average is the number to quote. That average covers a larger table, sources that re-stamp thousands of listings in bursts, and the refresh lanes from note 04, which went live the same night and re-price more listings every hour.

## Still open

WAL per listings update barely moved: about 54 KB before and about 52 KB now. Almost all of the gain came from doing fewer writes, not cheaper ones.

The statement that only refreshes countdowns now costs about 18 KB of WAL per call. The two statements that change a price are about 2% of update calls but about 29% of statement WAL, at roughly 800 KB per call. I haven't found out why yet. My first suspect is non-HOT updates touching every index, including the trigram (GIN) ones.
