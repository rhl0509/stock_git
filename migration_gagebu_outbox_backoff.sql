-- migration_gagebu_outbox_backoff.sql
-- gagebu_outbox 에 재시도 백오프 컬럼 추가. stock_stack DB. 재실행 안전.
--
-- ── 왜 ──
-- 기존 재시도 정책은 attempts < 5 로 선별하고 실패마다 attempts+1 이라, 재시도 가능한
-- 실패(연결 거부·5xx)도 5회 = 약 25분이면 영구 failed 로 굳었다. 가계부 앱이 밤새
-- 꺼져 있으면 그 사이 매매·배당이 전부 유실됐고, failed 를 되돌릴 수단도 없었다.
--
-- next_retry_at 으로 시간 기반 백오프를 도입한다:
--   재시도 가능 실패 → next_retry_at 을 지수 백오프로 미루고 pending 유지(attempts 는
--     진단용으로만 증가, 한도로 폐기하지 않음).
--   재시도 불가(4xx)·payload 파손 → 즉시 failed (같은 요청은 결과가 같다).
-- 이렇게 하면 가계부가 오래 죽어 있어도 살아나면 따라잡는다.
--
-- ── 재실행 안전 ──
-- MySQL 8.0 은 ADD COLUMN IF NOT EXISTS 를 지원하지 않으므로(MariaDB 문법)
-- information_schema 로 존재를 확인하고 동적 SQL 로 추가한다.

-- next_retry_at 컬럼
SET @col := (SELECT COUNT(*) FROM information_schema.columns
             WHERE table_schema = DATABASE()
               AND table_name = 'gagebu_outbox'
               AND column_name = 'next_retry_at');
SET @sql := IF(@col = 0,
    'ALTER TABLE gagebu_outbox ADD COLUMN next_retry_at DATETIME NULL AFTER attempts',
    'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- (status, next_retry_at) 인덱스 — pending 을 재시도 시각 기준으로 집는다.
SET @idx := (SELECT COUNT(*) FROM information_schema.statistics
             WHERE table_schema = DATABASE()
               AND table_name = 'gagebu_outbox'
               AND index_name = 'idx_outbox_retry');
SET @sql := IF(@idx = 0,
    'ALTER TABLE gagebu_outbox ADD INDEX idx_outbox_retry (status, next_retry_at)',
    'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 롤백:
--   ALTER TABLE gagebu_outbox DROP INDEX idx_outbox_retry, DROP COLUMN next_retry_at;
--   (코드도 함께 롤백 — gagebu_outbox.py 가 next_retry_at 을 읽고 쓴다.)
