-- ============================================================================
-- dividend_schema.sql — 배당·현금흐름 캘린더 스키마
-- 대상 DB: stock_git (주식 프로그램 전용, MySQL 8.0+)
--          2026-07-17 이전에는 가계부와 expense_tracker DB를 공유했으나,
--          가계부가 gagebu DB로 분리되면서 주식 테이블만 stock_stack 으로 이관했고,
--          2026-07-29 stock_tracker(8020)와 갈라서며 stock_git 으로 다시 분리했다.
--
-- 설계문서(배당캘린더_설계문서.md) 4장 기준.
-- 단, 보유종목은 신규 holdings 테이블을 만들지 않고 기존 stock_holdings 를
-- 재사용한다(중복 회피). 따라서 본 스키마는 다음 2요소만 정의한다.
--   1) dividends            — 배당 일정 (예상/확정)
--   2) v_dividend_calendar  — stock_holdings 와 조인한 캘린더 조회용 뷰
--
-- 멱등(idempotent): 재실행해도 안전하다.
-- 실행:  mysql -u <user> -p stock_git < dividend_schema.sql
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1) dividends — 배당 일정
--    (symbol, pay_date, dividend_per_share) 단위로 관리 → 분기/반기 배당 대응.
--    종목 단위 스케줄이므로 보유수량(member별)은 담지 않고, 뷰에서 조인 계산한다.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dividends (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    symbol             VARCHAR(20)  NOT NULL COMMENT '종목코드 (KR: 6자리, US: 티커)',
    market             ENUM('KR','US') NOT NULL DEFAULT 'KR' COMMENT '시장 구분',
    stock_name         VARCHAR(100)          COMMENT '종목명',
    record_date        DATE                  COMMENT '배당 기준일',
    pay_date           DATE                  COMMENT '지급(예정)일 — 캘린더 표시 기준',
    dividend_per_share DECIMAL(18,4) NOT NULL DEFAULT 0 COMMENT '주당 배당금',
    currency           ENUM('KRW','USD') NOT NULL DEFAULT 'KRW' COMMENT '통화',
    status             ENUM('estimated','confirmed') NOT NULL DEFAULT 'estimated'
                       COMMENT 'estimated=추정(작년 실적 기반), confirmed=확정(KIS 예탁원정보)',
    source             ENUM('kis','yfinance','manual') NOT NULL DEFAULT 'manual'
                       COMMENT '데이터 출처',
    created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                       ON UPDATE CURRENT_TIMESTAMP,
    -- 동일 종목·지급일·주당배당금 조합은 1건만 (upsert 키)
    UNIQUE KEY uniq_div (symbol, pay_date, dividend_per_share),
    KEY idx_pay_date (pay_date),
    KEY idx_symbol   (symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='배당 일정(예상/확정)';
-- 콜레이션은 기존 stock_holdings(utf8mb4_general_ci)에 맞춘다 → 뷰 조인 충돌 방지.

-- ----------------------------------------------------------------------------
-- 2) v_dividend_calendar — 캘린더 조회용 뷰
--    기존 stock_holdings(member_id, code, name, quantity, avg_price) 와 조인.
--    expected_amount = dividend_per_share × quantity 자동 계산.
--    KR 보유종목 기준(코드 6자리 매칭). US 수동 보유분은 서비스 계층에서 계산.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_dividend_calendar AS
SELECT
    h.member_id                              AS member_id,
    d.symbol                                 AS symbol,
    COALESCE(d.stock_name, h.name)           AS stock_name,
    d.market                                 AS market,
    d.record_date                            AS record_date,
    d.pay_date                               AS pay_date,
    d.dividend_per_share                     AS dividend_per_share,
    h.quantity                               AS quantity,
    ROUND(d.dividend_per_share * h.quantity, 2) AS expected_amount,
    d.currency                               AS currency,
    d.status                                 AS status,
    d.source                                 AS source
FROM dividends d
JOIN stock_holdings h
  -- 기존 stock_holdings 와 콜레이션이 달라도 조인되도록 명시적 COLLATE.
  ON h.code = d.symbol COLLATE utf8mb4_general_ci
WHERE h.quantity > 0;
