import React, { useState } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

export default function Tax() {
  const [form, setForm] = useState({ buy_price:'', sell_price:'', quantity:'', is_major_shareholder: false });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState('');

  const calc = async e => {
    e.preventDefault(); setLoading(true); setResult(null); setError('');
    try {
      const r = await api.post('/api/tax/calculate', { ...form, buy_price:+form.buy_price, sell_price:+form.sell_price, quantity:+form.quantity });
      setResult(r.data);
    } catch (err) {
      setError(err.response?.data?.error || '계산 실패');
    }
    setLoading(false);
  };

  const f = (v, unit='원') => `${(v||0).toLocaleString('ko')}${unit}`;

  return (
    <StockLayout title="세금 계산기">
      <div style={{ maxWidth:560, margin:'0 auto' }}>
      {error && <div className="alert alert-danger" style={{fontSize:'0.83rem',padding:'10px 14px',marginBottom:12}}>{error}</div>}
        <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'24px', marginBottom:20 }}>
          <div style={{ fontWeight:700, fontSize:'0.9rem', color:'var(--fg-1)', marginBottom:18 }}>
            <i className="bi bi-calculator me-2" style={{ color:'var(--accent)' }}/>국내 주식 세금 계산
          </div>
          <form onSubmit={calc}>
            <div style={{ display:'grid', gap:12, gridTemplateColumns:'1fr 1fr', marginBottom:16 }}>
              {[['buy_price','매수가 (원)','number','70000'],['sell_price','매도가 (원)','number','80000'],['quantity','수량 (주)','number','100']].map(([k,l,t,ph]) => (
                <div key={k}>
                  <label className="form-label" style={{ fontSize:'0.78rem', fontWeight:600, color:'var(--fg-2)' }}>{l}</label>
                  <input className="form-control" type={t} value={form[k]} placeholder={ph}
                    onChange={e => setForm(f=>({...f,[k]:e.target.value}))} required />
                </div>
              ))}
              <div style={{ display:'flex', alignItems:'center', gap:8, gridColumn:'1/-1' }}>
                <input type="checkbox" id="major" checked={form.is_major_shareholder}
                  onChange={e => setForm(f=>({...f,is_major_shareholder:e.target.checked}))}
                  style={{ accentColor:'var(--accent)', width:16, height:16, cursor:'pointer' }} />
                <label htmlFor="major" style={{ fontSize:'0.82rem', color:'var(--fg-2)', cursor:'pointer' }}>대주주 (지분 1% 이상 또는 10억 이상)</label>
              </div>
            </div>
            <button className="btn btn-primary w-100" type="submit" disabled={loading}>
              {loading ? '계산 중...' : '계산하기'}
            </button>
          </form>
        </div>

        {result && (
          <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'24px' }}>
            <div style={{ fontWeight:700, fontSize:'0.9rem', color:'var(--fg-1)', marginBottom:18 }}>계산 결과</div>
            <div style={{ display:'grid', gap:10 }}>
              {[
                ['매수 금액',   f(result.buy_total)],
                ['매도 금액',   f(result.sell_total)],
                ['증권거래세',  f(result.transaction_tax)],
                ['유관기관세',  f(result.securities_tax)],
                ['수수료 합계', f(result.fee)],
                ['양도소득세',  f(result.capital_gains_tax)],
                ['총 비용',     f(result.total_cost)],
              ].map(([l,v]) => (
                <div key={l} style={{ display:'flex', justifyContent:'space-between', padding:'6px 0', borderBottom:'1px solid var(--line-1)', fontSize:'0.83rem' }}>
                  <span style={{ color:'var(--fg-3)' }}>{l}</span>
                  <span style={{ fontFamily:'var(--font-mono)', fontWeight:600, color:'var(--fg-1)' }}>{v}</span>
                </div>
              ))}
            </div>

            <div style={{ marginTop:16, padding:'14px', background:'var(--lime-soft)', border:'1px solid var(--lime-border)', borderRadius:'var(--r-2)' }}>
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                <span style={{ fontWeight:700, color:'var(--fg-1)' }}>실수령 수익</span>
                <span style={{ fontWeight:900, fontSize:'1.3rem', fontFamily:'var(--font-mono)',
                  color: (result.net_profit||0) >= 0 ? 'var(--up)' : 'var(--down)' }}>
                  {(result.net_profit||0) >= 0 ? '+' : ''}{f(result.net_profit)}
                </span>
              </div>
              <div style={{ fontSize:'0.78rem', color:'var(--fg-3)', marginTop:4 }}>
                실수익률: <span style={{ fontFamily:'var(--font-mono)', fontWeight:700, color:(result.net_profit_pct||0)>=0?'var(--up)':'var(--down)' }}>
                  {(result.net_profit_pct||0)>=0?'+':''}{result.net_profit_pct?.toFixed(2)}%
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
    </StockLayout>
  );
}
