# 02 · Listing updates were 99% of the WAL, and most changed nothing

**When:** 3 October 2026, re-measured 16 and 17 October · **Stack:** Python, SQLAlchemy, PostgreSQL 16

_GhostNode's code is written by AI coding agents I direct; in this note, "I" means me working with them ([how](README.md))._

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

## Where the WAL goes now (17 Oct)

I looked at one 15½-minute window (17 Oct, 02:28–02:44 UTC, 499 MB of WAL) in two ways, both read-only. `pg_stat_statements`, diffed across the window, gives WAL per statement. `pg_waldump`, over exactly the same stretch of WAL, gives WAL by kind.

| Statement | Rows | WAL per row | Share of the window's WAL |
|---|---|---|---|
| Countdown and "last checked" only | 6,516 | ~27 KB | 35% |
| Price change (five statement shapes) | 311 | ~470 KB (230–780 by shape) | 29% |
| Description and images (enrichment) | 129 | ~227 KB | 6% |
| Close-time correction | 116 | ~116 KB | 3% |
| New listing | 187 | ~60 KB | 2% |

Other statements and background work make up the remaining quarter.

The table lists only the statements that wrote the most WAL. The table had 843 inserts in the window. The INSERT statement shown accounts for 187 of them, and the rest came from several other INSERT statements, not shown. New listings arrive in scrape bursts: 843 in 15½ minutes is about 2.6 times the day's average rate (30,419 in 24 hours).

- **Countdown writes:** each one is cheap, but they are by far the most common write, so they are the biggest single share. 83% of the table's updates were HOT. The countdown statement still averages 66 WAL records per row, which means some of its updates are not HOT and pay for every index.
- **Price changes:** a price change can't be a HOT update, because it changes indexed columns. So the new row version goes into all 28 indexes on the table.
  - Nine of those are GIN text-search indexes, trigram and full-text, 7.6 GB together. The largest cover title and description.
  - A GIN insert adds one entry per trigram or word. In this window that came to about 370 GIN records per new row version of the table (843 inserts and 1,562 non-HOT updates). That is an average over every kind of write, and it is above the 308 records an insert writes in total. The other statements in the table average about 350 records per row, GIN or not, so they cannot lift the average to 370 alone. The rest comes from countdown writes that could not be HOT. The countdown statement wrote 430,000 records in the window, enough for about 1,000 such rows, and each of those re-inserts every GIN entry for its row.

A new listing and a price change both add an entry to every index. So why does a price change cost several times more (a new listing is 60–160 KB, depending on the INSERT statement)? In the window, their WAL records per row are close: 308 and 431. The difference is full-page images: 2% of the insert's records, against 34% of the price change's. An insert lands on pages that are already hot: the end of the heap, and index pages that this cycle has already copied. A price change rewrites a row anywhere in the table, so it touches cold pages that have to be copied whole.

An earlier version of this note quoted ~650 KB per price change, from cumulative statistics. That figure holds: the commonest shape cost ~780 KB here. But it is not the cost of every non-HOT update. In this window only 311 of the 1,562 non-HOT updates were price changes.

### Correction: records are not bytes

The earlier version also said full-page images were a minority of the records, so the cost was index maintenance and not checkpoints. Counting bytes says otherwise:

- **In the window above:** full-page images were 79% of the WAL bytes, and GIN index inserts 89%.
- **In an earlier full checkpoint cycle** (01:21–01:44, 500 MB): 92% and 91%.

How large the full-page share is depends on where a window falls in the checkpoint cycle.

The first change to a page after a checkpoint copies the whole page into the WAL. So index maintenance and checkpoints work together: the indexes decide how many pages are touched, and the checkpoint interval decides how often each one is copied. The three largest text indexes run with `fastupdate=off`. That keeps searches fast, but every entry goes straight into the tree instead of a pending list.

## Deadlocks

The 190 in the symptom are the 28 hours before the fixes. 126 of them fell on 3 Oct before the fixes, and 84 of those involved the no-change UPDATEs: overlapping batches re-stamping the same rows in different orders.

After the fixes there were none for the first half hour. Then a Docker restart at 17:25 made every listing overdue at once, and the catch-up produced 48 deadlocks in 22 minutes, between scrape updates and clock updates. There were none from 18:06 to 19:07, when that day's measurement ended, and none in the 19-hour window on 16 Oct. Postgres has counted none since it last started, on 15 Oct (checked 17 Oct).

## What I'd do next, from first principles

- **Stop storing the countdown.** It can always be derived from the close time, which is stored once. Today it is still written once per refresh cadence, and in the window above those writes were 35% of the WAL. Deriving it at read time removes them entirely, instead of batching them.
- **Take search out of the hot table.** The trigram and full-text indexes serve search, but every price change pays for them, and they are about 90% of the WAL. A narrow search table, updated only when the title or description really changes, would let price updates be HOT and touch a few indexes instead of 28.
- **Copy each page less often.** A longer `checkpoint_timeout` writes each touched page whole fewer times, at the cost of a longer crash recovery. It is a setting, not a fix, so it comes after the search table.
