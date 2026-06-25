import React, { useState, useEffect } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import { Link } from 'react-router-dom';
import api from '../api/index.js';

export default function Screener52Week() {
  const [filter,  setFilter]  = useState('high');
  const [items,   setItems]   = useState([]);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState(null);

  const load = (f = filter) => {
    setLoading(true);
    setError(null);
    api.get('/api/screener/52week', { params: { filter: f } })
      .then(r => setItems(r.data?.items || []))
      .catch(() => { setItems([]); setError('데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.'); })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleFilter = f => { setFilter(f); load(f); };

  return (
    <StockLayout title="52주 스크리너">
      <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'20px' }}>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:16 }}>
          <div style={{ fontWeight:700, fontSize:'0.9rem', color:'var(--fg-1)', display:'flex', alignItems:'center', gap:6 }}>
            <i className="bi bi-bullseye" style={{ color:'var(--accent)' }}/>52주 신고가/신저가 근접
          </div>
          <div style={{ display:'flex', gap:8, alignItems:'center' }}>
            <div className="btn-group">
              {[['high','신고가 근접'],['low','신저가 근접']].map(([k,l]) => (
                <button key={k} onClick={() => handleFilter(k)}
                  className={`btn btn-sm ${filter === k ? 'btn-primary' : 'btn-outline-secondary'}`}>
                  {l}
                </button>
              ))}
            </div>
            <button onClick={() => load()} disabled={loading}
              style={{ background:'none', border:'1px solid var(--line-2)', borderRadius:'var(--r-1)', padding:'4px 10px', fontSize:'0.72rem', color:'var(--fg-3)', cursor:'pointer' }}>
              <i className={`bi bi-arrow-clockwise${loading ? ' spin' : ''}`}/>
            </button>
          </div>
        </div>

        <div style={{ fontSize:'0.73rem', color:'var(--fg-3)', marginBottom:14 }}>
          {filter === 'high' ? '52주 최고가 대비 -5% 이내 (돌파 임박)' : '52주 최저가 대비 +5% 이내 (반등 여부 주의)'}
        </div>

        {error && (
          <div style={{ background:'rgba(244,63,94,0.1)', border:'1px solid var(--down)', borderRadius:'var(--r-2)', padding:'10px 14px', marginBottom:12, color:'var(--down)', fontSize:'0.82rem', display:'flex', alignItems:'center', gap:8 }}>
            <i className="bi bi-exclamation-triangle-fill"/>{error}
          </div>
        )}
        {loading ? (
          <div style={{ textAlign:'center', padding:'60px', color:'var(--fg-3)' }}><div className="spinner" style={{ margin:'0 auto 10px' }}/> 조회 중 (최초 1분 소요)...</div>
        ) : items.length === 0 && !error ? (
          <div style={{ textAlign:'center', padding:'60px', color:'var(--fg-3)' }}>해당 종목 없음</div>
        ) : (
          <div style={{ display:'grid', gap:8 }}>
            {items.map(item => {
              const pct = filter === 'high' ? item.pct_from_high : item.pct_from_low;
              const barPct = filter === 'high'
                ? Math.max(0, 100 + pct)     // -5~0 → 95~100%
                : Math.max(0, 100 - pct);    // 0~5 → 100~95%
              return (
                <div key={item.code} style={{ background:'var(--bg-3)', borderRadius:'var(--r-2)', padding:'12px 14px' }}>
                  <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:8 }}>
                    <div>
                      <Link to={`/stock_detail?code=${item.code}&name=${encodeURIComponent(item.name)}`}
                        style={{ fontWeight:700, color:'var(--fg-1)', textDecoration:'none', fontSize:'0.87rem' }}>
                        {item.name}
                      </Link>
                      <span style={{ marginLeft:8, fontFamily:'var(--font-mono)', fontSize:'0.7rem', color:'var(--fg-3)' }}>{item.code}</span>
                    </div>
                    <div style={{ textAlign:'right' }}>
                      <div style={{ fontFamily:'var(--font-mono)', fontWeight:700, fontSize:'0.95rem' }}>{item.price.toLocaleString('ko')}</div>
                      {pct === 0 ? (
                        <div style={{ fontSize:'0.7rem', fontWeight:700, color:'#fff',
                          background: filter === 'high' ? 'var(--up)' : 'var(--down)',
                          borderRadius:'var(--r-1)', padding:'1px 7px', display:'inline-block', marginTop:2 }}>
                          <i className="bi bi-fire" style={{ marginRight:3 }}/>{filter === 'high' ? '신고가 경신' : '신저가 경신'}
                        </div>
                      ) : (
                        <div style={{ fontSize:'0.72rem', fontFamily:'var(--font-mono)', color:'var(--fg-3)' }}>
                          {filter === 'high' ? '고가까지 ' : '저가까지 '}{Math.abs(pct).toFixed(2)}%
                        </div>
                      )}
                    </div>
                  </div>
                  <div style={{ position:'relative', height:6, background:'var(--line-1)', borderRadius:4, marginBottom:6 }}>
                    <div style={{ position:'absolute', left:0, top:0, height:'100%', width:`${barPct}%`,
                      background: filter === 'high' ? 'var(--up)' : 'var(--down)', borderRadius:4 }} />
                  </div>
                  <div style={{ display:'flex', justifyContent:'space-between', fontSize:'0.65rem', color:'var(--fg-3)', fontFamily:'var(--font-mono)' }}>
                    <span>52주 저가 {item.week52_low.toLocaleString('ko')}</span>
                    <span>52주 고가 {item.week52_high.toLocaleString('ko')}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </StockLayout>
  );
}
