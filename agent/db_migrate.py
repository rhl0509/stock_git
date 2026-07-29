"""
agent/db_migrate.py
===================
agent 모듈 전체 테이블 생성. 앱 기동 시 또는 수동으로 실행.

  python -m agent.db_migrate
"""
from database.db_connection import get_db_connection
import logging

logger = logging.getLogger(__name__)


def run():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS market_reports (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    report_type ENUM('daily','weekly','monthly') NOT NULL,
                    report_date DATE                             NOT NULL,
                    title       VARCHAR(255)                     NOT NULL,
                    content     LONGTEXT                         NOT NULL,
                    summary     TEXT,
                    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_type_date (report_type, report_date)
                ) CHARACTER SET utf8mb4
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS recommend_track (
                    id             INT AUTO_INCREMENT PRIMARY KEY,
                    code           VARCHAR(10)                          NOT NULL,
                    name           VARCHAR(100),
                    recommend_type ENUM('daily','short','swing')        NOT NULL,
                    recommend_date DATE                                  NOT NULL,
                    confidence     FLOAT,
                    entry_price    FLOAT,
                    target_days    INT,
                    exit_price     FLOAT,
                    return_pct     FLOAT,
                    evaluated_at   DATETIME,
                    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_code_type_date (code, recommend_type, recommend_date)
                ) CHARACTER SET utf8mb4
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS event_calendar (
                    id           INT AUTO_INCREMENT PRIMARY KEY,
                    event_date   DATE         NOT NULL,
                    event_type   VARCHAR(50)  NOT NULL,
                    title        VARCHAR(255) NOT NULL,
                    description  TEXT,
                    importance   ENUM('high','medium','low') DEFAULT 'medium',
                    country      CHAR(5)      DEFAULT 'US',
                    notified     TINYINT(1)   DEFAULT 0,
                    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_date_type (event_date, event_type)
                ) CHARACTER SET utf8mb4
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS dart_summaries (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    rcept_no   VARCHAR(20)  NOT NULL UNIQUE,
                    corp_name  VARCHAR(100),
                    report_nm  VARCHAR(255),
                    `signal`   VARCHAR(30),
                    summary    VARCHAR(255),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                ) CHARACTER SET utf8mb4
            """)

        conn.commit()
        logger.info("[migrate] 테이블 준비 완료 (market_reports, recommend_track, event_calendar, dart_summaries)")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
