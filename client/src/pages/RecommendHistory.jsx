import React, { useState, useEffect } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

const CATS = [
  { key: 'triple', label: '트리플', color: '#a855f7', desc: '3개 모델 합의' },
  { key: 'daily',  label: '데일리', color: '#22c55e', desc: '단기(1~3일)' },
  { key: 'short',  label: '숏텀',   color: '#38bdf8', desc: '초단기' },
  { key: 'swing',  label: '스윙',   color: '#f59e0b', desc: '중기(1~2주)' },
];

const MODES = [
  { key: 'norm', label: '정규화 추천', icon: 'bi-graph-up', base: '/recommend',     accent: 'var(--accent)' },
  { key: 'abs',  label: '절대값 추천', icon: 'bi-bullseye', base: '/recommend_abs', accent: '#7c3aed' },
];

const fmtDate = d => d?.length === 8 ? `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}` : d;

export default function RecommendHistory() {
  const [mode,      setMode]      = useState('norm');
  const [dates,     setDates]     = useState([]);
  const [selDate,   setSelDate]   = useState(null);
  const [data,      setData]      = useState(null);
  const [loading,   setLoading]   = useState(true);
  const [listError, setListError] = useState('');
  const [dataError, setDataError] = useState('');
  const [cat,       setCat]       = useState('daily');

  const modeCfg = MODES.find(m => m.key === mode) || MODES[0];
  const accent  = modeCfg.accent;

  useEffect(() => {
    setLoading(true);
    setListError('');
    setData(null);
    setSelDate(null);
    api.get(`${modeCfg.base}/history`).then(r => {
      const list = r.data?.dates || [];
      setDates(list);
      if (list.length) setSelDate(list[0]);
    }).catch(() => setListError('날짜 목록을 불러오지 못했습니다.')).finally(() => setLoading(false));
  }, [mode]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selDate) { setData(null); return; }
    let cancelled = false;
    setDataError('');
    api.get(`${modeCfg.base}/history/${selDate}`)
      .then(r => {
        if (cancelled) return;
        setData(r.data);
        // 현재 탭에 데이터 없으면 데이터 있는 첫 카테고리로 이동
        const d = r.data || {};
        if (!(d[cat] || []).length) {
          const first = CATS.find(c => (d[c.key] || []).length);
          if (first) setCat(first.key);
        }
      })
      .catch(() => { if (cancelled) return; setData(null); setDataError('추천 데이터를 불러오지 못했습니다.'); });
    return () => { cancelled = true; };
  }, [selDate, mode]);  // eslint-disable-line react-hooks/exhaustive-deps

  const stocks = (data?.[cat] || []);

  return (
    <StockLayout title="추천 이력">
      {/* 정규화 / 절대값 모드 탭 */}
      <div style={{ display:'flex', gap:8, marginBottom:14 }}>
        {MODES.map(m => {
          const on = mode === m.key;
          return (
            <button key={m.key} onClick={() => setMode(m.key)}
              style={{ display:'flex', alignItems:'center', gap:7, padding:'8px 16px',
                fontSize:'0.83rem', fontWeight:700, borderRadius:'var(--r-2)', cursor:'pointer',
                border:`1px solid ${on ? m.accent : 'var(--line-2)'}`,
                background: on ? `${m.accent}1a` : 'transparent',
                color: on ? m.accent : 'var(--fg-3)' }}>
              <i className={`bi ${m.icon}`}/>{m.label}
            </button>
          );
        })}
      </div>

      <div style={{ display:'grid', gap:16, gridTemplateColumns:'180px 1fr' }}>

        {/* 날짜 목록 */}
        <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', overflow:'hidden', height:'fit-content' }}>
          <div style={{ padding:'12px 14px', borderBottom:'1px solid var(--line-1)', fontWeight:700, fontSize:'0.83rem', color:'var(--fg-1)' }}>날짜 선택</div>
          {listError && <div style={{ padding:'12px 14px', fontSize:'0.78rem', color:'var(--down)' }}><i className="bi bi-exclamation-triangle me-1"/>{listError}</div>}
          {loading ? <div style={{ padding:'24px', textAlign:'center', color:'var(--fg-3)' }}>로딩...</div> : (
            <div style={{ maxHeight:520, overflowY:'auto' }}>
              {dates.map(d => (
                <button key={d} onClick={() => setSelDate(d)}
                  style={{ width:'100%', padding:'9px 14px', textAlign:'left',
                    background: selDate===d?`${accent}1a`:'transparent',
                    border:'none', borderBottom:'1px solid var(--line-1)', cursor:'pointer',
                    color: selDate===d?accent:'var(--fg-2)', fontFamily:'var(--font-mono)', fontSize:'0.82rem' }}>
                  {fmtDate(d)}
                </button>
              ))}
              {!dates.length && <div style={{ padding:'24px', textAlign:'center', color:'var(--fg-3)', fontSize:'0.82rem' }}>이력 없음</div>}
            </div>
          )}
        </div>

        {/* 상세 */}
        <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', overflow:'hidden' }}>
          <div style={{ padding:'12px 16px', borderBottom:'1px solid var(--line-1)', display:'flex', alignItems:'center', gap:12, flexWrap:'wrap' }}>
            <span style={{ fontWeight:700, fontSize:'0.83rem', color:'var(--fg-1)' }}>
              {selDate ? `${fmtDate(selDate)} 추천` : '날짜를 선택하세요'}
            </span>
            {data && (
              <span style={{ fontSize:'0.7rem', color:'var(--fg-3)', fontFamily:'var(--font-mono)' }}>
                생성 {data.generated_at?.slice(0,16).replace('T',' ')} · 유니버스 {data.universe_size?.toLocaleString('ko')}종목
              </span>
            )}
            {/* 카테고리 탭 */}
            <div style={{ display:'flex', gap:4, marginLeft:'auto' }}>
              {CATS.map(c => {
                const n = (data?.[c.key] || []).length;
                return (
                  <button key={c.key} onClick={() => setCat(c.key)} disabled={!n}
                    title={c.desc}
                    style={{ padding:'3px 10px', fontSize:'0.72rem', fontWeight:700, borderRadius:12,
                      border:`1px solid ${cat===c.key ? c.color : 'var(--line-2)'}`,
                      background: cat===c.key ? `${c.color}22` : 'transparent',
                      color: n ? (cat===c.key ? c.color : 'var(--fg-3)') : 'var(--line-2)',
                      cursor: n ? 'pointer' : 'default' }}>
                    {c.label} {n ? n : ''}
                  </button>
                );
              })}
            </div>
          </div>

          {dataError && <div style={{ padding:'10px 16px', fontSize:'0.78rem', color:'var(--down)' }}><i className="bi bi-exclamation-triangle me-1"/>{dataError}</div>}

          <div style={{ overflowX:'auto' }}>
            <table style={{ width:'100%', borderCollapse:'collapse', fontSize:'0.82rem' }}>
              <thead>
                <tr style={{ background:'var(--bg-3)' }}>
                  {['#','종목','당시가','진입가','목표가','손절가','기대수익','신뢰도'].map(h => (
                    <th key={h} style={{ padding:'8px 12px', fontWeight:600, color:'var(--fg-2)', textAlign: ['#','종목'].includes(h)?'left':'right', whiteSpace:'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {stocks.map((s,i) => (
                  <tr key={s.code} style={{ borderBottom:'1px solid var(--line-1)' }}>
                    <td style={{ padding:'8px 12px', color:'var(--fg-3)', fontFamily:'var(--font-mono)', fontSize:'0.72rem' }}>{i+1}</td>
                    <td style={{ padding:'8px 12px' }}>
                      <span style={{ fontWeight:700 }}>{s.name}</span>
                      <span style={{ fontSize:'0.68rem', color:'var(--fg-3)', marginLeft:6, fontFamily:'var(--font-mono)' }}>{s.code}</span>
                    </td>
                    <td style={{ padding:'8px 12px', textAlign:'right', fontFamily:'var(--font-mono)' }}>{s.price?.toLocaleString('ko')}</td>
                    <td style={{ padding:'8px 12px', textAlign:'right', fontFamily:'var(--font-mono)' }}>{s.entry?.toLocaleString('ko')}</td>
                    <td style={{ padding:'8px 12px', textAlign:'right', fontFamily:'var(--font-mono)', color:'var(--up)' }}>{s.target?.toLocaleString('ko')}</td>
                    <td style={{ padding:'8px 12px', textAlign:'right', fontFamily:'var(--font-mono)', color:'var(--down)' }}>{s.stop?.toLocaleString('ko')}</td>
                    <td style={{ padding:'8px 12px', textAlign:'right', fontFamily:'var(--font-mono)', fontWeight:700, color:'var(--up)' }}>
                      {s.expected_return != null ? `+${(s.expected_return*100).toFixed(1)}%` : '-'}
                    </td>
                    <td style={{ padding:'8px 12px', textAlign:'right' }}>
                      <div style={{ display:'flex', alignItems:'center', gap:6, justifyContent:'flex-end' }}>
                        <div style={{ width:48, height:5, background:'var(--bg-3)', borderRadius:3, overflow:'hidden' }}>
                          <div style={{ width:`${Math.round((s.confidence||0)*100)}%`, height:'100%', background:accent }}/>
                        </div>
                        <span style={{ fontFamily:'var(--font-mono)', fontWeight:700, color:accent, minWidth:40 }}>
                          {s.confidence != null ? `${(s.confidence*100).toFixed(0)}%` : '-'}
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
                {!stocks.length && <tr><td colSpan={8} style={{ textAlign:'center', padding:'48px', color:'var(--fg-3)' }}>이 카테고리에 추천 없음</td></tr>}
              </tbody>
            </table>
          </div>
          <div style={{ padding:'8px 16px', fontSize:'0.68rem', color:'var(--fg-3)', textAlign:'right', borderTop:'1px solid var(--line-1)' }}>
            매일 20:00 자동 생성된 ML 추천의 스냅샷 · AI 분석 참고용 · 성과 검증은 "AI 성과" 탭
          </div>
        </div>
      </div>
    </StockLayout>
  );
}
