import React, { useState, useEffect } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

const card = { background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'20px', marginBottom:16 };

function corrColor(v) {
  // -1(파랑) ~ 0(투명) ~ +1(빨강)
  if (v == null) return 'transparent';
  const a = Math.min(Math.abs(v), 1) * 0.75;
  return v >= 0 ? `rgba(239,68,68,${a})` : `rgba(59,130,246,${a})`;
}

export default function RiskDashboard() {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState('');

  useEffect(() => {
    api.get('/api/risk/dashboard')
      .then(r => setData(r.data))
      .catch(err => setError(err.response?.data?.error || '리스크 데이터를 불러오지 못했습니다.'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return (
    <StockLayout title="리스크 분석">
      <div style={{ textAlign:'center', padding:'80px 0', color:'var(--fg-3)' }}>
        <div className="spinner" style={{ margin:'0 auto 10px' }}/>
        보유종목 6개월 시세 분석 중...
      </div>
    </StockLayout>
  );

  if (error || !data?.ok) return (
    <StockLayout title="리스크 분석">
      <div style={{ textAlign:'center', padding:'80px 0', color:'var(--fg-3)' }}>
        <i className="bi bi-shield-exclamation" style={{ fontSize:'2.5rem', display:'block', marginBottom:12, opacity:0.3 }}/>
        {error || '데이터 없음'}
      </div>
    </StockLayout>
  );

  const { portfolio, items, correlation, sectors, warnings, total_eval } = data;
  const hhiLabel = portfolio.hhi >= 2500 ? '고집중' : portfolio.hhi >= 1500 ? '보통' : '분산';

  return (
    <StockLayout title="리스크 분석">

      {/* 경고 배너 */}
      {warnings?.length > 0 && (
        <div style={{ background:'rgba(244,63,94,0.08)', border:'1px solid var(--down)', borderRadius:'var(--r-3)', padding:'12px 16px', marginBottom:16 }}>
          {warnings.map(w => (
            <div key={w} style={{ color:'var(--down)', fontSize:'0.83rem', fontWeight:600, padding:'2px 0' }}>
              <i className="bi bi-exclamation-triangle-fill me-2"/>{w}
            </div>
          ))}
        </div>
      )}

      {/* 포트폴리오 요약 */}
      <div style={{ display:'grid', gap:12, gridTemplateColumns:'repeat(auto-fill,minmax(170px,1fr))', marginBottom:16 }}>
        {[
          ['평가금액', `₩${(total_eval||0).toLocaleString('ko')}`, null],
          ['포트폴리오 베타', portfolio.beta != null ? portfolio.beta.toFixed(2) : '-',
            portfolio.beta != null ? (portfolio.beta <= 1.1) : null,
            'KOSPI=1.0 기준 민감도'],
          ['연환산 변동성', portfolio.volatility != null ? `${portfolio.volatility}%` : '-',
            portfolio.volatility != null ? (portfolio.volatility <= 30) : null,
            '최근 6개월'],
          ['집중도 (HHI)', `${portfolio.hhi} · ${hhiLabel}`, portfolio.hhi < 2500,
            '2500↑ 고집중'],
        ].map(([l, v, good, sub]) => (
          <div key={l} style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'14px 16px' }}>
            <div style={{ fontSize:'0.68rem', color:'var(--fg-3)', fontFamily:'var(--font-mono)', marginBottom:4 }}>{l}</div>
            <div style={{ fontSize:'1.15rem', fontWeight:800, fontFamily:'var(--font-mono)',
                          color: good == null ? 'var(--fg-1)' : good ? 'var(--up)' : 'var(--down)' }}>{v}</div>
            {sub && <div style={{ fontSize:'0.65rem', color:'var(--fg-3)', marginTop:2 }}>{sub}</div>}
          </div>
        ))}
      </div>

      {/* 종목별 리스크 테이블 */}
      <div style={card}>
        <div style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)', marginBottom:12 }}>
          <i className="bi bi-list-ol me-2" style={{ color:'var(--accent)' }}/>종목별 리스크
        </div>
        <div style={{ overflowX:'auto' }}>
          <table style={{ width:'100%', borderCollapse:'collapse', fontSize:'0.82rem' }}>
            <thead>
              <tr style={{ borderBottom:'2px solid var(--line-2)' }}>
                {['종목','비중','평가금액','변동성(연)','베타','최대낙폭(6M)'].map(h => (
                  <th key={h} style={{ padding:'8px 10px', textAlign:h==='종목'?'left':'right', color:'var(--fg-3)', fontWeight:600, fontSize:'0.72rem', whiteSpace:'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map(i => (
                <tr key={i.code} style={{ borderBottom:'1px solid var(--line-1)' }}>
                  <td style={{ padding:'9px 10px' }}>
                    <span style={{ fontWeight:700 }}>{i.name}</span>
                    <span style={{ fontSize:'0.68rem', color:'var(--fg-3)', marginLeft:6, fontFamily:'var(--font-mono)' }}>{i.code}</span>
                  </td>
                  <td style={{ padding:'9px 10px', textAlign:'right' }}>
                    <div style={{ display:'flex', alignItems:'center', gap:8, justifyContent:'flex-end' }}>
                      <div style={{ width:60, height:6, background:'var(--bg-3)', borderRadius:3, overflow:'hidden' }}>
                        <div style={{ width:`${Math.min(i.weight,100)}%`, height:'100%', background: i.weight > 40 ? 'var(--down)' : 'var(--accent)' }}/>
                      </div>
                      <span style={{ fontFamily:'var(--font-mono)', fontWeight:700, minWidth:44 }}>{i.weight}%</span>
                    </div>
                  </td>
                  <td style={{ padding:'9px 10px', textAlign:'right', fontFamily:'var(--font-mono)' }}>₩{i.eval_amount.toLocaleString('ko')}</td>
                  <td style={{ padding:'9px 10px', textAlign:'right', fontFamily:'var(--font-mono)',
                               color: i.volatility != null && i.volatility > 50 ? 'var(--down)' : 'var(--fg-1)' }}>
                    {i.volatility != null ? `${i.volatility}%` : '-'}
                  </td>
                  <td style={{ padding:'9px 10px', textAlign:'right', fontFamily:'var(--font-mono)' }}>{i.beta != null ? i.beta.toFixed(2) : '-'}</td>
                  <td style={{ padding:'9px 10px', textAlign:'right', fontFamily:'var(--font-mono)', color:'var(--down)' }}>
                    {i.mdd != null ? `${i.mdd}%` : '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div style={{ display:'grid', gap:16, gridTemplateColumns:'repeat(auto-fit,minmax(320px,1fr))' }}>
        {/* 업종 분포 */}
        <div style={{ ...card, marginBottom:0 }}>
          <div style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)', marginBottom:12 }}>
            <i className="bi bi-pie-chart me-2" style={{ color:'var(--accent)' }}/>업종 분포
          </div>
          {(sectors || []).map(s => (
            <div key={s.sector} style={{ display:'flex', alignItems:'center', gap:10, padding:'5px 0', fontSize:'0.8rem' }}>
              <span style={{ width:110, color:'var(--fg-2)', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{s.sector}</span>
              <div style={{ flex:1, height:10, background:'var(--bg-3)', borderRadius:5, overflow:'hidden' }}>
                <div style={{ width:`${Math.min(s.weight,100)}%`, height:'100%',
                              background: s.weight > 60 ? 'var(--down)' : 'var(--accent)', opacity:0.85 }}/>
              </div>
              <span style={{ width:48, textAlign:'right', fontFamily:'var(--font-mono)', fontWeight:700 }}>{s.weight}%</span>
            </div>
          ))}
        </div>

        {/* 상관관계 히트맵 */}
        {correlation && (
          <div style={{ ...card, marginBottom:0 }}>
            <div style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)', marginBottom:12 }}>
              <i className="bi bi-grid-3x3 me-2" style={{ color:'var(--accent)' }}/>종목 간 상관관계
              <span style={{ fontSize:'0.68rem', color:'var(--fg-3)', fontWeight:400, marginLeft:8 }}>붉을수록 같이 움직임 (분산효과 ↓)</span>
            </div>
            <div style={{ overflowX:'auto' }}>
              <table style={{ borderCollapse:'collapse', fontSize:'0.68rem', fontFamily:'var(--font-mono)' }}>
                <thead>
                  <tr>
                    <th/>
                    {correlation.labels.map(l => (
                      <th key={l} style={{ padding:4, color:'var(--fg-3)', fontWeight:600, maxWidth:54, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{l.slice(0,4)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {correlation.matrix.map((row, i) => (
                    <tr key={i}>
                      <td style={{ padding:'3px 6px', color:'var(--fg-2)', fontWeight:600, whiteSpace:'nowrap' }}>{correlation.labels[i].slice(0,6)}</td>
                      {row.map((v, j) => (
                        <td key={j} style={{ padding:0 }}>
                          <div style={{ width:42, height:26, display:'flex', alignItems:'center', justifyContent:'center',
                                        background: i === j ? 'var(--bg-3)' : corrColor(v),
                                        color: i === j ? 'var(--fg-3)' : 'var(--fg-1)', borderRadius:3, margin:1 }}>
                            {i === j ? '—' : v.toFixed(2)}
                          </div>
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      <div style={{ fontSize:'0.7rem', color:'var(--fg-3)', marginTop:12, textAlign:'right' }}>
        최근 6개월 일봉 기준 · 변동성=연환산 표준편차 · 베타=KOSPI 대비 · HHI=비중² 합계(0~10000)
      </div>
    </StockLayout>
  );
}
