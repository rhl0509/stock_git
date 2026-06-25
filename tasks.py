# tasks.py - 학습 파이프라인 invoke 태스크
#
# 사용법:
#   inv train-daily                     # daily 단독, Optuna 없음
#   inv train-daily --optuna            # daily + Optuna (기본 20회)
#   inv train-daily --optuna --trials 50
#   inv train-short --no-pit            # PIT 재무 매칭 비활성
#   inv train-all                       # daily + short + swing
#   inv train-all --optuna --trials 30
#   inv backup                          # 모델 백업
#   inv --list                          # 전체 태스크 목록
from invoke import task

PYTHON = r".venv64\Scripts\python.exe"
MODULE = "XGBoost_v2.train_v2"


def _build_cmd(labels: str | None, optuna: bool, trials: int, no_pit: bool) -> str:
    parts = [PYTHON, "-m", MODULE]
    if labels:
        parts += ["--labels"] + labels.split()
    if optuna:
        parts += ["--trials", str(trials)]
    else:
        parts.append("--skip-optuna")
    if no_pit:
        parts.append("--no-pit")
    return " ".join(parts)


@task(help={
    "optuna":  "Optuna 하이퍼파라미터 튜닝 활성화 (기본: 비활성)",
    "trials":  "Optuna 시도 횟수 (기본: 20)",
    "no_pit":  "PIT 재무 매칭 비활성화 - 빠른 학습",
})
def train_daily(c, optuna=False, trials=20, no_pit=False):
    """daily 라벨 단독 학습 (3일 후 +2% 목표)"""
    c.run(_build_cmd("daily", optuna, trials, no_pit), pty=False, in_stream=False)


@task(help={
    "optuna":  "Optuna 하이퍼파라미터 튜닝 활성화 (기본: 비활성)",
    "trials":  "Optuna 시도 횟수 (기본: 20)",
    "no_pit":  "PIT 재무 매칭 비활성화 - 빠른 학습",
})
def train_short(c, optuna=False, trials=20, no_pit=False):
    """short 라벨 단독 학습 (5일 후 +3% 목표)"""
    c.run(_build_cmd("short", optuna, trials, no_pit), pty=False, in_stream=False)


@task(help={
    "optuna":  "Optuna 하이퍼파라미터 튜닝 활성화 (기본: 비활성)",
    "trials":  "Optuna 시도 횟수 (기본: 20)",
    "no_pit":  "PIT 재무 매칭 비활성화 - 빠른 학습",
})
def train_swing(c, optuna=False, trials=20, no_pit=False):
    """swing 라벨 단독 학습 (14일 후 +7% 목표)"""
    c.run(_build_cmd("swing", optuna, trials, no_pit), pty=False, in_stream=False)


@task(help={
    "optuna":  "Optuna 하이퍼파라미터 튜닝 활성화 (기본: 비활성)",
    "trials":  "Optuna 시도 횟수 (기본: 20)",
    "no_pit":  "PIT 재무 매칭 비활성화 - 빠른 학습",
    "labels":  "학습할 라벨 공백 구분 (기본: 전체). 예: 'daily short'",
})
def train_all(c, optuna=False, trials=20, no_pit=False, labels=None):
    """전체 라벨 학습 (daily + short + swing)"""
    c.run(_build_cmd(labels, optuna, trials, no_pit), pty=False, in_stream=False)


@task
def backup(c):
    """현재 모델 파일 백업 (backup/model/날짜/)"""
    c.run("backup_model.bat", pty=False, in_stream=False)
