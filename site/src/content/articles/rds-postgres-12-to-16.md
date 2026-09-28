---
title: "RDS Postgres 12 to 16: what Blue/Green doesn't warn you about"
description: "Taking an old RDS database from about $650 to about $165 a month: deleting 280 million rows first, rehearsing on a real copy, and every place it broke along the way, with Claude Code running most of the commands."
pubDate: 2026-09-28
tags: [postgres, aws, rds, claude-code]
category: field
---

At work I look after an internal CI orchestration service. It has run on one RDS Postgres instance for most of a decade. By this summer that instance was on Postgres 12, past the end of AWS standard support, and paying Extended Support on top of the instance price. In September I moved it to Postgres 16 on a smaller Graviton instance. The bill went from around $650 a month to about $165.

I did most of it with Claude Code in the terminal. It wrote the queries, ran the AWS CLI calls, read the logs, and kept a notes file across sessions. I approved each step and ran the production-destructive ones myself. This post walks through what I did, in order, and every place it broke.

## What Extended Support is and what it costs

[RDS Extended Support](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/extended-support.html) lets you keep running a major engine version after its RDS end of standard support date, for a fee. You get fixes for critical and high CVEs, fixes for critical bugs, and AWS support cases. It lasts up to three years. After that, RDS upgrades the major version for you.

You don't have to sign up for it. If you didn't opt out when you created or restored the instance, RDS [enrolls it automatically](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/extended-support-overview.html) when standard support ends. The console checkbox starts unchecked, but `create-db-instance` from the CLI or API [enrolls you unless you say otherwise](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/extended-support-creating-db-instance.html). To opt out, pass `--engine-lifecycle-support open-source-rds-extended-support-disabled`. You can change `EngineLifecycleSupport` on an existing instance too. The catch is that if the instance is already past the end date, disabling it makes RDS upgrade the instance to the next major version. Otherwise the [charges](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/extended-support-charges.html) stop only when you upgrade or delete the database.

The [RDS for PostgreSQL release calendar](https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-release-calendar.html) has the dates for Postgres 12. The community ended support in November 2024. RDS standard support ended on February 28, 2025, and Extended Support billing started the next day. Extended Support for 12 ends in February 2028.

You pay per vCPU-hour, on top of the instance price. The [RDS for PostgreSQL pricing page](https://aws.amazon.com/rds/postgresql/pricing/) uses Postgres 12 in US East (Ohio) as its example: $0.10 per vCPU-hour from March 2025 through February 2027, then $0.20 from March 2027. So the price doubles in year 3. A Multi-AZ standby is billed too.

Our instance was a `db.r5.xlarge` with 4 vCPUs and 32GB of memory. Extended Support came to 4 vCPUs × $0.10 × about 730 hours, or about $290 a month.

| Scenario | Instance | Extended Support | Total per month |
| --- | --- | --- | --- |
| Postgres 12, years 1 and 2 | ~$370 | ~$290 | ~$660 |
| Postgres 12, year 3 | ~$370 | ~$580 | ~$950 |
| Postgres 16, same instance | ~$370 | $0 | ~$370 |
| Postgres 16 on `db.r8g.large` | ~$165 | $0 | ~$165 |

The upgrade alone cuts the bill almost in half. Right-sizing gets most of the rest. For the new size, Graviton classes cost about 10% less than Intel ones with the same vCPUs and memory, and stock Postgres doesn't care about the CPU architecture. I picked the newest generation, `db.r8g.large` (2 vCPUs, 16GB). Postgres 16 stays in standard support until February 2029, so this also buys a few quiet years.

## Free memory said nothing useful

CloudWatch showed about 23GB of the 32GB free, all the time. That looks like an easy case for a 16GB instance. It wasn't. The four biggest tables added up to about 67GB, twice the instance's memory. Their cache hit ratios sat between 73 and 88%, so they were already reading from disk. `FreeableMemory` doesn't tell you whether the hot data fits. Per-table hit ratios from [`pg_statio_user_tables`](https://www.postgresql.org/docs/16/monitoring-stats.html#MONITORING-PG-STATIO-ALL-TABLES-VIEW) do:

```sql
SELECT relname,
       round(100.0 * heap_blks_hit / nullif(heap_blks_hit + heap_blks_read, 0), 1) AS hit_pct
FROM pg_statio_user_tables
ORDER BY heap_blks_read DESC
LIMIT 10;
```

Small hot tables sat near 100%. The big history tables were the ones missing the cache. So the order became: delete old data, measure again, then downsize. Downsizing first risked slow queries right after cutover, not only a slower migration.

CPU was the easy part. Over 90 days it averaged about 2%, and the busiest daily peaks reached about 20%. EBS throughput was fine too. The smaller instance's baseline is about 80MB/s, and 90% of days stayed under about 70MB/s.

## Deleting 280 million rows

The database held almost a decade of build history. Nobody needed more than one year of it, which I confirmed by asking every team that might read it. Recent years are also much smaller than the peak, so keeping a full year costs little.

### Keep a copy that doesn't follow the deletes

Before deleting anything, I copied the old rows into a small separate archive instance, a `db.t4g.micro`. My first idea for a safety net was a read replica. That's wrong. A replica streams every change from the primary, deletes included, so the rows vanish there a moment later. You want a one-time copy that doesn't replicate. The agent pointed this out before I built the replica.

### How the delete works

Only two tables had real timestamps: the builds table and the events table. The rest had none. Their cutoffs come from foreign keys to a dated table, or from their own auto-increment ID used as a time proxy. For example, the script finds the largest build ID older than the cutoff, then deletes child rows linked to builds at or below that ID. One wrinkle: a CI rebuild reuses the original build row and resets its timestamp, so the script also excludes a list of rebuilt IDs.

The script runs `psql` inside a disposable Kubernetes debug pod through `kubectl exec`. It walks the tables in foreign-key-safe order, children before parents, copies any rows the archive doesn't have yet, deletes in batches, and runs `ANALYZE` at the end. It computes the cutoff once at the start instead of calling `now()` in every query, so the bounds don't drift during a long run. It also refuses a cutoff that would match more than half of the builds table unless you pass an override flag.

### Chunk by year, dry run every chunk

A first test removed only the oldest year: about 11 million rows in about an hour and a half. The rest was about 270 million rows. At that pace one continuous run would take 24 to 40 hours, and nobody watches a production job for 40 hours. So I moved a fixed-date cutoff forward one year at a time, with the rolling one-year cutoff last. Each real run took its own snapshot first, so every chunk had a rollback point. Load stayed light, with CPU peaking in the low 20s percent.

| Chunk | Rows deleted | What happened |
| --- | --- | --- |
| Oldest year (test) | ~11M | Clean |
| 2019 | ~33M | Clean, after the bad row below was fixed |
| 2020 | ~67M | Clean, about 10 hours overnight |
| 2021 | ~48M | Debug pod expired mid-run, then a resume bug |
| 2022 | ~46M | Clean |
| 2023 | ~28M | Credentials expired, then a stale debug pod |
| 2024 | ~23M | Clean |
| Rolling one year | ~25M | Credentials expired again |

The whole delete took four days. Every chunk got a dry run (`DRY_RUN=1`) first, even after five clean ones, because a new cutoff can surface new data.

Midway I considered a bigger batch size. Each batch paid about two seconds of `kubectl exec` overhead twice, so a bigger batch might have saved a quarter to a third of the time. I left it alone. An untried batch size, live on production, mid-run, wasn't worth a few hours.

### The row that almost deleted everything

The dry run for the full one-year cutoff crashed with this:

```text
exec /usr/bin/env: argument list too long
```

The cause was one row in the builds table, inserted by hand years ago. It had a 2019 timestamp but sat among IDs from 2026. The script derived its build cutoff with `MAX(id) WHERE created_at < cutoff`. For any cutoff after early 2019, that query latched onto this row and returned an ID close to the top of the table. Every ID-proxy cutoff derived from it grew to match. The one-year delete would have removed nearly everything.

The dry run didn't flag the bad number. It crashed by luck. The poisoned cutoff made the rebuild exclusion list about 100,000 IDs long, the script passed that list as a command argument, and the kernel refused it. The crash is the only reason I looked.

I checked that nothing depended on the row except a couple dozen parameter rows, then deleted it. The next dry run gave a sane cutoff, and the exclusion list shrank to one ID. `MAX(id) WHERE ts < X` assumes IDs and timestamps move together, and one row is enough to break that. Before any large cutoff, look for rows whose timestamp is far from both ID neighbors:

```sql
SELECT id, created_at, prev_ts, next_ts
FROM (
  SELECT id, created_at,
         lag(created_at)  OVER (ORDER BY id) AS prev_ts,
         lead(created_at) OVER (ORDER BY id) AS next_ts
  FROM builds
) t
WHERE abs(extract(epoch FROM created_at - prev_ts)) > 60 * 86400
  AND abs(extract(epoch FROM created_at - next_ts)) > 60 * 86400;
```

### Long runs fail for boring reasons

The script resumes by re-querying what still matches the cutoff instead of storing an offset. That design mattered, because runs died four times.

- **The debug pod expired.** Its command was `sleep 86400`. I reused one pod across chunks, the 24 hours ran out mid-run, and `kubectl exec` started failing with `cannot exec into a container in a completed pod`. I raised the sleep to seven days.
- **The fix didn't apply to the pod I had.** A day later the same error came back, with the seven-day sleep already merged. The live pod had been created a few hours before the merge and still ran the old command. The script's reuse check asked "is a pod Running?", not "does this pod match what I would create today?". Deleting the pod fixed it. If your script reuses long-lived resources, compare their spec, not only their status.
- **My cloud credentials expired, twice.** `kubectl` lost access to the cluster, and the script ran out of retries. I logged in again and resumed.
- **The exit code lied.** I piped the script through `tee` from a shell without `pipefail`, so a run that failed reported exit code 0. Read the log, not the exit code.

### Resumable means computed from data the job doesn't touch

The first resume after the pod fix hit a second bug, and this one was structural. Some cutoffs were derived from the tables being deleted. The first table in the order had already lost every row under the cutoff. So the query that derived the second table's cutoff from it returned nothing, and the script built SQL with an empty value: `WHERE id <= ;`. The second table still had about three million rows waiting.

The fix was to derive every cutoff from the archive copy, which the delete never changes. On a fresh run the archive-derived cutoffs matched the original ones exactly. On a resumed run they stay right. "Re-query, don't store an offset" only works if every bound comes from data the job doesn't mutate.

### Two smaller cleanups, two more lessons

After the main delete I trimmed a table of pull request records that had no timestamp and no foreign keys. About 250,000 of its 265,000 rows went. It took two mistakes.

First, while I sized the cleanup, I ran a correlated subquery against the archive's events table, about 100 million rows with no index on the column I filtered by. It ran one lookup per repository. The client timed out, but the query kept running on the server. Four and a half minutes later it was still using resources, and I killed it with `pg_terminate_backend`. A single `GROUP BY` pass over the table was fast. A client timeout doesn't stop the server, so set `statement_timeout` on exploratory sessions.

Second, the delete script fetched a frozen list of rows with `psql -tA` and fed it to `COPY ... FROM STDIN`. `psql -tA` separates columns with `|`. `COPY` expects tabs by default. `COPY` failed, zero rows were staged, and the `DELETE` that joined against them matched nothing. Adding `-F $'\t'` to the fetch fixed it. Good news is it failed safe.

### DELETE doesn't give storage back

After the first deletes, `FreeStorageSpace` sat at about 180GB free of 250GB, the same as before. Plain `DELETE` leaves dead tuples until vacuum reclaims them, and vacuum gives the space back to Postgres, not to the volume. My next idea was to shrink allocated storage to about 100GB. That doesn't work either: you [can't deallocate storage](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_PIOPS.ModifyingExisting.html) on an existing RDS instance.

Blue/Green solves this, because the new instance is a separate volume. The `--target-allocated-storage` option of [`create-blue-green-deployment`](https://docs.aws.amazon.com/cli/latest/reference/rds/create-blue-green-deployment.html) can decrease storage for the green instance. The [creation docs](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/blue-green-deployments-creating.html) set one rule: the target must be at least 20% above current storage usage. So measure real usage after the deletes, not `FreeStorageSpace` from before them. I went from 250GB allocated to 150GB, with 59GB in use.

The indexes on the trimmed tables were 40 to 50 times bloated. [`REINDEX INDEX CONCURRENTLY`](https://www.postgresql.org/docs/16/sql-reindex.html) on 13 of them got back about 7.5GB in about four minutes without blocking writes. I skipped the two indexes on the biggest table. They were only about 1.5 times bloated and the slowest to rebuild. The reindex also mattered for the measurement that came next.

### Measure again

After the deletes and the reindex, cache hit ratios on the big tables went from 73 to 88% up to 90 to 96%. That was still on the 32GB instance, so it wasn't proof on its own. A week of CloudWatch showed the working set holding around 9GB, with 25 to 30 connections on average. So 16GB was safe.

CPU was the one real tradeoff. The deletes and reindexing peaked around 45% of 4 vCPUs, and the same work on 2 vCPUs would come close to saturating them. I accepted that. Heavy maintenance goes into quiet weekend windows, which is how I ran the archival work anyway. Paying for `db.r8g.xlarge` all month, for headroom I only need during scheduled windows, made no sense. After the switch, CPU averaged about 3%.

## Rehearse on something real

A local Postgres 16 container had already run our full migration chain up and back down. That checks the schema, not the upgrade. For the upgrade I ran the full [Blue/Green deployment](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/blue-green-deployments-overview.html) on the archive instance. It was also on Postgres 12 and paying Extended Support, so the rehearsal was a real upgrade with its own savings, not a throwaway. It found two blockers that applied to production too.

**RDS-managed master passwords block Blue/Green.** If the source uses `ManageMasterUserPassword`, `create-blue-green-deployment` fails right away with `SourceDatabaseNotSupportedFault`. The [Blue/Green limitations page](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/blue-green-deployments-considerations.html) lists this. The source needs a self-managed master password, set with `modify-db-instance --no-manage-master-user-password`. It's a boolean flag. `--manage-master-user-password false` is a syntax error.

**[`pg_repack`](https://reorg.github.io/pg_repack/) fails the Postgres 16 precheck.** Someone installed it years ago, and nothing used it. I searched the code, cron jobs, and CI jobs to be sure. The deployment status only said that the precheck failed and pointed at the logs. The reason was in a log file named `error/pg_upgrade_precheck.log`:

```bash
aws rds describe-db-log-files --db-instance-identifier <instance> \
  --filename-contains precheck
aws rds download-db-log-file-portion --db-instance-identifier <instance> \
  --log-file-name <name-from-above> --output text
```

I dropped the extension on the source, and the green side stayed broken. For a major version upgrade, Blue/Green keeps green in sync with [logical replication](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/blue-green-deployments-replication-type.html), which carries data changes, not DDL. The green side is read-only, so you can't drop the extension there either. AWS documents the general rule: DDL on the blue side means you delete the deployment and create it again. So I ran `delete-blue-green-deployment --delete-target`, which leaves the source alone, and started over. Each failed attempt costs a full provisioning cycle, about 12 minutes even on a nearly idle micro instance. Drop unused extensions before the first create call. On production I first checked the extension's schema for leftover tables from an interrupted run, found only its own bookkeeping tables, and dropped it.

The second attempt was ready in about 20 minutes. Row counts matched on both sides, about 85 million rows in the biggest table. I also pointed the app's own database code at the upgraded archive for a read and write smoke test, plus the one Postgres-only query our SQLite-based test suite couldn't run. Then the archive switched over in 33 seconds.

## Production had five more

**A static parameter that was never applied.** Blue/Green with logical replication needs `rds.logical_replication=1`, and the [creation docs](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/blue-green-deployments-creating.html) say the instance must be in sync with its parameter group. I had set it about ten days earlier, deferred the reboot to a quiet window, and then forgot. The create call failed with the same `SourceDatabaseNotSupportedFault` as before, so one error covers several causes. Check for this before you start:

```bash
aws rds describe-db-instances --db-instance-identifier <prod-instance> \
  --query 'DBInstances[].DBParameterGroups[].ParameterApplyStatus'
```

`pending-reboot` means the instance still runs the old value. The reboot of a single-AZ instance took seconds, and the app reconnected on its own.

**A table without a primary key.** Logical replication needs a [replica identity](https://www.postgresql.org/docs/16/sql-altertable.html) to carry `UPDATE` and `DELETE`, and the default is the primary key. One table had only a unique constraint, left over from an old migration bug. Find these tables early:

```sql
SELECT n.nspname, c.relname
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r'
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND NOT EXISTS (
    SELECT 1 FROM pg_constraint p
    WHERE p.conrelid = c.oid AND p.contype = 'p'
  );
```

The quick fix is `ALTER TABLE ... REPLICA IDENTITY USING INDEX` on the unique index. I wanted a real primary key, since the missing one was a bug. That wasn't one statement. `ADD PRIMARY KEY USING INDEX` couldn't reuse the index, because a unique constraint already owned it and three foreign keys depended on it. So the migration drops the three foreign keys, swaps the unique constraint for a primary key, and recreates the foreign keys.

**Two migrations, one transaction, six hot tables.** That migration shipped next to a second one that dropped two unused indexes. Alembic runs all pending migrations in one transaction unless you set `transaction_per_migration=True`, and Postgres holds DDL locks until commit. So the first migration's `ACCESS EXCLUSIVE` locks on four tables would stay held while the second migration's `DROP INDEX` locked two more. Six of the busiest tables would be locked at once. A review bot caught this. The fix moves the index drops into Alembic's [`autocommit_block()`](https://alembic.sqlalchemy.org/en/latest/api/runtime.html#alembic.runtime.migration.MigrationContext.autocommit_block) with `CONCURRENTLY`. The forced commit releases the first migration's locks, and `CONCURRENTLY` avoids the exclusive lock on the index tables:

```python
def upgrade():
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_example_one")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_example_two")
```

The `IF EXISTS` came from a second finding. Each statement now commits on its own, so a failure halfway would make a retry fail on the index that's already gone. The bot suggested `op.drop_index(..., if_exists=True)`. That passed lint and failed at run time with `NotImplementedError`, because Alembic's `if_exists` needs SQLAlchemy 1.4 and we're pinned to 1.3. Raw SQL sidesteps it. Only a real migration run against Postgres catches this kind of thing.

**Schema drift at deploy time.** On staging, the schema was already at the target state while Alembic's version stamp was two revisions behind. An integration test run of the unmerged branch had applied both migrations to the shared staging database, and I had later moved the stamp back by hand to unblock an unrelated deploy. We confirmed every constraint and index matched the target, then stamped staging to head. For production, the agent assumed the schema was untouched and didn't check. Production already had the primary key but not the index drops, so a pod crash-looped on `DROP CONSTRAINT` for a constraint that was already gone. Stamping production to the first migration's revision, not head, fixed it, and the second migration then ran for real. Production deploys now run `alembic upgrade head` against the real database before rolling pods, as staging already did.

**No major version and new instance family in one step.** I asked for Postgres 16 on `db.r8g.large` in one deployment. RDS refused:

```text
RDS does not support creating a DB instance with the following combination: DBInstanceClass=db.r8g.large, Engine=postgres, EngineVersion=12.22
```

Blue/Green builds an intermediate instance on the source version with the target class, and Postgres 12 stops at the r6g family. [`describe-orderable-db-instance-options`](https://docs.aws.amazon.com/cli/latest/reference/rds/describe-orderable-db-instance-options.html) tells you this before you try. An empty list means the combination doesn't exist:

```bash
aws rds describe-orderable-db-instance-options --engine postgres \
  --engine-version 12.22 --db-instance-class db.r8g.large \
  --query 'OrderableDBInstanceOptions[].DBInstanceClass'
```

So I upgraded on the old class, then resized the green instance to r8g before switchover. Green wasn't serving traffic, so the resize cost production nothing. Production saw one interruption, straight onto the final configuration.

## The upgrade, in order

This is the sequence that worked, with placeholders:

```bash
# 1. A Postgres 16 parameter group with the same custom settings as the old one.
aws rds create-db-parameter-group --db-parameter-group-name <pg16-params> \
  --db-parameter-group-family postgres16 --description "Postgres 16"
aws rds modify-db-parameter-group --db-parameter-group-name <pg16-params> \
  --parameters "ParameterName=rds.logical_replication,ParameterValue=1,ApplyMethod=pending-reboot"

# 2. Engine upgrade only, smaller storage, same instance class.
aws rds create-blue-green-deployment --blue-green-deployment-name <name> \
  --source <source-instance-arn> \
  --target-engine-version 16.15 \
  --target-db-parameter-group-name <pg16-params> \
  --target-storage-type gp3 --target-allocated-storage 150

# 3. Wait for AVAILABLE, then resize green while it serves nothing.
aws rds describe-blue-green-deployments --blue-green-deployment-identifier <deployment-id>
aws rds modify-db-instance --db-instance-identifier <green-instance> \
  --db-instance-class db.r8g.large --apply-immediately

# 4. Switch over in a quiet window.
aws rds switchover-blue-green-deployment --blue-green-deployment-identifier <deployment-id>
```

Copy the old parameter group's other custom settings, like connection logging, into the new one too. Also, `--target-iops` and `--target-storage-throughput` can't be set below 400GiB of gp3 storage. At 150GB, gp3 gives its baseline of 3,000 IOPS and 125MB/s, which matched what the old instance had.

## Switchover: 45 seconds, then two errors five minutes later

Switchover took about 45 seconds. The app logged two failed requests in that window, as expected. Five minutes later it logged two more, on one of its three pods:

```text
psycopg2.errors.ReadOnlySqlTransaction: cannot execute INSERT in a read-only transaction
```

During [switchover](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/blue-green-deployments-switching.html), RDS drops connections on both sides, renames the instances, and moves the endpoint name to the new one. The old instance stays up, read-only. DNS only matters for new connections. The errors came from a pooled connection that was attached to the old instance. I think the pool reconnected while DNS still pointed at the old address. The switchover docs warn that clients caching DNS for longer than five seconds keep sending writes to the old side.

The pool had [`pool_pre_ping`](https://docs.sqlalchemy.org/en/20/core/pooling.html#disconnect-handling-pessimistic) and a 30-minute [`pool_recycle`](https://docs.sqlalchemy.org/en/20/core/pooling.html#setting-pool-recycle). Pre-ping checks that a connection is alive, not that it can write, and the old instance was alive. So it passed. SQLAlchemy dropped each bad connection after its failed write, and the errors stopped on their own. Next time I'll check DNS caching in the client path first, and do a rolling restart of the app right after switchover.

## Cleaning up

After switchover, RDS keeps the old instance, renamed and read-only, and still billing. I waited three days. `DatabaseConnections` on the old instance stayed at zero, daily backups on the new one ran clean, and nothing in our code or config referenced the old hostname. Point-in-time recovery on the new instance only reaches back to when green was created, so keep the old one around for as long as your recovery window needs.

Then I took a final snapshot and deleted the old instance. Deletion protection has to go first, with `modify-db-instance --no-deletion-protection`. The Blue/Green deployment object also stays behind after switchover, and AWS doesn't remove it. Delete it with `delete-blue-green-deployment`, without `--delete-target`. It's only metadata at that point.

## Working with the agent

The agent was most useful when it checked things instead of trusting summaries. Twice early on, `pg_stat_user_tables` made a table look broken. A stats reset a couple of weeks earlier had left `n_live_tup` stale, and both times a real `count(*)` cleared it up. It also caught two of my bad ideas before I acted on them: the read replica as a safety net, and shrinking storage in place.

It kept a notes file across about a dozen sessions over two weeks: every run, every row count, every fix and why. For a delete spread over four days of overnight runs, that file was the runbook.

It went wrong when it reasoned instead of checking. It verified staging's schema carefully, then assumed production was clean. The fix went into the pipeline, not the prompt, because a pre-deploy check doesn't depend on anyone remembering to look.

Review bots need the same treatment. The bot found a real locking problem that I had missed, and then suggested a fix that would have shipped a broken migration. Run the suggestion before you trust it.

I ran the steps that could hurt production myself: the reboot, deleting the bad row, killing the runaway query, and fixing the version stamp on staging. Claude Code's auto mode blocked the agent from those anyway, which was the right call.

## If I did it again

1. Check the Extended Support dates for your version on the release calendar, and pass `--engine-lifecycle-support` explicitly on anything you create.
2. Size the instance from per-table cache hit ratios, not free memory.
3. Archive to a copy that doesn't replicate. Delete in chunks, dry run each one, and derive every bound from the archive.
4. Scan for rows whose timestamps don't match their ID neighbors before trusting `MAX(id)` cutoffs.
5. Rehearse the whole Blue/Green on a real, smaller instance.
6. Before the first create call: drop unused extensions, look for `pending-reboot` parameters, find tables without a primary key, check which instance classes the source version supports, and switch off RDS-managed master passwords.
7. Run the migrations against the real database before deploying them, and check whether pending migrations share one transaction.
8. Resize green before switchover, and run `ANALYZE` on it. A major version upgrade doesn't carry planner statistics over, and AWS recommends it before switchover.
9. Restart the app right after switchover.
10. Delete the old instance and the leftover Blue/Green object once the new one has run clean for a few days.

The result is almost $500 a month saved, closer to $800 once the year 3 rate would have kicked in, for 45 seconds of downtime.
