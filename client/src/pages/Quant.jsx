import React, { useState, useRef, useEffect } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

// ── 등급/해석 헬퍼 ──────────────────────────────────────────────
function compositeGrade(v) {
  if (v >= 0.4)  return { label: '강한 매수', color: '#22c55e', bg: 'rgba(34,197,94,0.12)'  };
  if (v >= 0.15) return { label: '매수',      color: '#86efac', bg: 'rgba(134,239,172,0.12)' };
  if (v >= -0.15) return { label: '관망',     color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' };
  if (v >= -0.4) return { label: '매도',      color: '#fca5a5', bg: 'rgba(252,165,165,0.12)' };
  return              { label: '강한 매도',   color: '#ef4444', bg: 'rgba(239,68,68,0.12)'  };
}

function rsiGrade(v) {
  if (v < 30) return { label: '과매도', color: '#22c55e' };
  if (v > 70) return { label: '과매수', color: '#ef4444' };
  return           { label: '중립',    color: '#f59e0b' };
}

function hurstLabel(h) {
  if (h > 0.6) return { label: '추세 지속형', desc: '오르던 방향으로 계속 가는 성질이 강함', color: '#3b82f6' };
  if (h < 0.4) return { label: '평균 회귀형', desc: '평균 가격으로 되돌아오는 성질이 강함', color: '#8b5cf6' };
  return             { label: '랜덤 워크',   desc: '방향성 없음 — 예측이 어려운 구간',     color: '#94a3b8' };
}

function pct(v, digits = 2) { return v != null ? `${v > 0 ? '+' : ''}${v.toFixed(digits)}%` : '-'; }
function num(v, digits = 2)  { return v != null ? v.toFixed(digits) : '-'; }
function krw(v)               { return v != null ? `₩${Math.round(v).toLocaleString('ko')}` : '-'; }

// ── 지표 → 일반어 문장 + 투표 (쉬운 결론 생성기) ─────────────────
function buildPlainVerdict(L, lastRegime, lastVolLow, hurst) {
  const votes = [];   // {dir: 'buy'|'sell'|'hold', text}
  if (L.rsi != null) {
    if (L.rsi < 30)      votes.push({ dir: 'buy',  text: `RSI ${L.rsi.toFixed(0)} — 많이 팔려서 단기 반등 여지` });
    else if (L.rsi > 70) votes.push({ dir: 'sell', text: `RSI ${L.rsi.toFixed(0)} — 많이 사들여 과열 상태` });
    else                 votes.push({ dir: 'hold', text: `RSI ${L.rsi.toFixed(0)} — 과열도 침체도 아님` });
  }
  if (L.macd_hist != null) {
    if (L.macd_hist > 0) votes.push({ dir: 'buy',  text: 'MACD — 단기 흐름이 장기 흐름을 위로 돌파 (상승 전환 신호)' });
    else                 votes.push({ dir: 'sell', text: 'MACD — 단기 흐름이 장기 흐름 아래 (하락 우위)' });
  }
  if (L.bb_pct != null) {
    if (L.bb_pct < 20)      votes.push({ dir: 'buy',  text: '볼린저밴드 — 가격이 평소 범위 바닥권 (반등 가능)' });
    else if (L.bb_pct > 80) votes.push({ dir: 'sell', text: '볼린저밴드 — 가격이 평소 범위 천장권 (조정 가능)' });
    else                    votes.push({ dir: 'hold', text: '볼린저밴드 — 평소 가격 범위 안' });
  }
  if (L.stoch_k != null && L.stoch_d != null) {
    if (L.stoch_k > L.stoch_d) votes.push({ dir: 'buy',  text: '스토캐스틱 — 단기 상승 탄력 있음' });
    else                       votes.push({ dir: 'sell', text: '스토캐스틱 — 단기 탄력 꺾임' });
  }
  if (L.mom20 != null) {
    if (L.mom20 > 3)       votes.push({ dir: 'buy',  text: `최근 한 달 ${pct(L.mom20, 1)} 상승 흐름` });
    else if (L.mom20 < -3) votes.push({ dir: 'sell', text: `최근 한 달 ${pct(L.mom20, 1)} 하락 흐름` });
    else                   votes.push({ dir: 'hold', text: '최근 한 달 보합권' });
  }
  if (L.close != null && L.ma200 != null) {
    if (L.close > L.ma200) votes.push({ dir: 'buy',  text: '200일 평균선 위 — 장기 추세 살아있음' });
    else                   votes.push({ dir: 'sell', text: '200일 평균선 아래 — 장기 추세 약함' });
  }
  if (L.vol_ratio != null && L.vol_ratio > 2) {
    votes.push({ dir: 'buy', text: `거래량 평소 ${L.vol_ratio.toFixed(1)}배 — 시장 관심 급증` });
  }

  const buy  = votes.filter(v => v.dir === 'buy').length;
  const sell = votes.filter(v => v.dir === 'sell').length;
  const hold = votes.filter(v => v.dir === 'hold').length;

  let headline;
  if (buy >= sell + 2)      headline = `지표 ${votes.length}개 중 ${buy}개가 매수 쪽 — 긍정 신호 우세`;
  else if (sell >= buy + 2) headline = `지표 ${votes.length}개 중 ${sell}개가 매도 쪽 — 주의 신호 우세`;
  else                      headline = `매수 ${buy} · 매도 ${sell} — 신호가 엇갈려 관망 권장`;

  const ctx = [];
  if (lastRegime) ctx.push(lastRegime === 'BULL' ? '시장 국면은 상승장' : '시장 국면은 하락장');
  if (lastVolLow != null) ctx.push(lastVolLow ? '변동성 낮아 안정적' : '변동성 높아 급등락 주의');
  if (hurst != null) ctx.push(hurstLabel(hurst).desc);

  return { votes, buy, sell, hold, headline, context: ctx.join(' · ') };
}

// ── 소형 컴포넌트들 ─────────────────────────────────────────────

function Help({ text }) {
  return (
    <i className="bi bi-question-circle" title={text}
       style={{ fontSize: '0.72rem', color: 'var(--fg-3)', marginLeft: 5, cursor: 'help' }} />
  );
}

function GaugeBar({ value, min = 0, max = 100, label }) {
  const p = Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100));
  const color = value < 30 ? '#22c55e' : value > 70 ? '#ef4444' : '#f59e0b';
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3, fontSize: '0.68rem', color: 'var(--fg-3)' }}>
        <span>{min}</span><span style={{ color }}>{label || value?.toFixed(1)}</span><span>{max}</span>
      </div>
      <div style={{ height: 6, background: 'var(--line-1)', borderRadius: 3, overflow: 'hidden', position: 'relative' }}>
        <div style={{ position: 'absolute', left: '30%', width: 1, height: '100%', background: 'var(--line-2)' }} />
        <div style={{ position: 'absolute', left: '70%', width: 1, height: '100%', background: 'var(--line-2)' }} />
        <div style={{ width: `${p}%`, height: '100%', background: color, borderRadius: 3 }} />
      </div>
    </div>
  );
}

function StatCard({ icon, label, value, sub, color, help }) {
  return (
    <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '14px 16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
        {icon && <i className={`bi ${icon}`} style={{ color: color || 'var(--accent)', fontSize: '0.9rem' }} />}
        <span style={{ fontSize: '0.72rem', color: 'var(--fg-3)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{label}</span>
        {help && <Help text={help} />}
      </div>
      <div style={{ fontSize: '1.3rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: color || 'var(--fg-1)' }}>{value ?? '-'}</div>
      {sub && <div style={{ fontSize: '0.7rem', color: 'var(--fg-3)', marginTop: 3 }}>{sub}</div>}
    </div>
  );
}

function Row({ label, value, color, hint, help }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '7px 0', borderBottom: '1px solid var(--line-1)', fontSize: '0.82rem', gap: 8 }}>
      <span style={{ color: 'var(--fg-3)', flexShrink: 0 }}>{label}{help && <Help text={help} />}</span>
      <div style={{ textAlign: 'right' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: color || 'var(--fg-1)' }}>{value ?? '-'}</span>
        {hint && <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)' }}>{hint}</div>}
      </div>
    </div>
  );
}

// ── 관심종목 추가 (그룹 없으면 자동 생성) ─────────────────────────
async function addToWatchlist(code, name) {
  const r = await api.get('/api/watchlist/groups');
  let gid = (r.data?.groups || [])[0]?.id;
  if (!gid) {
    const c = await api.post('/api/watchlist/groups', { name: '관심종목' });
    gid = c.data?.id;
  }
  await api.post(`/api/watchlist/${gid}/items`, { stock_code: code, stock_name: name || code });
}

// ── 가격 차트 (종가 + 50/200일선 + 상승/하락 국면 배경) ──────────
function PriceChart({ dates, close, ma50, ma200, regime }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !close?.length) return;
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth, H = 220;
    canvas.width = W * dpr; canvas.height = H * dpr;
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    const PAD = { t: 10, b: 22, l: 56, r: 10 };
    const cw = W - PAD.l - PAD.r, ch = H - PAD.t - PAD.b;

    const series = [close, ma50, ma200].filter(Boolean);
    const all = series.flat().filter(v => v != null && isFinite(v));
    const min = Math.min(...all) * 0.99, max = Math.max(...all) * 1.01;
    const n = close.length;
    const x = i => PAD.l + (i / (n - 1 || 1)) * cw;
    const y = v => PAD.t + ch - ((v - min) / (max - min || 1)) * ch;

    ctx.clearRect(0, 0, W, H);

    // 국면 배경 (상승장 초록 / 하락장 빨강 미세 틴트)
    if (regime?.length) {
      for (let i = 0; i < n - 1; i++) {
        ctx.fillStyle = regime[i] === 'BULL' ? 'rgba(34,197,94,0.05)' : 'rgba(239,68,68,0.06)';
        ctx.fillRect(x(i), PAD.t, x(i + 1) - x(i) + 1, ch);
      }
    }

    // y축 그리드
    ctx.font = '9px monospace'; ctx.fillStyle = '#888'; ctx.textAlign = 'right';
    [min, (min + max) / 2, max].forEach(v => {
      ctx.strokeStyle = 'rgba(120,120,120,0.12)';
      ctx.beginPath(); ctx.moveTo(PAD.l, y(v)); ctx.lineTo(W - PAD.r, y(v)); ctx.stroke();
      ctx.fillText(Math.round(v).toLocaleString('ko'), PAD.l - 5, y(v) + 3);
    });
    // x축 날짜 (4개)
    ctx.textAlign = 'center';
    [0, Math.floor(n / 3), Math.floor(n * 2 / 3), n - 1].forEach(i => {
      if (dates?.[i]) ctx.fillText(dates[i].slice(5), x(i), H - 6);
    });

    const drawLine = (arr, color, width, dash) => {
      if (!arr) return;
      ctx.strokeStyle = color; ctx.lineWidth = width;
      ctx.setLineDash(dash || []);
      ctx.beginPath();
      let started = false;
      arr.forEach((v, i) => {
        if (v == null || !isFinite(v)) return;
        if (!started) { ctx.moveTo(x(i), y(v)); started = true; }
        else ctx.lineTo(x(i), y(v));
      });
      ctx.stroke(); ctx.setLineDash([]);
    };
    drawLine(ma200, '#8b5cf6', 1.2, [5, 3]);
    drawLine(ma50,  '#3b82f6', 1.2, [2, 2]);
    drawLine(close, '#f59e0b', 2);
  }, [dates, close, ma50, ma200, regime]);

  if (!close?.length) return null;
  return (
    <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '14px 16px', marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, flexWrap: 'wrap', gap: 6 }}>
        <span style={{ fontWeight: 700, fontSize: '0.85rem' }}>최근 6개월 가격 흐름</span>
        <span style={{ fontSize: '0.7rem', color: 'var(--fg-3)' }}>
          <span style={{ color: '#f59e0b' }}>━</span> 종가&nbsp;
          <span style={{ color: '#3b82f6' }}>┄</span> 50일선&nbsp;
          <span style={{ color: '#8b5cf6' }}>╌</span> 200일선&nbsp;
          배경: <span style={{ color: '#22c55e' }}>상승장</span>/<span style={{ color: '#ef4444' }}>하락장</span>
        </span>
      </div>
      <canvas ref={ref} style={{ width: '100%', height: 220, display: 'block' }} />
    </div>
  );
}

// ── 포지션 사이징: "그래서 몇 주 살까?" ──────────────────────────
function SizingWidget({ code, name, close }) {
  const [capital, setCapital]   = useState(10000000);
  const [riskPct, setRiskPct]   = useState(1);
  const [result, setResult]     = useState(null);
  const [loading, setLoading]   = useState(false);
  const [msg, setMsg]           = useState('');

  const calc = async () => {
    setLoading(true); setMsg('');
    try {
      const r = await api.post('/api/quant/risk', {
        codes: [code], capital, risk_per_trade: riskPct / 100,
      });
      setResult(r.data?.stock_risk?.[0] || null);
    } catch (e) { setMsg(e.response?.data?.error || '계산 실패'); }
    setLoading(false);
  };

  const registerAlert = async () => {
    if (!result) return;
    setMsg('');
    try {
      await api.post('/api/price_alerts', {
        code, name: name || code,
        stop_price: result.stop_price || null,
        target_price: null,
        note: '퀀트 분석에서 등록',
      });
      setMsg('✅ 손절가 알림 등록 완료 — 도달 시 카톡으로 알려드립니다');
    } catch (e) { setMsg(e.response?.data?.error || '알림 등록 실패'); }
  };

  const paperBuy = async () => {
    if (!result?.shares) return;
    setMsg('');
    try {
      await api.post('/api/paper_trading/buy', {
        code, name: name || code, price: close, quantity: result.shares,
      });
      setMsg(`✅ 가상매매 계좌에 ${result.shares}주 매수 완료 — '가상매매' 탭에서 성과를 확인하세요`);
    } catch (e) { setMsg(e.response?.data?.error || '가상 매수 실패'); }
  };

  const watch = async () => {
    setMsg('');
    try {
      await addToWatchlist(code, name);
      setMsg('✅ 관심종목 추가 완료 — 공시 감시 에이전트가 자동으로 지켜봅니다');
    } catch { setMsg('관심종목 추가 실패'); }
  };

  return (
    <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '16px 20px', marginBottom: 16 }}>
      <div style={{ fontWeight: 700, fontSize: '0.85rem', marginBottom: 4 }}>
        <i className="bi bi-calculator me-2" style={{ color: 'var(--accent)' }} />그래서 몇 주 살까?
        <Help text="감수할 손실을 먼저 정하고 거꾸로 매수량을 계산합니다. 손절가는 평소 하루 변동폭(ATR)의 2배 아래." />
      </div>
      <div style={{ fontSize: '0.72rem', color: 'var(--fg-3)', marginBottom: 12 }}>
        "한 번 틀려도 이만큼만 잃겠다"를 정하면 안전한 매수량이 나옵니다.
      </div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap', marginBottom: 12 }}>
        <div>
          <label style={{ fontSize: '0.72rem', color: 'var(--fg-3)', display: 'block', marginBottom: 4 }}>투자 가능 원금</label>
          <input className="form-control form-control-sm" type="number" value={capital} step={1000000}
            onChange={e => setCapital(+e.target.value)} style={{ width: 140 }} />
        </div>
        <div>
          <label style={{ fontSize: '0.72rem', color: 'var(--fg-3)', display: 'block', marginBottom: 4 }}>1회 최대 감수 손실</label>
          <select className="form-select form-select-sm" value={riskPct} onChange={e => setRiskPct(+e.target.value)} style={{ width: 130 }}>
            <option value={0.5}>원금의 0.5%</option>
            <option value={1}>원금의 1%</option>
            <option value={2}>원금의 2%</option>
            <option value={3}>원금의 3%</option>
          </select>
        </div>
        <button className="btn btn-primary btn-sm" onClick={calc} disabled={loading}>
          {loading ? '계산 중...' : '계산'}
        </button>
      </div>

      {result && (
        <>
          <div style={{ background: 'var(--bg-3)', borderRadius: 'var(--r-2)', padding: '12px 16px', marginBottom: 10, fontSize: '0.88rem', color: 'var(--fg-1)' }}>
            <b style={{ fontSize: '1.05rem', color: 'var(--accent)', fontFamily: 'var(--font-mono)' }}>{result.shares?.toLocaleString('ko')}주</b> 매수
            (<span style={{ fontFamily: 'var(--font-mono)' }}>{krw(result.position_value)}</span>, 원금의 {result.position_pct}%)
            · 손절가 <b style={{ color: '#ef4444', fontFamily: 'var(--font-mono)' }}>{result.stop_price?.toLocaleString('ko')}원</b>
            <div style={{ fontSize: '0.74rem', color: 'var(--fg-3)', marginTop: 4 }}>
              손절가에 도달해도 손실은 약 {krw(result.risk_amount)} ({riskPct}%)로 제한됩니다
              {result.kelly != null && <> · 켈리 공식 권장 비중: 원금의 {result.kelly}%<Help text="과거 승률·손익비로 계산한 이론상 최적 투자 비중. 보통 이 절반만 쓰는 게 안전합니다." /></>}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="btn btn-outline-danger btn-sm" onClick={registerAlert}>
              <i className="bi bi-bell me-1" />손절가 알림 걸기
            </button>
            <button className="btn btn-outline-success btn-sm" onClick={paperBuy}>
              <i className="bi bi-controller me-1" />가상으로 사보기 ({result.shares}주)
            </button>
            <button className="btn btn-outline-secondary btn-sm" onClick={watch}>
              <i className="bi bi-star me-1" />관심종목 추가
            </button>
          </div>
        </>
      )}
      {msg && <div style={{ marginTop: 10, fontSize: '0.78rem', color: msg.startsWith('✅') ? '#22c55e' : 'var(--down)' }}>{msg}</div>}
    </div>
  );
}

// ── 종목 검색 자동완성 (코드를 몰라도 이름으로 검색) ─────────────
function StockSearch({ onPick, loading, onSubmit, btnLabel, initial }) {
  const [q, setQ]       = useState(initial || '');
  const [sugg, setSugg] = useState([]);
  const [picked, setPicked] = useState(null);
  const timer = useRef(null);

  useEffect(() => { if (initial) setQ(initial); }, [initial]);

  const search = v => {
    setQ(v); setPicked(null);
    clearTimeout(timer.current);
    if (!v.trim()) { setSugg([]); return; }
    // 6자리 숫자면 그대로 사용 가능
    timer.current = setTimeout(async () => {
      const r = await api.get('/search-stock-kr', { params: { q: v } }).catch(() => ({ data: [] }));
      setSugg((r.data || []).slice(0, 8));
    }, 250);
  };

  const pick = s => {
    setQ(`${s.name} (${s.code})`); setSugg([]); setPicked(s.code);
    onPick(s.code);
  };

  const submit = () => {
    const code = picked || (q.trim().match(/\d{6}/)?.[0] ?? '');
    if (!code) return;
    onPick(code);
    onSubmit(code);
  };

  return (
    <div style={{ display: 'flex', gap: 8, position: 'relative', flexWrap: 'wrap' }}>
      <div style={{ position: 'relative', flex: 1, minWidth: 220, maxWidth: 320 }}>
        <input className="form-control" value={q} onChange={e => search(e.target.value)}
          placeholder="종목명 또는 코드 (예: 삼성전자)" onKeyDown={e => e.key === 'Enter' && submit()} autoComplete="off" />
        {sugg.length > 0 && (
          <div style={{ position: 'absolute', zIndex: 20, top: '100%', left: 0, right: 0, background: 'var(--bg-2)', border: '1px solid var(--line-2)', borderRadius: 'var(--r-2)', maxHeight: 240, overflowY: 'auto', boxShadow: '0 4px 14px rgba(0,0,0,0.18)' }}>
            {sugg.map(s => (
              <div key={s.code} onClick={() => pick(s)}
                style={{ padding: '8px 12px', cursor: 'pointer', fontSize: '0.82rem', borderBottom: '1px solid var(--line-1)' }}>
                <span style={{ fontWeight: 600 }}>{s.name}</span>
                <span style={{ fontSize: '0.7rem', color: 'var(--fg-3)', marginLeft: 8, fontFamily: 'var(--font-mono)' }}>{s.code}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <button className="btn btn-primary" onClick={submit} disabled={loading || !q.trim()}>
        {loading ? <><span className="spinner-border spinner-border-sm me-1" />분석 중...</> : btnLabel || '분석'}
      </button>
    </div>
  );
}

// ── 자산곡선 차트 (백테스트) ─────────────────────────────────────
function EquityChart({ equity, benchmarkRet }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !equity?.length) return;
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth, H = 180;
    canvas.width = W * dpr; canvas.height = H * dpr;
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    const PAD = { t: 14, b: 8, l: 44, r: 10 };
    const cw = W - PAD.l - PAD.r, ch = H - PAD.t - PAD.b;

    // 벤치마크(그냥 보유) 직선 포함해 스케일 결정
    const bhEnd = 100 + (benchmarkRet ?? 0);
    const all = [...equity, bhEnd, 100];
    const min = Math.min(...all) * 0.98, max = Math.max(...all) * 1.02;
    const x = i => PAD.l + (i / (equity.length - 1 || 1)) * cw;
    const y = v => PAD.t + ch - ((v - min) / (max - min || 1)) * ch;

    ctx.clearRect(0, 0, W, H);
    // 그리드 + 축 레이블
    ctx.font = '9px monospace'; ctx.fillStyle = '#888'; ctx.textAlign = 'right';
    [min, (min + max) / 2, max].forEach(v => {
      ctx.strokeStyle = 'rgba(120,120,120,0.12)';
      ctx.beginPath(); ctx.moveTo(PAD.l, y(v)); ctx.lineTo(W - PAD.r, y(v)); ctx.stroke();
      ctx.fillText(`${v.toFixed(0)}`, PAD.l - 4, y(v) + 3);
    });
    // 원금선 (100)
    ctx.strokeStyle = 'rgba(148,163,184,0.5)'; ctx.setLineDash([4, 3]);
    ctx.beginPath(); ctx.moveTo(PAD.l, y(100)); ctx.lineTo(W - PAD.r, y(100)); ctx.stroke();
    ctx.setLineDash([]);
    // 벤치마크 (시작→끝 직선)
    if (benchmarkRet != null) {
      ctx.strokeStyle = '#94a3b8'; ctx.lineWidth = 1.5; ctx.setLineDash([6, 4]);
      ctx.beginPath(); ctx.moveTo(x(0), y(100)); ctx.lineTo(x(equity.length - 1), y(bhEnd)); ctx.stroke();
      ctx.setLineDash([]);
    }
    // 전략 자산곡선
    const up = equity[equity.length - 1] >= 100;
    const lineColor = up ? '#22c55e' : '#ef4444';
    const grad = ctx.createLinearGradient(0, PAD.t, 0, PAD.t + ch);
    grad.addColorStop(0, up ? 'rgba(34,197,94,0.22)' : 'rgba(239,68,68,0.22)');
    grad.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.beginPath();
    equity.forEach((v, i) => i === 0 ? ctx.moveTo(x(i), y(v)) : ctx.lineTo(x(i), y(v)));
    ctx.lineTo(x(equity.length - 1), PAD.t + ch); ctx.lineTo(x(0), PAD.t + ch); ctx.closePath();
    ctx.fillStyle = grad; ctx.fill();
    ctx.beginPath();
    equity.forEach((v, i) => i === 0 ? ctx.moveTo(x(i), y(v)) : ctx.lineTo(x(i), y(v)));
    ctx.strokeStyle = lineColor; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.stroke();
  }, [equity, benchmarkRet]);

  if (!equity?.length) return null;
  return (
    <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '14px 16px', marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, flexWrap: 'wrap', gap: 6 }}>
        <span style={{ fontWeight: 700, fontSize: '0.85rem' }}>내 돈이 어떻게 변했나 (원금=100 기준)</span>
        <span style={{ fontSize: '0.7rem', color: 'var(--fg-3)' }}>
          <span style={{ color: '#22c55e' }}>━</span> 이 전략 &nbsp;
          <span style={{ color: '#94a3b8' }}>╌╌</span> 그냥 사서 보유 &nbsp;
          <span style={{ color: '#94a3b8' }}>┄</span> 원금
        </span>
      </div>
      <canvas ref={ref} style={{ width: '100%', height: 180, display: 'block' }} />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// 탭 1 — 종목 분석
// ═══════════════════════════════════════════════════════════════
function AnalyzeTab({ initCode, onAnalyzed }) {
  const [code, setCode]     = useState(initCode || '');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]   = useState('');

  const run = async (c) => {
    const target = (c || code || '').trim();
    if (!target) return;
    setLoading(true); setError(''); setResult(null);
    try {
      const r = await api.post('/api/quant/signals', { code: target });
      setResult(r.data);
      onAnalyzed?.(target);
    } catch (e) { setError(e.response?.data?.error || '분석 실패'); }
    setLoading(false);
  };

  // 스캐너에서 넘어온 종목 자동 분석
  useEffect(() => { if (initCode) { setCode(initCode); run(initCode); } }, [initCode]);  // eslint-disable-line

  const L = result?.latest || {};
  const R = result?.regime || {};
  const lastRegime  = R.regime?.[R.regime.length - 1];
  const lastVolLow  = R.vol_low?.[R.vol_low.length - 1];
  const cg = L.composite != null ? compositeGrade(L.composite) : null;
  const hurst = result?.hurst;
  const hl = hurst != null ? hurstLabel(hurst) : null;
  const verdict = result ? buildPlainVerdict(L, lastRegime, lastVolLow, hurst) : null;

  return (
    <>
      <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '16px 20px', marginBottom: 16 }}>
        <StockSearch onPick={setCode} onSubmit={run} loading={loading} initial={initCode ? undefined : undefined} />
        {error && <div style={{ marginTop: 8, fontSize: '0.82rem', color: 'var(--down)', padding: '7px 10px', background: 'rgba(239,68,68,0.07)', borderRadius: 'var(--r-2)', border: '1px solid rgba(239,68,68,0.2)' }}><i className="bi bi-exclamation-triangle me-1" />{error}</div>}
        <div style={{ marginTop: 10, fontSize: '0.72rem', color: 'var(--fg-3)' }}>
          <i className="bi bi-info-circle me-1" />차트의 기술적 지표 8개(RSI·MACD·볼린저밴드 등)를 종합해 지금이 사기 좋은 타이밍인지 판단합니다.
        </div>
      </div>

      {result && (
        <>
          {/* 종합 신호 */}
          <div style={{ background: cg?.bg, border: `2px solid ${cg?.color}55`, borderRadius: 'var(--r-3)', padding: '20px 24px', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}>
            <div style={{ textAlign: 'center', minWidth: 120 }}>
              <div style={{ fontSize: '0.72rem', color: 'var(--fg-3)', marginBottom: 4 }}>종합 신호</div>
              <div style={{ fontSize: '2.2rem', fontWeight: 900, color: cg?.color, lineHeight: 1 }}>{cg?.label}</div>
              <div style={{ fontSize: '0.78rem', color: 'var(--fg-3)', marginTop: 4, fontFamily: 'var(--font-mono)' }}>점수 {L.composite?.toFixed(3)}</div>
            </div>
            <div style={{ flex: 1, minWidth: 200 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: '0.68rem', color: 'var(--fg-3)' }}>
                <span>강한 매도</span><span>관망</span><span>강한 매수</span>
              </div>
              <div style={{ height: 10, background: 'var(--line-1)', borderRadius: 5, position: 'relative' }}>
                <div style={{ position: 'absolute', left: '50%', width: 1, height: '100%', background: 'var(--line-2)' }} />
                <div style={{ position: 'absolute', left: `${Math.min(100, Math.max(0, (L.composite + 1) / 2 * 100))}%`, top: -3, width: 16, height: 16, borderRadius: '50%', background: cg?.color, border: '2px solid var(--bg-1)', transform: 'translateX(-50%)' }} />
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.78rem' }}>
              <div style={{ color: lastRegime === 'BULL' ? '#22c55e' : '#ef4444' }}>
                <i className={`bi bi-${lastRegime === 'BULL' ? 'arrow-up-circle' : 'arrow-down-circle'} me-1`} />
                {lastRegime === 'BULL' ? '상승장' : '하락장'}
              </div>
              <div style={{ color: lastVolLow ? '#3b82f6' : '#f59e0b' }}>
                <i className={`bi bi-${lastVolLow ? 'wind' : 'exclamation-triangle'} me-1`} />
                {lastVolLow ? '출렁임 적음' : '출렁임 큼'}
              </div>
              {hl && <div style={{ color: hl.color }}><i className="bi bi-activity me-1" />{hl.label}</div>}
            </div>
          </div>

          {/* 가격 차트 */}
          <PriceChart dates={result.dates} close={result.data?.close}
            ma50={R.ma50} ma200={R.ma200} regime={R.regime} />

          {/* ── 쉬운 결론 ── */}
          {verdict && (
            <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderLeft: `4px solid ${cg?.color}`, borderRadius: 'var(--r-3)', padding: '16px 20px', marginBottom: 16 }}>
              <div style={{ fontWeight: 800, fontSize: '0.95rem', color: 'var(--fg-1)', marginBottom: 4 }}>
                <i className="bi bi-chat-square-text me-2" style={{ color: cg?.color }} />{verdict.headline}
              </div>
              {verdict.context && <div style={{ fontSize: '0.76rem', color: 'var(--fg-3)', marginBottom: 10 }}>{verdict.context}</div>}
              <div style={{ display: 'grid', gap: 4 }}>
                {verdict.votes.map((v, i) => (
                  <div key={i} style={{ fontSize: '0.8rem', color: 'var(--fg-2)', display: 'flex', gap: 8, alignItems: 'baseline' }}>
                    <span style={{ flexShrink: 0, fontSize: '0.66rem', fontWeight: 800, width: 34, textAlign: 'center', borderRadius: 4, padding: '1px 0',
                      color:      v.dir === 'buy' ? '#22c55e' : v.dir === 'sell' ? '#ef4444' : '#f59e0b',
                      background: v.dir === 'buy' ? 'rgba(34,197,94,0.12)' : v.dir === 'sell' ? 'rgba(239,68,68,0.12)' : 'rgba(245,158,11,0.12)' }}>
                      {v.dir === 'buy' ? '매수' : v.dir === 'sell' ? '매도' : '중립'}
                    </span>
                    {v.text}
                  </div>
                ))}
              </div>
              <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)', marginTop: 10 }}>
                ⚠ 기술적 지표 기반 참고용입니다. 기업 실적·뉴스는 반영되지 않으며, 투자 판단과 책임은 본인에게 있습니다.
              </div>
            </div>
          )}

          {/* 포지션 사이징 + 원클릭 액션 */}
          <SizingWidget code={result.code} name={result.name} close={L.close} />

          {/* 지표 카드 그리드 (상세) */}
          <details style={{ marginBottom: 16 }}>
            <summary style={{ cursor: 'pointer', fontSize: '0.85rem', fontWeight: 700, color: 'var(--fg-2)', padding: '8px 4px' }}>
              <i className="bi bi-graph-up me-2" style={{ color: 'var(--accent)' }} />지표 상세 보기 (8개)
            </summary>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12, marginTop: 10 }}>

              <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '14px 16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                  <span style={{ fontWeight: 700, fontSize: '0.85rem' }}>RSI<Help text="최근 14일간 오른 힘과 내린 힘의 비율. 30 이하면 너무 많이 팔린 상태(반등 여지), 70 이상이면 너무 많이 산 상태(조정 위험)." /></span>
                  {L.rsi != null && (() => { const g = rsiGrade(L.rsi); return <span style={{ fontSize: '0.7rem', fontWeight: 700, color: g.color, background: g.color + '22', borderRadius: 4, padding: '1px 6px' }}>{g.label}</span>; })()}
                </div>
                <div style={{ fontSize: '1.6rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: L.rsi < 30 ? '#22c55e' : L.rsi > 70 ? '#ef4444' : 'var(--fg-1)' }}>{num(L.rsi)}</div>
                <GaugeBar value={L.rsi} />
                <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)', marginTop: 6 }}>30 이하 과매도 · 70 이상 과매수</div>
              </div>

              <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '14px 16px' }}>
                <div style={{ fontWeight: 700, fontSize: '0.85rem', marginBottom: 8 }}>MACD<Help text="단기 평균과 장기 평균의 간격 변화로 추세 전환을 포착. 히스토그램이 +면 상승 전환, -면 하락 전환 신호." /></div>
                <Row label="MACD 선" value={num(L.macd)} />
                <Row label="시그널 선" value={num(L.macd_sig)} />
                <Row label="히스토그램" value={num(L.macd_hist)}
                  color={L.macd_hist > 0 ? '#22c55e' : L.macd_hist < 0 ? '#ef4444' : 'var(--fg-1)'}
                  hint={L.macd_hist > 0 ? '골든크로스 (상승 신호)' : L.macd_hist < 0 ? '데드크로스 (하락 신호)' : ''} />
              </div>

              <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '14px 16px' }}>
                <div style={{ fontWeight: 700, fontSize: '0.85rem', marginBottom: 8 }}>볼린저밴드<Help text="평소 가격이 움직이는 범위(밴드). 하단에 닿으면 반등, 상단에 닿으면 조정 가능성을 봅니다." /></div>
                <Row label="상단 (저항)" value={L.bb_upper?.toLocaleString('ko')} />
                <Row label="중심선" value={L.vwap?.toLocaleString('ko')} />
                <Row label="하단 (지지)" value={L.bb_lower?.toLocaleString('ko')} />
                <Row label="밴드 내 위치" value={`${num(L.bb_pct, 1)}%`}
                  color={L.bb_pct < 20 ? '#22c55e' : L.bb_pct > 80 ? '#ef4444' : 'var(--fg-1)'}
                  hint={L.bb_pct < 20 ? '바닥권 (반등 가능)' : L.bb_pct > 80 ? '천장권 (조정 가능)' : '중간 구간'} />
              </div>

              <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '14px 16px' }}>
                <div style={{ fontWeight: 700, fontSize: '0.85rem', marginBottom: 8 }}>스토캐스틱<Help text="최근 가격 범위에서 현재가의 위치로 단기 탄력을 측정. %K가 %D 위로 올라서면 단기 상승 신호." /></div>
                <Row label="%K (빠른 선)" value={num(L.stoch_k)} color={L.stoch_k < 20 ? '#22c55e' : L.stoch_k > 80 ? '#ef4444' : 'var(--fg-1)'} />
                <Row label="%D (느린 선)" value={num(L.stoch_d)} />
                {L.stoch_k != null && L.stoch_d != null && (
                  <div style={{ marginTop: 8, fontSize: '0.72rem', color: L.stoch_k > L.stoch_d ? '#22c55e' : '#ef4444' }}>
                    <i className={`bi bi-arrow-${L.stoch_k > L.stoch_d ? 'up' : 'down'} me-1`} />
                    {L.stoch_k > L.stoch_d ? '상승 탄력' : '하락 탄력'}
                  </div>
                )}
              </div>

              <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '14px 16px' }}>
                <div style={{ fontWeight: 700, fontSize: '0.85rem', marginBottom: 8 }}>모멘텀<Help text="기간별 수익률. 오르던 주식이 계속 오르는 관성을 봅니다." /></div>
                <Row label="최근 1주" value={pct(L.mom5)} color={L.mom5 > 0 ? '#22c55e' : L.mom5 < 0 ? '#ef4444' : 'var(--fg-1)'} />
                <Row label="최근 1개월" value={pct(L.mom20)} color={L.mom20 > 0 ? '#22c55e' : L.mom20 < 0 ? '#ef4444' : 'var(--fg-1)'} />
                <Row label="최근 3개월" value={pct(L.mom60)} color={L.mom60 > 0 ? '#22c55e' : L.mom60 < 0 ? '#ef4444' : 'var(--fg-1)'} />
              </div>

              <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '14px 16px' }}>
                <div style={{ fontWeight: 700, fontSize: '0.85rem', marginBottom: 8 }}>이동평균선<Help text="과거 N일 평균 가격. 현재가가 평균선 위면 추세가 살아있다고 봅니다. 200일선은 장기 추세의 기준." /></div>
                <Row label="현재가" value={L.close?.toLocaleString('ko')} />
                <Row label="50일선 대비" value={L.close != null && L.ma50 != null ? pct((L.close / L.ma50 - 1) * 100, 1) : '-'}
                  color={L.close > L.ma50 ? '#22c55e' : '#ef4444'} hint={L.close > L.ma50 ? '중기 추세 위' : '중기 추세 아래'} />
                <Row label="200일선 대비" value={L.close != null && L.ma200 != null ? pct((L.close / L.ma200 - 1) * 100, 1) : '-'}
                  color={L.close > L.ma200 ? '#22c55e' : '#ef4444'} hint={L.close > L.ma200 ? '장기 추세 위 (강세)' : '장기 추세 아래 (약세)'} />
                <Row label="VWAP 이탈" value={`${num(L.vwap_dev, 1)}%`} color={L.vwap_dev > 0 ? '#22c55e' : '#ef4444'}
                  help="거래량 가중 평균가 대비 현재가. +면 평균 매수자보다 비싸게 거래 중." />
              </div>

              <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '14px 16px' }}>
                <div style={{ fontWeight: 700, fontSize: '0.85rem', marginBottom: 8 }}>거래량 · 변동성</div>
                <Row label="거래량 배율" value={`${num(L.vol_ratio)}x`}
                  color={L.vol_ratio > 2 ? '#22c55e' : 'var(--fg-1)'}
                  hint={L.vol_ratio > 2 ? '평소 2배 이상 — 관심 급증' : '평소 20일 평균 대비'} />
                <Row label="하루 변동폭" value={L.atr?.toLocaleString('ko')} hint="평균적으로 하루에 움직이는 금액(원)" help="ATR(14일): 최근 2주간 하루 평균 가격 변동폭" />
                <Row label="변동폭 비율" value={`${num(L.atr_pct)}%`} hint="현재가 대비 하루 변동폭" />
                <Row label="매집 강도" value={num(L.obv_norm)}
                  color={L.obv_norm > 0.5 ? '#22c55e' : L.obv_norm < -0.5 ? '#ef4444' : 'var(--fg-1)'}
                  hint="+면 사 모으는 중, -면 팔아치우는 중" help="OBV: 거래량을 누적해 큰손의 매집/배분을 추정" />
              </div>

              {hurst != null && (
                <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '14px 16px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                    <span style={{ fontWeight: 700, fontSize: '0.85rem' }}>가격 성향<Help text="허스트 지수: 이 종목 가격의 '성격'. 추세형은 가던 방향으로 계속 가고, 회귀형은 평균으로 되돌아오는 경향." /></span>
                    {hl && <span style={{ fontSize: '0.7rem', fontWeight: 700, color: hl.color, background: hl.color + '22', borderRadius: 4, padding: '1px 6px' }}>{hl.label}</span>}
                  </div>
                  <div style={{ fontSize: '1.6rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: hl?.color }}>{hurst.toFixed(3)}</div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--fg-3)', marginTop: 6 }}>{hl?.desc}</div>
                </div>
              )}
            </div>
          </details>
        </>
      )}
    </>
  );
}

// ═══════════════════════════════════════════════════════════════
// 탭 2 — 백테스팅
// ═══════════════════════════════════════════════════════════════
const PRESETS = [
  { key: 'stable',   label: '🛡 안정형', holdDays: 10, stopPct: 3,  targetPct: 6,  desc: '작게 먹고 빨리 자름' },
  { key: 'standard', label: '⚖ 표준',   holdDays: 5,  stopPct: 5,  targetPct: 10, desc: '기본 설정' },
  { key: 'aggro',    label: '🔥 공격형', holdDays: 15, stopPct: 8,  targetPct: 20, desc: '크게 노리고 길게 버팀' },
];

const SAVED_KEY = 'quantBacktests';

function loadSaved() {
  try { return JSON.parse(localStorage.getItem(SAVED_KEY) || '[]'); } catch { return []; }
}

function BacktestTab() {
  const [code, setCode]       = useState('');
  const [holdDays, setHoldDays] = useState(5);
  const [stopPct, setStopPct]  = useState(5);
  const [targetPct, setTargetPct] = useState(10);
  const [capital, setCapital]  = useState(10000000);
  const [mode, setMode]        = useState('composite');
  const [result, setResult]    = useState(null);
  const [loading, setLoading]  = useState(false);
  const [error, setError]      = useState('');
  const [wf, setWf]            = useState(null);    // 워크포워드
  const [wfLoading, setWfLoading] = useState(false);
  const [opt, setOpt]          = useState(null);    // 자동 튜닝
  const [optLoading, setOptLoading] = useState(false);
  const [saved, setSaved]      = useState(loadSaved);

  const MODE_LABEL = {
    composite: '종합 신호', rsi: 'RSI 과매도', macd: 'MACD 전환',
    stoch_rsi: '스토캐스틱', bb: '볼린저 하단',
  };

  const run = async (c) => {
    const target = (c || code || '').trim();
    if (!target) return;
    setLoading(true); setError(''); setResult(null); setWf(null); setOpt(null);
    try {
      const r = await api.post('/api/quant/backtest', {
        code: target, hold_days: holdDays,
        stop_pct: stopPct / 100, target_pct: targetPct / 100,
        capital, signal_params: { mode },
      });
      setResult(r.data);
      // 결과 자동 저장 (최근 12개)
      const mt = r.data?.metrics || {};
      const entry = {
        ts: new Date().toISOString().slice(0, 16).replace('T', ' '),
        code: target, mode, holdDays, stopPct, targetPct,
        total_ret: mt.total_ret, benchmark: r.data?.benchmark_ret,
        win_rate: mt.win_rate, mdd: mt.max_drawdown, sharpe: mt.sharpe, n_trades: mt.n_trades,
      };
      const next = [entry, ...loadSaved()].slice(0, 12);
      localStorage.setItem(SAVED_KEY, JSON.stringify(next));
      setSaved(next);
    } catch (e) { setError(e.response?.data?.error || '백테스팅 실패'); }
    setLoading(false);
  };

  const runWalkForward = async () => {
    if (!code.trim()) return;
    setWfLoading(true); setWf(null);
    try {
      const r = await api.post('/api/quant/walkforward', {
        code: code.trim(), n_splits: 5, hold_days: holdDays,
        stop_pct: stopPct / 100, target_pct: targetPct / 100,
        capital, signal_params: { mode },
      });
      setWf(r.data);
    } catch (e) { setWf({ ok: false, error: e.response?.data?.error || '검증 실패' }); }
    setWfLoading(false);
  };

  const runOptimize = async () => {
    if (!code.trim()) return;
    setOptLoading(true); setOpt(null);
    try {
      const r = await api.post('/api/quant/optimize', {
        code: code.trim(), hold_days: holdDays,
        stop_pct: stopPct / 100, target_pct: targetPct / 100, capital,
      });
      setOpt(r.data);
    } catch (e) { setOpt({ ok: false, error: e.response?.data?.error || '튜닝 실패' }); }
    setOptLoading(false);
  };

  const clearSaved = () => { localStorage.removeItem(SAVED_KEY); setSaved([]); };

  const m = result?.metrics || {};
  const mc = result?.monte_carlo || {};

  // 쉬운 요약 문장
  const finalAmt  = result ? Math.round(capital * (1 + (m.total_ret || 0) / 100)) : null;
  const bhAmt     = result ? Math.round(capital * (1 + (result.benchmark_ret || 0) / 100)) : null;
  const winOf10   = m.win_rate != null ? Math.round(m.win_rate / 10) : null;
  const beats     = result ? (m.total_ret || 0) > (result.benchmark_ret || 0) : null;

  return (
    <>
      <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '18px 20px', marginBottom: 16 }}>
        <div style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--fg-1)', marginBottom: 4 }}>
          <i className="bi bi-clock-history me-2" style={{ color: 'var(--accent)' }} />과거로 시간여행 테스트
        </div>
        <div style={{ fontSize: '0.74rem', color: 'var(--fg-3)', marginBottom: 14 }}>
          "이 규칙대로 과거에 샀다 팔았다 했다면 얼마를 벌었을까?"를 실제 과거 데이터로 시뮬레이션합니다.
        </div>

        {/* 프리셋 */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
          {PRESETS.map(p => {
            const active = holdDays === p.holdDays && stopPct === p.stopPct && targetPct === p.targetPct;
            return (
              <button key={p.key} onClick={() => { setHoldDays(p.holdDays); setStopPct(p.stopPct); setTargetPct(p.targetPct); }}
                title={p.desc}
                style={{ padding: '5px 14px', fontSize: '0.78rem', fontWeight: 700, borderRadius: 14, cursor: 'pointer',
                  border: active ? '2px solid var(--accent)' : '1px solid var(--line-2)',
                  background: active ? 'rgba(99,102,241,0.1)' : 'var(--bg-3)', color: active ? 'var(--accent)' : 'var(--fg-2)' }}>
                {p.label}
              </button>
            );
          })}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))', gap: 10, marginBottom: 14 }}>
          <div style={{ gridColumn: 'span 1' }}>
            <label style={{ fontSize: '0.72rem', color: 'var(--fg-3)', display: 'block', marginBottom: 4 }}>종목</label>
            <StockSearch onPick={setCode} onSubmit={run} loading={loading} btnLabel="실행" />
          </div>
          <div>
            <label style={{ fontSize: '0.72rem', color: 'var(--fg-3)', display: 'block', marginBottom: 4 }}>최대 보유일<Help text="신호로 산 뒤 이 일수가 지나면 무조건 판다" /></label>
            <input className="form-control form-control-sm" type="number" value={holdDays} onChange={e => setHoldDays(+e.target.value)} min={1} max={60} />
          </div>
          <div>
            <label style={{ fontSize: '0.72rem', color: 'var(--fg-3)', display: 'block', marginBottom: 4 }}>손절선 (%)<Help text="이만큼 떨어지면 손해 보고라도 판다" /></label>
            <input className="form-control form-control-sm" type="number" value={stopPct} onChange={e => setStopPct(+e.target.value)} min={1} max={30} step={0.5} />
          </div>
          <div>
            <label style={{ fontSize: '0.72rem', color: 'var(--fg-3)', display: 'block', marginBottom: 4 }}>익절선 (%)<Help text="이만큼 오르면 이익을 챙기고 판다" /></label>
            <input className="form-control form-control-sm" type="number" value={targetPct} onChange={e => setTargetPct(+e.target.value)} min={1} max={50} step={0.5} />
          </div>
          <div>
            <label style={{ fontSize: '0.72rem', color: 'var(--fg-3)', display: 'block', marginBottom: 4 }}>투자 원금 (원)</label>
            <input className="form-control form-control-sm" type="number" value={capital} onChange={e => setCapital(+e.target.value)} step={1000000} />
          </div>
          <div>
            <label style={{ fontSize: '0.72rem', color: 'var(--fg-3)', display: 'block', marginBottom: 4 }}>언제 살까 (진입 규칙)</label>
            <select className="form-select form-select-sm" value={mode} onChange={e => setMode(e.target.value)}>
              <option value="composite">종합 신호가 매수일 때</option>
              <option value="rsi">많이 떨어졌을 때 (RSI 과매도)</option>
              <option value="macd">상승 전환됐을 때 (MACD)</option>
              <option value="stoch_rsi">단기 탄력 생겼을 때 (스토캐스틱)</option>
              <option value="bb">바닥권에 닿았을 때 (볼린저 하단)</option>
            </select>
          </div>
        </div>
        {error && <div style={{ fontSize: '0.82rem', color: 'var(--down)' }}><i className="bi bi-exclamation-triangle me-1" />{error}</div>}
      </div>

      {result && (
        <>
          {/* ── 쉬운 결론 ── */}
          <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderLeft: `4px solid ${beats ? '#22c55e' : '#f59e0b'}`, borderRadius: 'var(--r-3)', padding: '16px 20px', marginBottom: 16 }}>
            <div style={{ fontWeight: 800, fontSize: '0.95rem', color: 'var(--fg-1)', marginBottom: 8 }}>
              <i className="bi bi-chat-square-text me-2" style={{ color: beats ? '#22c55e' : '#f59e0b' }} />
              {krw(capital)}으로 시작했다면 → <span style={{ color: m.total_ret > 0 ? '#22c55e' : '#ef4444', fontFamily: 'var(--font-mono)' }}>{krw(finalAmt)}</span>
            </div>
            <div style={{ display: 'grid', gap: 4, fontSize: '0.82rem', color: 'var(--fg-2)' }}>
              <div>· 같은 기간 <b>그냥 사서 보유</b>했다면: <span style={{ fontFamily: 'var(--font-mono)' }}>{krw(bhAmt)}</span> ({pct(result.benchmark_ret)})
                — 이 전략이 {beats ? <b style={{ color: '#22c55e' }}>더 좋았습니다</b> : <b style={{ color: '#f59e0b' }}>더 나빴습니다</b>}</div>
              <div>· 총 <b>{m.n_trades}번</b> 사고팔았고, 10번 중 <b>{winOf10}번</b>꼴로 수익이 났습니다 (승률 {num(m.win_rate, 1)}%)</div>
              <div>· 가장 힘들었던 순간엔 고점 대비 <b style={{ color: '#ef4444' }}>{num(Math.abs(m.max_drawdown), 1)}%</b>까지 평가액이 줄었습니다 — 이걸 버틸 수 있어야 이 전략을 쓸 수 있습니다</div>
              {mc.ruin_prob != null && <div>· 운이 나쁘게 흘러갔을 경우 원금의 절반을 잃을 확률: <b style={{ color: mc.ruin_prob > 0.1 ? '#ef4444' : '#22c55e' }}>{(mc.ruin_prob * 100).toFixed(1)}%</b></div>}
            </div>
            <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)', marginTop: 10 }}>
              ⚠ 과거 성과는 미래 수익을 보장하지 않습니다. 수수료·세금·호가 미끄러짐은 단순화되어 실제와 다를 수 있습니다.
            </div>
          </div>

          {/* 자산곡선 */}
          <EquityChart equity={result.equity} benchmarkRet={result.benchmark_ret} />

          {/* ── 추가 검증 도구 ── */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
            <button className="btn btn-outline-primary btn-sm" onClick={runWalkForward} disabled={wfLoading}>
              {wfLoading ? <><span className="spinner-border spinner-border-sm me-1" />검증 중...</> : <><i className="bi bi-check2-square me-1" />이 결과, 우연 아닐까? (구간 검증)</>}
            </button>
            <button className="btn btn-outline-primary btn-sm" onClick={runOptimize} disabled={optLoading}>
              {optLoading ? <><span className="spinner-border spinner-border-sm me-1" />탐색 중...</> : <><i className="bi bi-magic me-1" />최적 진입 기준 찾기</>}
            </button>
          </div>

          {/* 워크포워드 결과 */}
          {wf && (wf.ok === false ? (
            <div style={{ fontSize: '0.8rem', color: 'var(--down)', marginBottom: 16 }}>{wf.error}</div>
          ) : (
            <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)',
                          borderLeft: `4px solid ${wf.summary.consistency >= 80 ? '#22c55e' : wf.summary.consistency >= 60 ? '#f59e0b' : '#ef4444'}`,
                          borderRadius: 'var(--r-3)', padding: '16px 20px', marginBottom: 16 }}>
              <div style={{ fontWeight: 800, fontSize: '0.9rem', marginBottom: 6 }}>
                기간을 {wf.summary.total}조각으로 나눠 각각 따로 테스트한 결과:
                <span style={{ color: wf.summary.consistency >= 80 ? '#22c55e' : wf.summary.consistency >= 60 ? '#f59e0b' : '#ef4444', marginLeft: 8 }}>
                  {wf.summary.profitable}/{wf.summary.total} 구간에서 수익
                  {wf.summary.consistency >= 80 ? ' — 꾸준합니다, 우연이 아닐 가능성이 높습니다'
                    : wf.summary.consistency >= 60 ? ' — 절반 이상 통과, 그럭저럭 일관적'
                    : ' — 들쭉날쭉합니다. 특정 시기 운이었을 수 있으니 주의'}
                </span>
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ borderCollapse: 'collapse', fontSize: '0.76rem', width: '100%' }}>
                  <thead><tr style={{ background: 'var(--bg-3)' }}>
                    {['구간', '기간', '매매', '수익률', '그냥 보유', '승률'].map(h => (
                      <th key={h} style={{ padding: '6px 10px', fontWeight: 600, color: 'var(--fg-2)', textAlign: 'left', whiteSpace: 'nowrap' }}>{h}</th>))}
                  </tr></thead>
                  <tbody>
                    {wf.periods.map(p => (
                      <tr key={p.period} style={{ borderBottom: '1px solid var(--line-1)' }}>
                        <td style={{ padding: '5px 10px', fontFamily: 'var(--font-mono)' }}>{p.period}</td>
                        <td style={{ padding: '5px 10px', fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--fg-3)' }}>{p.start} ~ {p.end}</td>
                        <td style={{ padding: '5px 10px', fontFamily: 'var(--font-mono)' }}>{p.n_trades}회</td>
                        <td style={{ padding: '5px 10px', fontFamily: 'var(--font-mono)', fontWeight: 700, color: p.total_ret > 0 ? '#22c55e' : '#ef4444' }}>{pct(p.total_ret)}</td>
                        <td style={{ padding: '5px 10px', fontFamily: 'var(--font-mono)', color: 'var(--fg-3)' }}>{pct(p.benchmark)}</td>
                        <td style={{ padding: '5px 10px', fontFamily: 'var(--font-mono)' }}>{num(p.win_rate, 0)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}

          {/* 자동 튜닝 결과 */}
          {opt && (opt.ok === false ? (
            <div style={{ fontSize: '0.8rem', color: 'var(--down)', marginBottom: 16 }}>{opt.error}</div>
          ) : (
            <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '16px 20px', marginBottom: 16 }}>
              <div style={{ fontWeight: 800, fontSize: '0.9rem', marginBottom: 4 }}>
                <i className="bi bi-magic me-2" style={{ color: 'var(--accent)' }} />
                진입 기준 자동 탐색 결과: 최적 임계값 <span style={{ color: 'var(--accent)', fontFamily: 'var(--font-mono)' }}>{opt.best?.threshold}</span>
              </div>
              <div style={{ fontSize: '0.72rem', color: '#f59e0b', marginBottom: 10 }}>
                ⚠ 과거에 가장 좋았던 설정일 뿐, 미래에도 최적이라는 보장은 없습니다 (과최적화 주의). 구간 검증과 함께 보세요.
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ borderCollapse: 'collapse', fontSize: '0.76rem', width: '100%' }}>
                  <thead><tr style={{ background: 'var(--bg-3)' }}>
                    {['진입 임계값', '매매', '수익률', '승률', '위험대비수익', '최대하락'].map(h => (
                      <th key={h} style={{ padding: '6px 10px', fontWeight: 600, color: 'var(--fg-2)', textAlign: 'left', whiteSpace: 'nowrap' }}>{h}</th>))}
                  </tr></thead>
                  <tbody>
                    {(opt.grid || []).map(g => (
                      <tr key={g.threshold} style={{ borderBottom: '1px solid var(--line-1)',
                          background: g.threshold === opt.best?.threshold ? 'rgba(99,102,241,0.08)' : 'transparent' }}>
                        <td style={{ padding: '5px 10px', fontFamily: 'var(--font-mono)', fontWeight: g.threshold === opt.best?.threshold ? 800 : 400 }}>
                          {g.threshold}{g.threshold === opt.best?.threshold && ' ⭐'}
                        </td>
                        <td style={{ padding: '5px 10px', fontFamily: 'var(--font-mono)' }}>{g.n_trades}회</td>
                        <td style={{ padding: '5px 10px', fontFamily: 'var(--font-mono)', color: g.total_ret > 0 ? '#22c55e' : '#ef4444' }}>{pct(g.total_ret)}</td>
                        <td style={{ padding: '5px 10px', fontFamily: 'var(--font-mono)' }}>{num(g.win_rate, 0)}%</td>
                        <td style={{ padding: '5px 10px', fontFamily: 'var(--font-mono)' }}>{num(g.sharpe, 2)}</td>
                        <td style={{ padding: '5px 10px', fontFamily: 'var(--font-mono)', color: '#ef4444' }}>{pct(g.max_dd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}

          {/* 핵심 성과 지표 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 10, marginBottom: 16 }}>
            <StatCard icon="bi-graph-up-arrow" label="총 수익률" value={pct(m.total_ret)} color={m.total_ret > 0 ? '#22c55e' : '#ef4444'} sub={`그냥 보유 시 ${pct(m.benchmark_ret)}`} />
            <StatCard icon="bi-speedometer2" label="연평균 수익" value={pct(m.cagr)} color={m.cagr > 0 ? '#22c55e' : '#ef4444'} help="1년 단위로 환산한 평균 수익률 (CAGR)" />
            <StatCard icon="bi-shield-exclamation" label="최대 하락폭" value={pct(m.max_drawdown)} color="#ef4444" sub="고점에서 최악일 때까지" help="MDD: 자산이 고점 대비 가장 많이 빠졌던 비율. 멘탈이 버텨야 하는 한계치." />
            <StatCard icon="bi-trophy" label="위험 대비 수익" value={num(m.sharpe, 2)} color={m.sharpe > 1 ? '#22c55e' : m.sharpe > 0 ? '#f59e0b' : '#ef4444'} sub="1 이상이면 양호" help="샤프 비율: 출렁임(위험) 1단위당 얻은 수익. 높을수록 효율적." />
            <StatCard icon="bi-percent" label="승률" value={`${num(m.win_rate, 1)}%`} color={m.win_rate > 50 ? '#22c55e' : '#f59e0b'} sub={`총 ${m.n_trades}회 매매`} />
            <StatCard icon="bi-calculator" label="손익비" value={num(m.profit_factor, 2)} color={m.profit_factor > 1.5 ? '#22c55e' : '#f59e0b'} sub="1.5 이상이면 양호" help="번 돈 합계 ÷ 잃은 돈 합계. 2면 잃은 돈의 2배를 벌었다는 뜻." />
          </div>

          {/* 세부 지표 (접이식) */}
          <details style={{ marginBottom: 16 }}>
            <summary style={{ cursor: 'pointer', fontSize: '0.85rem', fontWeight: 700, color: 'var(--fg-2)', padding: '8px 4px' }}>
              <i className="bi bi-table me-2" style={{ color: 'var(--accent)' }} />상세 통계 · 매매 내역 보기
            </summary>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 10, marginBottom: 16 }}>
              <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '16px 18px' }}>
                <div style={{ fontWeight: 700, fontSize: '0.85rem', marginBottom: 10 }}>매매 통계</div>
                <Row label="이긴 거래 평균" value={pct(m.avg_win)} color="#22c55e" />
                <Row label="진 거래 평균" value={pct(m.avg_loss)} color="#ef4444" />
                <Row label="1회당 기대 수익" value={pct(m.expectancy)} color={m.expectancy > 0 ? '#22c55e' : '#ef4444'} hint="한 번 매매할 때마다 평균적으로 이만큼" />
                <Row label="하락 변동성 효율" value={num(m.sortino, 2)} help="소르티노 비율: 떨어질 때의 출렁임만 위험으로 계산한 효율" />
                <Row label="수익/최대하락 비율" value={num(m.calmar, 2)} help="칼마 비율: 연수익을 최대 하락폭으로 나눈 값" />
                <Row label="최악 5% 하루 손실" value={pct(m.var_95)} color="#ef4444" help="VaR 95%: 100일 중 최악인 5일의 평균적인 하루 손실" />
              </div>
              {mc.p50 != null && (
                <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '16px 18px' }}>
                  <div style={{ fontWeight: 700, fontSize: '0.85rem', marginBottom: 4 }}>운 빼고 보기<Help text="몬테카를로: 같은 매매들을 순서만 1,000번 섞어서, 운이 좋았던/나빴던 경우의 결과 범위를 봅니다." /></div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--fg-3)', marginBottom: 10 }}>매매 순서를 1,000번 섞은 결과 분포</div>
                  <Row label="보통의 경우" value={pct(mc.p50)} color={mc.p50 > 0 ? '#22c55e' : '#ef4444'} />
                  <Row label="운 좋은 경우 (상위 25%)" value={pct(mc.p75)} color="#22c55e" />
                  <Row label="운 나쁜 경우 (하위 25%)" value={pct(mc.p25)} color="#ef4444" />
                  <Row label="최악의 경우 (하위 5%)" value={pct(mc.p5)} color="#ef4444" />
                  <Row label="원금 반토막 확률" value={mc.ruin_prob != null ? `${(mc.ruin_prob * 100).toFixed(1)}%` : '-'} color={mc.ruin_prob > 0.1 ? '#ef4444' : '#22c55e'} />
                </div>
              )}
            </div>

            {result.trades?.length > 0 && (
              <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'hidden' }}>
                <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--line-1)', fontWeight: 700, fontSize: '0.85rem' }}>
                  매매 내역 <span style={{ fontWeight: 400, color: 'var(--fg-3)', fontSize: '0.75rem' }}>최근 20건</span>
                </div>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
                    <thead>
                      <tr style={{ background: 'var(--bg-3)' }}>
                        {['산 날', '판 날', '보유', '산 가격', '판 가격', '수익률', '판 이유'].map(h => (
                          <th key={h} style={{ padding: '7px 12px', fontWeight: 600, color: 'var(--fg-2)', textAlign: 'left', whiteSpace: 'nowrap' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.trades.slice(-20).reverse().map((t, i) => (
                        <tr key={i} style={{ borderBottom: '1px solid var(--line-1)' }}>
                          <td style={{ padding: '6px 12px', fontFamily: 'var(--font-mono)' }}>{t.entry_date}</td>
                          <td style={{ padding: '6px 12px', fontFamily: 'var(--font-mono)' }}>{t.exit_date}</td>
                          <td style={{ padding: '6px 12px', fontFamily: 'var(--font-mono)', color: 'var(--fg-3)' }}>{t.days_held}일</td>
                          <td style={{ padding: '6px 12px', fontFamily: 'var(--font-mono)' }}>{t.entry_price?.toLocaleString('ko')}</td>
                          <td style={{ padding: '6px 12px', fontFamily: 'var(--font-mono)' }}>{t.exit_price?.toLocaleString('ko')}</td>
                          <td style={{ padding: '6px 12px', fontFamily: 'var(--font-mono)', fontWeight: 700, color: t.return_pct > 0 ? '#22c55e' : '#ef4444' }}>{pct(t.return_pct)}</td>
                          <td style={{ padding: '6px 12px', fontSize: '0.7rem', color: 'var(--fg-3)' }}>
                            {{ stop: '손절선 도달', target: '익절선 도달', timeout: '보유기간 만료', force: '기간 종료' }[t.exit_reason] || t.exit_reason}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </details>
        </>
      )}

      {/* ── 지난 테스트 비교 ── */}
      {saved.length > 0 && (
        <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'hidden', marginTop: 8 }}>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--line-1)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontWeight: 700, fontSize: '0.85rem' }}>
              <i className="bi bi-collection me-2" style={{ color: 'var(--accent)' }} />지난 테스트 비교 <span style={{ fontWeight: 400, color: 'var(--fg-3)', fontSize: '0.72rem' }}>(자동 저장, 최근 12개)</span>
            </span>
            <button onClick={clearSaved} style={{ background: 'none', border: 'none', color: 'var(--fg-3)', fontSize: '0.72rem', cursor: 'pointer' }}>
              <i className="bi bi-trash me-1" />전체 삭제
            </button>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.76rem' }}>
              <thead><tr style={{ background: 'var(--bg-3)' }}>
                {['시각', '종목', '전략', '보유/손절/익절', '수익률', '그냥 보유', '승률', '최대하락', '매매'].map(h => (
                  <th key={h} style={{ padding: '7px 10px', fontWeight: 600, color: 'var(--fg-2)', textAlign: 'left', whiteSpace: 'nowrap' }}>{h}</th>))}
              </tr></thead>
              <tbody>
                {saved.map((s, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid var(--line-1)' }}>
                    <td style={{ padding: '6px 10px', fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--fg-3)' }}>{s.ts}</td>
                    <td style={{ padding: '6px 10px', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{s.code}</td>
                    <td style={{ padding: '6px 10px', fontSize: '0.72rem' }}>{MODE_LABEL[s.mode] || s.mode}</td>
                    <td style={{ padding: '6px 10px', fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--fg-3)' }}>{s.holdDays}일/{s.stopPct}%/{s.targetPct}%</td>
                    <td style={{ padding: '6px 10px', fontFamily: 'var(--font-mono)', fontWeight: 700, color: s.total_ret > 0 ? '#22c55e' : '#ef4444' }}>{pct(s.total_ret)}</td>
                    <td style={{ padding: '6px 10px', fontFamily: 'var(--font-mono)', color: 'var(--fg-3)' }}>{pct(s.benchmark)}</td>
                    <td style={{ padding: '6px 10px', fontFamily: 'var(--font-mono)' }}>{num(s.win_rate, 0)}%</td>
                    <td style={{ padding: '6px 10px', fontFamily: 'var(--font-mono)', color: '#ef4444' }}>{pct(s.mdd)}</td>
                    <td style={{ padding: '6px 10px', fontFamily: 'var(--font-mono)', color: 'var(--fg-3)' }}>{s.n_trades}회</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

// ═══════════════════════════════════════════════════════════════
// 탭 3 — 시장 스캐너
// ═══════════════════════════════════════════════════════════════
function ScannerTab({ onPickStock }) {
  const [result, setResult]     = useState(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState('');
  const [topN, setTopN]         = useState(20);
  const [view, setView]         = useState('buy');
  const [fromCache, setFromCache] = useState(false);
  const [starred, setStarred]   = useState({});   // code → true (이번 세션 추가분)

  // 페이지 진입 시 캐시 즉시 표시 (장마감 후 자동 스캔 결과)
  useEffect(() => {
    api.get('/api/quant/scanner/cached', { params: { top_n: topN } })
      .then(r => { if (r.data?.ok) { setResult(r.data); setFromCache(true); } })
      .catch(() => {});
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const run = async () => {
    setLoading(true); setError('');
    try {
      const r = await api.post('/api/quant/scanner', { top_n: topN });
      setResult(r.data); setFromCache(false);
    } catch (e) { setError(e.response?.data?.error || '스캔 실패'); }
    setLoading(false);
  };

  const star = async (s) => {
    try {
      await addToWatchlist(s.code, s.name);
      setStarred(p => ({ ...p, [s.code]: true }));
    } catch { /* 무시 */ }
  };

  const ms = result?.market_stats || {};
  const list = view === 'buy' ? (result?.buy || []) : (result?.sell || []);

  return (
    <>
      <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '16px 20px', marginBottom: 16 }}>
        <div style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--fg-1)', marginBottom: 4 }}>
          <i className="bi bi-radar me-2" style={{ color: 'var(--accent)' }} />시장 전체에서 신호 잡힌 종목 찾기
        </div>
        <div style={{ fontSize: '0.74rem', color: 'var(--fg-3)', marginBottom: 12 }}>
          시장의 주요 종목 전체에 종목 분석과 같은 계산을 돌려서, 매수/매도 신호가 강한 순서로 추려줍니다.
          <b> 종목 이름을 클릭하면 바로 상세 분석으로 이동합니다.</b>
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <label style={{ fontSize: '0.72rem', color: 'var(--fg-3)', display: 'block', marginBottom: 4 }}>표시 종목 수</label>
            <select className="form-select form-select-sm" value={topN} onChange={e => setTopN(+e.target.value)} style={{ width: 100 }}>
              {[10, 20, 30, 50].map(n => <option key={n} value={n}>{n}개</option>)}
            </select>
          </div>
          <button className="btn btn-primary btn-sm" onClick={run} disabled={loading}>
            {loading ? <><span className="spinner-border spinner-border-sm me-1" />스캔 중 (수 분 소요)...</> : <><i className="bi bi-radar me-1" />전체 시장 스캔</>}
          </button>
          {result && <div style={{ fontSize: '0.75rem', color: 'var(--fg-3)' }}>
            <i className="bi bi-clock me-1" />{result.scanned_at} 기준 · 총 {result.total}종목
            {fromCache && <span style={{ marginLeft: 6, fontSize: '0.66rem', padding: '2px 7px', borderRadius: 8, background: 'rgba(34,197,94,0.12)', color: '#22c55e', fontWeight: 700 }}>
              자동 스캔 결과 — 기다림 없이 표시됨</span>}
          </div>}
          {error && <div style={{ fontSize: '0.8rem', color: 'var(--down)' }}><i className="bi bi-exclamation-triangle me-1" />{error}</div>}
        </div>
      </div>

      {result && (
        <>
          {/* 시장 체온계 */}
          <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '14px 18px', marginBottom: 14 }}>
            <div style={{ fontWeight: 700, fontSize: '0.85rem', marginBottom: 4 }}>
              <i className="bi bi-thermometer-half me-2" style={{ color: 'var(--accent)' }} />시장 체온계
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--fg-3)', marginBottom: 12 }}>
              {ms.bull_ratio > 60 ? '전반적으로 따뜻합니다 — 장기 추세 위에 있는 종목이 다수.'
                : ms.bull_ratio > 40 ? '미지근합니다 — 강세와 약세가 섞여 있는 시장.'
                : '차갑습니다 — 다수 종목이 장기 추세 아래. 보수적 접근 권장.'}
            </div>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              {[
                { label: '장기 추세 위 종목', value: `${ms.bull_ratio?.toFixed(1)}%`, hint: `${ms.n_above_ma200}개 / 200일선 기준`, color: ms.bull_ratio > 50 ? '#22c55e' : '#ef4444' },
                { label: '시장 평균 신호', value: num(ms.avg_composite, 3), hint: '+면 매수 우위', color: ms.avg_composite > 0 ? '#22c55e' : '#ef4444' },
                { label: '상승 전환 (MACD)', value: `${ms.n_macd_cross}개`, color: '#3b82f6' },
                { label: '단기 탄력 발생', value: `${ms.n_stoch_cross}개`, color: '#8b5cf6' },
                { label: '폭발 대기 (스퀴즈)', value: `${ms.n_bb_squeeze}개`, hint: '조용하다 크게 움직이기 직전', color: '#f59e0b' },
                { label: '거래량 급증', value: `${ms.n_vol_surge}개`, hint: '평소 2배 이상', color: '#22c55e' },
              ].map(({ label, value, hint, color }) => (
                <div key={label} style={{ flex: '0 0 auto' }}>
                  <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)' }}>{label}</div>
                  <div style={{ fontSize: '1.1rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color }}>{value}</div>
                  {hint && <div style={{ fontSize: '0.65rem', color: 'var(--fg-3)' }}>{hint}</div>}
                </div>
              ))}
            </div>
          </div>

          {/* 매수/매도 탭 */}
          <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
            <button onClick={() => setView('buy')} style={{ padding: '6px 16px', borderRadius: 'var(--r-2)', border: view === 'buy' ? '2px solid #22c55e' : '2px solid var(--line-1)', background: view === 'buy' ? 'rgba(34,197,94,0.1)' : 'var(--bg-2)', color: view === 'buy' ? '#22c55e' : 'var(--fg-2)', fontWeight: 700, cursor: 'pointer', fontSize: '0.82rem' }}>
              <i className="bi bi-arrow-up-circle me-1" />매수 신호 상위 {result.buy?.length}개
            </button>
            <button onClick={() => setView('sell')} style={{ padding: '6px 16px', borderRadius: 'var(--r-2)', border: view === 'sell' ? '2px solid #ef4444' : '2px solid var(--line-1)', background: view === 'sell' ? 'rgba(239,68,68,0.1)' : 'var(--bg-2)', color: view === 'sell' ? '#ef4444' : 'var(--fg-2)', fontWeight: 700, cursor: 'pointer', fontSize: '0.82rem' }}>
              <i className="bi bi-arrow-down-circle me-1" />매도 신호 상위 {result.sell?.length}개
            </button>
          </div>

          {/* 종목 테이블 */}
          <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'hidden' }}>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
                <thead>
                  <tr style={{ background: 'var(--bg-3)' }}>
                    {['', '순위', '종목명', '현재가', '신호 강도', 'RSI', '밴드 위치', '1개월', '거래량', '잡힌 패턴'].map((h, hi) => (
                      <th key={hi} style={{ padding: '8px 10px', fontWeight: 600, color: 'var(--fg-2)', textAlign: 'left', whiteSpace: 'nowrap', fontSize: '0.72rem' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {list.map((s, i) => (
                    <tr key={s.code} style={{ borderBottom: '1px solid var(--line-1)' }}>
                      <td style={{ padding: '7px 4px 7px 10px', textAlign: 'center' }}>
                        <button onClick={() => star(s)} title={starred[s.code] ? '관심종목에 추가됨' : '관심종목 추가 (공시 감시 자동 시작)'}
                          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0,
                                   color: starred[s.code] ? '#f59e0b' : 'var(--fg-3)', fontSize: '0.9rem' }}>
                          <i className={`bi bi-star${starred[s.code] ? '-fill' : ''}`} />
                        </button>
                      </td>
                      <td style={{ padding: '7px 10px', fontFamily: 'var(--font-mono)', color: 'var(--fg-3)', textAlign: 'center' }}>{i + 1}</td>
                      <td style={{ padding: '7px 10px', whiteSpace: 'nowrap' }}>
                        <button onClick={() => onPickStock(s.code)}
                          title="클릭하면 종목 분석 탭에서 상세 분석"
                          style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontWeight: 700, color: 'var(--accent)', textDecoration: 'underline', textUnderlineOffset: 3 }}>
                          {s.name}
                        </button>
                        <span style={{ fontSize: '0.68rem', color: 'var(--fg-3)', marginLeft: 6, fontFamily: 'var(--font-mono)' }}>{s.code}</span>
                      </td>
                      <td style={{ padding: '7px 10px', fontFamily: 'var(--font-mono)' }}>{s.close?.toLocaleString('ko')}</td>
                      <td style={{ padding: '7px 10px' }}>
                        {(() => { const g = compositeGrade(s.composite ?? 0); return (
                          <span style={{ fontSize: '0.7rem', fontWeight: 700, color: g.color, background: g.color + '22', borderRadius: 4, padding: '2px 7px' }}>
                            {g.label} {num(s.composite, 2)}
                          </span>); })()}
                      </td>
                      <td style={{ padding: '7px 10px', fontFamily: 'var(--font-mono)', color: s.rsi < 30 ? '#22c55e' : s.rsi > 70 ? '#ef4444' : 'var(--fg-2)' }}>{num(s.rsi, 0)}</td>
                      <td style={{ padding: '7px 10px', fontFamily: 'var(--font-mono)', color: s.bb_pct < 20 ? '#22c55e' : s.bb_pct > 80 ? '#ef4444' : 'var(--fg-2)' }}>{num(s.bb_pct, 0)}%</td>
                      <td style={{ padding: '7px 10px', fontFamily: 'var(--font-mono)', color: s.mom20 > 0 ? '#22c55e' : '#ef4444' }}>{pct(s.mom20, 1)}</td>
                      <td style={{ padding: '7px 10px', fontFamily: 'var(--font-mono)', color: s.vol_ratio > 2 ? '#22c55e' : 'var(--fg-2)' }}>{num(s.vol_ratio, 1)}x</td>
                      <td style={{ padding: '7px 10px' }}>
                        <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
                          {s.macd_cross  && <span title="MACD 골든크로스 — 상승 전환 신호" style={{ fontSize: '0.62rem', background: 'rgba(34,197,94,0.15)',  color: '#22c55e', borderRadius: 3, padding: '1px 4px', cursor: 'help' }}>상승전환</span>}
                          {s.stoch_cross && <span title="스토캐스틱 골든크로스 — 단기 탄력 발생" style={{ fontSize: '0.62rem', background: 'rgba(59,130,246,0.15)', color: '#3b82f6', borderRadius: 3, padding: '1px 4px', cursor: 'help' }}>탄력</span>}
                          {s.bb_squeeze  && <span title="볼린저밴드 스퀴즈 — 변동성 수축, 곧 크게 움직일 수 있음" style={{ fontSize: '0.62rem', background: 'rgba(245,158,11,0.15)', color: '#f59e0b', borderRadius: 3, padding: '1px 4px', cursor: 'help' }}>폭발대기</span>}
                          {s.vol_surge   && <span title="거래량 평소 2배 이상" style={{ fontSize: '0.62rem', background: 'rgba(34,197,94,0.15)',  color: '#22c55e', borderRadius: 3, padding: '1px 4px', cursor: 'help' }}>거래량↑</span>}
                          {s.above_ma200 && <span title="200일 이동평균선 위 — 장기 추세 양호" style={{ fontSize: '0.62rem', background: 'rgba(99,102,241,0.15)', color: '#6366f1', borderRadius: 3, padding: '1px 4px', cursor: 'help' }}>장기추세↑</span>}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {!list.length && <tr><td colSpan={10} style={{ textAlign: 'center', padding: '40px', color: 'var(--fg-3)' }}>신호 포착 종목 없음</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </>
  );
}

// ═══════════════════════════════════════════════════════════════
// 용어사전
// ═══════════════════════════════════════════════════════════════
const GLOSSARY = [
  ['종합 신호',   'RSI·MACD 등 8개 지표를 하나의 점수(-1~+1)로 합친 값. +는 매수 우위, -는 매도 우위.'],
  ['RSI',        '최근 14일간 오른 날과 내린 날의 힘 비율 (0~100). 30 이하 = 너무 팔림, 70 이상 = 너무 사들임.'],
  ['MACD',       '단기 평균과 장기 평균의 간격. 간격이 +로 바뀌면(골든크로스) 상승 전환 신호.'],
  ['볼린저밴드',  '평소 가격이 움직이는 범위. 하단에 닿으면 반등, 상단에 닿으면 조정을 의심.'],
  ['스토캐스틱',  '최근 가격 범위에서 현재가가 어디쯤인지로 단기 탄력을 측정.'],
  ['이동평균선',  '과거 N일 평균 가격. 200일선 위면 장기 추세가 살아있다고 봄.'],
  ['백테스팅',    '"이 규칙으로 과거에 매매했다면?"을 실제 과거 데이터로 시뮬레이션하는 것.'],
  ['승률',        '전체 매매 중 수익으로 끝난 비율. 단, 승률이 높아도 한 번에 크게 잃으면 손해.'],
  ['손익비',      '번 돈 합계 ÷ 잃은 돈 합계. 1.5 이상이면 잃을 때보다 벌 때가 충분히 큼.'],
  ['최대 하락폭 (MDD)', '자산이 고점 대비 가장 많이 빠졌던 비율. 이걸 멘탈이 버틸 수 있는지가 핵심.'],
  ['샤프 비율',   '출렁임(위험) 1단위당 수익. 1 이상이면 위험 대비 효율이 양호.'],
  ['몬테카를로',  '매매 순서를 수백 번 섞어 "운이 좋았던 건 아닌지"를 검증하는 방법.'],
  ['허스트 지수', '가격의 성격. 0.5보다 크면 가던 방향으로 계속(추세형), 작으면 평균으로 회귀(반등형).'],
];

// ═══════════════════════════════════════════════════════════════
// 메인
// ═══════════════════════════════════════════════════════════════
const TABS = [
  { key: 'analyze',  label: '종목 분석',   icon: 'bi-search',      desc: '이 종목, 지금 사도 될까?' },
  { key: 'backtest', label: '전략 테스트', icon: 'bi-clock-history', desc: '과거였다면 얼마 벌었을까?' },
  { key: 'scanner',  label: '시장 스캐너', icon: 'bi-radar',       desc: '신호 잡힌 종목 한눈에' },
];

export default function Quant() {
  const [tab, setTab] = useState('analyze');
  const [jumpCode, setJumpCode] = useState(null);   // 스캐너 → 분석 연결

  const pickFromScanner = code => {
    setJumpCode(code);
    setTab('analyze');
  };

  return (
    <StockLayout title="퀀트 트레이딩">
      {/* 탭 */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 20, flexWrap: 'wrap' }}>
        {TABS.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '9px 18px', borderRadius: 'var(--r-3)', border: tab === t.key ? '2px solid var(--accent)' : '2px solid var(--line-1)', background: tab === t.key ? 'rgba(99,102,241,0.08)' : 'var(--bg-2)', cursor: 'pointer', textAlign: 'left' }}>
            <i className={`bi ${t.icon}`} style={{ fontSize: '1rem', color: tab === t.key ? 'var(--accent)' : 'var(--fg-3)' }} />
            <div>
              <div style={{ fontSize: '0.85rem', fontWeight: tab === t.key ? 700 : 600, color: tab === t.key ? 'var(--accent)' : 'var(--fg-2)' }}>{t.label}</div>
              <div style={{ fontSize: '0.66rem', color: 'var(--fg-3)' }}>{t.desc}</div>
            </div>
          </button>
        ))}
      </div>

      {tab === 'analyze' && <AnalyzeTab initCode={jumpCode} onAnalyzed={() => setJumpCode(null)} />}
      {tab === 'backtest' && <BacktestTab />}
      {tab === 'scanner' && <ScannerTab onPickStock={pickFromScanner} />}

      {/* 용어사전 */}
      <details style={{ marginTop: 24 }}>
        <summary style={{ cursor: 'pointer', fontSize: '0.82rem', fontWeight: 700, color: 'var(--fg-3)', padding: '8px 4px' }}>
          <i className="bi bi-book me-2" />용어가 어렵다면 — 쉬운 용어사전
        </summary>
        <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '14px 18px', marginTop: 8, display: 'grid', gap: 8, gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))' }}>
          {GLOSSARY.map(([term, def]) => (
            <div key={term} style={{ fontSize: '0.78rem', lineHeight: 1.5 }}>
              <b style={{ color: 'var(--fg-1)' }}>{term}</b>
              <span style={{ color: 'var(--fg-3)' }}> — {def}</span>
            </div>
          ))}
        </div>
      </details>
    </StockLayout>
  );
}
