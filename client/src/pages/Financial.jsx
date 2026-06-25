import React, { useState, useRef, useEffect, useCallback } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

function FinanceTable({ title, headers, rows }) {
  if (!headers?.length || !rows?.length) return null;
  return (
    <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', overflow:'hidden', marginBottom:16 }}>
      <div style={{ padding:'12px 16px', borderBottom:'1px solid var(--line-1)', fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)' }}>
        {title}
      </div>
      <div style={{ overflowX:'auto' }}>
        <table style={{ width:'100%', borderCollapse:'collapse', fontSize:'0.8rem' }}>
          <thead>
            <tr style={{ background:'var(--bg-3)' }}>
              <th style={{ padding:'8px 12px', textAlign:'left', fontWeight:600, color:'var(--fg-2)', minWidth:80 }}>항목</th>
              {headers.map((h, i) => (
                <th key={i} style={{ padding:'8px 12px', textAlign:'right', fontWeight:600, color: h.isConsensus ? '#38bdf8' : 'var(--fg-2)', fontFamily:'var(--font-mono)' }}>
                  {h.title}{h.isConsensus ? '*' : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} style={{ borderBottom: i < rows.length - 1 ? '1px solid var(--line-1)' : 'none' }}>
                <td style={{ padding:'7px 12px', color:'var(--fg-3)' }}>{row.label}</td>
                {row.values.map((v, j) => (
                  <td key={j} style={{ padding:'7px 12px', textAlign:'right', fontFamily:'var(--font-mono)', fontWeight:600, color: headers[j]?.isConsensus ? '#38bdf8' : 'var(--fg-1)' }}>
                    {v != null ? v.toLocaleString('ko') : '-'}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ padding:'4px 12px 6px', fontSize:'0.68rem', color:'var(--fg-3)', textAlign:'right' }}>
        단위: 억원&nbsp;&nbsp;* 컨센서스 추정치
      </div>
    </div>
  );
}

function EpsChart({ headers, values }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !values?.length) return;
    const ctx    = canvas.getContext('2d');
    const dpr    = window.devicePixelRatio || 1;
    const W      = canvas.clientWidth  * dpr;
    const H      = canvas.clientHeight * dpr;
    canvas.width  = W;
    canvas.height = H;
    ctx.scale(dpr, dpr);
    const cW = canvas.clientWidth;
    const cH = canvas.clientHeight;

    const PAD = { top: 20, bottom: 30, left: 4, right: 4 };
    const valid = values.filter(v => v != null);
    if (!valid.length) return;
    const maxVal = Math.max(...valid);
    const minVal = Math.min(0, ...valid);
    const range  = maxVal - minVal || 1;

    ctx.clearRect(0, 0, cW, cH);

    const n    = values.length;
    const slot = (cW - PAD.left - PAD.right) / n;
    const barW = Math.max(4, slot * 0.6);
    const zeroY = cH - PAD.bottom - (-minVal / range) * (cH - PAD.top - PAD.bottom);

    // Zero line
    ctx.strokeStyle = 'rgba(120,120,120,0.3)';
    ctx.lineWidth   = 1;
    ctx.beginPath();
    ctx.moveTo(PAD.left, zeroY);
    ctx.lineTo(cW - PAD.right, zeroY);
    ctx.stroke();

    values.forEach((v, i) => {
      if (v == null) return;
      const consensus = headers[i]?.isConsensus;
      const cx  = PAD.left + (i + 0.5) * slot;
      const barH = Math.max(2, (Math.abs(v) / range) * (cH - PAD.top - PAD.bottom));
      const y   = v >= 0 ? zeroY - barH : zeroY;

      ctx.fillStyle = consensus ? 'rgba(56,189,248,0.6)' : (v >= 0 ? 'rgba(74,222,128,0.75)' : 'rgba(248,113,113,0.75)');
      ctx.fillRect(cx - barW / 2, y, barW, barH);

      // Quarter label
      ctx.fillStyle  = consensus ? '#38bdf8' : '#888';
      ctx.font       = `${9 * dpr / dpr}px monospace`;
      ctx.textAlign  = 'center';
      ctx.fillText(headers[i]?.title || '', cx, cH - 8);

      // Value label above bar
      const labelY = v >= 0 ? y - 4 : zeroY + barH + 12;
      ctx.fillStyle = consensus ? '#38bdf8' : (v >= 0 ? '#4ade80' : '#f87171');
      ctx.fillText(v.toLocaleString('ko'), cx, labelY);
    });
  }, [headers, values]);

  return (
    <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', overflow:'hidden', marginBottom:16 }}>
      <div style={{ padding:'12px 16px', borderBottom:'1px solid var(--line-1)', fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)' }}>
        EPS 추이 <span style={{ fontSize:'0.72rem', color:'var(--fg-3)', fontWeight:400 }}>(원)</span>
      </div>
      <canvas ref={canvasRef} style={{ width:'100%', height:130, display:'block', padding:'8px 12px', boxSizing:'border-box' }} />
    </div>
  );
}

// ── 주가 캔버스 차트 ──
function PriceChart({ chartData }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !chartData?.length) return;

    const dpr = window.devicePixelRatio || 1;
    const W   = canvas.clientWidth;
    const H   = canvas.clientHeight;
    canvas.width  = W * dpr;
    canvas.height = H * dpr;
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    const PAD = { top: 20, bottom: 36, left: 10, right: 10 };
    const cW  = W - PAD.left - PAD.right;
    const cH  = H - PAD.top  - PAD.bottom;

    const prices = chartData.map(d => d.close);
    const maxP   = Math.max(...prices) * 1.02;
    const minP   = Math.min(...prices) * 0.98;
    const range  = maxP - minP || 1;

    const n    = chartData.length;
    const xPos = i => PAD.left + (i / (n - 1)) * cW;
    const yPos = v => PAD.top + cH - ((v - minP) / range) * cH;

    ctx.clearRect(0, 0, W, H);

    // 그리드
    const gridCnt = 4;
    ctx.strokeStyle = 'rgba(100,100,100,0.12)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= gridCnt; i++) {
      const y = PAD.top + (i / gridCnt) * cH;
      ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(W - PAD.right, y); ctx.stroke();
      const v = maxP - (i / gridCnt) * range;
      ctx.fillStyle = '#666';
      ctx.font = '9px monospace';
      ctx.textAlign = 'right';
      ctx.fillText(v.toLocaleString('ko', { maximumFractionDigits: 0 }), PAD.left - 2, y + 3);
    }

    // 가격 면적 그라디언트
    const grad = ctx.createLinearGradient(0, PAD.top, 0, PAD.top + cH);
    grad.addColorStop(0, 'rgba(56,189,248,0.25)');
    grad.addColorStop(1, 'rgba(56,189,248,0)');
    ctx.beginPath();
    chartData.forEach((d, i) => {
      const x = xPos(i), y = yPos(d.close);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.lineTo(xPos(n - 1), PAD.top + cH);
    ctx.lineTo(xPos(0), PAD.top + cH);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // 가격 라인
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth   = 2;
    ctx.lineJoin    = 'round';
    ctx.beginPath();
    chartData.forEach((d, i) => {
      const x = xPos(i), y = yPos(d.close);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();

    // X축 레이블 (6개월 간격)
    ctx.fillStyle = '#888';
    ctx.font = '9px monospace';
    ctx.textAlign = 'center';
    chartData.forEach((d, i) => {
      if (i % 6 !== 0 && i !== n - 1) return;
      ctx.fillText(d.date.slice(0, 7), xPos(i), H - 8);
    });
  }, [chartData]);

  if (!chartData?.length) return (
    <div style={{ textAlign:'center', padding:'40px 0', color:'var(--fg-3)', fontSize:'0.83rem' }}>차트 데이터 없음</div>
  );

  return (
    <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', overflow:'hidden', marginBottom:16 }}>
      <div style={{ padding:'12px 16px', borderBottom:'1px solid var(--line-1)', fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)' }}>
        주가 추이 <span style={{ fontSize:'0.72rem', color:'var(--fg-3)', fontWeight:400 }}>(3년 월봉 · Yahoo Finance)</span>
      </div>
      <canvas ref={canvasRef} style={{ width:'100%', height:200, display:'block', padding:'8px 20px 4px', boxSizing:'border-box' }} />
    </div>
  );
}

const RATIO_FIELDS = [
  { k: 'per',           label: 'PER',      suffix: '배' },
  { k: 'pbr',           label: 'PBR',      suffix: '배' },
  { k: 'eps',           label: 'EPS',      suffix: '원' },
  { k: 'bps',           label: 'BPS',      suffix: '원' },
  { k: 'est_per',       label: '추정PER',  suffix: '배' },
  { k: 'est_eps',       label: '추정EPS',  suffix: '원' },
  { k: 'dividend',      label: '배당수익률', suffix: '%' },
  { k: 'foreign_ratio', label: '외인비율',  suffix: '%' },
  { k: 'week52_high',   label: '52주최고', suffix: '원' },
  { k: 'week52_low',    label: '52주최저', suffix: '원' },
];

export default function Financial() {
  const [query,        setQuery]        = useState('');
  const [sugg,         setSugg]         = useState([]);
  const [data,         setData]         = useState(null);
  const [loading,      setLoading]      = useState(false);
  const [error,        setError]        = useState('');
  const [tab,          setTab]          = useState('fundamentals'); // 'fundamentals' | 'chart'
  const [chartData,    setChartData]    = useState(null);
  const [chartLoading, setChartLoading] = useState(false);

  const search = async v => {
    if (!v.trim()) { setSugg([]); return; }
    const r = await api.get('/search-stock-kr', { params: { q: v } }).catch(() => ({ data: [] }));
    setSugg(r.data || []);
  };

  const select = async s => {
    setQuery(s.name); setSugg([]); setLoading(true);
    setData(null); setChartData(null); setError(''); setTab('fundamentals');
    try {
      const r = await api.get(`/api/financial/${s.code}`);
      setData(r.data);
    } catch (err) {
      setError(err.response?.data?.error || '데이터 로드 실패');
    }
    setLoading(false);
  };

  const loadChart = useCallback(async (code) => {
    if (chartData || chartLoading) return;
    setChartLoading(true);
    try {
      const r = await api.get(`/api/financial/${code}/chart`);
      setChartData(r.data?.chart || []);
    } catch {
      setChartData([]);
    }
    setChartLoading(false);
  }, [chartData, chartLoading]);

  const handleTabChange = (t) => {
    setTab(t);
    if (t === 'chart' && data?.code) loadChart(data.code);
  };

  return (
    <StockLayout title="기업 실적 분석">
      {error && <div className="alert alert-danger" style={{ fontSize:'0.83rem', padding:'10px 14px', marginBottom:12 }}>{error}</div>}

      <div style={{ position:'relative', marginBottom:24 }}>
        <input className="form-control" value={query}
          onChange={e => { setQuery(e.target.value); search(e.target.value); }}
          placeholder="종목명 검색 (예: 삼성전자)"
          style={{ fontSize:'0.9rem', padding:'10px 14px' }} />
        {sugg.length > 0 && (
          <div className="autocomplete-list" style={{ display:'block', position:'absolute', zIndex:10, top:'100%', left:0, right:0 }}>
            {sugg.slice(0, 8).map(s => (
              <div key={s.code} className="autocomplete-item" onClick={() => select(s)} style={{ cursor:'pointer' }}>
                <span style={{ fontWeight:600 }}>{s.name}</span>
                <span style={{ fontSize:'0.75rem', color:'var(--fg-3)', marginLeft:8, fontFamily:'monospace' }}>{s.code}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {loading && (
        <div style={{ textAlign:'center', padding:'60px 0' }}>
          <div className="spinner" style={{ margin:'0 auto' }} />
        </div>
      )}

      {data && !loading && (
        <>
          {/* 종목 기본 정보 */}
          <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'14px 18px', marginBottom:16, display:'flex', gap:20, flexWrap:'wrap', fontSize:'0.83rem', alignItems:'center' }}>
            <span style={{ fontWeight:800, fontSize:'1rem', color:'var(--fg-1)' }}>{data.name}</span>
            <span style={{ fontFamily:'var(--font-mono)', color:'var(--fg-3)' }}>{data.code}</span>
            {data.price > 0 && (
              <span style={{ fontFamily:'var(--font-mono)', fontWeight:700, color:'var(--accent)' }}>
                {data.price.toLocaleString('ko')}원
              </span>
            )}
            {data.market_cap && (
              <span style={{ color:'var(--fg-3)' }}>시총 {data.market_cap}</span>
            )}
          </div>

          {/* 탭 */}
          <div style={{ display:'flex', gap:6, marginBottom:16, borderBottom:'1px solid var(--line-1)', paddingBottom:0 }}>
            {[
              { key:'fundamentals', label:'실적 분석', icon:'bi-bar-chart' },
              { key:'chart',        label:'주가 차트', icon:'bi-graph-up'  },
            ].map(t => (
              <button key={t.key} onClick={() => handleTabChange(t.key)}
                style={{
                  padding:'8px 16px', border:'none', background:'none', cursor:'pointer',
                  fontWeight:700, fontSize:'0.83rem',
                  color: tab === t.key ? 'var(--accent)' : 'var(--fg-3)',
                  borderBottom: tab === t.key ? '2px solid var(--accent)' : '2px solid transparent',
                  marginBottom:-1,
                }}>
                <i className={`bi ${t.icon} me-1`} />{t.label}
              </button>
            ))}
          </div>

          {tab === 'fundamentals' && (<>
            {/* 투자 지표 카드 */}
            <div style={{ display:'grid', gap:10, gridTemplateColumns:'repeat(auto-fill,minmax(130px,1fr))', marginBottom:16 }}>
              {RATIO_FIELDS.map(({ k, label, suffix }) => {
                const v = data[k];
                if (v == null || v === 0) return null;
                return (
                  <div key={k} style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'12px 14px' }}>
                    <div style={{ fontSize:'0.68rem', color:'var(--fg-3)', fontFamily:'var(--font-mono)', marginBottom:4 }}>{label}</div>
                    <div style={{ fontWeight:700, fontFamily:'var(--font-mono)', fontSize:'0.92rem', color:'var(--fg-1)' }}>
                      {typeof v === 'number' ? v.toLocaleString('ko') : v}{suffix}
                    </div>
                  </div>
                );
              })}
            </div>

            <FinanceTable title="연간 실적" headers={data.annual?.headers} rows={data.annual?.rows} />
            <FinanceTable title="분기 실적" headers={data.quarter?.headers} rows={data.quarter?.rows} />
            {data.epsChart?.values?.length > 0 && (
              <EpsChart headers={data.epsChart.headers} values={data.epsChart.values} />
            )}
          </>)}

          {tab === 'chart' && (
            chartLoading
              ? <div style={{ textAlign:'center', padding:'60px 0' }}><div className="spinner" style={{ margin:'0 auto' }} /></div>
              : <PriceChart chartData={chartData} />
          )}
        </>
      )}

      {!data && !loading && (
        <div style={{ textAlign:'center', padding:'80px 0', color:'var(--fg-3)' }}>
          <i className="bi bi-graph-up" style={{ fontSize:'2.5rem', display:'block', marginBottom:12, opacity:0.3 }} />
          <p style={{ margin:0, fontSize:'0.85rem' }}>종목을 검색하여 기업 실적을 확인하세요.</p>
        </div>
      )}
    </StockLayout>
  );
}
