"""
fmp_client.py — kr_finance_client.py 로 위임 (FMP v3 API 2025-08 종료 대응).

feature_v2.py / train_v2.py 의 import 경로 유지를 위해 re-export.
"""
from .kr_finance_client import (  # noqa: F401
    get_financial_features,
    get_financial_features_pit,
    get_quarterly_history,
    FINANCIAL_COLS,
    _FIN_DEFAULTS,
)
