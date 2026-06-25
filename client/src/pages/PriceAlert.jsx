import React, { useState, useEffect, useRef } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

export default function PriceAlert() {
  const [alerts,  setAlerts]  = useState([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({ code:'', name:'', target_price:'', stop_price:'', note:'' });
  const [adding, setAdding]   = useState(false);
  const [error,   setError]   = useState('');
  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; }, []);

  const load = () => {
    setLoading(true);
    api.get('/api/price_alerts').then(r => {
      if (!mountedRef.current) return;
      setAlerts(r.data?.alerts || []);
    }).catch(err => {
      if (!mountedRef.current) return;
      setError(err.response?.data?.error || '데이터를 불러올 수 없습니다.');
    }).finally(() => { if (mountedRef.current) setLoading(false); });
  };
  useEffect(load, []);

  const add = async e => {
    e.preventDefault(); setAdding(true); setError('');
    try {
      await api.post('/api/price_alerts', {
        code: form.code, name: form.name,
        target_price: form.target_price ? +form.target_price : null,
        stop_price:   form.stop_price   ? +form.stop_price   : null,
        note: form.note || null,
      });
      setForm({ code:'', name:'', target_price:'', stop_price:'', note:'' });
      load();
    } catch (err) {
      setError(err.response?.data?.error || '데이터를 불러올 수 없습니다.');
    }
    setAdding(false);
  };

  const del = async id => {
    try { await api.delete(`/api/price_alerts/${id}`); load(); }
    catch { alert('삭제에 실패했습니다.'); }
  };

  const toggle = async id => {
    try { await api.patch(`/api/price_alert/${id}/toggle`); load(); }
    catch { alert('상태 변경에 실패했습니다.'); }
  };

  return (
    <StockLayout title="가격 알림">
      {error && <div className="alert alert-danger" style={{fontSize:'0.83rem',padding:'10px 14px',marginBottom:12}}>{error}</div>}
      {/* 추가 폼 */}
      <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'18px 20px', marginBottom:20 }}>
        <div style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)', marginBottom:14 }}>알림 추가</div>
        <form onSubmit={add} style={{ display:'grid', gap:10, gridTemplateColumns:'repeat(auto-fill,minmax(160px,1fr))' }}>
          {[['code','종목코드','text','005930'],['name','종목명','text','삼성전자'],['target_price','목표가','number','80000'],['stop_price','손절가','number','60000'],['note','메모','text','']].map(([k,l,t,ph]) => (
            <div key={k}>
              <label style={{ fontSize:'0.72rem', color:'var(--fg-3)', display:'block', marginBottom:3 }}>{l}</label>
              <input className="form-control" type={t} value={form[k]} placeholder={ph}
                onChange={e => setForm(f=>({...f,[k]:e.target.value}))} style={{ fontSize:'0.82rem' }}
                required={k==='code'||k==='name'}/>
            </div>
          ))}
          <div style={{ display:'flex', alignItems:'flex-end' }}>
            <button className="btn btn-primary w-100" type="submit" disabled={adding} style={{ fontSize:'0.82rem' }}>추가</button>
          </div>
        </form>
      </div>

      {/* 알림 목록 */}
      {loading ? (
        <div style={{ textAlign:'center', padding:'60px 0', color:'var(--fg-3)' }}><div className="spinner" style={{ margin:'0 auto 10px' }}/>로딩 중...</div>
      ) : (
        <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', overflow:'hidden' }}>
          <table style={{ width:'100%', borderCollapse:'collapse', fontSize:'0.82rem' }}>
            <thead>
              <tr style={{ background:'var(--bg-3)' }}>
                {['종목','목표가','손절가','메모','활성',''].map(h => (
                  <th key={h} style={{ padding:'9px 12px', fontWeight:600, color:'var(--fg-2)', textAlign:'left' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {alerts.map(a => (
                <tr key={a.id} style={{ borderBottom:'1px solid var(--line-1)', opacity: a.active ? 1 : 0.5 }}>
                  <td style={{ padding:'9px 12px' }}>
                    <div style={{ fontWeight:700, color:'var(--fg-1)' }}>{a.name || a.code}</div>
                    <div style={{ fontSize:'0.7rem', color:'var(--fg-3)', fontFamily:'var(--font-mono)' }}>{a.code}</div>
                  </td>
                  <td style={{ padding:'9px 12px', fontFamily:'var(--font-mono)', fontWeight:700, color:'var(--up)' }}>
                    {a.target_price ? `${a.target_price.toLocaleString('ko')}원` : '-'}
                  </td>
                  <td style={{ padding:'9px 12px', fontFamily:'var(--font-mono)', fontWeight:700, color:'var(--down)' }}>
                    {a.stop_price ? `${a.stop_price.toLocaleString('ko')}원` : '-'}
                  </td>
                  <td style={{ padding:'9px 12px', color:'var(--fg-3)', fontSize:'0.75rem' }}>{a.note || '-'}</td>
                  <td style={{ padding:'9px 12px' }}>
                    <button onClick={() => toggle(a.id)} style={{ background:'none', border:'none', cursor:'pointer', fontSize:'1.1rem', color: a.active ? 'var(--accent)' : 'var(--fg-3)' }}>
                      <i className={`bi bi-toggle-${a.active ? 'on' : 'off'}`}/>
                    </button>
                  </td>
                  <td style={{ padding:'9px 12px' }}>
                    <button onClick={() => del(a.id)} style={{ background:'none', border:'none', color:'var(--down)', cursor:'pointer' }}><i className="bi bi-trash"/></button>
                  </td>
                </tr>
              ))}
              {!alerts.length && <tr><td colSpan={6} style={{ textAlign:'center', padding:'48px', color:'var(--fg-3)' }}>알림이 없습니다.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </StockLayout>
  );
}
