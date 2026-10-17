# 02 · Listing updates were 99% of the WAL, and most changed nothing

**When:** 3 October 2026, re-measured 16 and 17 October · **Stack:** Python, SQLAlchemy, PostgreSQL 16

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

| | 3 Oct, before (a few-minute sample) | 3 Oct, after (9-min window) | 16 Oct, 19-hour average |
|---|---|---|---|
| Listings UPDATEs / hour | 69,898 | 11,541 | 28,676 |
| WAL / hour | 3,772 MB | 707 MB | 1,509 MB (**−60%**) |
| HOT share of updates | 67% | 78% | 86.9% |
| Deadlocks | 190 in 28 h | see below | 0 in the same 19 h |

The 9-minute window was the best case; the 19-hour average is the number to quote. That average covers a larger table, sources that re-stamp thousands of listings in bursts, and the refresh lanes from note 04, which went live the same night and re-price more listings every hour. The "before" figure is a short sample, so −60% is approximate.

## Why a price change costs so much WAL (17 Oct)

The average hid two very different writes. `pg_stat_statements` per statement, read-only, one row per call:

| Statement | WAL records per row | WAL per row | Full-page images among its records |
|---|---|---|---|
| Countdown and "last checked" only | ~46 | ~24 KB | 9% |
| Price change | ~590 | ~650 KB | 21% |

A price change can't be a HOT update, because it changes indexed columns. So the new row version is inserted into all 28 indexes on the table. Nine of those are GIN text-search indexes, trigram and full-text, 7.6 GB together; the largest cover title and description. A GIN insert adds one entry per trigram or word of the indexed text, which matches several hundred WAL records for a single row.

### Correction: records are not bytes

An earlier version of this note said that full-page images were a minority of the records, so most of the cost was index maintenance and not checkpoints. Counting bytes says otherwise. I read one checkpoint cycle of WAL with `pg_waldump --stats=record`: 17 Oct, 01:21–01:44 UTC, from the checkpoint's redo point, 500 MB.

- Full-page images were 92% of the bytes, though a minority of the records.
- GIN inserts were 91% of the bytes, and 93% of those bytes were full-page images.
- B-tree indexes were 4%, and the table itself (heap and pruning) another 4%.

In those 23 minutes, 4,130 new row versions needed index entries (3,021 inserts and 1,109 non-HOT updates). They produced 451,156 GIN insert records, about 109 each, on pages scattered across 7.6 GB of index. The first change to a page after a checkpoint copies the whole page into the WAL, so each page they touch is written whole the first time in every cycle.

Index maintenance and checkpoints work together: the indexes decide how many pages are touched, and the checkpoint interval decides how often each one is copied. The three largest text indexes run with `fastupdate=off`. That keeps searches fast, but every entry goes straight into the tree instead of a pending list.

## Deadlocks

The 190 in the symptom are the 28 hours before the fixes. 126 of them fell on 3 Oct before the fixes, and 84 of those involved the no-change UPDATEs: overlapping batches re-stamping the same rows in different orders.

After the fixes there were none for the first half hour. Then a Docker restart at 17:25 made every listing overdue at once, and the catch-up produced 48 deadlocks in 22 minutes, between scrape updates and clock updates. There were none from 18:06 to 19:07, when that day's measurement ended, and none in the 19-hour window on 16 Oct. Postgres has counted none since it last started, on 15 Oct (checked 17 Oct).

## What I'd do next, from first principles

- **Stop storing the countdown.** It can always be derived from the close time, which is stored once. Today it is still written once per refresh cadence. Deriving it at read time removes those writes entirely, instead of batching them.
- **Take search out of the hot table.** The trigram and full-text indexes serve search, but every price change pays for them, and they are 91% of the WAL. A narrow search table, updated only when the title or description really changes, would let price updates be HOT and touch a few indexes instead of 28.
- **Copy each page less often.** A longer `checkpoint_timeout` writes each touched page whole fewer times, at the cost of a longer crash recovery. It is a setting, not a fix, so it comes after the search table.
