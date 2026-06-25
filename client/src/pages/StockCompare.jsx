import React, { useState, useRef, useEffect } from 'react';
import {
  Chart as ChartJS,
  CategoryScale, LinearScale, PointElement, LineElement,
  Title, Tooltip, Legend,
} from 'chart.js';
import { Line } from 'react-chartjs-2';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend);

const PALETTE = ['#6366f1', '#f59e0b', '#10b981'];

/* ── 자동완성 입력 ── */
function StockInput({ label, value, onChange }) {
  const [sugg, setSugg] = useState([]);
  const timer = useRef(null);
  const wrap  = useRef(null);

  useEffect(() => {
    const fn = e => { if (!wrap.current?.contains(e.target)) setSugg([]); };
    document.addEventListener('mousedown', fn);
    return () => document.removeEventListener('mousedown', fn);
  }, []);

  const onType = v => {
    onChange({ name: v, ticker: null });
    clearTimeout(timer.current);
    if (!v.trim()) { setSugg([]); return; }
    timer.current = setTimeout(() =>
      api.get('/search-stock-kr', { params: { q: v } })
         .then(r => setSugg(r.data || []))
         .catch(() => {}), 220);
  };

  const pick = s => {
    onChange(s);
    setSugg([]);
  };

  return (
    <div ref={wrap} style={{ flex: 1, minWidth: 0 }}>
      <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--fg-3)',
                      display: 'block', marginBottom: 5 }}>{label}</label>
      <div style={{ position: 'relative' }}>
        <input
          className="form-control"
          value={value.name || ''}
          onChange={e => onType(e.target.value)}
          placeholder="종목명 또는 코드"
          style={{ fontSize: '0.85rem' }}
        />
        {sugg.length > 0 && (
          <div className="autocomplete-list"
               style={{ display: 'block', position: 'absolute', zIndex: 50,
                        top: '100%', left: 0, right: 0, marginTop: 2 }}>
            {sugg.slice(0, 7).map(s => (
              <div key={s.code} className="autocomplete-item"
                   onMouseDown={e => { e.preventDefault(); pick(s); }}
                   style={{ cursor: 'pointer' }}>
                <span style={{ fontWeight: 600 }}>{s.name}</span>
                <span style={{ fontSize: '0.73rem', color: 'var(--fg-3)',
                               fontFamily: 'var(--font-mono)', marginLeft: 8 }}>{s.code}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      {value.ticker && (
        <div style={{ fontSize: '0.7rem', color: PALETTE[0], marginTop: 3,
                      fontFamily: 'var(--font-mono)' }}>✓ {value.ticker}</div>
      )}
    </div>
  );
}

/* ── 성과 차트 ── */
function PerfChart({ stocks }) {
  const labels   = stocks[0]?.dates?.map(d => d.slice(5)) ?? [];
  const datasets = stocks.map((s, i) => ({
    label:            s.name,
    data:             s.normalized,
    borderColor:      PALETTE[i],
    backgroundColor:  PALETTE[i] + '22',
    borderWidth:      2.5,
    pointRadius:      0,
    pointHoverRadius: 5,
    tension:          0.3,
  }));

  return (
    <div style={{ height: 240 }}>
      <Line
        data={{ labels, datasets }}
        options={{
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { position: 'top',
              labels: { color: '#94a3b8', font: { size: 12 }, boxWidth: 14, padding: 16 } },
            tooltip: {
              backgroundColor: '#1e293b', borderColor: '#334155', borderWidth: 1,
              callbacks: {
                label: ctx => {
                  const d = ctx.parsed.y - 100;
                  return ` ${ctx.dataset.label}  ${d >= 0 ? '+' : ''}${d.toFixed(1)}%`;
                },
              },
            },
          },
          scales: {
            x: { ticks: { color: '#64748b', font: { size: 10 }, maxTicksLimit: 8, maxRotation: 0 },
                 grid:  { color: '#1e293b22' } },
            y: { ticks: { color: '#64748b', font: { size: 10 },
                          callback: v => `${v >= 100 ? '+' : ''}${(v - 100).toFixed(0)}%` },
                 grid: { color: '#1e293b22' } },
          },
        }}
      />
    </div>
  );
}

/* ── 지표 테이블 ── */
const METRICS = [
  { key: 'current_price', label: '현재가',   best: null,   fmt: v => v != null ? v.toLocaleString('ko') + '원' : '-' },
  { key: 'change_pct',    label: '등락률',   best: 'high', fmt: v => v != null ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}%` : '-', color: true },
  { key: 'per',           label: 'PER',      best: 'low',  fmt: v => v != null ? `${v}배` : '-' },
  { key: 'pbr',           label: 'PBR',      best: 'low',  fmt: v => v != null ? `${v}배` : '-' },
  { key: 'eps',           label: 'EPS',      best: 'high', fmt: v => v != null ? v.toLocaleString('ko') + '원' : '-' },
  { key: 'market_cap',    label: '시가총액', best: null,
    fmt: v => v == null ? '-' : v >= 1e12 ? `${(v / 1e12).toFixed(1)}조` : `${Math.round(v / 1e8)}억` },
];

function MetricsTable({ stocks }) {
  const bestOf = m => {
    if (!m.best) return -1;
    const vals = stocks.map(s => s[m.key]).filter(v => v != null);
    if (!vals.length) return -1;
    const t = m.best === 'high' ? Math.max(...vals) : Math.min(...vals);
    return stocks.findIndex(s => s[m.key] === t);
  };

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.83rem' }}>
        <thead>
          <tr style={{ background: 'var(--bg-3)' }}>
            <th style={{ padding: '10px 14px', textAlign: 'left', fontWeight: 600,
                         color: 'var(--fg-3)', width: 90 }}>지표</th>
            {stocks.map((s, i) => (
              <th key={s.ticker} style={{ padding: '10px 14px', textAlign: 'right' }}>
                <div style={{ fontWeight: 700, color: PALETTE[i] }}>{s.name}</div>
                <div style={{ fontSize: '0.7rem', fontFamily: 'var(--font-mono)',
                              color: 'var(--fg-3)', fontWeight: 400, marginTop: 2 }}>
                  {s.ticker?.replace('.KS', '').replace('.KQ', '')}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {METRICS.map(m => {
            const bi = bestOf(m);
            return (
              <tr key={m.key} style={{ borderBottom: '1px solid var(--line-1)' }}>
                <td style={{ padding: '9px 14px', color: 'var(--fg-3)', fontWeight: 500 }}>{m.label}</td>
                {stocks.map((s, i) => {
                  const v = s[m.key];
                  let clr = 'var(--fg-1)';
                  if (m.color && v != null) clr = v > 0 ? '#22c55e' : v < 0 ? '#ef4444' : 'var(--fg-2)';
                  else if (bi === i)        clr = PALETTE[i];
                  return (
                    <td key={s.ticker}
                        style={{ padding: '9px 14px', textAlign: 'right',
                                 fontFamily: 'var(--font-mono)', fontWeight: bi === i ? 800 : 600,
                                 color: clr }}>
                      {m.fmt(v)}
                      {bi === i && !m.color &&
                        <span style={{ marginLeft: 4, fontSize: '0.62rem', opacity: 0.65 }}>
                          {m.best === 'low' ? '▼' : '▲'}
                        </span>}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}


/* ── 메인 ── */
const EMPTY = { name: '', ticker: null };

export default function StockCompare() {
  const [inputs,  setInputs]  = useState([{ ...EMPTY }, { ...EMPTY }, { ...EMPTY }]);
  const [stocks,  setStocks]  = useState([]);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState('');

  const setInput = (i, v) => setInputs(prev => prev.map((x, idx) => idx === i ? v : x));

  const validInputs = inputs.filter(x => x.ticker);

  const compare = async () => {
    if (validInputs.length < 2) { setError('종목을 2개 이상 선택하세요.'); return; }
    setLoading(true); setError(''); setStocks([]);
    try {
      const tickers = validInputs.map(s => s.ticker).join(',');
      const r = await api.get('/stock-compare-data', { params: { tickers } });
      const items = r.data?.stocks ?? [];
      const ok    = items.filter(i => !i.error);
      const errs  = items.filter(i => i.error);
      if (!ok.length) throw new Error(errs[0]?.error || '데이터 없음');
      if (errs.length) setError(errs.map(i => `${i.ticker}: ${i.error}`).join(' / '));
      setStocks(ok);
    } catch (e) {
      setError(e.response?.data?.error ?? e.message ?? '데이터 로딩 실패');
    }
    setLoading(false);
  };

  return (
    <StockLayout title="종목 분석">

      {/* 입력 패널 */}
      <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)',
                    borderRadius: 'var(--r-3)', padding: '18px 20px', marginBottom: 20 }}>
        <div style={{ fontWeight: 700, fontSize: '0.88rem', color: 'var(--fg-1)', marginBottom: 14 }}>
          비교할 종목 선택
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 14 }}>
          {inputs.map((inp, i) => (
            <StockInput
              key={i}
              label={`종목 ${i + 1}${i === 2 ? ' (선택)' : ''}`}
              value={inp}
              onChange={v => setInput(i, v)}
            />
          ))}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button className="btn btn-primary"
                  onClick={compare}
                  disabled={loading || validInputs.length < 2}
                  style={{ padding: '7px 24px' }}>
            {loading
              ? <><span className="spinner-border spinner-border-sm me-2" role="status" />로딩 중...</>
              : <><i className="bi bi-bar-chart-steps me-2" />비교하기</>}
          </button>
          <span style={{ fontSize: '0.78rem', color: 'var(--fg-3)' }}>
            {validInputs.length < 2 ? `종목 2개 이상 필요 (현재 ${validInputs.length}개)` : `${validInputs.length}개 선택됨`}
          </span>
        </div>

        {error && (
          <div style={{ marginTop: 10, fontSize: '0.78rem', color: '#ef4444',
                        padding: '7px 12px', background: 'rgba(239,68,68,0.07)',
                        borderRadius: 'var(--r-1)', border: '1px solid rgba(239,68,68,0.2)' }}>
            <i className="bi bi-exclamation-circle me-1" />{error}
          </div>
        )}
      </div>

      {/* 결과 */}
      {stocks.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* 종목별 요약 카드 */}
          <div style={{ display: 'grid', gap: 10,
                        gridTemplateColumns: `repeat(${stocks.length}, 1fr)` }}>
            {stocks.map((s, i) => {
              const chg  = s.change_pct;
              const perf = s.normalized?.at?.(-1);
              return (
                <div key={s.ticker}
                     style={{ background: 'var(--bg-2)',
                              border: `1px solid ${PALETTE[i]}55`,
                              borderTop: `3px solid ${PALETTE[i]}`,
                              borderRadius: 'var(--r-2)', padding: '14px 16px' }}>
                  <div style={{ fontWeight: 700, fontSize: '0.88rem',
                                color: 'var(--fg-1)', marginBottom: 6 }}>{s.name}</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 800,
                                fontSize: '1.15rem', color: 'var(--fg-1)', marginBottom: 6 }}>
                    {s.current_price?.toLocaleString('ko')}원
                  </div>
                  <div style={{ display: 'flex', gap: 10, fontSize: '0.75rem',
                                fontFamily: 'var(--font-mono)' }}>
                    <span style={{ fontWeight: 700,
                                   color: chg >= 0 ? '#22c55e' : '#ef4444' }}>
                      당일 {chg >= 0 ? '+' : ''}{chg?.toFixed(2)}%
                    </span>
                    {perf != null && (
                      <span style={{ color: perf >= 100 ? '#22c55e' : '#ef4444', fontWeight: 700 }}>
                        6개월 {perf >= 100 ? '+' : ''}{(perf - 100).toFixed(1)}%
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* 차트 */}
          <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)',
                        borderRadius: 'var(--r-3)', padding: '16px 18px' }}>
            <div style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--fg-2)',
                          marginBottom: 14 }}>
              6개월 수익률 비교
              <span style={{ fontWeight: 400, fontSize: '0.72rem',
                             color: 'var(--fg-3)', marginLeft: 8 }}>시작일 = 100</span>
            </div>
            <PerfChart stocks={stocks} />
          </div>

          {/* 지표 테이블 */}
          <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)',
                        borderRadius: 'var(--r-3)', overflow: 'hidden' }}>
            <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--line-1)',
                          fontWeight: 700, fontSize: '0.85rem', color: 'var(--fg-2)' }}>
              투자 지표 비교
            </div>
            <MetricsTable stocks={stocks} />
          </div>
        </div>
      )}

      {/* 초기 안내 */}
      {stocks.length === 0 && !loading && (
        <div style={{ textAlign: 'center', padding: '70px 0', color: 'var(--fg-3)' }}>
          <i className="bi bi-bar-chart-steps"
             style={{ fontSize: '2.8rem', display: 'block', marginBottom: 14, opacity: 0.2 }} />
          <p style={{ fontSize: '0.9rem', margin: '0 0 6px',
                      color: 'var(--fg-2)', fontWeight: 600 }}>종목 2~3개를 선택하고 비교하기를 누르세요</p>
          <p style={{ fontSize: '0.78rem', margin: 0, opacity: 0.7 }}>
            6개월 수익률 차트 · 밸류에이션 비교 · AI 분석을 제공합니다
          </p>
        </div>
      )}
    </StockLayout>
  );
}
