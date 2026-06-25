# MySQL 优化与事务场景说明（阶段 23E）

围绕本项目的简历投递数据库问答（`job_applications` / `application_events`），说明索引设计、EXPLAIN、慢查询定位、大表优化和必须使用事务的业务场景。面试高频题“慢查询怎么排查、大表怎么优化、什么业务必须用事务、最左匹配”都可对照本文回答。

## 1. 表结构与索引设计

`job_applications`（投递记录）核心字段：`company`、`role`、`channel`、`applied_at`、`status`、`city`、`salary_min/max`。

数据库问答（`app/tools/query_database.py`）的高频查询模式：

- `WHERE status IN ('interview','offer') ... ORDER BY applied_at DESC, id DESC`（按状态筛选 + 按时间排序）
- `GROUP BY channel ORDER BY application_count DESC`（渠道投递统计）
- `WHERE applied_at >= 本月初 ...`（时间范围）
- 几乎所有查询都 `ORDER BY applied_at DESC, id DESC`

对应索引（`docker/mysql/init/01_job_applications.sql`）：

| 索引 | 字段 | 服务的查询 |
|---|---|---|
| idx_status | status | 状态筛选 |
| idx_applied_at | applied_at | 时间范围 / 排序 |
| idx_company | company | 按公司查询 |
| idx_channel | channel | 渠道分组统计 |
| idx_status_applied_at | (status, applied_at) | 状态筛选 + 时间排序的复合查询，减少额外 filesort |

`application_events` 建了 `application_id`（外键 join）、`event_type`、`event_at` 索引。

> 现有库加索引（init SQL 用 `CREATE TABLE IF NOT EXISTS`，对已存在的表不会自动改）：
>
> ```sql
> ALTER TABLE job_applications ADD INDEX idx_job_applications_channel (channel);
> ALTER TABLE job_applications ADD INDEX idx_job_applications_status_applied_at (status, applied_at);
> ```

## 2. 最左匹配原则

复合索引 `(status, applied_at)` 遵循最左匹配：

- `WHERE status = ?`：用到索引（最左列）。
- `WHERE status = ? AND applied_at >= ?`：两列都用到，applied_at 还可用于范围 + 排序。
- `WHERE applied_at >= ?`（不带 status）：用不到复合索引的最左列，会走单列 idx_applied_at。

所以单列 idx_applied_at 和复合 idx_status_applied_at 并存：前者服务“只按时间”，后者服务“状态 + 时间”。

## 3. 用 EXPLAIN 看执行计划

```sql
EXPLAIN SELECT company, role, status, applied_at
FROM job_applications
WHERE status IN ('interview','offer')
ORDER BY applied_at DESC, id DESC;
```

关注列：

- `type`：`ALL`=全表扫描（差），`ref`/`range`=用到索引（好）。
- `key`：实际使用的索引；为 `NULL` 说明没走索引。
- `rows`：预估扫描行数，越小越好。
- `Extra`：`Using filesort` / `Using temporary` 说明排序 / 分组没被索引覆盖，可考虑复合索引或覆盖索引。

注意：demo 数据量很小时，优化器可能直接全表扫描（因为比走索引更快），这是正常的；索引价值在数据量增大后体现。

## 4. 慢查询定位

```sql
SET GLOBAL slow_query_log = ON;
SET GLOBAL long_query_time = 1;        -- 超过 1s 记入慢查询日志
SHOW VARIABLES LIKE 'slow_query_log_file';
```

流程：开启慢查询日志 -> 用 `mysqldumpslow` / `pt-query-digest` 聚合 -> 对 Top 慢 SQL 跑 `EXPLAIN` -> 加合适索引 / 改写 SQL / 减少回表。

## 5. 大表优化

- **覆盖索引**：让索引包含查询所需列，避免回表。
- **分页**：避免 `LIMIT 100000, 20` 深分页（要扫前 10 万行）；改用游标分页 `WHERE id < ? ORDER BY id DESC LIMIT 20`。
- **归档**：历史投递按时间归档到历史表，热表只留近期数据。
- **避免 SELECT \***：只查需要的列，减少 IO。
- **分库分表**：数据量到千万级再考虑，按用户 / 时间水平拆分（本项目是个人单用户 demo，不需要）。

本项目数据库问答工具已强制 `LIMIT`（`MYSQL_DEFAULT_LIMIT` / `MYSQL_MAX_LIMIT`），从源头限制返回行数。

## 6. 必须使用事务的业务场景

结合后续“求职投递辅助 Agent”（阶段 21）：用户确认投递后，需要在一个事务里完成多步写入，保证原子性：

```sql
START TRANSACTION;
-- 1) 创建投递记录
INSERT INTO job_applications (company, role, channel, applied_at, status)
VALUES ('示例公司', '后端实习生', '官网', CURRENT_DATE, 'draft');
-- 2) 写入投递事件（关联上面的记录）
INSERT INTO application_events (application_id, event_type, event_at)
VALUES (LAST_INSERT_ID(), 'applied', NOW());
-- 3) 更新投递状态
UPDATE job_applications SET status = 'submitted_by_user' WHERE id = LAST_INSERT_ID();
COMMIT;
```

如果第 2、3 步失败必须整体回滚，避免“有投递记录却没有对应事件 / 状态不一致”的脏数据。这是必须用事务（ACID 的原子性 + 一致性）的典型业务场景。

> 当前 demo 的数据库问答是**只读** SELECT（`agent_reader` 只读账号 + SQL 安全校验 + 强制 LIMIT），不涉及写事务；上面的事务设计属于投递辅助 Agent 落地时的写路径，会用独立读写账号并包在事务里。

## 7. MySQL 5.6 vs 8.0（面试常问）

- 8.0 默认字符集 `utf8mb4`（本项目用 `utf8mb4_0900_ai_ci`），更好支持 emoji 和多语言。
- 8.0 支持窗口函数、CTE（`WITH`）、降序索引、不可见索引、原子 DDL。
- 8.0 默认认证插件改为 `caching_sha2_password`。
- 8.0 移除了查询缓存（Query Cache）。

## 8. 不能夸大的边界

- 当前是个人单用户 demo，数据量很小（样例 5 条），没有真实百万级大表慢查询调优案例；以上是基于查询模式的索引设计和通用优化方法论。
- 数据库问答目前是确定性 SQL 模板 + 只读账号，不是 LLM 自由生成 SQL，也没有分库分表、读写分离的生产实战。
