import React, { useState, useEffect } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

const CATEGORIES = [
  { key: 'triple', label: '강력 추천', icon: 'bi-fire',             desc: '3개 라벨 모두 기준 초과' },
  { key: 'daily',  label: '당일',      icon: 'bi-stars',            desc: '5일 단기 급등 기반' },
  { key: 'short',  label: '단기',      icon: 'bi-lightning',        desc: '20일 모멘텀 기반' },
  { key: 'swing',  label: '스윙',      icon: 'bi-arrow-left-right', desc: '90일 추세 기반' },
];

function RawScoreBar({ value }) {
  const pct   = Math.min(100, Math.max(0, (value ?? 0) * 100));
  const color = pct >= 75 ? '#22c55e' : pct >= 60 ? '#f59e0b' : '#94a3b8';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{ width: 52, height: 5, background: 'var(--line-1)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontSize: '0.78rem', fontFamily: 'var(--font-mono)', fontWeight: 800, color, minWidth: 42 }}>
        {pct.toFixed(2)}%
      </span>
    </div>
  );
}

function FactorChip({ label, value }) {
  const pct   = Math.round((value ?? 0) * 100);
  const color = pct >= 70 ? '#22c55e' : pct >= 50 ? '#f59e0b' : '#94a3b8';
  return (
    <span style={{ fontSize: '0.65rem', padding: '1px 5px', borderRadius: 3, fontFamily: 'var(--font-mono)', fontWeight: 700,
      background: `${color}22`, color, border: `1px solid ${color}44`, whiteSpace: 'nowrap' }}>
      {label} {pct}
    </span>
  );
}

export default function RecommendAbs() {
  const [category, setCategory] = useState('triple');
  const [allData, setAllData]   = useState(null);
  const [loading, setLoading]   = useState(true);
  const [limit, setLimit]       = useState(20);

  useEffect(() => {
    api.get('/recommend_abs/json')
      .then(r => {
        if (r.data?.ok === false) { setAllData(null); return; }
        setAllData(r.data);
      })
      .catch(() => setAllData(null))
      .finally(() => setLoading(false));
  }, []);

  const items = (() => {
    if (!allData) return [];
    const list = allData[category] || [];
    return list.slice(0, limit);
  })();

  const meta = allData ? (() => {
    const bd   = allData.base_date;
    const tm   = allData.generated_at?.slice(11, 16);
    const date = (bd ? `${bd.slice(0,4)}-${bd.slice(4,6)}-${bd.slice(6,8)}` : allData.generated_at?.slice(0,10))
               + (tm ? ` ${tm}` : '');
    return {
      date,
      model_used: allData.model_used,
      model:      allData.model_used ? '앙상블(XGB+LGB+메타)' : '팩터 스코어',
      min_conf:   allData.min_conf,
      n_total:    allData.n_total,
      n_buy:      allData.n_buy,
    };
  })() : null;

  const totalForCategory = allData ? (allData[category] || []).length : 0;

  const fmtPrice = v => v ? v.toLocaleString('ko') : '-';
  const fmtRet   = v => v != null ? `${v > 0 ? '+' : ''}${(v * 100).toFixed(2)}%` : '-';

  return (
    <StockLayout title="AI 추천 (절대값)">

      {/* 상단 배너 */}
      <div style={{ background: '#7c3aed11', border: '1px solid #7c3aed44', borderRadius: 'var(--r-2)', padding: '10px 14px', marginBottom: 16, fontSize: '0.78rem', color: 'var(--fg-2)' }}>
        <i className="bi bi-info-circle me-1" style={{ color: '#7c3aed' }} />
        모델이 출력한 <b>원시(raw) 확률값</b>을 정규화 없이 그대로 표시합니다. 절대적 신뢰도를 비교할 때 사용하세요.
        정규화 기준 추천은 <a href="/recommend" style={{ color: 'var(--accent)' }}>정규화 추천</a> 페이지를 이용하세요.
      </div>

      {/* 탭 */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        {CATEGORIES.map(c => (
          <button key={c.key} onClick={() => { setCategory(c.key); setLimit(20); }}
            style={{
              padding: '7px 14px', borderRadius: 'var(--r-2)', fontSize: '0.82rem', fontWeight: 600,
              border: category === c.key ? (c.key === 'triple' ? '1px solid #f59e0b' : '1px solid var(--accent)') : '1px solid var(--line-2)',
              background: category === c.key ? (c.key === 'triple' ? '#f59e0b' : 'var(--accent)') : 'var(--bg-2)',
              color: category === c.key ? '#fff' : 'var(--fg-2)', cursor: 'pointer',
            }}>
            <i className={`bi ${c.icon} me-1`} />{c.label}
            {c.key === 'triple' && allData?.triple?.length > 0 && (
              <span style={{ marginLeft: 5, fontSize: '0.68rem', background: '#fff3', padding: '1px 5px', borderRadius: 8 }}>
                {allData.triple.length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* 메타 */}
      {meta && (
        <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-2)', padding: '10px 14px', marginBottom: 16, fontSize: '0.78rem', color: 'var(--fg-2)', display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          {meta.date      && <span><i className="bi bi-calendar3 me-1" />기준일: <b>{meta.date}</b></span>}
          {meta.model     && <span><i className="bi bi-cpu me-1" />모델: <b style={{ color: meta.model_used ? '#7c3aed' : 'var(--fg-3)' }}>{meta.model}</b></span>}
          {meta.min_conf  != null && <span><i className="bi bi-sliders me-1" />최소 신뢰도: <b>{(meta.min_conf * 100).toFixed(0)}%</b></span>}
          {meta.n_buy     != null && <span><i className="bi bi-list-check me-1" />전체 추천: <b>{meta.n_buy}</b>종목</span>}
          {meta.n_total   != null && <span><i className="bi bi-buildings me-1" />유니버스: <b>{meta.n_total}</b>종목</span>}
        </div>
      )}

      {loading ? (
        <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--fg-3)' }}>
          <div className="spinner" style={{ margin: '0 auto 10px' }} />로딩 중...
        </div>
      ) : !allData ? (
        <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--fg-3)' }}>
          데이터 없음 — <code>python -m XGBoost_v2.daily_recommend</code> 를 실행해주세요.
        </div>
      ) : (
        <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.81rem', minWidth: 860 }}>
            <thead>
              <tr style={{ background: 'var(--bg-3)', borderBottom: '1px solid var(--line-1)' }}>
                {['#', '종목', '코드', '출처', '원시 신뢰도', '진입가', '목표가', '손절가', '예상수익', '팩터 분해'].map(h => (
                  <th key={h} style={{ padding: '10px 12px', fontWeight: 600, color: 'var(--fg-2)', textAlign: 'left', fontFamily: 'var(--font-mono)', fontSize: '0.71rem', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((s, i) => (
                <tr key={s.code} style={{ borderBottom: '1px solid var(--line-1)' }}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-3)'}
                  onMouseLeave={e => e.currentTarget.style.background = ''}>
                  <td style={{ padding: '9px 12px', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)', fontSize: '0.71rem' }}>{i + 1}</td>
                  <td style={{ padding: '9px 12px', fontWeight: 700, color: 'var(--fg-1)', whiteSpace: 'nowrap' }}>
                    {s.name}
                    {s.multi_signal === 3 && (
                      <span style={{ marginLeft: 5, fontSize: '0.62rem', padding: '1px 4px', borderRadius: 3, background: '#f59e0b22', color: '#f59e0b', fontWeight: 700, border: '1px solid #f59e0b44' }}>
                        ★ 강력
                      </span>
                    )}
                  </td>
                  <td style={{ padding: '9px 12px', fontFamily: 'var(--font-mono)', color: 'var(--fg-3)', fontSize: '0.75rem' }}>{s.code}</td>
                  <td style={{ padding: '9px 12px' }}>
                    <span style={{ fontSize: '0.68rem', padding: '2px 6px', borderRadius: 3, fontWeight: 700,
                      background: s.source === 'model' ? '#7c3aed22' : '#f59e0b22',
                      color:      s.source === 'model' ? '#7c3aed'   : '#f59e0b' }}>
                      {s.source === 'model' ? 'MODEL' : 'FACTOR'}
                    </span>
                  </td>
                  <td style={{ padding: '9px 12px' }}><RawScoreBar value={s.confidence} /></td>
                  <td style={{ padding: '9px 12px', fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>{fmtPrice(s.entry)}</td>
                  <td style={{ padding: '9px 12px', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--up)', fontWeight: 600 }}>{fmtPrice(s.target)}</td>
                  <td style={{ padding: '9px 12px', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--down)' }}>{fmtPrice(s.stop)}</td>
                  <td style={{ padding: '9px 12px', fontFamily: 'var(--font-mono)', fontWeight: 700,
                    color: (s.expected_return ?? 0) > 0 ? 'var(--up)' : 'var(--fg-3)' }}>
                    {fmtRet(s.expected_return)}
                  </td>
                  <td style={{ padding: '6px 12px' }}>
                    {s.factors && (
                      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                        <FactorChip label="모멘텀" value={s.factors.momentum}  />
                        <FactorChip label="수급"   value={s.factors.flow}      />
                        <FactorChip label="EPS"    value={s.factors.eps}       />
                        <FactorChip label="유동성" value={s.factors.liquidity} />
                      </div>
                    )}
                  </td>
                </tr>
              ))}
              {!items.length && (
                <tr><td colSpan={10} style={{ textAlign: 'center', padding: '48px', color: 'var(--fg-3)' }}>
                  이 카테고리에 추천 데이터가 없습니다.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {limit < totalForCategory && (
        <div style={{ textAlign: 'center', marginTop: 14 }}>
          <button className="btn btn-outline-secondary btn-sm" onClick={() => setLimit(l => l + 20)}>
            더 보기 ({limit} / {totalForCategory})
          </button>
        </div>
      )}
    </StockLayout>
  );
}
