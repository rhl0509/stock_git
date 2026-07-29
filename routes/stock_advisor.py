"""
종목 AI 어드바이저
키움 + yfinance + DART + KIS + 한국은행 통합 분석
"""
from fastapi import APIRouter, Request, Depends, Body
from fastapi.responses import JSONResponse
from routes.utils import api_require_login
from routes.tier import require_feature
from routes.advisor_data import _collect_analysis_data
from config import Config
import os
import anthropic
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


_SYSTEM_PROMPT = (
    "당신은 국내 주식 전문 애널리스트입니다. "
    "제공된 정량 데이터를 근거로 매수/매도 의견을 제시합니다. "
    "반드시 한국어로 답하고 마크다운 없이 작성하세요. "
    "현재가는 반드시 키움 API 실시간 가격을 사용하세요. "
    "목표가·손절가는 구체적 원화 수치로 제시하세요. "
    "투자 결정은 본인 책임임을 마지막에 한 줄로 언급하세요."
)

def _call_claude(prompt: str) -> str:
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        return "ANTHROPIC_API_KEY가 설정되지 않았습니다."
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model='claude-opus-4-7',
        max_tokens=4000,
        thinking={'type': 'adaptive'},
        system=_SYSTEM_PROMPT,
        messages=[{'role': 'user', 'content': prompt}],
    )
    try:
        from agent.usage_log import log_usage
        log_usage('claude-opus-4-7', msg.usage, 'advisor')
    except Exception:
        pass
    return next(b.text for b in msg.content if b.type == 'text')


def _build_prompt(name, code, kw, yf, dart, kis, bok, consensus=None, ml=None, ui=None, short=None):
    def fv(v, suf='', fmt='f'):
        if not v: return 'N/A'
        if fmt == 'f': return f"{float(v):.2f}{suf}"
        if fmt == 'c': return f"{int(v):,}{suf}"
        return f"{v}{suf}"

    per = kw.get('per') or (yf.get('yf_per') if yf else None)
    pbr = kw.get('pbr') or (yf.get('yf_pbr') if yf else None)
    roe = kw.get('roe') or (yf.get('yf_roe') if yf else None)
    eps = kw.get('eps') or (yf.get('yf_eps') if yf else None)
    div = kw.get('dividend') or (yf.get('yf_div') if yf else None)

    kw_sec = ""
    if kw:
        kw_sec = (
            "\n[키움 실시간 — 이 현재가가 유일한 기준]"
            f"\n현재가:      {kw.get('price',0):,}원 (출처: {kw.get('price_source','KRX')})"
            f"\n전일대비:    {kw.get('change',0):+,}원  등락률: {kw.get('rate',0):+.2f}%"
            f"\n거래량:      {kw.get('volume',0):,}주   거래대금: {kw.get('trade_amount',0):,}만원"
            f"\n시가총액:    {kw.get('market_cap',0):,}억원"
            f"\nPER: {fv(per,'배')}  PBR: {fv(pbr,'배')}  EPS: {fv(eps,'원','c')}"
            f"\nROE: {fv(roe,'%')}  배당수익률: {fv(div,'%')}"
            f"\n52주 고: {kw.get('week52_high',0):,}원  52주 저: {kw.get('week52_low',0):,}원"
            f"\n외국인소진율: {kw.get('foreign_ratio',0):.2f}%"
            f"\n시가: {kw.get('open',0):,}  고가: {kw.get('high',0):,}  저가: {kw.get('low',0):,}원"
        )

    yf_sec = ""
    if yf:
        kw_price = yf.get('current_price', kw.get('price', 0))
        fib      = yf.get('fib', {})
        ks       = yf.get('kospi', {})
        atr      = yf.get('atr')

        fib_str = "  ".join(f"{k}%={int(v):,}" for k,v in fib.items()) if fib else "N/A"
        ks_str  = (f"{ks.get('current',0):,.2f}pt  주간{ks.get('change_1w',0):+.2f}%  "
                   f"월간{ks.get('change_1m',0):+.2f}%  추세:{ks.get('trend','-')}") if ks else "N/A"
        atr_str = (f"ATR(14)={int(atr):,}원  "
                   f"1.5×ATR 손절={int(yf.get('stop_atr15',0)):,}원  "
                   f"2.0×ATR 손절={int(yf.get('stop_atr20',0)):,}원") if atr else "N/A"

        dev5  = f"{yf.get('ma5_dev'):+.2f}%"  if yf.get('ma5_dev')  is not None else 'N/A'
        dev20 = f"{yf.get('ma20_dev'):+.2f}%" if yf.get('ma20_dev') is not None else 'N/A'
        dev60 = f"{yf.get('ma60_dev'):+.2f}%" if yf.get('ma60_dev') is not None else 'N/A'

        yf_sec = (
            "\n[기술적 분석 — 현재가 기준: 키움 실시간]"
            f"\n현재가(키움): {int(kw_price):,}원"
            f"\nMA5/20/60/120: {fv(yf.get('ma5'),'원','c')} / {fv(yf.get('ma20'),'원','c')} / {fv(yf.get('ma60'),'원','c')} / {fv(yf.get('ma120'),'원','c')}"
            f"\n이격도(MA5/20/60): {dev5} / {dev20} / {dev60}"
            f"\nRSI(14): {yf.get('rsi','N/A')}  볼린저: 상단 {fv(yf.get('bb_upper'),'원','c')} / 하단 {fv(yf.get('bb_lower'),'원','c')}"
            f"\nMACD: {yf.get('macd','N/A')}  시그널: {yf.get('macd_signal','N/A')}  히스토그램: {yf.get('macd_hist','N/A')}"
            f"\n거래량(5일/20일평균): {yf.get('vol_ratio_5_20','N/A')}배"
            f"\n52주위치: {yf.get('w52_position','N/A')}%  (52주고: {fv(yf.get('w52_high'),'원','c')} / 52주저: {fv(yf.get('w52_low'),'원','c')})"
            f"\n섹터: {yf.get('sector','N/A')}  베타: {yf.get('beta','N/A')}"
            f"\n\n[ATR 손절 기준 — 키움 현재가 기반]\n{atr_str}"
            f"\n\n[피보나치 되돌림 (52주 고저 기준)]\n{fib_str}"
            f"\n\n[코스피]\n{ks_str}"
        )

    dart_sec = ""
    if dart:
        fin = dart.get('financials', {})
        dis = dart.get('disclosures', [])
        if fin:
            rev_yoy = fin.get('revenue_yoy')
            ni_yoy  = fin.get('net_income_yoy')
            yoy_parts = []
            if rev_yoy is not None: yoy_parts.append(f"매출 {rev_yoy:+.1f}%")
            if ni_yoy  is not None: yoy_parts.append(f"순이익 {ni_yoy:+.1f}%")
            yoy_str = f"\n전년동기대비(YoY): {' / '.join(yoy_parts)}" if yoy_parts else ""
            dart_sec += (
                f"\n\n[DART 공식 재무제표 — {fin.get('year')}년 {fin.get('period','')}]"
                f"\n매출액:      {fin.get('revenue',0)//100000000:,}억원"
                f"\n영업이익:    {fin.get('operating_income',0)//100000000:,}억원  (영업이익률: {fin.get('op_margin','N/A')}%)"
                f"\n당기순이익:  {fin.get('net_income',0)//100000000:,}억원"
                f"\n부채비율:    {fin.get('debt_ratio','N/A')}%"
                + yoy_str
            )
        if dis:
            dart_sec += "\n\n[최근 30일 공시]"
            for d in dis:
                dart_sec += f"\n  {d.get('date','')} — {d.get('title','')}"

    kis_sec = ""
    if kis:
        inv = kis.get('investor', {})
        if inv:
            days = inv.get('days', 5)
            kis_sec = (
                f"\n\n[KIS 투자자별 수급 — 최근 {days}일 누적]"
                f"\n기관:    {inv.get('inst_net_5d',0):+,}주  ({inv.get('inst_trend','-')})"
                f"\n외국인:  {inv.get('frgn_net_5d',0):+,}주  ({inv.get('frgn_trend','-')})"
                f"\n프로그램:{inv.get('prgm_net_5d',0):+,}주"
            )

    bok_sec = ""
    if bok:
        br  = bok.get('base_rate', {})
        fx  = bok.get('usd_krw', {})
        b10 = bok.get('bond_10y', {})
        parts = []
        if br:  parts.append(f"기준금리: {br.get('value','N/A')}% (최근변동: {br.get('change',0):+.2f}%p)")
        if fx:  parts.append(f"원달러환율: {fx.get('value','N/A')}원 (변동: {fx.get('change',0):+.2f}원)")
        if b10: parts.append(f"국채10년: {b10.get('value','N/A')}% (변동: {b10.get('change',0):+.4f}%p)")
        if parts:
            bok_sec = "\n\n[한국은행 거시경제]\n" + "\n".join(parts)

    news     = yf.get('news', []) if yf else []
    news_sec = ""
    if news:
        news_sec = "\n\n[최근 뉴스 (네이버 금융)]\n" + "\n".join(f"  - {n}" for n in news)

    consensus_sec = ""
    if consensus and (consensus.get("target_price") or consensus.get("opinions")):
        tp      = consensus.get("target_price")
        kw_price_now = kw.get("price", 0) if kw else 0
        opinions    = consensus.get("opinions", {})
        total_cnt   = consensus.get("total_count", 0)
        buy_ratio   = consensus.get("buy_ratio", 0)
        dominant    = consensus.get("dominant_opinion", "N/A")

        if tp and kw_price_now:
            diff_pct = abs(tp - kw_price_now) / kw_price_now * 100
            if diff_pct < 3.0:
                logger.info(f"[Consensus] 목표주가({tp:,})가 현재가({kw_price_now:,})와 너무 가까움 → 오탐으로 제거")
                tp = None
                consensus["target_price"] = None

        gap_str = ""
        if tp and kw_price_now:
            gap     = round((tp - kw_price_now) / kw_price_now * 100, 1)
            gap_str = f"  (현재가 대비 {gap:+.1f}%)"

        op_str = ""
        if opinions and total_cnt:
            op_parts = []
            for name, cnt in opinions.items():
                pct = round(cnt / total_cnt * 100)
                op_parts.append(f"{name} {cnt}명({pct}%)")
            op_str = " / ".join(op_parts)

        consensus_sec = (
            "\n\n[애널리스트 컨센서스 (네이버 금융)]"
            + (f"\n목표주가:     {tp:,}원{gap_str}" if tp else "")
            + (f"\n대표의견:     {dominant}  (매수의견 비율: {buy_ratio}%)" if dominant != "N/A" else "")
            + (f"\n의견분포:     {op_str}" if op_str else "")
            + (f"\n참여애널리스트: {total_cnt}명" if total_cnt else "")
        )
        logger.info(f"[Consensus] 프롬프트 반영: 목표주가={tp}, 대표의견={dominant}, 매수비율={buy_ratio}%")

    short_sec = ""
    if short:
        r5  = short.get('short_ratio_5d')
        r20 = short.get('short_ratio_20d')
        bal = short.get('short_balance_pct')
        if r5 is not None or bal is not None:
            risk = "위험" if (bal or 0) > 5 else ("주의" if (bal or 0) > 2 else "낮음")
            short_sec = (
                "\n\n[공매도 현황 (pykrx)]"
                + (f"\n거래비중:    5일평균 {r5:.2f}% / 20일평균 {r20:.2f}%" if r5 is not None and r20 is not None else "")
                + (f"\n잔고비율:    {bal:.2f}%  (위험도: {risk})" if bal is not None else "")
            )

    ml_sec = ""
    if ml and not ml.get("error") and ml.get("prob_up") is not None:
        prob_up   = ml.get("prob_up", 0)
        prob_down = ml.get("prob_down", 0)
        signal    = ml.get("signal", "N/A")
        cv_acc    = ml.get("cv_accuracy", 0)
        baseline  = ml.get("baseline", 0)
        lift      = ml.get("lift", 0)
        top_feats = ml.get("top_features", [])
        sample_sz = ml.get("sample_size", 0)
        from_cache= ml.get("from_cache", False)

        feat_str = ", ".join(f"{n}({v:.3f})" for n, v in top_feats[:3]) if top_feats else "N/A"

        if cv_acc >= 0.60 and lift >= 0.05:
            reliability = "높음 (통계적으로 유의미)"
        elif cv_acc >= 0.55:
            reliability = "보통 (참고 수준)"
        else:
            reliability = "낮음 (기준선 근접, 참고만)"

        ml_sec = (
            "\n\n[ML 예측 (GradientBoosting) — 5일 후 방향성]"
            f"\n상승 확률:   {prob_up}%  |  하락 확률: {prob_down}%"
            f"\n예측 신호:   {signal}"
            f"\n모델 정확도: {cv_acc*100:.1f}% (5-fold 교차검증, 샘플 {sample_sz}개)"
            f"\n기준선:      {baseline*100:.1f}% (단순 상승 예측 정확도)"
            f"\n모델 향상:   +{lift*100:.1f}%p"
            f"\n신뢰도:      {reliability}"
            f"\n주요 피처:   {feat_str}"
            + ("  [캐시]" if from_cache else "  [신규 학습]")
            + "\n※ 과거 패턴 기반이며 미래를 보장하지 않습니다."
        )
    elif ml and ml.get("error"):
        ml_sec = f"\n\n[ML 예측] 오류: {ml.get('error')}"

    ui_sec = ""
    if ui:
        period    = ui.get('period', '중기(1~3개월)')
        hold_type = ui.get('hold_type', '미보유')
        holding   = ui.get('holding', {})
        stop_pct  = ui.get('stop_loss_pct', 10)
        buy_type  = ui.get('buy_type', '일괄매수')
        extra     = ui.get('extra', '')

        hold_str = "미보유 (신규 매수 검토)"
        if hold_type == '보유중' and holding:
            avg = holding.get('avg_price', 0)
            qty = holding.get('quantity', 0)
            kw_price = kw.get('price', 0)
            if avg and kw_price:
                pnl_pct = round((kw_price - avg) / avg * 100, 2)
                pnl_amt = (kw_price - avg) * qty if qty else 0
                hold_str = (f"보유중 | 평균단가: {avg:,}원 | 수량: {qty:,}주 | "
                            f"현재손익: {pnl_pct:+.2f}% ({pnl_amt:+,}원)")
            else:
                hold_str = f"보유중 | 평균단가: {avg:,}원" if avg else "보유중"

        ui_sec = (
            "\n\n[투자자 조건]"
            f"\n투자기간:   {period}"
            f"\n보유현황:   {hold_str}"
            f"\n손실허용:   최대 -{stop_pct}% (이 기준으로 손절가 계산)"
            f"\n매수방식:   {buy_type}"
            + (f"\n추가정보:   {extra}" if extra else "")
        )

    return (
        f"종목: {name} ({code})"
        f"{kw_sec}{yf_sec}{dart_sec}{kis_sec}{bok_sec}{consensus_sec}{short_sec}{ml_sec}{news_sec}{ui_sec}"
        "\n\n위 데이터를 종합 분석해주세요:\n"
        "1. 현재 주가 상태 (키움 실시간 현재가 기준 — 과매수/과매도/중립)\n"
        "2. 기술적 분석 (MA배열, RSI, MACD, 볼린저밴드 종합)\n"
        "3. 피보나치 분석 (현재가 위치, 가까운 지지/저항)\n"
        "4. 가치 평가 (DART 재무 + PER/PBR/ROE + 애널리스트 목표주가 괴리율)\n"
        "5. 수급 분석 (기관/외인 동향 + 공매도 거래비중·잔고 위험도)\n"
        "6. 거시경제 영향 (금리/환율 → 업종/종목 영향)\n"
        "7. 최근 공시 및 뉴스 영향\n"
        "8. 매수 추천 구간 (투자자 조건 반영, 피보나치 지지선 근거)\n"
        "9. 목표가: 투자기간별 제시 (피보나치 저항선 + 수급 근거)\n"
        "10. 손절가: ATR + 허용손실(-{stop_pct}%) 기준, 지지선 고려\n"
        "11. 분할매수 계획 (해당 시): 1차/2차/3차 가격대\n"
        "12. 핵심 리스크\n\n"
        "각 항목에 구체적 수치를 포함하세요."
    ).replace('{stop_pct}', str(ui.get('stop_loss_pct', 10) if ui else 10))


@router.post('/stock/advisor/analyze', dependencies=[Depends(api_require_login), Depends(require_feature('advisor'))])
def analyze_stock(request: Request, body: dict = Body(default={})):
    """종목 AI 분석 (Claude 유료). 호출 1회당 고정 크레딧(ADVISOR_CREDIT_COST) 차감.
    차감 정책은 챗봇과 동일: 호출 전 잔액 확인 → Claude 성공 후에만 차감."""
    code = body.get('code', '').strip()
    name = body.get('name', code).strip()
    ui   = body.get('user_input', {})

    if not code:
        return JSONResponse({"error": "종목코드를 입력해주세요."}, status_code=400)

    if not Config.ANTHROPIC_API_KEY:
        return JSONResponse({"error": "AI 분석이 설정되지 않았습니다(API 키 없음)."}, status_code=503)

    user_no = request.session['user_no']
    cost = Config.ADVISOR_CREDIT_COST

    # 1) 선차감(원자적) — 동시 요청이 와도 한 건만 통과, 나머지는 여기서 막혀 데이터 수집/Claude 호출을 안 함.
    from routes.credits import deduct_credits, refund_credits
    d = deduct_credits(user_no, cost, memo=f"AI 종목분석 {name}({code})")
    if not d.get("ok"):
        bal = d.get("balance")
        return JSONResponse(
            {"error": f"크레딧이 부족합니다. (필요 {cost:,}C / 보유 {bal:,}C) "
                      f"내 정보 → 크레딧/충전에서 충전해 주세요.",
             "balance": bal, "cost": cost},
            status_code=402)

    r  = _collect_analysis_data(code)
    kw = r['kw']
    yf = r['yf']

    if not kw and not yf:
        refund_credits(user_no, cost, memo=f"AI 종목분석 데이터 수집 실패 환불 ({code})")
        return JSONResponse({"error": "데이터 수집 실패. 키움 API 연결을 확인하세요."}, status_code=500)

    # 2) Claude 호출 (실패 시 선차감분을 환불)
    try:
        analysis = _call_claude(
            _build_prompt(name, code, kw, yf,
                          r['dart'], r['kis'], r['bok'], r['consensus'], r['ml'], ui, r.get('short', {}))
        )
    except Exception as e:
        refund_credits(user_no, cost, memo=f"AI 종목분석 호출 실패 환불 ({code})")
        return JSONResponse({"error": f"AI 분석 실패: {e}"}, status_code=500)

    new_bal = d.get("balance")

    return {
        "name": name, "code": code, "analysis": analysis,
        "cost": cost, "balance": new_bal,
        "kiwoom": kw, "yfinance": yf, "dart": r['dart'],
        "kis": r['kis'], "bok": r['bok'],
        "consensus": r['consensus'], "short": r.get('short', {}), "ml": r['ml'],
    }
