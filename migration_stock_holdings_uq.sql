-- stock_holdings: (member_id, code) 유니크 제약 추가
--
-- 목적:
--   1) 한 회원이 같은 종목을 중복 보유행으로 갖지 못하게 한다.
--   2) 매수 핸들러(routes/stock_holdings.py buy_stock)의
--      INSERT ... ON DUPLICATE KEY UPDATE(원자적 upsert)를 성립시킨다.
--      → 동시 첫매수 중복 INSERT · 동시 매수 lost update를 DB 레벨에서 한 번에 방어.
--
-- ⚠️ 배포 DB에 반드시 적용해야 코드가 정상 동작한다(미적용 시 upsert의
--    ON DUPLICATE KEY가 발동하지 않아 중복 INSERT가 그대로 발생).
--
-- 적용 전 반드시 중복 검사(중복 있으면 ALTER 실패):
--   SELECT member_id, code, COUNT(*) FROM stock_holdings
--   GROUP BY member_id, code HAVING COUNT(*) > 1;
--   (중복이 있으면 병합/정리 후 ALTER)
--
-- MySQL 8.0.19+ 필요(매수 upsert가 VALUES(...) AS new 별칭 문법 사용).

ALTER TABLE stock_holdings
  ADD UNIQUE KEY uq_member_code (member_id, code);
