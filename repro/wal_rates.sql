-- Note 02: how much WAL and how many row writes per hour, from two snapshots.
-- Run this once, wait ~10 minutes, run it again, and diff the two rows
-- (divide each difference by the elapsed seconds, multiply by 3600).
-- Needs PostgreSQL 14+ (pg_stat_wal). Change 'listings' to your table.
SELECT now()                                  AS taken_at,
       w.wal_records,
       w.wal_fpi                              AS full_page_images,
       w.wal_bytes,
       t.n_tup_upd                            AS row_updates,
       t.n_tup_hot_upd                        AS hot_updates,
       d.deadlocks
FROM pg_stat_wal w
CROSS JOIN pg_stat_user_tables t
CROSS JOIN pg_stat_database d
WHERE t.relname = 'listings'
  AND d.datname = current_database();

-- Which statements write the most (needs the pg_stat_statements extension):
-- SELECT calls, wal_bytes, left(query, 120) AS query
-- FROM pg_stat_statements ORDER BY wal_bytes DESC LIMIT 10;
