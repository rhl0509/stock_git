import React, { useState, useEffect } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

const IMPORTANCE_COLOR = { high: 'var(--down)', medium: 'var(--accent)', low: 'var(--fg-3)' };
const IMPORTANCE_LABEL = { high: '★★★', medium: '★★', low: '★' };

export default function EarningsCalendar() {
  const [events,  setEvents]  = useState([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ event_date:'', event_type:'earnings', title:'', importance:'medium', country:'KR' });

  const load = () => {
    setLoading(true);
    setError(null);
    api.get('/api/agent/events', { params: { upcoming_only: false } })
      .then(r => setEvents(r.data?.events || []))
      .catch(() => { setEvents([]); setError('이벤트 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.'); })
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const handleAdd = async e => {
    e.preventDefault();
    await api.post('/api/agent/events', form);
    setShowAdd(false);
    setForm({ event_date:'', event_type:'earnings', title:'', importance:'medium', country:'KR' });
    load();
  };

  const today = new Date().toISOString().slice(0, 10);
  const upcoming = events.filter(e => e.event_date >= today);
  const past     = events.filter(e => e.event_date < today);

  const EventRow = ({ ev }) => (
    <div style={{ display:'flex', alignItems:'center', gap:12, padding:'10px 12px', borderBottom:'1px solid var(--line-1)', opacity: ev.event_date < today ? 0.6 : 1 }}>
      <div style={{ minWidth:90, fontFamily:'var(--font-mono)', fontSize:'0.78rem', color:'var(--fg-3)' }}>{ev.event_date?.slice(0,10)}</div>
      <div style={{ flexShrink:0, fontSize:'0.72rem', color: IMPORTANCE_COLOR[ev.importance] || 'var(--fg-3)' }}>
        {IMPORTANCE_LABEL[ev.importance] || '★'}
      </div>
      <div style={{ flexShrink:0, background:'var(--bg-3)', borderRadius:'var(--r-1)', padding:'2px 8px', fontSize:'0.68rem', color:'var(--fg-3)' }}>
        {ev.country || 'KR'}
      </div>
      <div style={{ flex:1, fontSize:'0.83rem', fontWeight:600, color:'var(--fg-1)' }}>{ev.title}</div>
      <div style={{ fontSize:'0.7rem', color:'var(--fg-3)' }}>{ev.event_type}</div>
      {ev.notified && <i className="bi bi-check-circle-fill" style={{ color:'var(--up)', fontSize:'0.8rem' }}/>}
    </div>
  );

  return (
    <StockLayout title="실적 · 이벤트 캘린더">
      <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'20px', marginBottom:16 }}>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:16 }}>
          <div style={{ fontWeight:700, fontSize:'0.9rem', color:'var(--fg-1)', display:'flex', alignItems:'center', gap:6 }}>
            <i className="bi bi-calendar-event" style={{ color:'var(--accent)' }}/>예정 이벤트 ({upcoming.length}건)
          </div>
          <button onClick={() => setShowAdd(v => !v)}
            style={{ background:'var(--accent)', color:'#fff', border:'none', borderRadius:'var(--r-2)', padding:'5px 12px', fontSize:'0.78rem', fontWeight:700, cursor:'pointer', display:'flex', alignItems:'center', gap:5 }}>
            <i className="bi bi-plus-lg"/>추가
          </button>
        </div>

        {showAdd && (
          <form onSubmit={handleAdd} style={{ background:'var(--bg-3)', borderRadius:'var(--r-2)', padding:'14px', marginBottom:16, display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(160px,1fr))', gap:10 }}>
            {[['event_date','날짜','date'],['title','제목','text']].map(([k,l,t]) => (
              <div key={k} style={{ gridColumn: k === 'title' ? 'span 2' : undefined }}>
                <label style={{ fontSize:'0.7rem', color:'var(--fg-3)', display:'block', marginBottom:3 }}>{l}</label>
                <input className="form-control" type={t} required={k==='event_date'||k==='title'} value={form[k]}
                  onChange={e => setForm(p => ({...p,[k]:e.target.value}))} />
              </div>
            ))}
            {[['event_type','유형',['earnings','FOMC','CPI','BOK','기타']],
              ['importance','중요도',['high','medium','low']],
              ['country','국가',['KR','US','EU']]
            ].map(([k,l,opts]) => (
              <div key={k}>
                <label style={{ fontSize:'0.7rem', color:'var(--fg-3)', display:'block', marginBottom:3 }}>{l}</label>
                <select className="form-control" value={form[k]} onChange={e => setForm(p => ({...p,[k]:e.target.value}))}>
                  {opts.map(o => <option key={o} value={o}>{o}</option>)}
                </select>
              </div>
            ))}
            <div style={{ gridColumn:'1/-1', display:'flex', gap:8 }}>
              <button type="submit" style={{ background:'var(--accent)', color:'#fff', border:'none', borderRadius:'var(--r-2)', padding:'6px 16px', fontSize:'0.78rem', fontWeight:700, cursor:'pointer' }}>저장</button>
              <button type="button" onClick={() => setShowAdd(false)} style={{ background:'var(--bg-2)', color:'var(--fg-2)', border:'1px solid var(--line-2)', borderRadius:'var(--r-2)', padding:'6px 12px', fontSize:'0.78rem', cursor:'pointer' }}>취소</button>
            </div>
          </form>
        )}

        {error && (
          <div style={{ background:'rgba(244,63,94,0.1)', border:'1px solid var(--down)', borderRadius:'var(--r-2)', padding:'10px 14px', marginBottom:12, color:'var(--down)', fontSize:'0.82rem', display:'flex', alignItems:'center', gap:8 }}>
            <i className="bi bi-exclamation-triangle-fill"/>{error}
          </div>
        )}
        {loading ? (
          <div style={{ textAlign:'center', padding:'40px', color:'var(--fg-3)' }}><div className="spinner" style={{ margin:'0 auto 8px' }}/> 로딩 중...</div>
        ) : upcoming.length === 0 && !error ? (
          <div style={{ textAlign:'center', padding:'30px', color:'var(--fg-3)', fontSize:'0.83rem' }}>예정된 이벤트가 없습니다</div>
        ) : (
          upcoming.map((ev, i) => <EventRow key={i} ev={ev} />)
        )}
      </div>

      {past.length > 0 && (
        <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'16px 20px' }}>
          <div style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-3)', marginBottom:12 }}>
            <i className="bi bi-clock-history me-2"/>지난 이벤트 ({past.length}건)
          </div>
          {past.slice(0, 10).map((ev, i) => <EventRow key={i} ev={ev} />)}
        </div>
      )}
    </StockLayout>
  );
}
