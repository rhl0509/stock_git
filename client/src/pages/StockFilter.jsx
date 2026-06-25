import React, { useState, useCallback } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

/* ── 필터 프리셋 정의 ─────────────────────────────────────── */
const PRESETS = [
  { key: 'all',          label: '전체',       icon: 'bi-grid',             color: '#6366f1' },
  { key: 'strong_buy',   label: '강력매수',   icon: 'bi-arrow-up-circle',  color: '#22c55e' },
  { key: 'golden_cross', label: '골든크로스', icon: 'bi-arrow-up-right',   color: '#10b981' },
  { key: 'rsi_low',      label: 'RSI 과매도', icon: 'bi-bar-chart-fill',   color: '#3b82f6' },
  { key: 'volume_surge', label: '거래량급등', icon: 'bi-fire',             color: '#f59e0b' },
  { key: 'near_52w_high',label: '52주신고가', icon: 'bi-trophy',           color: '#8b5cf6' },
  { key: 'near_52w_low', label: '52주신저가', icon: 'bi-arrow-down-circle',color: '#64748b' },
  { key: 'rsi_high',     label: 'RSI 과매수', icon: 'bi-bar-chart',        color: '#f97316' },
  { key: 'dead_cross',   label: '데드크로스', icon: 'bi-arrow-down-right', color: '#ef4444' },
  { key: 'strong_sell',  label: '강력매도',   icon: 'bi-arrow-down-circle',color: '#dc2626' },
];

const SORTS = [
  { key: 'score',         label: '매수점수' },
  { key: 'sell_score',    label: '매도점수' },
  { key: 'rsi',           label: 'RSI' },
  { key: 'vol_ratio',     label: '거래량비율' },
  { key: 'price_vs_ma20', label: 'MA20이격도' },
  { key: 'macd_hist',     label: 'MACD Hist' },
  { key: 'price',         label: '현재가' },
];

/* ── 태그 배지 ───────────────────────────────────────────── */
const TAG_COLOR = {
  '강력매수':  ['#dcfce7', '#22c55e', '#166534'],
  '골든크로스':['#dbeafe', '#3b82f6', '#1e40af'],
  'RSI과매도': ['#dbeafe', '#3b82f6', '#1e40af'],
  '거래량급등':['#fef9c3', '#eab308', '#713f12'],
  '52주신고가':['#f3e8ff', '#a855f7', '#581c87'],
  '52주신저가':['#f1f5f9', '#64748b', '#1e293b'],
  'RSI과매수': ['#ffedd5', '#f97316', '#7c2d12'],
  '강력매도':  ['#fee2e2', '#ef4444', '#7f1d1d'],
  '데드크로스':['#fee2e2', '#ef4444', '#7f1d1d'],
};

function Tag({ label }) {
  const [bg, border, text] = TAG_COLOR[label] || ['var(--bg-3)', 'var(--line-2)', 'var(--fg-3)'];
  return (
    <span style={{ fontSize: '0.63rem', fontWeight: 700, padding: '1px 6px', borderRadius: 10,
      background: bg, border: `1px solid ${border}`, color: text, whiteSpace: 'nowrap' }}>
      {label}
    </span>
  );
}

/* ── RSI 게이지 ─────────────────────────────────────────── */
function RsiBar({ val }) {
  const color = val < 30 ? '#3b82f6' : val > 70 ? '#ef4444' : val > 60 ? '#f97316' : '#22c55e';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
      <div style={{ width: 40, height: 5, background: 'var(--line-1)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${val}%`, background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', color }}>{val}</span>
    </div>
  );
}

export default function StockFilter() {
  const [filter,  setFilter]  = useState('all');
  const [sortBy,  setSortBy]  = useState('score');
  const [sortDir, setSortDir] = useState('desc');
  const [results, setResults] = useState(null);  // null = 초기, [] = 결과 없음
  const [meta,    setMeta]    = useState(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState('');
  const [lastRun, setLastRun] = useState(null);

  const run = useCallback(async (f = filter, sb = sortBy, sd = sortDir) => {
    setLoading(true); setError('');
    try {
      const r = await api.post('/stock/screen', { filter: f, sort_by: sb, sort_dir: sd });
      setResults(r.data?.results || []);
      setMeta({ count: r.data?.count, total: r.data?.total });
      setLastRun(new Date());
    } catch (e) {
      setError(e.response?.data?.error || '스크리닝 실패 (yfinance 다운로드에 시간이 걸릴 수 있습니다)');
    }
    setLoading(false);
  }, [filter, sortBy, sortDir]);

  const refresh = async () => {
    try {
      await api.post('/stock/screen/refresh');
      await run(filter, sortBy, sortDir);
    } catch {}
  };

  const changeFilter = f => { setFilter(f); if (results !== null) run(f, sortBy, sortDir); };
  const changeSort = (sb, sd) => { setSortBy(sb); setSortDir(sd); if (results !== null) run(filter, sb, sd); };

  const preset = PRESETS.find(p => p.key === filter) || PRESETS[0];

  return (
    <StockLayout title="기술적 종목 필터">

      {/* 필터 프리셋 버튼 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 16 }}>
        {PRESETS.map(p => (
          <button key={p.key} onClick={() => changeFilter(p.key)}
            style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 12px', fontSize: '0.78rem',
              border: `1px solid ${filter === p.key ? p.color : 'var(--line-2)'}`,
              background: filter === p.key ? `${p.color}15` : 'var(--bg-2)',
              color: filter === p.key ? p.color : 'var(--fg-2)',
              borderRadius: 20, cursor: 'pointer', fontWeight: filter === p.key ? 700 : 400, transition: 'all 0.15s' }}>
            <i className={`bi ${p.icon}`} style={{ fontSize: '0.75rem' }} />
            {p.label}
          </button>
        ))}
      </div>

      {/* 정렬 + 실행 */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 20, flexWrap: 'wrap' }}>
        <span style={{ fontSize: '0.75rem', color: 'var(--fg-3)' }}>정렬:</span>
        <select className="form-select" value={sortBy} onChange={e => changeSort(e.target.value, sortDir)}
          style={{ width: 'auto', fontSize: '0.8rem', padding: '4px 24px 4px 8px' }}>
          {SORTS.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
        </select>
        <button onClick={() => changeSort(sortBy, sortDir === 'desc' ? 'asc' : 'desc')}
          style={{ background: 'var(--bg-2)', border: '1px solid var(--line-2)', borderRadius: 'var(--r-1)', padding: '4px 8px', cursor: 'pointer', color: 'var(--fg-2)', fontSize: '0.8rem' }}>
          {sortDir === 'desc' ? '↓ 내림차순' : '↑ 오름차순'}
        </button>
        <div style={{ flex: 1 }} />
        <button className="btn btn-outline-secondary btn-sm" onClick={refresh} disabled={loading} title="캐시 초기화 후 재조회 (약 30~60초)">
          <i className="bi bi-arrow-clockwise me-1" />새로고침
        </button>
        <button className="btn btn-primary" onClick={() => run()} disabled={loading}>
          {loading ? <><div style={{ display: 'inline-block', width: 12, height: 12, border: '2px solid rgba(255,255,255,0.3)', borderTopColor: '#fff', borderRadius: '50%', animation: 'spin 0.8s linear infinite', marginRight: 5, verticalAlign: 'middle' }} />스크리닝 중...</> : <><i className="bi bi-funnel me-1" />종목 필터링</>}
        </button>
      </div>

      {error && (
        <div style={{ padding: '10px 14px', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 'var(--r-2)', fontSize: '0.82rem', color: '#ef4444', marginBottom: 16 }}>
          <i className="bi bi-exclamation-triangle me-1" />{error}
          <div style={{ fontSize: '0.72rem', marginTop: 4, opacity: 0.8 }}>처음 실행 시 yfinance 데이터 다운로드로 30~60초 소요됩니다.</div>
        </div>
      )}

      {/* 결과 */}
      {results !== null && !loading && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <div style={{ fontSize: '0.8rem', color: 'var(--fg-3)' }}>
              <span style={{ color: preset.color, fontWeight: 700 }}>{preset.label}</span>
              <span style={{ marginLeft: 8 }}>— {meta?.count}개 / 전체 {meta?.total}개</span>
              {lastRun && <span style={{ marginLeft: 8, fontSize: '0.7rem' }}>({lastRun.toLocaleTimeString('ko-KR')} 기준)</span>}
            </div>
          </div>

          {results.length > 0 ? (
            <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'hidden' }}>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
                  <thead>
                    <tr style={{ background: 'var(--bg-3)', borderBottom: '1px solid var(--line-1)' }}>
                      {['종목', '현재가', 'RSI', 'MA20 이격도', '거래량비율', 'MACD Hist', '점수', '시그널'].map(h => (
                        <th key={h} style={{ padding: '9px 12px', fontWeight: 600, color: 'var(--fg-2)', textAlign: h === '종목' || h === '시그널' ? 'left' : 'right', whiteSpace: 'nowrap' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {results.map((s, i) => {
                      const pct = s.price_vs_ma20;
                      return (
                        <tr key={s.code} style={{ borderBottom: '1px solid var(--line-1)', background: i % 2 === 0 ? 'transparent' : 'var(--bg-1)' }}>
                          <td style={{ padding: '9px 12px' }}>
                            <div style={{ fontWeight: 700, color: 'var(--fg-1)' }}>{s.name}</div>
                            <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)', marginTop: 1 }}>{s.code}</div>
                          </td>
                          <td style={{ padding: '9px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                            {s.price?.toLocaleString('ko')}
                          </td>
                          <td style={{ padding: '9px 12px', textAlign: 'right' }}>
                            <RsiBar val={s.rsi} />
                          </td>
                          <td style={{ padding: '9px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 600,
                            color: pct > 0 ? 'var(--up)' : pct < 0 ? 'var(--down)' : 'var(--fg-3)' }}>
                            {pct != null ? `${pct > 0 ? '+' : ''}${pct.toFixed(2)}%` : '-'}
                          </td>
                          <td style={{ padding: '9px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)',
                            color: s.vol_ratio >= 2 ? '#f59e0b' : s.vol_ratio >= 1.5 ? '#f97316' : 'var(--fg-2)' }}>
                            {s.vol_ratio?.toFixed(2)}x
                          </td>
                          <td style={{ padding: '9px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)',
                            color: (s.macd_hist ?? 0) > 0 ? 'var(--up)' : (s.macd_hist ?? 0) < 0 ? 'var(--down)' : 'var(--fg-3)' }}>
                            {s.macd_hist != null ? `${s.macd_hist > 0 ? '+' : ''}${s.macd_hist.toFixed(2)}` : '-'}
                          </td>
                          <td style={{ padding: '9px 12px', textAlign: 'right' }}>
                            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 4, alignItems: 'center' }}>
                              {s.strong_buy && <span style={{ fontSize: '0.68rem', fontWeight: 700, color: '#22c55e' }}>{s.score}점</span>}
                              {s.strong_sell && <span style={{ fontSize: '0.68rem', fontWeight: 700, color: '#ef4444' }}>{s.sell_score}점</span>}
                              {!s.strong_buy && !s.strong_sell && <span style={{ fontSize: '0.72rem', color: 'var(--fg-3)' }}>{s.score}</span>}
                            </div>
                          </td>
                          <td style={{ padding: '9px 12px' }}>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
                              {(s.tags || []).map(t => <Tag key={t} label={t} />)}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--fg-3)' }}>
              <i className="bi bi-search" style={{ fontSize: '2rem', display: 'block', marginBottom: 8, opacity: 0.3 }} />
              조건에 해당하는 종목이 없습니다.
            </div>
          )}
        </div>
      )}

      {/* 초기 상태 */}
      {results === null && !loading && (
        <div style={{ textAlign: 'center', padding: '80px 0', color: 'var(--fg-3)' }}>
          <i className="bi bi-funnel" style={{ fontSize: '2.5rem', display: 'block', marginBottom: 12, opacity: 0.25 }} />
          <p style={{ margin: 0, fontSize: '0.85rem' }}>필터 조건을 선택하고 종목 필터링 버튼을 눌러주세요.</p>
          <p style={{ fontSize: '0.74rem', marginTop: 6, opacity: 0.7 }}>RSI · MACD · 이동평균 · 거래량 기반 기술적 분석 스크리닝</p>
          <p style={{ fontSize: '0.72rem', marginTop: 4, color: '#f59e0b' }}>
            <i className="bi bi-clock me-1" />첫 실행 시 yfinance 데이터 수집으로 30~60초 소요됩니다.
          </p>
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </StockLayout>
  );
}
