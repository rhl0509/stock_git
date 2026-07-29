-- migration_gagebu_outbox.sql
-- 가계부(gagebu) 자동기록용 아웃박스. stock_git DB 대상. 재실행 안전(IF NOT EXISTS).
--
-- ── 왜 아웃박스인가 ─────────────────────────────────────────────────
-- 기존에는 매수/매도가 자기 DB의 transactions 테이블에 가계부 거래를 직접 INSERT 했고
-- (routes/stock_holdings.py 매수:387 매도:459) 매매 기록과 한 커밋으로 묶여 있었다.
-- 2026-07-17 가계부가 별도 DB(gagebu)로 분리되면서 그 테이블은 아무도 읽지 않는
-- 고아가 됐다(실측: gagebu 에 주식발 거래 0건, stock_stack 에 고아 배당 12건).
--
-- 이제 가계부는 HTTP 로 기록해야 하는데, 그 호출을 매매 트랜잭션 안에서 하면 안 된다:
--   ① 가계부가 죽었다고 매수를 실패시킬 수 없다(매매가 본 기능, 기록은 부수효과).
--   ② HTTP 는 롤백되지 않는다 — 커밋 전에 보냈는데 커밋이 실패하면 유령 거래가 남는다.
--   ③ 요청 스레드에서 외부 I/O 를 하면 응답이 상대 서비스 지연에 묶인다.
-- 아웃박스는 매매와 **같은 커밋**으로 의도를 기록하고(원자성 유지), 전송은 디스패처가
-- 분리해 재시도한다. 가계부가 죽어도 매매는 성공하고, 살아나면 밀린 게 나간다.
--
-- ── 왜 status 에 skipped 가 있나 ────────────────────────────────────
-- 가계부 토큰은 .env 에 하나뿐이고 rho 의 장부에 매핑된다. 다른 회원의 매매를 그
-- 토큰으로 보내면 rho 장부에 남의 거래가 들어간다. 그래서 소유자(OWNER_USER_NO)가
-- 아니면 애초에 pending 으로 넣지 않고 skipped 로 기록한다 — 행을 안 만들면
-- "왜 연동이 안 됐는지" 를 알 방법이 없어진다(이 프로젝트가 반복해 온 무증상 실패).

CREATE TABLE IF NOT EXISTS gagebu_outbox (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    -- 발신측이 만든다(의미를 아는 쪽이므로). 가계부의 stock_ingest_ledger 가
    -- UNIQUE(account_book_id, idempotency_key) 로 중복을 구조적으로 막는다.
    --   배당: SHA2('dividend|{user_no}|{code}|{ex_div_date}', 256)
    --   매매: SHA2('trade|{user_no}|{stock_transactions.id}', 256)
    --   (user_no 포함 — 아웃박스는 UNIQUE(idempotency_key) 전역이라 회원별 충돌 방지.
    --    gagebu_outbox.py make_key / auto_jobs.py / stock_holdings.py 와 일치.)
    idempotency_key CHAR(64) NOT NULL,
    source          VARCHAR(20) NOT NULL,          -- 'dividend' | 'trade'
    member_id       INT NOT NULL,
    payload         JSON NOT NULL,                 -- type/amount/title/date/category_hint
    status          VARCHAR(10) NOT NULL DEFAULT 'pending',  -- pending|sent|skipped|failed
    attempts        INT NOT NULL DEFAULT 0,
    last_error      TEXT NULL,
    remote_txn_id   BIGINT NULL,                   -- 가계부가 돌려준 transaction_id
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at         DATETIME NULL,
    UNIQUE KEY uq_outbox_idem (idempotency_key),
    KEY idx_outbox_status (status, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='가계부 자동기록 아웃박스(매매·배당과 같은 커밋으로 적재, 디스패처가 전송)';

-- 롤백:
--   DROP TABLE IF EXISTS gagebu_outbox;
--   (코드도 함께 롤백해야 한다 — stock_holdings.py 의 매수/매도가 이 테이블에 쓴다.)
