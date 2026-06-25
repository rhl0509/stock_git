"""
recommend_history 폴더에서 30일 이상 된 JSON 파일을 삭제합니다.
run_monthly.bat 또는 단독 실행 가능.
"""
from pathlib import Path
from datetime import datetime, timedelta

HISTORY_DIRS = [
    Path(__file__).parent / "XGBoost_v2" / "model" / "recommend_history",
]
KEEP_DAYS = 30
cutoff = datetime.now() - timedelta(days=KEEP_DAYS)

for history_dir in HISTORY_DIRS:
    if not history_dir.exists():
        continue
    removed = 0
    for f in history_dir.glob("*.json"):
        try:
            file_date = datetime.strptime(f.stem.replace("-", ""), "%Y%m%d")
        except ValueError:
            continue
        if file_date < cutoff:
            f.unlink()
            removed += 1
            print(f"  Removed: {f.name}")
    print(f"[recommend_history] {removed} files removed")
