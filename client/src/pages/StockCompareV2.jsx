import React, { useState } from 'react';
import {
  Chart as ChartJS,
  CategoryScale, LinearScale, PointElement, LineElement,
  Title, Tooltip, Legend,
} from 'chart.js';
import { Line } from 'react-chartjs-2';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend);

const PALETTE = ['#6366f1','#f59e0b','#10b981','#ef4444','#8b5cf6','#06b6d4','#f43f5e','#84cc16','#f97316','#a855f7'];

const METRICS = [
  { key:'current_price', label:'현재가',   best:null,   fmt:v=>v!=null?v.toLocaleString('ko')+'원':'-' },
  { key:'change_pct',    label:'등락률',   best:'high', fmt:v=>v!=null?`${v>=0?'+':''}${v.toFixed(2)}%`:'-', color:true },
  { key:'per',           label:'PER',      best:'low',  fmt:v=>v!=null?`${v}배`:'-' },
  { key:'pbr',           label:'PBR',      best:'low',  fmt:v=>v!=null?`${v}배`:'-' },
  { key:'eps',           label:'EPS',      best:'high', fmt:v=>v!=null?v.toLocaleString('ko')+'원':'-' },
  { key:'market_cap',    label:'시가총액', best:null,
    fmt:v=>v==null?'-':v>=1e12?`${(v/1e12).toFixed(1)}조`:`${Math.round(v/1e8)}억` },
];

function PerfChart({ stocks }) {
  const labels   = stocks[0]?.dates?.map(d => d.slice(5)) ?? [];
  const datasets = stocks.map((s, i) => ({
    label:            s.name,
    data:             s.normalized,
    borderColor:      PALETTE[i],
    backgroundColor:  PALETTE[i] + '22',
    borderWidth:      2,
    pointRadius:      0,
    pointHoverRadius: 5,
    tension:          0.3,
  }));

  return (
    <div style={{ height: 240 }}>
      <Line
        data={{ labels, datasets }}
        options={{
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { position:'top', labels:{ color:'#94a3b8', font:{size:11}, boxWidth:12, padding:14 } },
            tooltip: {
              backgroundColor:'#1e293b', borderColor:'#334155', borderWidth:1,
              callbacks: { label: ctx => { const d=ctx.parsed.y-100; return ` ${ctx.dataset.label}  ${d>=0?'+':''}${d.toFixed(1)}%`; } },
            },
          },
          scales: {
            x: { ticks:{color:'#64748b',font:{size:10},maxTicksLimit:8,maxRotation:0}, grid:{color:'#1e293b22'} },
            y: { ticks:{color:'#64748b',font:{size:10},callback:v=>`${v>=100?'+':''}${(v-100).toFixed(0)}%`}, grid:{color:'#1e293b22'} },
          },
        }}
      />
    </div>
  );
}

function MetricsTable({ stocks }) {
  const bestOf = m => {
    if (!m.best) return -1;
    const vals = stocks.map(s => s[m.key]).filter(v => v != null);
    if (!vals.length) return -1;
    const t = m.best === 'high' ? Math.max(...vals) : Math.min(...vals);
    return stocks.findIndex(s => s[m.key] === t);
  };

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width:'100%', borderCollapse:'collapse', fontSize:'0.82rem' }}>
        <thead>
          <tr style={{ background:'var(--bg-3)' }}>
            <th style={{ padding:'10px 14px', textAlign:'left', fontWeight:600,
                         color:'var(--fg-3)', position:'sticky', left:0,
                         background:'var(--bg-3)', width:80, whiteSpace:'nowrap' }}>지표</th>
            {stocks.map((s, i) => (
              <th key={s.ticker} style={{ padding:'10px 14px', textAlign:'right', minWidth:120 }}>
                <div style={{ fontWeight:700, color:PALETTE[i], fontSize:'0.83rem' }}>{s.name}</div>
                <div style={{ fontSize:'0.7rem', fontFamily:'var(--font-mono)',
                              color:'var(--fg-3)', fontWeight:400, marginTop:2 }}>
                  {s.ticker?.replace('.KS','').replace('.KQ','')}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {METRICS.map(m => {
            const bi = bestOf(m);
            return (
              <tr key={m.key} style={{ borderBottom:'1px solid var(--line-1)' }}>
                <td style={{ padding:'9px 14px', color:'var(--fg-3)', fontWeight:500,
                             position:'sticky', left:0, background:'var(--bg-2)' }}>{m.label}</td>
                {stocks.map((s, i) => {
                  const v = s[m.key];
                  let clr = 'var(--fg-1)';
                  if (m.color && v!=null) clr = v>0?'#22c55e':v<0?'#ef4444':'var(--fg-2)';
                  else if (bi===i)        clr = PALETTE[i];
                  return (
                    <td key={s.ticker}
                        style={{ padding:'9px 14px', textAlign:'right',
                                 fontFamily:'var(--font-mono)', fontWeight:bi===i?800:600, color:clr }}>
                      {m.fmt(v)}
                      {bi===i && !m.color &&
                        <span style={{ marginLeft:3, fontSize:'0.6rem', opacity:0.6 }}>
                          {m.best==='low'?'▼':'▲'}
                        </span>}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function StockCompareV2() {
  const [inputCodes, setInputCodes] = useState('');
  const [stocks,     setStocks]     = useState([]);
  const [loading,    setLoading]    = useState(false);
  const [error,      setError]      = useState('');

  const compare = async () => {
    const codes = inputCodes.split(/[\s,]+/).map(c => c.trim()).filter(Boolean);
    if (!codes.length) return;

    const invalid = codes.filter(c => !/^\d{6}$/.test(c));
    if (invalid.length) { setError(`잘못된 종목 코드: ${invalid.join(', ')}`); return; }
    if (codes.length > 10) { setError('최대 10개까지 비교 가능합니다.'); return; }

    setError(''); setLoading(true); setStocks([]);

    try {
      // 각 코드의 yfinance ticker 조회
      const lookups = await Promise.all(
        codes.map(code =>
          api.get('/search-stock-kr', { params: { q: code } })
             .then(r => {
               const found = (r.data || []).find(s => s.code === code);
               return found?.ticker ?? (code + '.KS');
             })
             .catch(() => code + '.KS')
        )
      );

      const tickers = lookups.join(',');
      const r = await api.get('/stock-compare-data', { params: { tickers } });
      const items = r.data?.stocks ?? [];
      const ok    = items.filter(i => !i.error);
      const errs  = items.filter(i => i.error);

      if (!ok.length) throw new Error(errs[0]?.error || '데이터를 불러올 수 없습니다.');
      if (errs.length) setError(errs.map(i => `${i.ticker}: ${i.error}`).join(' / '));
      setStocks(ok);
    } catch (e) {
      setError(e.response?.data?.error ?? e.message ?? '데이터 로딩 실패');
    }

    setLoading(false);
  };

  return (
    <StockLayout title="종목 다중 비교">

      {/* 입력 */}
      <div style={{ display:'flex', gap:10, marginBottom:16 }}>
        <input
          className="form-control"
          value={inputCodes}
          onChange={e => setInputCodes(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && compare()}
          placeholder="종목 코드 입력 (쉼표 구분, 예: 005930, 000660, 035720)"
          style={{ flex:1, fontSize:'0.88rem' }}
        />
        <button className="btn btn-primary" onClick={compare}
                disabled={loading || !inputCodes.trim()}
                style={{ whiteSpace:'nowrap', padding:'7px 22px' }}>
          {loading
            ? <><span className="spinner-border spinner-border-sm me-2" role="status" />로딩 중...</>
            : <><i className="bi bi-bar-chart-steps me-2" />비교</>}
        </button>
      </div>

      {error && (
        <div style={{ marginBottom:14, padding:'8px 12px', fontSize:'0.8rem', color:'#ef4444',
                      background:'rgba(239,68,68,0.07)', border:'1px solid rgba(239,68,68,0.2)',
                      borderRadius:'var(--r-2)' }}>
          <i className="bi bi-exclamation-circle me-1"/>{error}
        </div>
      )}

      {/* 결과 */}
      {stocks.length > 0 && (
        <div style={{ display:'flex', flexDirection:'column', gap:16 }}>

          {/* 요약 카드 */}
          <div style={{ display:'grid', gap:10,
                        gridTemplateColumns:`repeat(${Math.min(stocks.length,5)}, 1fr)` }}>
            {stocks.map((s, i) => {
              const chg  = s.change_pct;
              const perf = s.normalized?.at?.(-1);
              return (
                <div key={s.ticker}
                     style={{ background:'var(--bg-2)', borderRadius:'var(--r-2)',
                              border:`1px solid ${PALETTE[i]}44`,
                              borderTop:`3px solid ${PALETTE[i]}`,
                              padding:'12px 14px' }}>
                  <div style={{ fontWeight:700, fontSize:'0.84rem',
                                color:'var(--fg-1)', marginBottom:5 }}>{s.name}</div>
                  <div style={{ fontFamily:'var(--font-mono)', fontWeight:800,
                                fontSize:'1.05rem', color:'var(--fg-1)', marginBottom:4 }}>
                    {s.current_price?.toLocaleString('ko')}원
                  </div>
                  <div style={{ display:'flex', gap:8, fontSize:'0.73rem', fontFamily:'var(--font-mono)' }}>
                    <span style={{ fontWeight:700, color:chg>=0?'#22c55e':'#ef4444' }}>
                      {chg>=0?'+':''}{chg?.toFixed(2)}%
                    </span>
                    {perf!=null && (
                      <span style={{ color:perf>=100?'#22c55e':'#ef4444', fontWeight:700 }}>
                        6mo {perf>=100?'+':''}{(perf-100).toFixed(1)}%
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* 차트 */}
          <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)',
                        borderRadius:'var(--r-3)', padding:'16px 18px' }}>
            <div style={{ fontWeight:700, fontSize:'0.85rem', color:'var(--fg-2)', marginBottom:14 }}>
              6개월 수익률 비교
              <span style={{ fontWeight:400, fontSize:'0.72rem', color:'var(--fg-3)', marginLeft:8 }}>
                시작일 = 100
              </span>
            </div>
            <PerfChart stocks={stocks} />
          </div>

          {/* 지표 테이블 */}
          <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)',
                        borderRadius:'var(--r-3)', overflow:'hidden' }}>
            <div style={{ padding:'12px 16px', borderBottom:'1px solid var(--line-1)',
                          fontWeight:700, fontSize:'0.85rem', color:'var(--fg-2)' }}>
              투자 지표 비교
            </div>
            <MetricsTable stocks={stocks} />
          </div>
        </div>
      )}

      {/* 초기 안내 */}
      {stocks.length === 0 && !loading && (
        <div style={{ textAlign:'center', padding:'70px 0', color:'var(--fg-3)' }}>
          <i className="bi bi-bar-chart-steps"
             style={{ fontSize:'2.5rem', display:'block', marginBottom:12, opacity:0.2 }}/>
          <p style={{ fontSize:'0.88rem', margin:'0 0 6px', color:'var(--fg-2)', fontWeight:600 }}>
            종목 코드를 입력하고 비교 버튼을 누르세요
          </p>
          <p style={{ fontSize:'0.78rem', margin:0, opacity:0.7 }}>
            예: <code style={{ fontFamily:'var(--font-mono)' }}>005930, 000660, 035720</code>
          </p>
        </div>
      )}
    </StockLayout>
  );
}
