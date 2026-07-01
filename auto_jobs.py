"""auto_jobs.py — 서버 내장 스케줄러(APScheduler) 자동화 잡 모음.

app.py 시작 시 register(scheduler)로 등록된다. 기존 수동 작업의 자동화:
  - 키움 포트폴리오 동기화   평일 15:50 (장마감 후)
  - 배당 자동 기록            토요일 09:00
  - 테마 인덱스 빌드          일요일 17:00
  - 모델 백업                 일요일 01:30 (02:00 재학습 직전)
  - DB 백업 (mysqldump)       매일 21:00, 14일 보관 (Windows StockTracker_DbBackup와 이중화)

대상 사용자: OWNER_USER_NO 환경변수 → 없으면 보유종목/거래내역 있는 회원 자동 탐지.
"""
import gzip
import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent

_MYSQLDUMP_CANDIDATES = [
    r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe",
    r"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqldump.exe",
    r"C:\Program Files\MariaDB 10.11\bin\mysqldump.exe",
    "mysqldump",  # PATH
]


def get_owner_user_no() -> int | None:
    """자동화 대상 사용자. OWNER_USER_NO env 우선, 없으면 데이터 보유 회원 자동 탐지."""
    env = os.getenv('OWNER_USER_NO')
    if env and env.isdigit():
        return int(env)
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            for sql in (
                "SELECT member_id AS u FROM stock_holdings ORDER BY id LIMIT 1",
                "SELECT member_id AS u FROM stock_transactions ORDER BY id LIMIT 1",
                "SELECT MIN(id) AS u FROM members",
            ):
                cur.execute(sql)
                row = cur.fetchone()
                if row and row.get('u'):
                    return int(row['u'])
    finally:
        conn.close()
    return None


def _notify(msg: str) -> None:
    try:
        from notify.telegram import send_telegram
        send_telegram(msg)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────
# 1. 배당 자동 기록 (주 1회)
# ─────────────────────────────────────────────────────────────────
def job_dividend_autoimport():
    user_no = get_owner_user_no()
    if not user_no:
        return
    try:
        from datetime import timedelta
        from database.db_connection import get_db_connection
        from routes.dividend import _get_holdings_for, _fetch_div_history, _enrich_kr_dividend

        holdings, _src = _get_holdings_for(user_no)
        if not holdings:
            logger.info("[auto/dividend] 보유종목 없음 — 스킵")
            return

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT stock_code, ex_div_date FROM dividend_records "
                    "WHERE user_no=%s AND ex_div_date IS NOT NULL", (user_no,))
                existing = {(r['stock_code'], r['ex_div_date'].isoformat()) for r in cur.fetchall()}

                now, one_year = datetime.now(), datetime.now() - timedelta(days=365)
                inserted, total_won = 0, 0
                for h in holdings:
                    code, qty = h['code'], h['quantity']
                    for dt, amt in _fetch_div_history(code):
                        if dt < one_year or dt > now:
                            continue
                        ex_date = dt.strftime('%Y-%m-%d')
                        if (code, ex_date) in existing:
                            continue
                        enr = _enrich_kr_dividend(code, dt, amt, qty)   # KR은 KIS 확정 우선
                        cur.execute("""
                            INSERT INTO dividend_records
                                (user_no, stock_code, stock_name, ex_div_date, pay_date,
                                 dividend_per_share, quantity, total_amount, memo)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """, (user_no, code, h['name'], ex_date,
                              enr['pay_date'], enr['dps'], qty, enr['total'],
                              'KIS 확정 자동기록' if enr['confirmed'] else '키움 연동 자동기록'))
                        inserted += 1
                        total_won += enr['total']
            conn.commit()
        finally:
            conn.close()

        if inserted:
            logger.info(f"[auto/dividend] {inserted}건 자동 기록 (₩{total_won:,})")
            _notify(f"💰 배당 자동 기록 {inserted}건 (₩{total_won:,})\n배당 캘린더에서 확인하세요.")
        else:
            logger.info("[auto/dividend] 신규 배당 없음")
    except Exception as e:
        logger.error(f"[auto/dividend] 실패: {e}", exc_info=True)


# ─────────────────────────────────────────────────────────────────
# 2. 모델 백업 (재학습 직전, backup_model.bat 대체)
# ─────────────────────────────────────────────────────────────────
def job_model_backup():
    try:
        src = ROOT / "XGBoost_v2" / "model"
        if not src.is_dir():
            return
        dst_base = ROOT / "backup" / "model"
        dst_base.mkdir(parents=True, exist_ok=True)
        dst = dst_base / datetime.now().strftime('%Y-%m-%d')
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        # 최근 10개만 보관
        dirs = sorted([d for d in dst_base.iterdir() if d.is_dir()], key=lambda d: d.name)
        for old in dirs[:-10]:
            shutil.rmtree(old, ignore_errors=True)
        logger.info(f"[auto/model_backup] 완료 → {dst.name} (보관 {min(len(dirs),10)}개)")
    except Exception as e:
        logger.error(f"[auto/model_backup] 실패: {e}", exc_info=True)


# ─────────────────────────────────────────────────────────────────
# 5. DB 백업 (매일, mysqldump → gzip, 14일 보관)
# ─────────────────────────────────────────────────────────────────
def _find_mysqldump() -> str | None:
    for cand in _MYSQLDUMP_CANDIDATES:
        if cand == "mysqldump":
            if shutil.which(cand):
                return cand
        elif Path(cand).exists():
            return cand
    return None


def job_db_backup():
    exe = _find_mysqldump()
    if not exe:
        logger.error("[auto/db_backup] mysqldump 미발견 — 백업 불가")
        return
    try:
        from config import Config
        dst_dir = ROOT / "backup" / "db"
        dst_dir.mkdir(parents=True, exist_ok=True)
        out_gz = dst_dir / f"{Config.MYSQL_DB}_{datetime.now():%Y%m%d}.sql.gz"

        env = os.environ.copy()
        env['MYSQL_PWD'] = Config.MYSQL_PASSWORD  # 비밀번호를 인자/로그에 노출하지 않음
        proc = subprocess.run(
            [exe, f"--host={Config.MYSQL_HOST}", f"--user={Config.MYSQL_USER}",
             "--single-transaction", "--routines", "--triggers",
             "--default-character-set=utf8mb4", Config.MYSQL_DB],
            capture_output=True, env=env, timeout=600,
        )
        if proc.returncode != 0:
            logger.error(f"[auto/db_backup] mysqldump 실패: {proc.stderr.decode(errors='replace')[:300]}")
            _notify(f"⚠️ DB 백업 실패\n{datetime.now():%m/%d %H:%M}")
            return
        with gzip.open(out_gz, 'wb') as f:
            f.write(proc.stdout)
        # 14일 보관
        backups = sorted(dst_dir.glob("*.sql.gz"), key=lambda p: p.name)
        for old in backups[:-14]:
            old.unlink(missing_ok=True)
        logger.info(f"[auto/db_backup] 완료 → {out_gz.name} ({out_gz.stat().st_size//1024:,}KB)")
    except Exception as e:
        logger.error(f"[auto/db_backup] 실패: {e}", exc_info=True)
        _notify(f"⚠️ DB 백업 오류\n{datetime.now():%m/%d %H:%M}")


# ─────────────────────────────────────────────────────────────────
# 6. 오프사이트 백업 (DB 백업 + git 번들 → OneDrive)
# ─────────────────────────────────────────────────────────────────
def job_offsite_backup():
    """backup/db의 덤프와 git 저장소 번들을 클라우드 동기화 폴더로 복사.
    OneDrive가 동기화하므로 PC 유실에도 생존."""
    dst_root = Path(os.getenv('OFFSITE_BACKUP_DIR',
                              r'C:\Users\PC\OneDrive\stock_tracker_backup'))
    try:
        dst_db = dst_root / 'db'
        dst_db.mkdir(parents=True, exist_ok=True)

        # DB 덤프 미러 (최신 14개)
        src_db = ROOT / 'backup' / 'db'
        copied = 0
        if src_db.is_dir():
            for f in sorted(src_db.glob('*.sql.gz'))[-14:]:
                dst = dst_db / f.name
                if not dst.exists() or dst.stat().st_size != f.stat().st_size:
                    shutil.copy2(f, dst)
                    copied += 1
            # 오래된 미러 정리
            for old in sorted(dst_db.glob('*.sql.gz'))[:-14]:
                old.unlink(missing_ok=True)

        # git 번들 (전체 코드+이력 단일 파일)
        bundle = dst_root / 'stock_tracker.bundle'
        proc = subprocess.run(
            ['git', '-C', str(ROOT), 'bundle', 'create', str(bundle), '--all'],
            capture_output=True, timeout=120,
        )
        bundle_ok = proc.returncode == 0
        if not bundle_ok:
            logger.warning(f"[auto/offsite] git bundle 실패: {proc.stderr.decode(errors='replace')[:200]}")

        logger.info(f"[auto/offsite] 완료 — DB 미러 {copied}개 복사, "
                    f"git bundle {'OK' if bundle_ok else 'FAIL'} → {dst_root}")
    except Exception as e:
        logger.error(f"[auto/offsite] 실패: {e}", exc_info=True)
        _notify(f"⚠️ 오프사이트 백업 실패\n{datetime.now():%m/%d %H:%M}")


# ─────────────────────────────────────────────────────────────────
# 7. 장애 자가진단 (매일 아침 — 이상 있을 때만 카톡)
# ─────────────────────────────────────────────────────────────────
def job_self_check():
    """시스템이 조용히 죽는 것을 방지하는 아침 점검.
    이상 항목만 모아 카톡 1건 발송. 정상이면 침묵(로그만)."""
    problems = []
    now = datetime.now()

    # 1) DB 연결
    try:
        from database.db_connection import get_db_connection
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        finally:
            conn.close()
    except Exception as e:
        problems.append(f"DB 연결 실패: {type(e).__name__}")

    # 2) 시세 소스 (KIS) — 평일만 의미
    if now.weekday() < 5:
        try:
            from kiwoom_client import kiwoom
            if not kiwoom.market_data_ready():
                problems.append("KIS 시세 미설정 (KIS_APP_KEY/SECRET 확인)")
        except Exception:
            problems.append("시세 소스(KIS) 확인 실패")

    # 3) DB 백업 최신성 (36시간)
    db_dir = ROOT / 'backup' / 'db'
    backups = sorted(db_dir.glob('*.sql.gz')) if db_dir.is_dir() else []
    if not backups:
        problems.append("DB 백업 파일 없음")
    elif (now.timestamp() - backups[-1].stat().st_mtime) > 36 * 3600:
        problems.append(f"DB 백업 오래됨 (최신: {backups[-1].name})")

    # 4) 데일리 추천 갱신 (26시간 — 매일 20:00 생성)
    rec = ROOT / 'XGBoost_v2' / 'model' / 'daily_recommend.json'
    if rec.exists() and (now.timestamp() - rec.stat().st_mtime) > 26 * 3600:
        problems.append("데일리 추천 미갱신 (24h+)")

    # 5) OHLCV 증분 수집 (4일 — 주말/휴일 허용)
    sample = ROOT / 'XGBoost_v2' / 'data' / 'ohlcv' / '005930.parquet'
    if sample.exists() and (now.timestamp() - sample.stat().st_mtime) > 4 * 86400:
        problems.append("OHLCV 데이터 미갱신 (4일+, run_collect.bat/StockTracker_CollectOHLCV 점검 필요)")

    # 6) 디스크 여유 (10GB)
    try:
        free_gb = shutil.disk_usage(str(ROOT)).free / 1e9
        if free_gb < 10:
            problems.append(f"디스크 여유 부족 ({free_gb:.1f}GB)")
    except Exception:
        pass

    if problems:
        msg = "🚨 시스템 점검 이상 감지\n" + "\n".join(f"· {p}" for p in problems)
        logger.warning(f"[auto/self_check] 이상 {len(problems)}건: {problems}")
        _notify(msg)
    else:
        logger.info("[auto/self_check] 전 항목 정상")


# ─────────────────────────────────────────────────────────────────
# 8. 퀀트 시장 스캔 (장 마감 후 — 페이지에서 대기 없이 캐시 사용)
# ─────────────────────────────────────────────────────────────────
def job_quant_scan():
    try:
        from routes.quant import run_market_scan
        result = run_market_scan(top_n=50)
        logger.info(f"[auto/quant_scan] 완료 — {result.get('total', 0)}종목, "
                    f"매수후보 {len(result.get('buy', []))}개")
    except Exception as e:
        logger.error(f"[auto/quant_scan] 실패: {e}", exc_info=True)


# ─────────────────────────────────────────────────────────────────
# 9. 사용자 워크플로 스케줄 디스패처 (매분)
# ─────────────────────────────────────────────────────────────────
def job_workflow_dispatch():
    """예약된 사용자 워크플로(자동화 탭)를 현재 시각과 대조해 실행."""
    try:
        from routes.workflows import run_scheduled_workflows
        n = run_scheduled_workflows()
        if n:
            logger.info(f"[auto/workflow] 예약 워크플로 {n}건 실행")
    except Exception as e:
        logger.error(f"[auto/workflow] 디스패처 오류: {e}", exc_info=True)


# ─────────────────────────────────────────────────────────────────
# 등록
# ─────────────────────────────────────────────────────────────────
def register(scheduler) -> None:
    """app.py 의 BackgroundScheduler에 자동화 잡 등록."""
    from apscheduler.triggers.cron import CronTrigger
    TZ = 'Asia/Seoul'
    scheduler.add_job(job_dividend_autoimport,
                      CronTrigger(day_of_week='sat', hour=9, minute=0, timezone=TZ),
                      id='auto_dividend', replace_existing=True)
    scheduler.add_job(job_model_backup,
                      CronTrigger(day_of_week='sun', hour=1, minute=30, timezone=TZ),
                      id='auto_model_backup', replace_existing=True)
    scheduler.add_job(job_db_backup,
                      CronTrigger(hour=21, minute=0, timezone=TZ),
                      id='auto_db_backup', replace_existing=True)
    scheduler.add_job(job_offsite_backup,
                      CronTrigger(hour=3, minute=0, timezone=TZ),
                      id='auto_offsite_backup', replace_existing=True)
    scheduler.add_job(job_self_check,
                      CronTrigger(hour=9, minute=0, timezone=TZ),
                      id='auto_self_check', replace_existing=True)
    scheduler.add_job(job_quant_scan,
                      CronTrigger(day_of_week='mon-fri', hour=16, minute=25, timezone=TZ),
                      id='auto_quant_scan', replace_existing=True)
    scheduler.add_job(job_workflow_dispatch,
                      CronTrigger(minute='*', timezone=TZ),
                      id='auto_workflow_dispatch', replace_existing=True)
    logger.info("[auto_jobs] 자동화 잡 7종 등록 완료 "
                "(배당기록/모델백업/DB백업/오프사이트/자가진단/퀀트스캔/워크플로디스패처)")
