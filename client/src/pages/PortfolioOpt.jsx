import React, { useState, useEffect, useRef } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

const MAX_ITEMS = 10;

export default function PortfolioOpt() {
  const [items,   setItems]   = useState(['', '']);
  const [result,  setResult]  = useState(null);
  const [missing, setMissing] = useState([]);
  const [names,   setNames]   = useState({});
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState('opt');
  const [error, setError] = useState('');

  // 자동완성: 활성 입력칸 인덱스와 검색 결과
  const [acIdx,   setAcIdx]   = useState(-1);
  const [acList,  setAcList]  = useState([]);
  const [acHi,    setAcHi]    = useState(-1);   // 키보드 하이라이트 인덱스
  const acTimer = useRef(null);
  const acSeq   = useRef(0);

  const fetchSuggest = (i, q) => {
    const query = q.trim();
    if (acTimer.current) clearTimeout(acTimer.current);
    if (query.length < 1) { setAcIdx(i); setAcList([]); setAcHi(-1); return; }
    const seq = ++acSeq.current;
    acTimer.current = setTimeout(async () => {
      try {
        const r = await api.get('/search-stock-kr', { params: { q: query } });
        if (seq !== acSeq.current) return;  // 오래된 응답 무시
        setAcIdx(i);
        setAcList(Array.isArray(r.data) ? r.data : []);
        setAcHi(-1);
      } catch { setAcList([]); setAcHi(-1); }
    }, 180);
  };

  const pickSuggest = (i, s) => {
    setItem(i, `${s.name} (${s.code})`);
    setAcIdx(-1); setAcList([]); setAcHi(-1);
  };

  // "삼성전자 (005930)" 형태면 코드만 추출, 아니면 입력값 그대로
  const toCode = (s) => { const m = s.match(/\((\d{6})\)\s*$/); return m ? m[1] : s.trim(); };

  const onAcKeyDown = (i, e) => {
    if (acIdx !== i || acList.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setAcHi(h => (h + 1) % acList.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setAcHi(h => (h - 1 + acList.length) % acList.length);
    } else if (e.key === 'Enter') {
      if (acHi >= 0 && acHi < acList.length) { e.preventDefault(); pickSuggest(i, acList[acHi]); }
    } else if (e.key === 'Escape') {
      setAcIdx(-1); setAcList([]); setAcHi(-1);
    }
  };

  useEffect(() => {
    if (tab === 'history')
      api.get('/api/portfolio_opt/history')
        .then(r => setHistory(Array.isArray(r.data) ? r.data : (r.data?.history || [])))
        .catch(() => setError('이력을 불러오지 못했습니다.'));
  }, [tab]);

  const setItem    = (i, v) => setItems(arr => arr.map((x, idx) => idx === i ? v : x));
  const addItem    = () => setItems(arr => arr.length < MAX_ITEMS ? [...arr, ''] : arr);
  const removeItem = (i) => setItems(arr => arr.length > 2 ? arr.filter((_, idx) => idx !== i) : arr);

  const filled = items.map(s => s.trim()).filter(Boolean);

  const runOptimize = async (codes) => {
    if (codes.length < 2) return alert('최소 2개 종목을 입력하세요.');
    setLoading(true); setResult(null); setMissing([]); setNames({});
    try {
      const r = await api.post('/api/portfolio_opt/optimize', { codes });
      setResult(r.data?.result || r.data);
      setMissing(Array.isArray(r.data?.missing) ? r.data.missing : []);
      setNames(r.data?.names || {});
    } catch (e) { alert(e.response?.data?.error || '최적화 실패'); }
    setLoading(false);
  };

  const optimize = () => runOptimize(filled.map(toCode));

  // 이력 항목 클릭 → 해당 종목들로 입력칸 채우고 최적화 탭에서 재실행
  const loadHistory = (h) => {
    const codes = h.codes || [];
    if (codes.length < 2) return;
    setItems(codes.map(c => (h.names?.[c] && h.names[c] !== c) ? `${h.names[c]} (${c})` : c));
    setTab('opt');
    runOptimize(codes);
  };

  const deleteHistory = async (idx) => {
    try {
      await api.delete('/api/portfolio_opt/history', { params: { index: idx } });
      setHistory(arr => arr.filter((_, i) => i !== idx));
    } catch { setError('이력 삭제에 실패했습니다.'); }
  };

  const clearHistory = async () => {
    if (!history.length) return;
    if (!window.confirm('이력을 전체 삭제할까요?')) return;
    try {
      await api.delete('/api/portfolio_opt/history', { params: { all: true } });
      setHistory([]);
    } catch { setError('이력 전체 삭제에 실패했습니다.'); }
  };

  const weights = result?.weights || {};
  const wEntries = Object.entries(weights).map(([k, v]) => [k, Number(v)]).filter(([, v]) => isFinite(v));
  const maxW = wEntries.length ? Math.max(...wEntries.map(([, v]) => v), 0.001) : 0.001;

  return (
    <StockLayout title="포트폴리오 최적화">
      <div style={{ display:'flex', gap:8, marginBottom:20 }}>
        {[['opt','최적화'],['history','이력']].map(([k,l]) => (
          <button key={k} onClick={() => setTab(k)} className={`btn btn-sm ${tab===k?'btn-primary':'btn-outline-secondary'}`}>{l}</button>
        ))}
      </div>

      {tab === 'opt' && (
        <>
          <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'20px', marginBottom:20 }}>
            <div style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)', marginBottom:12 }}>종목 입력</div>
            <div style={{ display:'grid', gap:8 }}>
              {items.map((v, i) => (
                <div key={i} style={{ display:'flex', alignItems:'center', gap:8 }}>
                  <span style={{ width:20, textAlign:'right', fontSize:'0.78rem', color:'var(--fg-3)', fontFamily:'var(--font-mono)' }}>{i+1}</span>
                  <div style={{ flex:1, position:'relative' }}>
                    <input className="form-control" value={v}
                      onChange={e => { setItem(i, e.target.value); fetchSuggest(i, e.target.value); }}
                      onFocus={e => fetchSuggest(i, e.target.value)}
                      onKeyDown={e => onAcKeyDown(i, e)}
                      onBlur={() => setTimeout(() => setAcIdx(c => c === i ? -1 : c), 150)}
                      placeholder="종목코드 또는 종목명 (예: 005930 또는 삼성전자)"
                      autoComplete="off"
                      style={{ width:'100%', fontFamily:'var(--font-mono)' }}/>
                    {acIdx === i && acList.length > 0 && (
                      <div style={{ position:'absolute', top:'calc(100% + 4px)', left:0, right:0, zIndex:20,
                        background:'var(--bg-1)', border:'1px solid var(--line-1)', borderRadius:'var(--r-2)',
                        boxShadow:'0 6px 20px rgba(0,0,0,0.18)', maxHeight:280, overflowY:'auto' }}>
                        {acList.map((s, si) => (
                          <div key={s.code} onMouseDown={e => { e.preventDefault(); pickSuggest(i, s); }}
                            onMouseEnter={() => setAcHi(si)}
                            style={{ display:'flex', alignItems:'center', justifyContent:'space-between', gap:10,
                              padding:'8px 12px', cursor:'pointer', borderBottom:'1px solid var(--line-1)',
                              background: acHi === si ? 'var(--bg-2)' : 'transparent' }}>
                            <span style={{ fontWeight:700, fontSize:'0.84rem', color:'var(--fg-1)', whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>{s.name}</span>
                            <span style={{ display:'flex', gap:8, alignItems:'center', flexShrink:0 }}>
                              <span style={{ fontFamily:'var(--font-mono)', fontSize:'0.76rem', color:'var(--fg-3)' }}>{s.code}</span>
                              <span style={{ fontSize:'0.66rem', color:'var(--fg-3)', border:'1px solid var(--line-1)', borderRadius:4, padding:'1px 5px' }}>{s.market}</span>
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  <button type="button" className="btn btn-sm btn-outline-secondary" onClick={() => removeItem(i)}
                    disabled={items.length <= 2} title="삭제" style={{ width:36 }}>
                    <i className="bi bi-x-lg"/>
                  </button>
                </div>
              ))}
            </div>
            <button type="button" className="btn btn-sm btn-outline-primary mt-2" onClick={addItem} disabled={items.length >= MAX_ITEMS}>
              <i className="bi bi-plus-lg me-1"/>종목 추가 ({items.length}/{MAX_ITEMS})
            </button>
            <div style={{ fontSize:'0.72rem', color:'var(--fg-3)', marginTop:10 }}>최소 2개, 최대 {MAX_ITEMS}개 · 종목코드/종목명 모두 가능 (과거 OHLCV 데이터 필요)</div>
            <button className="btn btn-primary mt-3" onClick={optimize} disabled={loading || filled.length < 2}>
              {loading ? '최적화 중...' : '샤프 비율 최적화'}
            </button>
          </div>

          {missing.length > 0 && (
            <div style={{ padding:'10px 14px', marginBottom:16, background:'var(--down-soft, #fef2f2)', border:'1px solid var(--down)', borderRadius:'var(--r-2)', fontSize:'0.8rem', color:'var(--down)' }}>
              <i className="bi bi-exclamation-triangle me-1"/>
              과거 가격(OHLCV) 데이터가 없어 제외된 종목: {missing.map(c => names[c] && names[c] !== c ? `${names[c]}(${c})` : c).join(', ')}
            </div>
          )}

          {result && (
            <div style={{ display:'grid', gap:16, gridTemplateColumns:'1fr 1fr' }}>
              <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'18px', gridColumn:'1/-1' }}>
                <div style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)', marginBottom:14 }}>최적 비중</div>
                <div style={{ display:'grid', gap:8 }}>
                  {wEntries.sort((a,b) => b[1]-a[1]).map(([code, w]) => {
                    const zero = w < 0.00005;
                    return (
                    <div key={code} style={{ display:'flex', alignItems:'center', gap:12, opacity: zero ? 0.55 : 1 }}>
                      <span style={{ fontFamily:'var(--font-mono)', fontWeight:700, color:'var(--fg-1)', width:120, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }} title={code}>{names[code] || code}</span>
                      <div style={{ flex:1, height:16, background:'var(--line-1)', borderRadius:8, overflow:'hidden' }}>
                        <div style={{ width:`${isFinite(w/maxW) ? (w/maxW)*100 : 0}%`, height:'100%', background:'var(--accent)', borderRadius:8 }}/>
                      </div>
                      {zero && <span style={{ fontSize:'0.66rem', color:'var(--fg-3)' }}>미편입</span>}
                      <span style={{ fontFamily:'var(--font-mono)', fontWeight:700, color: zero ? 'var(--fg-3)' : 'var(--accent)', width:50, textAlign:'right' }}>
                        {(w*100).toFixed(1)}%
                      </span>
                    </div>
                    );
                  })}
                </div>
              </div>

              {/* 서버는 annual_ret/annual_vol을 이미 % 단위로 반환 */}
              {[
                ['예상 연수익률', `${(result.annual_ret ?? 0) >= 0 ? '+' : ''}${(result.annual_ret ?? 0).toFixed(2)}%`, (result.annual_ret ?? 0) > 0],
                ['예상 연변동성', `${(result.annual_vol ?? 0).toFixed(2)}%`, null],
                ['샤프 비율',     (result.sharpe ?? 0).toFixed(3), (result.sharpe ?? 0) > 1],
              ].map(([l,v,g]) => (
                <div key={l} style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'16px' }}>
                  <div style={{ fontSize:'0.68rem', color:'var(--fg-3)', textTransform:'uppercase', fontFamily:'var(--font-mono)', marginBottom:6 }}>{l}</div>
                  <div style={{ fontSize:'1.4rem', fontWeight:800, fontFamily:'var(--font-mono)', color: g == null ? 'var(--fg-1)' : g ? 'var(--up)' : 'var(--down)' }}>{v}</div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {tab === 'history' && (
        <div style={{ display:'grid', gap:10 }}>
          {error && (
            <div style={{ padding:'9px 14px', background:'var(--down-soft, #fef2f2)', border:'1px solid var(--down)', borderRadius:'var(--r-2)', fontSize:'0.82rem', color:'var(--down)' }}>
              <i className="bi bi-exclamation-triangle me-1"/>{error}
            </div>
          )}
          {history.length > 0 && (
            <div style={{ display:'flex', justifyContent:'flex-end' }}>
              <button type="button" className="btn btn-sm btn-outline-danger" onClick={clearHistory}>
                <i className="bi bi-trash me-1"/>전체 삭제
              </button>
            </div>
          )}
          {history.map((h, i) => (
            <div key={h.saved_at || i} onClick={() => loadHistory(h)} title="클릭하면 이 종목들로 다시 최적화"
              style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'14px 16px', cursor:'pointer', transition:'border-color .12s' }}
              onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--accent)'}
              onMouseLeave={e => e.currentTarget.style.borderColor = 'var(--line-1)'}>
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', gap:10, marginBottom:8 }}>
                <span style={{ fontWeight:700, fontSize:'0.85rem', color:'var(--fg-1)' }}>
                  {(h.codes || []).map(c => (h.names?.[c] && h.names[c] !== c) ? `${h.names[c]} (${c})` : c).join(', ')}
                </span>
                <span style={{ display:'flex', alignItems:'center', gap:8, flexShrink:0 }}>
                  <span style={{ fontSize:'0.72rem', color:'var(--fg-3)', fontFamily:'var(--font-mono)' }}>{h.saved_at}</span>
                  <button type="button" className="btn btn-sm btn-outline-secondary"
                    onClick={e => { e.stopPropagation(); deleteHistory(i); }} title="이력 삭제"
                    style={{ width:30, height:30, padding:0, lineHeight:1 }}>
                    <i className="bi bi-trash"/>
                  </button>
                </span>
              </div>
              <div style={{ display:'flex', gap:16, fontSize:'0.78rem', color:'var(--fg-3)' }}>
                <span>샤프: <b style={{ color:'var(--accent)', fontFamily:'var(--font-mono)' }}>{(h.sharpe ?? 0).toFixed(3)}</b></span>
                <span>연수익: <b style={{ color:(h.annual_ret??0)>=0?'var(--up)':'var(--down)', fontFamily:'var(--font-mono)' }}>{(h.annual_ret??0)>=0?'+':''}{(h.annual_ret??0).toFixed(2)}%</b></span>
              </div>
            </div>
          ))}
          {!history.length && <div style={{ textAlign:'center', padding:'60px 0', color:'var(--fg-3)' }}>이력 없음</div>}
        </div>
      )}
    </StockLayout>
  );
}
