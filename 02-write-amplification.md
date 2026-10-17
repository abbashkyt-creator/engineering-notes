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

## Why a price change costs so much WAL (17 Oct)

The average hid two very different writes. `pg_stat_statements` per statement, read-only, one row per call:

| Statement | WAL records per row | WAL per row | Full-page images among its records |
|---|---|---|---|
| Countdown and "last checked" only | ~46 | ~24 KB | 9% |
| Price change | ~590 | ~650 KB | 21% |

A price change can't be a HOT update, because it changes indexed columns. So the new row version is inserted into all 28 indexes on the table. Nine of those are GIN text-search indexes, trigram and full-text, and one covers title plus description. A GIN insert adds one entry per trigram or word of the indexed text, which matches several hundred WAL records for a single row.

Full-page images are a minority, so most of the cost is index maintenance, not checkpoints.

## Deadlocks

On 3 Oct, 84 of the 126 deadlocks involved the no-change UPDATEs: overlapping batches re-stamping the same rows in different orders. With those writes gone, the lock traffic that caused them went too.

## What I'd do next, from first principles

- **Stop storing the countdown.** It can always be derived from the close time, which is stored once. Today it is still written once per refresh cadence. Deriving it at read time removes those writes entirely, instead of batching them.
- **Take search out of the hot table.** The trigram and full-text indexes serve search, but every price change pays for them. A narrow search table, updated only when the title or description really changes, would let price updates be HOT and touch a few indexes instead of 28.
