/*
  NEXTCAM — SQL Server performance maintenance (ADR-0031). SQL Server 2019 or later.

  Run in SSMS or sqlcmd against the shop's database (replace nextcam with its name).
  Every section is read-only except 1 (Query Store, a database setting) and 2 (statistics).
  Nothing here changes data. Indexes themselves come only from Alembic migrations, never
  from this file: an index created by hand is unknown to the next upgrade.
*/

USE nextcam;
GO

/* 1. Query Store: keeps the history of plans and timings, so a query that became slow
      after an upgrade or more data can be found and compared. Small overhead; available
      in every edition including Express. Once per installation. */
ALTER DATABASE CURRENT SET QUERY_STORE = ON;
ALTER DATABASE CURRENT SET QUERY_STORE (
    OPERATION_MODE = READ_WRITE,
    QUERY_CAPTURE_MODE = AUTO,          -- ignores tiny one-off statements
    MAX_STORAGE_SIZE_MB = 512,
    INTERVAL_LENGTH_MINUTES = 60,
    CLEANUP_POLICY = (STALE_QUERY_THRESHOLD_DAYS = 30)
);
GO

/* 2. Statistics: SQL Server updates them by itself after enough changes, but a busy day's
      sales sit past the last histogram step until then. Weekly, out of hours (minutes on
      a year of data; reads the tables, does not block sales under RCSI). */
EXEC sp_updatestats;
GO

/* 3. Fragmentation of the large tables (read-only). Above ~30% on an index over ~1000
      pages, rebuild it out of hours:  ALTER INDEX <name> ON <table> REBUILD;  */
SELECT OBJECT_NAME(ips.object_id) AS table_name, i.name AS index_name,
       ips.page_count, CAST(ips.avg_fragmentation_in_percent AS DECIMAL(5, 1)) AS frag_pct
FROM sys.dm_db_index_physical_stats(DB_ID(), NULL, NULL, NULL, 'LIMITED') ips
JOIN sys.indexes i ON i.object_id = ips.object_id AND i.index_id = ips.index_id
WHERE ips.page_count > 1000
ORDER BY ips.avg_fragmentation_in_percent DESC;
GO

/* 4. Indexes SQL Server wished it had since the last restart (read-only). A suggestion,
      not a decision: measure first (scripts/volume_timing.py) and add it through a
      migration, weighing the cost on every INSERT of a sale. */
SELECT TOP 15
    CAST(gs.avg_total_user_cost * gs.avg_user_impact * (gs.user_seeks + gs.user_scans) AS BIGINT) AS score,
    OBJECT_NAME(d.object_id) AS table_name, d.equality_columns, d.inequality_columns, d.included_columns
FROM sys.dm_db_missing_index_details d
JOIN sys.dm_db_missing_index_groups g ON g.index_handle = d.index_handle
JOIN sys.dm_db_missing_index_group_stats gs ON gs.group_handle = g.index_group_handle
WHERE d.database_id = DB_ID()
ORDER BY score DESC;
GO

/* 5. The most expensive statements since the last restart (read-only). */
SELECT TOP 15
    qs.execution_count,
    qs.total_worker_time / qs.execution_count / 1000 AS avg_cpu_ms,
    qs.total_elapsed_time / qs.execution_count / 1000 AS avg_ms,
    qs.total_logical_reads / qs.execution_count AS avg_reads,
    SUBSTRING(st.text, 1, 200) AS statement_start
FROM sys.dm_exec_query_stats qs
CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) st
WHERE st.dbid = DB_ID()
ORDER BY qs.total_worker_time DESC;
GO

/* 6. What the server waited on since the last restart (read-only). PAGEIOLATCH = disk
      reads (more memory or a faster disk), LCK_ = locks between registers, CXPACKET /
      CXCONSUMER = parallel queries (reports). */
SELECT TOP 10 wait_type, waiting_tasks_count, wait_time_ms / 1000 AS wait_s
FROM sys.dm_os_wait_stats
WHERE wait_type NOT LIKE 'SLEEP%' AND wait_type NOT LIKE '%QUEUE%'
  AND wait_type NOT IN ('BROKER_TASK_STOP', 'XE_TIMER_EVENT', 'DIRTY_PAGE_POLL',
                        'SQLTRACE_INCREMENTAL_FLUSH_SLEEP', 'HADR_FILESTREAM_IOMGR_IOCOMPLETION',
                        'SP_SERVER_DIAGNOSTICS_SLEEP', 'QDS_PERSIST_TASK_MAIN_LOOP_SLEEP',
                        'QDS_ASYNC_QUEUE', 'WAITFOR', 'CHECKPOINT_QUEUE')
ORDER BY wait_time_ms DESC;
GO
