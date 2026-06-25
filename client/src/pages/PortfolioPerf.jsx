import React, { useState, useEffect } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

const fmtWon = v => `${v >= 0 ? '+' : ''}₩${Math.abs(v).toLocaleString('ko')}`.replace('+₩', '+₩').replace('-₩', '-₩');
const fmtPct = v => v == null ? '-' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;

export default function PortfolioPerf() {
  const [data,    setData]    = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState('');
  const [expanded, setExpanded] = useState({});   // ym → bool

  const toggle = ym => setExpanded(e => ({ ...e, [ym]: !e[ym] }));

  useEffect(() => {
    api.get('/api/portfolio_perf').then(r => {
      setData(r.data?.monthly || []);
      setSummary(r.data?.summary || null);
    }).catch(err => {
      setError(err.response?.data?.error || '데이터를 불러올 수 없습니다.');
    }).finally(() => setLoading(false));
  }, []);

  const cards = summary ? [
    ['누적 실현손익', fmtWon(summary.total_pnl || 0), (summary.total_pnl || 0) >= 0],
    ['월 승률', `${summary.win_rate ?? 0}%`, (summary.win_rate ?? 0) >= 50],
    ['수익 월 / 매도 월', `${summary.win_months ?? 0} / ${summary.total_months ?? 0}`, null],
    ['거래 월수', `${data.length}개월`, null],
  ] : [];

  return (
    <StockLayout title="월별 성과">
      {error && <div className="alert alert-danger" style={{fontSize:'0.83rem',padding:'10px 14px',marginBottom:12}}>{error}</div>}
      {loading ? (
        <div style={{ textAlign:'center', padding:'80px 0' }}><div className="spinner" style={{ margin:'0 auto' }}/></div>
      ) : (
        <>
          <div style={{ display:'grid', gap:12, gridTemplateColumns:'repeat(auto-fill,minmax(180px,1fr))', marginBottom:20 }}>
            {cards.map(([l,v,g]) => (
              <div key={l} style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'14px 16px' }}>
                <div style={{ fontSize:'0.68rem', color:'var(--fg-3)', textTransform:'uppercase', fontFamily:'var(--font-mono)', marginBottom:4 }}>{l}</div>
                <div style={{ fontSize:'1.2rem', fontWeight:800, fontFamily:'var(--font-mono)', color:g==null?'var(--fg-1)':g?'var(--up)':'var(--down)' }}>{v}</div>
              </div>
            ))}
          </div>

          {data.length > 0 ? (
            <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', overflow:'hidden' }}>
              <table style={{ width:'100%', borderCollapse:'collapse', fontSize:'0.82rem' }}>
                <thead>
                  <tr style={{ background:'var(--bg-3)' }}>
                    {['','월','매수금액','매도금액','실현손익','수익률','KOSPI','거래'].map((h,hi) => (
                      <th key={hi} style={{ padding:'9px 12px', fontWeight:600, color:'var(--fg-2)', textAlign:(h==='월'||h==='')?'left':'right' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.map((d,i) => {
                    const hasTrades = (d.trades || []).length > 0;
                    const isOpen = !!expanded[d.ym];
                    return (
                    <React.Fragment key={i}>
                    <tr onClick={() => hasTrades && toggle(d.ym)}
                      style={{ borderBottom:'1px solid var(--line-1)', cursor: hasTrades ? 'pointer' : 'default', background: isOpen ? 'var(--bg-3)' : 'transparent' }}>
                      <td style={{ padding:'9px 12px', color:'var(--fg-3)', width:28 }}>
                        {hasTrades && <i className={`bi bi-chevron-${isOpen ? 'down' : 'right'}`} style={{ fontSize:'0.7rem' }}/>}
                      </td>
                      <td style={{ padding:'9px 12px', fontFamily:'var(--font-mono)', fontWeight:700, color:'var(--fg-1)' }}>{d.ym}</td>
                      <td style={{ padding:'9px 12px', textAlign:'right', fontFamily:'var(--font-mono)' }}>
                        {d.buy_amt ? `₩${d.buy_amt.toLocaleString('ko')}` : '-'}
                      </td>
                      <td style={{ padding:'9px 12px', textAlign:'right', fontFamily:'var(--font-mono)' }}>
                        {d.sell_amt ? `₩${d.sell_amt.toLocaleString('ko')}` : '-'}
                      </td>
                      <td style={{ padding:'9px 12px', textAlign:'right', fontFamily:'var(--font-mono)', fontWeight:700, color:(d.pnl||0)>=0?'var(--up)':'var(--down)' }}>
                        {d.sell_cnt ? fmtWon(d.pnl || 0) : '-'}
                      </td>
                      <td style={{ padding:'9px 12px', textAlign:'right', fontFamily:'var(--font-mono)', fontWeight:700, color:(d.ret_pct??0)>=0?'var(--up)':'var(--down)' }}>
                        {fmtPct(d.ret_pct)}
                      </td>
                      <td style={{ padding:'9px 12px', textAlign:'right', fontFamily:'var(--font-mono)', color:(d.kospi_ret??0)>=0?'var(--up)':'var(--down)' }}>
                        {fmtPct(d.kospi_ret)}
                      </td>
                      <td style={{ padding:'9px 12px', textAlign:'right', color:'var(--fg-3)' }}>
                        매수 {d.buy_cnt || 0} · 매도 {d.sell_cnt || 0}
                      </td>
                    </tr>
                    {isOpen && hasTrades && (
                      <tr style={{ background:'var(--bg-3)' }}>
                        <td colSpan={8} style={{ padding:'0 12px 12px 40px' }}>
                          <table style={{ width:'100%', borderCollapse:'collapse', fontSize:'0.76rem' }}>
                            <thead>
                              <tr style={{ color:'var(--fg-3)' }}>
                                {['일자','종목','수량','매도단가','실현손익','수익률'].map((h,hi) => (
                                  <th key={hi} style={{ padding:'5px 8px', fontWeight:600, textAlign:(h==='종목'||h==='일자')?'left':'right' }}>{h}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {d.trades.map((t,ti) => (
                                <tr key={ti} style={{ borderTop:'1px solid var(--line-1)' }}>
                                  <td style={{ padding:'5px 8px', fontFamily:'var(--font-mono)', color:'var(--fg-3)' }}>{t.date}</td>
                                  <td style={{ padding:'5px 8px' }}>
                                    <span style={{ color:'var(--fg-1)', fontWeight:600 }}>{t.name}</span>
                                    <span style={{ marginLeft:6, fontFamily:'var(--font-mono)', fontSize:'0.66rem', color:'var(--fg-3)' }}>{t.code}</span>
                                  </td>
                                  <td style={{ padding:'5px 8px', textAlign:'right', fontFamily:'var(--font-mono)' }}>{t.quantity?.toLocaleString('ko')}</td>
                                  <td style={{ padding:'5px 8px', textAlign:'right', fontFamily:'var(--font-mono)' }}>₩{t.sell_price?.toLocaleString('ko')}</td>
                                  <td style={{ padding:'5px 8px', textAlign:'right', fontFamily:'var(--font-mono)', fontWeight:700, color:(t.pnl||0)>=0?'var(--up)':'var(--down)' }}>{fmtWon(t.pnl||0)}</td>
                                  <td style={{ padding:'5px 8px', textAlign:'right', fontFamily:'var(--font-mono)', color:(t.ret_pct??0)>=0?'var(--up)':'var(--down)' }}>{fmtPct(t.ret_pct)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    )}
                    </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
              <div style={{ padding:'6px 12px', fontSize:'0.68rem', color:'var(--fg-3)', textAlign:'right' }}>
                실현손익: FIFO 기준 · 수익률: 실현손익 ÷ 매도분 취득원가
              </div>
            </div>
          ) : (
            <div style={{ textAlign:'center', padding:'80px 0', color:'var(--fg-3)' }}>
              <i className="bi bi-bar-chart-fill" style={{ fontSize:'2.5rem', display:'block', marginBottom:12, opacity:0.3 }}/>
              성과 데이터 없음 — 포트폴리오에서 매수/매도 거래를 기록하면 표시됩니다.
            </div>
          )}
        </>
      )}
    </StockLayout>
  );
}
