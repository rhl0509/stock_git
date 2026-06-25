import React, { useState, useEffect } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

export default function PaperTrading() {
  const [account,   setAccount]   = useState(null);
  const [positions, setPositions] = useState([]);
  const [log,       setLog]       = useState([]);
  const [loading,   setLoading]   = useState(true);
  const [form, setForm] = useState({ code:'', name:'', price:'', quantity:'', action:'buy' });
  const [submitting, setSubmitting] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([
      api.get('/api/paper_trading/portfolio').catch(() => ({ data: null })),
      api.get('/api/paper_trading/log').catch(() => ({ data: { logs: [] } })),
    ]).then(([port, lg]) => {
      setAccount(port.data?.account || null);
      setPositions(port.data?.positions || []);
      setLog(lg.data?.logs || []);
    }).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const trade = async e => {
    e.preventDefault(); setSubmitting(true);
    const endpoint = form.action === 'buy' ? '/api/paper_trading/buy' : '/api/paper_trading/sell';
    try {
      await api.post(endpoint, {
        code: form.code, name: form.name,
        price: +form.price, quantity: +form.quantity,
      });
      setForm(f => ({ ...f, code:'', name:'', price:'', quantity:'' }));
      load();
    } catch (err) { alert(err.response?.data?.error || '거래 실패'); }
    setSubmitting(false);
  };

  const reset = async () => {
    if (!confirm('가상매매 계좌를 초기화하시겠습니까?')) return;
    try {
      await api.post('/api/paper_trading/reset');
      load();
    } catch (err) { alert(err.response?.data?.error || '초기화 실패'); }
  };

  const totalEval = account?.total_eval ?? positions.reduce((s, p) => s + (p.eval_amount || 0), 0);

  return (
    <StockLayout title="가상매매">
      {loading ? (
        <div style={{ textAlign:'center', padding:'80px 0' }}><div className="spinner" style={{ margin:'0 auto' }}/></div>
      ) : (
        <div style={{ display:'grid', gap:16 }}>
          {/* 계좌 현황 */}
          {account && (
            <div style={{ display:'grid', gap:12, gridTemplateColumns:'repeat(auto-fill,minmax(180px,1fr))' }}>
              {[
                ['예수금',   `₩${(account.cash ?? 0).toLocaleString('ko')}`],
                ['평가금액', `₩${totalEval.toLocaleString('ko')}`],
                ['평가손익', `${(account.total_profit ?? 0) >= 0 ? '+' : ''}₩${(account.total_profit ?? 0).toLocaleString('ko')}`, (account.total_profit ?? 0) >= 0],
                ['총자산',   `₩${((account.cash ?? 0) + totalEval).toLocaleString('ko')}`],
              ].map(([l, v, g]) => (
                <div key={l} style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'14px 16px' }}>
                  <div style={{ fontSize:'0.68rem', color:'var(--fg-3)', textTransform:'uppercase', fontFamily:'var(--font-mono)', marginBottom:4 }}>{l}</div>
                  <div style={{ fontSize:'1.1rem', fontWeight:800, fontFamily:'var(--font-mono)', color: g == null ? 'var(--fg-1)' : g ? 'var(--up)' : 'var(--down)' }}>{v}</div>
                </div>
              ))}
            </div>
          )}

          {/* 거래 폼 */}
          <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'18px' }}>
            <div style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)', marginBottom:14 }}>모의 거래</div>
            <form onSubmit={trade} style={{ display:'grid', gap:10, gridTemplateColumns:'repeat(auto-fill,minmax(150px,1fr))' }}>
              {[['code','종목코드','text','005930'],['name','종목명','text','삼성전자'],['price','가격','number','70000'],['quantity','수량','number','10']].map(([k,l,t,ph]) => (
                <div key={k}>
                  <label style={{ fontSize:'0.72rem', color:'var(--fg-3)', display:'block', marginBottom:3 }}>{l}</label>
                  <input className="form-control" type={t} value={form[k]} placeholder={ph}
                    onChange={e => setForm(f => ({ ...f, [k]: e.target.value }))} required style={{ fontSize:'0.82rem' }}/>
                </div>
              ))}
              <div>
                <label style={{ fontSize:'0.72rem', color:'var(--fg-3)', display:'block', marginBottom:3 }}>구분</label>
                <select className="form-select" value={form.action} onChange={e => setForm(f => ({ ...f, action: e.target.value }))} style={{ fontSize:'0.82rem' }}>
                  <option value="buy">매수</option>
                  <option value="sell">매도</option>
                </select>
              </div>
              <div style={{ display:'flex', flexDirection:'column', justifyContent:'flex-end', gap:6 }}>
                <button className={`btn btn-sm ${form.action === 'buy' ? 'btn-success' : 'btn-danger'}`} type="submit" disabled={submitting}>
                  {submitting ? '처리 중...' : form.action === 'buy' ? '매수' : '매도'}
                </button>
                <button className="btn btn-outline-secondary btn-sm" type="button" onClick={reset}>초기화</button>
              </div>
            </form>
          </div>

          {/* 보유 포지션 */}
          {positions.length > 0 && (
            <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', overflow:'hidden' }}>
              <div style={{ padding:'12px 16px', borderBottom:'1px solid var(--line-1)', fontWeight:700, fontSize:'0.85rem', color:'var(--fg-1)' }}>보유 포지션</div>
              <table style={{ width:'100%', borderCollapse:'collapse', fontSize:'0.8rem' }}>
                <thead><tr style={{ background:'var(--bg-3)' }}>
                  {['종목','수량','평균단가','현재가','손익','평가금액'].map(h => (
                    <th key={h} style={{ padding:'8px 12px', fontWeight:600, color:'var(--fg-2)', textAlign: h === '종목' ? 'left' : 'right' }}>{h}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {positions.map(p => (
                    <tr key={p.id} style={{ borderBottom:'1px solid var(--line-1)' }}>
                      <td style={{ padding:'8px 12px', fontWeight:700 }}>{p.name || p.code}</td>
                      <td style={{ padding:'8px 12px', textAlign:'right', fontFamily:'var(--font-mono)' }}>{p.quantity}</td>
                      <td style={{ padding:'8px 12px', textAlign:'right', fontFamily:'var(--font-mono)' }}>{p.avg_price?.toLocaleString('ko')}</td>
                      <td style={{ padding:'8px 12px', textAlign:'right', fontFamily:'var(--font-mono)' }}>{p.current_price?.toLocaleString('ko') || '-'}</td>
                      <td style={{ padding:'8px 12px', textAlign:'right', fontFamily:'var(--font-mono)', fontWeight:700, color:(p.profit || 0) >= 0 ? 'var(--up)' : 'var(--down)' }}>
                        {(p.profit || 0) >= 0 ? '+' : ''}{(p.profit || 0).toLocaleString('ko')}
                      </td>
                      <td style={{ padding:'8px 12px', textAlign:'right', fontFamily:'var(--font-mono)' }}>{(p.eval_amount || 0).toLocaleString('ko')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* 거래 이력 */}
          {log.length > 0 && (
            <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', overflow:'hidden' }}>
              <div style={{ padding:'12px 16px', borderBottom:'1px solid var(--line-1)', fontWeight:700, fontSize:'0.85rem', color:'var(--fg-1)' }}>거래 이력</div>
              <div style={{ maxHeight:300, overflowY:'auto' }}>
                <table style={{ width:'100%', borderCollapse:'collapse', fontSize:'0.78rem' }}>
                  <thead><tr style={{ background:'var(--bg-3)', position:'sticky', top:0 }}>
                    {['일시','종목','구분','가격','수량','금액'].map(h => (
                      <th key={h} style={{ padding:'7px 12px', fontWeight:600, color:'var(--fg-2)', textAlign:'left' }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {log.map(l => (
                      <tr key={l.id} style={{ borderBottom:'1px solid var(--line-1)' }}>
                        <td style={{ padding:'7px 12px', fontFamily:'var(--font-mono)', color:'var(--fg-3)', fontSize:'0.72rem' }}>{l.created_at?.slice(0, 16)}</td>
                        <td style={{ padding:'7px 12px', fontWeight:600 }}>{l.name || l.code}</td>
                        <td style={{ padding:'7px 12px', fontWeight:700, color: l.action === 'buy' ? 'var(--up)' : 'var(--down)' }}>{l.action === 'buy' ? '매수' : '매도'}</td>
                        <td style={{ padding:'7px 12px', fontFamily:'var(--font-mono)' }}>{l.price?.toLocaleString('ko')}</td>
                        <td style={{ padding:'7px 12px', fontFamily:'var(--font-mono)' }}>{l.quantity}</td>
                        <td style={{ padding:'7px 12px', fontFamily:'var(--font-mono)' }}>{((l.price ?? 0) * (l.quantity ?? 0)).toLocaleString('ko')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </StockLayout>
  );
}
