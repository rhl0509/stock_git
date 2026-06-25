import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

function HeatCell({ name, rate, active, onClick }) {
  const abs = Math.abs(rate);
  const intensity = Math.min(abs / 4, 1); // 4% = 최대 채도
  const bg = rate > 0
    ? `rgba(34,197,94,${0.1 + intensity * 0.55})`
    : rate < 0
    ? `rgba(239,68,68,${0.1 + intensity * 0.55})`
    : 'var(--bg-3)';
  const color = rate > 0 ? '#16a34a' : rate < 0 ? '#dc2626' : 'var(--fg-3)';
  return (
    <div onClick={onClick} style={{
      background: bg,
      border: active ? '2px solid var(--accent)' : '1px solid var(--line-1)',
      borderRadius: 'var(--r-2)',
      padding: active ? '13px 9px' : '14px 10px',
      textAlign: 'center',
      cursor: 'pointer',
      transition: 'transform 0.12s',
    }}
      onMouseEnter={e => e.currentTarget.style.transform = 'scale(1.03)'}
      onMouseLeave={e => e.currentTarget.style.transform = 'scale(1)'}
    >
      <div style={{ fontSize: '0.72rem', color: 'var(--fg-2)', fontWeight: 600, marginBottom: 6, lineHeight: 1.3 }}>
        {name}
      </div>
      <div style={{ fontSize: '1rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color }}>
        {rate > 0 ? '+' : ''}{rate.toFixed(2)}%
      </div>
    </div>
  );
}

export default function SectorHeatmap() {
  const [sectors, setSectors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState('');

  const [sel, setSel] = useState(null);        // 선택된 섹터 {code,name,rate}
  const [stocks, setStocks] = useState([]);
  const [stLoading, setStLoading] = useState(false);
  const [stError, setStError] = useState(null);

  const load = () => {
    setLoading(true);
    api.get('/sector/list')
      .then(r => {
        setSectors(r.data?.sectors ?? []);
        setLastUpdated(new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }));
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const openSector = (s) => {
    setSel(s);
    setStLoading(true);
    setStError(null);
    setStocks([]);
    api.post('/sector/stocks', { code: s.code, name: s.name })
      .then(r => setStocks(r.data?.stocks ?? []))
      .catch(() => setStError('구성종목을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.'))
      .finally(() => setStLoading(false));
  };

  const sorted = [...sectors].sort((a, b) => b.rate - a.rate);
  const positive = sorted.filter(s => s.rate > 0).length;
  const negative = sorted.filter(s => s.rate < 0).length;
  const neutral  = sorted.filter(s => s.rate === 0).length;

  return (
    <StockLayout title="섹터 히트맵">
      <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '20px', marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--fg-1)', display: 'flex', alignItems: 'center', gap: 6 }}>
            <i className="bi bi-grid-3x3-gap-fill" style={{ color: 'var(--accent)' }} />
            업종별 등락률
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {lastUpdated && (
              <span style={{ fontSize: '0.72rem', color: 'var(--fg-3)' }}>기준 {lastUpdated}</span>
            )}
            <button onClick={load} disabled={loading}
              style={{ background: 'none', border: '1px solid var(--line-2)', borderRadius: 'var(--r-1)', padding: '3px 10px', fontSize: '0.72rem', color: 'var(--fg-3)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
              <i className={`bi bi-arrow-clockwise${loading ? ' spin' : ''}`} />
              새로고침
            </button>
          </div>
        </div>

        {/* 요약 배지 */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
          <span style={{ background: 'rgba(34,197,94,0.12)', color: '#16a34a', borderRadius: 'var(--r-1)', padding: '3px 10px', fontSize: '0.75rem', fontWeight: 700 }}>
            ▲ 상승 {positive}
          </span>
          <span style={{ background: 'rgba(239,68,68,0.12)', color: '#dc2626', borderRadius: 'var(--r-1)', padding: '3px 10px', fontSize: '0.75rem', fontWeight: 700 }}>
            ▼ 하락 {negative}
          </span>
          {neutral > 0 && (
            <span style={{ background: 'var(--bg-3)', color: 'var(--fg-3)', borderRadius: 'var(--r-1)', padding: '3px 10px', fontSize: '0.75rem', fontWeight: 700 }}>
              — 보합 {neutral}
            </span>
          )}
        </div>

        {loading ? (
          <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--fg-3)', fontSize: '0.83rem' }}>
            <div className="spinner" style={{ margin: '0 auto 10px' }} /> 업종 데이터 로딩 중...
          </div>
        ) : sectors.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--fg-3)' }}>데이터 없음</div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: 8 }}>
            {sorted.map(s => (
              <HeatCell key={s.code} name={s.name} rate={s.rate}
                active={sel?.code === s.code} onClick={() => openSector(s)} />
            ))}
          </div>
        )}
        {!loading && sectors.length > 0 && (
          <div style={{ marginTop: 12, fontSize: '0.72rem', color: 'var(--fg-3)', textAlign: 'center' }}>
            <i className="bi bi-hand-index" style={{ marginRight: 4 }} />업종을 클릭하면 구성종목이 표시됩니다
          </div>
        )}
      </div>

      {/* 선택 섹터 구성종목 */}
      {sel && (
        <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '20px', marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <div style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--fg-1)', display: 'flex', alignItems: 'center', gap: 8 }}>
              <i className="bi bi-collection" style={{ color: 'var(--accent)' }} />
              {sel.name}
              <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '0.8rem', color: sel.rate > 0 ? 'var(--up)' : sel.rate < 0 ? 'var(--down)' : 'var(--fg-3)' }}>
                {sel.rate > 0 ? '+' : ''}{sel.rate.toFixed(2)}%
              </span>
              {!stLoading && stocks.length > 0 && (
                <span style={{ fontSize: '0.72rem', color: 'var(--fg-3)', fontWeight: 500 }}>· {stocks.length}종목</span>
              )}
            </div>
            <button onClick={() => setSel(null)}
              style={{ background: 'none', border: '1px solid var(--line-2)', borderRadius: 'var(--r-1)', padding: '3px 9px', fontSize: '0.72rem', color: 'var(--fg-3)', cursor: 'pointer' }}>
              <i className="bi bi-x-lg" />
            </button>
          </div>

          {stLoading ? (
            <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--fg-3)', fontSize: '0.83rem' }}>
              <div className="spinner" style={{ margin: '0 auto 10px' }} /> 구성종목 로딩 중...
            </div>
          ) : stError ? (
            <div style={{ textAlign: 'center', padding: '30px 0', color: 'var(--down)', fontSize: '0.82rem' }}>
              <i className="bi bi-exclamation-triangle-fill" style={{ marginRight: 6 }} />{stError}
            </div>
          ) : stocks.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '30px 0', color: 'var(--fg-3)' }}>구성종목 없음</div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 6 }}>
              {stocks.map(st => (
                <Link key={st.code} to={`/stock_detail?code=${st.code}&name=${encodeURIComponent(st.name)}`}
                  style={{ textDecoration: 'none', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    background: 'var(--bg-3)', borderRadius: 'var(--r-2)', padding: '9px 12px' }}>
                  <span style={{ display: 'flex', flexDirection: 'column' }}>
                    <span style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--fg-1)' }}>{st.name}</span>
                    <span style={{ fontSize: '0.66rem', fontFamily: 'var(--font-mono)', color: 'var(--fg-3)' }}>{st.code}</span>
                  </span>
                  <span style={{ textAlign: 'right' }}>
                    <span style={{ display: 'block', fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '0.82rem', color: 'var(--fg-1)' }}>
                      {st.price ? st.price.toLocaleString('ko') : '-'}
                    </span>
                    <span style={{ fontSize: '0.72rem', fontFamily: 'var(--font-mono)', color: st.rate > 0 ? 'var(--up)' : st.rate < 0 ? 'var(--down)' : 'var(--fg-3)' }}>
                      {st.rate > 0 ? '+' : ''}{st.rate.toFixed(2)}%
                    </span>
                  </span>
                </Link>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 등락률 상위/하위 */}
      {sectors.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          {[
            { label: '상승 상위', icon: 'bi-arrow-up-circle', color: 'var(--up)', items: sorted.slice(0, 5) },
            { label: '하락 상위', icon: 'bi-arrow-down-circle', color: 'var(--down)', items: [...sorted].reverse().slice(0, 5) },
          ].map(group => (
            <div key={group.label} style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '16px' }}>
              <div style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--fg-1)', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
                <i className={`bi ${group.icon}`} style={{ color: group.color }} />{group.label}
              </div>
              {group.items.map((s, i) => (
                <div key={s.code} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 0', borderBottom: i < 4 ? '1px solid var(--line-1)' : 'none' }}>
                  <span style={{ fontSize: '0.82rem', color: 'var(--fg-2)' }}>{s.name}</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '0.85rem', color: s.rate > 0 ? 'var(--up)' : s.rate < 0 ? 'var(--down)' : 'var(--fg-3)' }}>
                    {s.rate > 0 ? '+' : ''}{s.rate.toFixed(2)}%
                  </span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </StockLayout>
  );
}
