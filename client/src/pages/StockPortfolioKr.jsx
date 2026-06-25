import React, { useState, useEffect } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

function HoldingRow({ h, onDelete }) {
  const pl   = h.profit ?? 0;
  const plPct = typeof h.profit_rate === 'number' && isFinite(h.profit_rate) ? h.profit_rate : 0;
  return (
    <tr style={{ borderBottom:'1px solid var(--line-1)' }}>
      <td style={{ padding:'10px 12px' }}>
        <div style={{ fontWeight:700, color:'var(--fg-1)' }}>{h.name || h.code}</div>
        <div style={{ fontSize:'0.72rem', color:'var(--fg-3)', fontFamily:'var(--font-mono)' }}>{h.code}</div>
      </td>
      <td style={{ padding:'10px 12px', fontFamily:'var(--font-mono)', textAlign:'right' }}>{h.quantity?.toLocaleString('ko')}</td>
      <td style={{ padding:'10px 12px', fontFamily:'var(--font-mono)', textAlign:'right' }}>{h.avg_price?.toLocaleString('ko')}</td>
      <td style={{ padding:'10px 12px', fontFamily:'var(--font-mono)', textAlign:'right' }}>
        {h.current_price ? h.current_price.toLocaleString('ko') : '-'}
      </td>
      <td style={{ padding:'10px 12px', textAlign:'right' }}>
        <div style={{ fontFamily:'var(--font-mono)', fontWeight:700, color: pl >= 0 ? 'var(--up)' : 'var(--down)' }}>
          {pl >= 0 ? '+' : ''}{pl.toLocaleString('ko')}
        </div>
        <div style={{ fontSize:'0.72rem', fontFamily:'var(--font-mono)', color: plPct >= 0 ? 'var(--up)' : 'var(--down)' }}>
          {plPct >= 0 ? '+' : ''}{plPct.toFixed(2)}%
        </div>
      </td>
      <td style={{ padding:'10px 12px', fontFamily:'var(--font-mono)', textAlign:'right', color:'var(--fg-1)' }}>
        {h.eval_amount ? h.eval_amount.toLocaleString('ko') : (h.avg_price * h.quantity).toLocaleString('ko')}
      </td>
      <td style={{ padding:'10px 12px', textAlign:'center' }}>
        <button onClick={() => onDelete(h.id)} style={{ background:'transparent', border:'none', color:'var(--down)', cursor:'pointer', padding:'3px 6px' }}>
          <i className="bi bi-trash"/>
        </button>
      </td>
    </tr>
  );
}

export default function StockPortfolioKr() {
  const [holdings, setHoldings] = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [showAdd,  setShowAdd]  = useState(false);
  const [form, setForm] = useState({ stock_code:'', quantity:'', avg_price:'' });
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState('');
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState(null);   // { ok:bool, text:str }

  const load = () => {
    setLoading(true);
    api.get('/stock/holdings').then(r => setHoldings(r.data?.holdings || [])).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const syncFromKiwoom = async () => {
    if (syncing) return;
    setSyncing(true);
    setSyncMsg(null);
    try {
      const r = await api.post('/stock/sync', {}, { timeout: 60_000 });
      setSyncMsg({ ok: true, text: r.data?.message || '키움 계좌 동기화 완료' });
      load();
    } catch (err) {
      const msg = err.response?.data?.error || err.message || '동기화에 실패했습니다.';
      setSyncMsg({ ok: false, text: msg });
    }
    setSyncing(false);
  };

  const addHolding = async e => {
    e.preventDefault();
    setAdding(true);
    setAddError('');
    try {
      await api.post('/stock/holdings', { code: form.stock_code, name: form.stock_code, quantity: +form.quantity, avg_price: +form.avg_price });
      setForm({ stock_code:'', quantity:'', avg_price:'' });
      setShowAdd(false);
      load();
    } catch (err) {
      setAddError(err.response?.data?.error || '종목 추가 실패');
    }
    setAdding(false);
  };

  const deleteHolding = async id => {
    if (!confirm('삭제하시겠습니까?')) return;
    try {
      await api.delete(`/stock/holdings/${id}`);
      load();
    } catch (err) {
      alert(err.response?.data?.error || '삭제 실패');
    }
  };

  const totalValue  = holdings.reduce((s, h) => s + (h.eval_amount || h.avg_price * h.quantity || 0), 0);
  const totalCost   = holdings.reduce((s, h) => s + (h.invest || h.avg_price * h.quantity || 0), 0);
  const totalPL     = holdings.reduce((s, h) => s + (h.profit || 0), 0);
  const totalPlPct  = totalCost > 0 ? (totalPL / totalCost * 100) : 0;

  return (
    <StockLayout title="포트폴리오">
      {/* 요약 카드 */}
      <div style={{ display:'grid', gap:12, gridTemplateColumns:'repeat(auto-fill,minmax(180px,1fr))', marginBottom:20 }}>
        {[
          { label:'총 평가금액', value:`₩${totalValue.toLocaleString('ko')}`, good:null },
          { label:'총 투자금액', value:`₩${totalCost.toLocaleString('ko')}`,  good:null },
          { label:'평가 손익',   value:`${totalPL>=0?'+':''}₩${totalPL.toLocaleString('ko')}`, good:totalPL>=0 },
          { label:'수익률',      value:`${totalPlPct>=0?'+':''}${totalPlPct.toFixed(2)}%`, good:totalPlPct>=0 },
        ].map(c => (
          <div key={c.label} style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'14px 16px' }}>
            <div style={{ fontSize:'0.68rem', color:'var(--fg-3)', fontFamily:'var(--font-mono)', textTransform:'uppercase', marginBottom:4 }}>{c.label}</div>
            <div style={{ fontSize:'1.15rem', fontWeight:800, fontFamily:'var(--font-mono)',
              color: c.good == null ? 'var(--fg-1)' : c.good ? 'var(--up)' : 'var(--down)' }}>{c.value}</div>
          </div>
        ))}
      </div>

      {/* 수익 기여도 차트 */}
      {holdings.length > 0 && (
        <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'16px 18px', marginBottom:16 }}>
          <div style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)', marginBottom:14 }}>
            <i className="bi bi-pie-chart me-2" style={{ color:'var(--accent)' }}/>종목별 수익 기여도
          </div>
          <div style={{ display:'grid', gap:8 }}>
            {[...holdings]
              .filter(h => h.profit !== 0 && h.profit != null)
              .sort((a, b) => Math.abs(b.profit || 0) - Math.abs(a.profit || 0))
              .slice(0, 8)
              .map(h => {
                const maxPL = Math.max(...holdings.map(x => Math.abs(x.profit || 0)), 1);
                const barW  = Math.abs(h.profit || 0) / maxPL * 100;
                const isPos = (h.profit || 0) >= 0;
                return (
                  <div key={h.id}>
                    <div style={{ display:'flex', justifyContent:'space-between', fontSize:'0.75rem', marginBottom:3 }}>
                      <span style={{ color:'var(--fg-2)', fontWeight:600 }}>{h.name || h.code}</span>
                      <span style={{ fontFamily:'var(--font-mono)', fontWeight:700, color: isPos ? 'var(--up)' : 'var(--down)' }}>
                        {isPos ? '+' : ''}₩{(h.profit||0).toLocaleString('ko')}
                        {h.profit_rate != null && <span style={{ fontSize:'0.68rem', marginLeft:5, opacity:0.8 }}>({isPos?'+':''}{(+h.profit_rate).toFixed(1)}%)</span>}
                      </span>
                    </div>
                    <div style={{ height:8, background:'var(--line-1)', borderRadius:4, overflow:'hidden' }}>
                      <div style={{ height:'100%', width:`${barW}%`, background: isPos ? 'var(--up)' : 'var(--down)', borderRadius:4, transition:'width 0.4s' }} />
                    </div>
                  </div>
                );
              })}
          </div>
        </div>
      )}

      {/* 보유 테이블 */}
      <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', overflow:'hidden', marginBottom:16 }}>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', padding:'14px 16px', borderBottom:'1px solid var(--line-1)' }}>
          <span style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)' }}>보유 종목 ({holdings.length})</span>
          <div style={{ display:'flex', gap:8 }}>
            <button className="btn btn-outline-primary btn-sm" onClick={syncFromKiwoom} disabled={syncing}>
              <i className={`bi bi-arrow-repeat me-1${syncing ? ' spin' : ''}`}/>{syncing ? '동기화 중...' : '계좌 동기화'}
            </button>
            <button className="btn btn-primary btn-sm" onClick={() => setShowAdd(v=>!v)}>
              <i className="bi bi-plus me-1"/>종목 추가
            </button>
          </div>
        </div>

        {syncMsg && (
          <div style={{ padding:'9px 16px', borderBottom:'1px solid var(--line-1)', fontSize:'0.8rem',
            background: syncMsg.ok ? 'rgba(34,197,94,0.1)' : 'rgba(244,63,94,0.1)',
            color: syncMsg.ok ? 'var(--up)' : 'var(--down)', display:'flex', alignItems:'center', gap:8 }}>
            <i className={`bi ${syncMsg.ok ? 'bi-check-circle-fill' : 'bi-exclamation-triangle-fill'}`}/>
            <span style={{ flex:1 }}>{syncMsg.text}</span>
            {!syncMsg.ok && syncMsg.text.includes('로그인') && (
              <span style={{ fontSize:'0.72rem', color:'var(--fg-3)' }}>← 사이드바 프로필 메뉴에서 키움 API 로그인 후 다시 시도</span>
            )}
            <button onClick={() => setSyncMsg(null)} style={{ background:'none', border:'none', color:'inherit', cursor:'pointer', opacity:0.6 }}>
              <i className="bi bi-x-lg"/>
            </button>
          </div>
        )}

        {showAdd && (
          <form onSubmit={addHolding} style={{ padding:'14px 16px', borderBottom:'1px solid var(--line-1)', background:'var(--bg-3)', display:'flex', gap:10, flexWrap:'wrap', alignItems:'flex-end' }}>
            {addError && (
              <div style={{ width:'100%', padding:'7px 12px', background:'var(--down-soft, #fef2f2)', border:'1px solid var(--down)', borderRadius:'var(--r-2)', fontSize:'0.78rem', color:'var(--down)' }}>
                <i className="bi bi-exclamation-triangle me-1"/>{addError}
              </div>
            )}
            {[['stock_code','코드','text','005930'],['quantity','수량','number','100'],['avg_price','평균단가','number','70000']].map(([k,l,t,ph]) => (
              <div key={k}>
                <label style={{ fontSize:'0.72rem', color:'var(--fg-3)', display:'block', marginBottom:3 }}>{l}</label>
                <input className="form-control" type={t} value={form[k]} placeholder={ph} style={{ width:120, fontSize:'0.82rem' }}
                  onChange={e => setForm(f => ({...f, [k]:e.target.value}))} required />
              </div>
            ))}
            <button className="btn btn-success btn-sm" type="submit" disabled={adding}>추가</button>
            <button className="btn btn-outline-secondary btn-sm" type="button" onClick={() => setShowAdd(false)}>취소</button>
          </form>
        )}

        {loading ? (
          <div style={{ textAlign:'center', padding:'60px 0', color:'var(--fg-3)' }}><div className="spinner" style={{ margin:'0 auto 8px' }}/>로딩 중...</div>
        ) : (
          <div style={{ overflowX:'auto' }}>
            <table style={{ width:'100%', borderCollapse:'collapse', fontSize:'0.82rem' }}>
              <thead>
                <tr style={{ background:'var(--bg-3)' }}>
                  {['종목','수량','평균단가','현재가','손익','평가금액',''].map(h => (
                    <th key={h} style={{ padding:'9px 12px', fontWeight:600, color:'var(--fg-2)', textAlign: h==='종목'||h===''?'left':'right', whiteSpace:'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {holdings.map(h => <HoldingRow key={h.id} h={h} onDelete={deleteHolding} />)}
                {!holdings.length && <tr><td colSpan={7} style={{ textAlign:'center', padding:'48px', color:'var(--fg-3)' }}>보유 종목이 없습니다.</td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </StockLayout>
  );
}
