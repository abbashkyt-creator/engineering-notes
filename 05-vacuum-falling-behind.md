# 05 · Vacuum could not keep the main table clean

**When:** 10 and 17 September 2026 · **Stack:** PostgreSQL 16, SQLAlchemy

## 10 Sep: a corrupt index killed every vacuum

Page loads swung between 1 second and 20. The listings table held more dead row versions than live ones.

- **The cause.** The Postgres log showed every autovacuum of that table dying `while vacuuming index` on a trigram (GIN) index; one of its files pointed at a block that didn't exist. An identical healthy copy of the index already existed. I dropped the corrupt one and renamed the copy, and that night a vacuum completed for the first time in the logs I had.
- **Startup DDL cancelled vacuums.** Startup ran `CREATE INDEX IF NOT EXISTS`, which takes its lock before checking whether the index exists, so every start cancelled a running vacuum. Startup now checks `pg_indexes` first.
- **No update could be HOT.** A covering index included two columns that change on every refresh, so no update qualified. Without them, HOT updates went from 0% to 34% within the first hour.

## 17 Sep: back to 77% dead

A week later the table was back to 77.4% dead tuples, and `count(*)` took 215.7 seconds.

- **API sessions were idle in transaction for 18+ minutes.** I set `idle_in_transaction_session_timeout` with `ALTER DATABASE`, and the sessions survived anyway. The app's connect hook ran its own `SET` on every new connection with a 30-minute value, and a session-level setting overrides the database default.
  - I split the setting by role. The engine keeps 30 minutes, because it holds a session across a long multi-page job. The API gets 2 minutes.
  - One endpoint held a read transaction open across a third-party HTTP call. It now commits before the call. A regression test checks that the commit comes first, and it fails on the old code.
- **The cleanup.** I ran a manual `VACUUM (ANALYZE)` of the table. It took 61 minutes and blocked nothing, so the site stayed up the whole time. `VACUUM FULL` would have locked the table.

## Result

| | 17 Sep, before | After the fixes and the manual vacuum |
|---|---|---|
| Dead tuples, listings table | 77.4% | 0.1% |
| `count(*)`, listings table | 215.7 s | 4.2 s |
| Index size (also dropped an unused 6.6 GB trigram index) | 14 GB | 7.8 GB |

**Checked again on 17 Oct:** 3.7% of the table's row versions were dead, under the 5% at which autovacuum is set to start on it. API transactions end after 2 minutes idle; the longest open one at the time was 1 min 40 s.

## Still open

**What corrupted the index is unproven.** The database had gone through crash recovery the day before. It runs in Docker Desktop's VM on Windows, where a flush to disk isn't guaranteed to reach the physical disk before a crash. That is the likely trigger. What would catch it early: an alert when a large table's last completed autovacuum is more than a day old, and a scan of the Postgres log for `while vacuuming index`.


I haven't proven which of the idle sessions held back cleanup. In READ COMMITTED, an idle transaction whose last statement was a SELECT holds no snapshot, so only sessions that had written would block it. Next time I'll capture `backend_xid` and `backend_xmin` from `pg_stat_activity` while it is happening.
