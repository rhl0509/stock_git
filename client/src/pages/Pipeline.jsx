import React, { useState, useEffect, useRef } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

/* ── 종목 검색 자동완성 ─────────────────────────────────────── */
function StockSearch({ onSearch, loading }) {
  const [query,     setQuery]     = useState('');
  const [suggs,     setSuggs]     = useState([]);
  const [selected,  setSelected]  = useState(null);
  const [open,      setOpen]      = useState(false);
  const [searching, setSearching] = useState(false);
  const ref = useRef(null);
  const tmr = useRef(null);

  useEffect(() => {
    const h = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  const onChange = e => {
    const v = e.target.value;
    setQuery(v); setSelected(null);
    clearTimeout(tmr.current);
    if (!v.trim()) { setSuggs([]); setOpen(false); return; }
    tmr.current = setTimeout(async () => {
      setSearching(true);
      try {
        const r = await api.get(`/search-stock-kr?q=${encodeURIComponent(v.trim())}`);
        setSuggs(r.data || []); setOpen((r.data || []).length > 0);
      } catch { setSuggs([]); }
      setSearching(false);
    }, 280);
  };

  const pick = s => { setSelected(s); setQuery(`${s.name} (${s.code})`); setSuggs([]); setOpen(false); };
  const submit = () => { if (selected) onSearch(selected.code, selected.name); };

  return (
    <div ref={ref} style={{ display: 'flex', gap: 8, maxWidth: 580, position: 'relative' }}>
      <div style={{ position: 'relative', flex: 1 }}>
        <i className="bi bi-search" style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--fg-3)', fontSize: '0.9rem', pointerEvents: 'none' }} />
        <input className="form-control" value={query} onChange={onChange}
          onFocus={() => suggs.length > 0 && setOpen(true)}
          onKeyDown={e => { if (e.key === 'Enter') submit(); if (e.key === 'Escape') setOpen(false); }}
          placeholder="종목명 또는 코드 (예: 삼성전자, 005930)" disabled={loading}
          style={{ paddingLeft: 36, fontSize: '0.9rem' }} />
        {searching && <i className="bi bi-arrow-clockwise spin" style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--fg-3)', pointerEvents: 'none' }} />}
        {open && suggs.length > 0 && (
          <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50, background: 'var(--bg-1)', border: '1px solid var(--line-2)', borderRadius: 'var(--r-2)', boxShadow: 'var(--menu-shadow)', marginTop: 4, maxHeight: 240, overflowY: 'auto' }}>
            {suggs.map(s => (
              <button key={s.code} onMouseDown={() => pick(s)}
                style={{ display: 'flex', alignItems: 'center', gap: 10, width: '100%', padding: '9px 14px', border: 'none', background: 'none', cursor: 'pointer' }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-3)'}
                onMouseLeave={e => e.currentTarget.style.background = 'none'}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--fg-3)', minWidth: 52 }}>{s.code}</span>
                <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--fg-1)', flex: 1 }}>{s.name}</span>
                {s.market && <span style={{ fontSize: '0.65rem', color: 'var(--fg-3)', background: 'var(--bg-3)', borderRadius: 4, padding: '1px 6px' }}>{s.market}</span>}
              </button>
            ))}
          </div>
        )}
      </div>
      <button onClick={submit} disabled={!selected || loading}
        style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '0 22px', borderRadius: 'var(--r-2)', border: 'none', background: selected && !loading ? 'var(--accent)' : 'var(--bg-3)', color: selected && !loading ? '#fff' : 'var(--fg-3)', cursor: selected && !loading ? 'pointer' : 'not-allowed', fontSize: '0.88rem', fontWeight: 700, whiteSpace: 'nowrap', transition: 'background 0.15s' }}>
        {loading ? <><i className="bi bi-arrow-clockwise spin" /> 분석 중</> : <><i className="bi bi-diagram-3" /> 분석</>}
      </button>
    </div>
  );
}

/* ── 공통 유틸 ──────────────────────────────────────────────── */
const SUP_COL  = { 원자재:'#f59e0b', 부품:'#3b82f6', 에너지:'#ef4444', 서비스:'#8b5cf6', 인력:'#22c55e' };
const CUST_COL = { B2B:'#3b82f6', B2C:'#22c55e', B2G:'#f59e0b' };
const PROD_COL = { 제품:'#6366f1', 서비스:'#10b981', 솔루션:'#f59e0b' };
const RISK_COL = { 공급망:'#ef4444', 시장:'#f59e0b', 규제:'#8b5cf6', 기술:'#3b82f6', 환율:'#10b981' };
const GROW_ICON = { 성장:'bi-graph-up-arrow', 유지:'bi-dash', 감소:'bi-graph-down-arrow' };
const GROW_COL  = { 성장:'#22c55e', 유지:'#94a3b8', 감소:'#ef4444' };
const CHAIN_META = {
  upstream:   { label:'원재료·부품 제조', icon:'bi-boxes',            color:'#f59e0b' },
  midstream:  { label:'가공·조립·유통',   icon:'bi-arrow-left-right', color:'#3b82f6' },
  downstream: { label:'최종 소비재',       icon:'bi-bag-check',       color:'#22c55e' },
  platform:   { label:'플랫폼·생태계',     icon:'bi-grid',            color:'#8b5cf6' },
};

function Tag({ label, color }) {
  return <span style={{ display:'inline-block', fontSize:'0.65rem', fontWeight:700, padding:'2px 7px', borderRadius:10, background:`${color}18`, color, border:`1px solid ${color}30`, whiteSpace:'nowrap' }}>{label}</span>;
}

function SectionTitle({ icon, label, count, color = 'var(--accent)' }) {
  return (
    <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:12 }}>
      <div style={{ width:30, height:30, borderRadius:'var(--r-2)', background:`${color}15`, border:`1px solid ${color}30`, display:'flex', alignItems:'center', justifyContent:'center' }}>
        <i className={`bi ${icon}`} style={{ color, fontSize:'0.85rem' }} />
      </div>
      <div style={{ fontWeight:700, fontSize:'0.85rem', color:'var(--fg-1)' }}>
        {label}
        {count !== undefined && <span style={{ fontWeight:400, color:'var(--fg-3)', fontSize:'0.75rem', marginLeft:5 }}>({count})</span>}
      </div>
    </div>
  );
}

/* ── 퍼센트 바 ─────────────────────────────────────────────── */
function PctBar({ value, color = 'var(--accent)', max = 100 }) {
  const pct = Math.min(100, Math.round((value / max) * 100));
  return (
    <div style={{ height:5, background:'var(--line-1)', borderRadius:4, overflow:'hidden', marginTop:5 }}>
      <div style={{ height:'100%', width:`${pct}%`, background:color, borderRadius:4, transition:'width 0.4s' }} />
    </div>
  );
}

/* ── 공급망 카드 ────────────────────────────────────────────── */
function SupplierCard({ s }) {
  const c = SUP_COL[s.category] || '#94a3b8';
  return (
    <div style={{ background:'var(--bg-3)', border:`1px solid var(--line-1)`, borderLeft:`3px solid ${c}`, borderRadius:'var(--r-2)', padding:'12px 14px' }}>
      <div style={{ display:'flex', alignItems:'center', gap:6, marginBottom:6, flexWrap:'wrap' }}>
        <Tag label={s.category} color={c} />
        {s.importance === '높음' && <Tag label="핵심" color="#ef4444" />}
        {s.substitutability && <Tag label={`대체성 ${s.substitutability}`} color={s.substitutability==='낮음'?'#ef4444':s.substitutability==='중간'?'#f59e0b':'#22c55e'} />}
      </div>
      <div style={{ fontWeight:700, fontSize:'0.85rem', color:'var(--fg-1)', marginBottom: s.detail ? 4 : 0 }}>{s.name}</div>
      {s.detail && <div style={{ fontSize:'0.72rem', color:'var(--fg-3)', lineHeight:1.5 }}>{s.detail}</div>}
    </div>
  );
}

/* ── 제품 카드 ──────────────────────────────────────────────── */
function ProductCard({ p }) {
  const c = PROD_COL[p.category] || '#6366f1';
  const gc = GROW_COL[p.growth] || '#94a3b8';
  return (
    <div style={{ background:'var(--bg-3)', border:'1px solid var(--line-1)', borderRadius:'var(--r-2)', padding:'13px 15px' }}>
      <div style={{ display:'flex', alignItems:'center', gap:6, marginBottom:7, flexWrap:'wrap' }}>
        <Tag label={p.category} color={c} />
        {p.is_main && <Tag label="주력" color="#f59e0b" />}
        {p.growth && (
          <span style={{ display:'inline-flex', alignItems:'center', gap:3, fontSize:'0.65rem', fontWeight:700, color:gc }}>
            <i className={`bi ${GROW_ICON[p.growth] || 'bi-dash'}`} />{p.growth}
          </span>
        )}
      </div>
      <div style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)', marginBottom:3 }}>{p.name}</div>
      {p.description && <div style={{ fontSize:'0.72rem', color:'var(--fg-3)', marginBottom:6 }}>{p.description}</div>}
      {p.revenue_share > 0 && (
        <>
          <div style={{ display:'flex', justifyContent:'space-between', fontSize:'0.68rem', color:'var(--fg-3)' }}>
            <span>매출 비중</span><span style={{ fontWeight:700, color:c }}>{p.revenue_share}%</span>
          </div>
          <PctBar value={p.revenue_share} color={c} />
        </>
      )}
    </div>
  );
}

/* ── 고객 카드 ──────────────────────────────────────────────── */
function CustomerCard({ c: cust }) {
  const c = CUST_COL[cust.type] || '#94a3b8';
  return (
    <div style={{ background:'var(--bg-3)', border:`1px solid var(--line-1)`, borderLeft:`3px solid ${c}`, borderRadius:'var(--r-2)', padding:'12px 14px' }}>
      <div style={{ display:'flex', alignItems:'center', gap:6, marginBottom:6, flexWrap:'wrap' }}>
        <Tag label={cust.type} color={c} />
        {cust.revenue_contribution && <Tag label={`기여 ${cust.revenue_contribution}`} color={cust.revenue_contribution==='높음'?'#22c55e':cust.revenue_contribution==='중간'?'#f59e0b':'#94a3b8'} />}
        {cust.region && <Tag label={cust.region} color="#8b5cf6" />}
      </div>
      <div style={{ fontWeight:700, fontSize:'0.85rem', color:'var(--fg-1)', marginBottom: cust.description ? 4 : 0 }}>{cust.segment}</div>
      {cust.description && <div style={{ fontSize:'0.72rem', color:'var(--fg-3)', lineHeight:1.5 }}>{cust.description}</div>}
    </div>
  );
}

/* ── 경쟁사 카드 ────────────────────────────────────────────── */
function CompetitorCard({ c: comp }) {
  const thr = comp.threat_level === '높음' ? '#ef4444' : comp.threat_level === '중간' ? '#f59e0b' : '#22c55e';
  return (
    <div style={{ background:'var(--bg-3)', border:'1px solid var(--line-1)', borderRadius:'var(--r-2)', padding:'12px 14px' }}>
      <div style={{ display:'flex', alignItems:'center', gap:6, marginBottom:6 }}>
        <Tag label={comp.country || '해외'} color="#8b5cf6" />
        <Tag label={`위협 ${comp.threat_level}`} color={thr} />
      </div>
      <div style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)', marginBottom: comp.note ? 4 : 0 }}>{comp.name}</div>
      {comp.note && <div style={{ fontSize:'0.72rem', color:'var(--fg-3)', lineHeight:1.5 }}>{comp.note}</div>}
    </div>
  );
}

/* ── 리스크 카드 ────────────────────────────────────────────── */
function RiskCard({ r }) {
  const c = RISK_COL[r.type] || '#94a3b8';
  return (
    <div style={{ background:`${c}08`, border:`1px solid ${c}25`, borderRadius:'var(--r-2)', padding:'12px 14px' }}>
      <div style={{ display:'flex', alignItems:'center', gap:6, marginBottom:5 }}>
        <Tag label={r.type} color={c} />
      </div>
      <div style={{ fontWeight:700, fontSize:'0.83rem', color:'var(--fg-1)', marginBottom: r.description ? 4 : 0 }}>{r.title}</div>
      {r.description && <div style={{ fontSize:'0.72rem', color:'var(--fg-3)', lineHeight:1.5 }}>{r.description}</div>}
    </div>
  );
}

/* ── 지역 매출 바 ───────────────────────────────────────────── */
const GEO_COLORS = ['#6366f1','#3b82f6','#10b981','#f59e0b','#ef4444'];
function GeoBreakdown({ geographies }) {
  if (!geographies?.length) return null;
  return (
    <div>
      {geographies.map((g, i) => (
        <div key={i} style={{ marginBottom: 10 }}>
          <div style={{ display:'flex', justifyContent:'space-between', fontSize:'0.78rem', marginBottom:4 }}>
            <span style={{ fontWeight:600, color:'var(--fg-1)' }}>{g.region}</span>
            <div style={{ display:'flex', alignItems:'center', gap:8 }}>
              {g.note && <span style={{ fontSize:'0.68rem', color:'var(--fg-3)' }}>{g.note}</span>}
              <span style={{ fontWeight:700, color:GEO_COLORS[i % GEO_COLORS.length] }}>{g.share}%</span>
            </div>
          </div>
          <PctBar value={g.share} color={GEO_COLORS[i % GEO_COLORS.length]} />
        </div>
      ))}
    </div>
  );
}

/* ── 파트너십 ───────────────────────────────────────────────── */
function PartnerCard({ p }) {
  const typeColor = { 기술협력:'#3b82f6', 합작투자:'#8b5cf6', 납품계약:'#f59e0b', 유통:'#10b981', 전략적제휴:'#6366f1' };
  const c = typeColor[p.type] || '#94a3b8';
  return (
    <div style={{ background:'var(--bg-3)', border:`1px solid ${c}30`, borderRadius:'var(--r-2)', padding:'10px 14px', display:'flex', gap:10, alignItems:'flex-start' }}>
      <div style={{ width:28, height:28, flexShrink:0, borderRadius:'var(--r-1)', background:`${c}15`, display:'flex', alignItems:'center', justifyContent:'center' }}>
        <i className="bi bi-link-45deg" style={{ color:c, fontSize:'0.85rem' }} />
      </div>
      <div>
        <div style={{ display:'flex', alignItems:'center', gap:6, marginBottom:3 }}>
          <span style={{ fontWeight:700, fontSize:'0.85rem', color:'var(--fg-1)' }}>{p.partner}</span>
          <Tag label={p.type} color={c} />
        </div>
        {p.note && <div style={{ fontSize:'0.72rem', color:'var(--fg-3)', lineHeight:1.5 }}>{p.note}</div>}
      </div>
    </div>
  );
}

/* ── 메인 ────────────────────────────────────────────────────── */
export default function Pipeline() {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState('');

  const search = async (code, name) => {
    setLoading(true); setError(''); setData(null);
    try {
      const r = await api.get(`/api/pipeline/company?code=${code}`);
      setData(r.data);
    } catch (e) {
      setError(e.response?.data?.error || `${name} 분석 실패`);
    }
    setLoading(false);
  };

  const p = data?.pipeline;
  const chain = p?.value_chain_position ? CHAIN_META[p.value_chain_position] : null;

  return (
    <StockLayout title="기업 파이프라인">

      {/* 검색창 */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize:'0.8rem', color:'var(--fg-3)', marginBottom:8 }}>
          기업을 검색하면 공급망·제품·고객군·경쟁사·리스크를 AI로 분석합니다.
        </div>
        <StockSearch onSearch={search} loading={loading} />
      </div>

      {error && (
        <div style={{ padding:'10px 14px', background:'rgba(239,68,68,0.08)', border:'1px solid rgba(239,68,68,0.25)', borderRadius:'var(--r-2)', fontSize:'0.82rem', color:'var(--down)', marginBottom:16 }}>
          <i className="bi bi-exclamation-triangle me-2" />{error}
        </div>
      )}

      {loading && (
        <div style={{ textAlign:'center', padding:'80px 0', color:'var(--fg-3)' }}>
          <div className="spinner" style={{ margin:'0 auto 14px' }} />
          <div style={{ fontSize:'0.85rem' }}>AI가 기업 파이프라인을 분석 중입니다...</div>
          <div style={{ fontSize:'0.75rem', marginTop:6, opacity:0.6 }}>약 20~40초 소요됩니다</div>
        </div>
      )}

      {!loading && data && p && (
        <div style={{ display:'flex', flexDirection:'column', gap:20 }}>

          {/* ── 기업 헤더 ── */}
          <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'20px 24px' }}>
            <div style={{ display:'flex', alignItems:'flex-start', gap:12, flexWrap:'wrap' }}>
              <div style={{ flex:1 }}>
                <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:8, flexWrap:'wrap' }}>
                  <span style={{ fontWeight:800, fontSize:'1.2rem', color:'var(--fg-1)' }}>{data.name}</span>
                  <span style={{ fontFamily:'var(--font-mono)', fontSize:'0.78rem', color:'var(--fg-3)', background:'var(--bg-3)', padding:'2px 8px', borderRadius:'var(--r-1)' }}>{data.code}</span>
                  {data.industry && <span style={{ fontSize:'0.75rem', color:'var(--fg-3)' }}>{data.industry}</span>}
                  {chain && (
                    <span style={{ display:'inline-flex', alignItems:'center', gap:5, fontSize:'0.72rem', fontWeight:700, color:chain.color, background:`${chain.color}15`, border:`1px solid ${chain.color}30`, borderRadius:20, padding:'2px 10px' }}>
                      <i className={`bi ${chain.icon}`} />{chain.label}
                    </span>
                  )}
                </div>
                <div style={{ fontSize:'0.88rem', color:'var(--fg-2)', lineHeight:1.7, marginBottom:8 }}>{p.business_summary}</div>
                {p.founded_context && (
                  <div style={{ fontSize:'0.78rem', color:'var(--fg-3)', marginBottom:8 }}>
                    <i className="bi bi-clock-history me-1" />{p.founded_context}
                  </div>
                )}
                {p.competitive_advantage && (
                  <div style={{ display:'flex', alignItems:'flex-start', gap:6, padding:'8px 12px', background:'rgba(99,102,241,0.06)', borderRadius:'var(--r-2)', border:'1px solid rgba(99,102,241,0.15)' }}>
                    <i className="bi bi-lightning-charge-fill" style={{ color:'var(--accent)', flexShrink:0, marginTop:2 }} />
                    <span style={{ fontSize:'0.82rem', color:'var(--fg-2)' }}>{p.competitive_advantage}</span>
                  </div>
                )}
              </div>
              {data.home_url && (
                <a href={data.home_url.startsWith('http') ? data.home_url : `https://${data.home_url}`}
                  target="_blank" rel="noreferrer"
                  style={{ display:'flex', alignItems:'center', gap:5, fontSize:'0.75rem', color:'var(--accent)', textDecoration:'none', whiteSpace:'nowrap' }}>
                  <i className="bi bi-globe2" />공식 홈페이지
                </a>
              )}
            </div>
          </div>

          {/* ── 핵심 파이프라인: 공급 → 제품 → 고객 ── */}
          <div style={{ display:'grid', gridTemplateColumns:'1fr 32px 1fr 32px 1fr', gap:0, alignItems:'start' }}>

            {/* 공급망 */}
            <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'16px' }}>
              <SectionTitle icon="bi-boxes" label="매입처 · 원자재" count={p.suppliers?.length} color="#f59e0b" />
              <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
                {p.suppliers?.length > 0
                  ? p.suppliers.map((s, i) => <SupplierCard key={i} s={s} />)
                  : <div style={{ textAlign:'center', padding:'20px 0', color:'var(--fg-3)', fontSize:'0.78rem' }}>정보 없음</div>}
              </div>
            </div>

            {/* 화살표 */}
            <div style={{ display:'flex', alignItems:'center', justifyContent:'center', paddingTop:50 }}>
              <i className="bi bi-arrow-right" style={{ fontSize:'1.4rem', color:'var(--line-2)' }} />
            </div>

            {/* 제품·서비스 */}
            <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'16px' }}>
              <SectionTitle icon="bi-building" label="주요 제품 · 서비스" count={p.products?.length} color="#6366f1" />
              <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
                {p.products?.length > 0
                  ? p.products.map((prod, i) => <ProductCard key={i} p={prod} />)
                  : <div style={{ textAlign:'center', padding:'20px 0', color:'var(--fg-3)', fontSize:'0.78rem' }}>정보 없음</div>}
              </div>
            </div>

            {/* 화살표 */}
            <div style={{ display:'flex', alignItems:'center', justifyContent:'center', paddingTop:50 }}>
              <i className="bi bi-arrow-right" style={{ fontSize:'1.4rem', color:'var(--line-2)' }} />
            </div>

            {/* 고객군 */}
            <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'16px' }}>
              <SectionTitle icon="bi-people" label="매출처 · 고객군" count={p.customers?.length} color="#22c55e" />
              <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
                {p.customers?.length > 0
                  ? p.customers.map((c, i) => <CustomerCard key={i} c={c} />)
                  : <div style={{ textAlign:'center', padding:'20px 0', color:'var(--fg-3)', fontSize:'0.78rem' }}>정보 없음</div>}
              </div>
            </div>
          </div>

          {/* ── 하단 4분할: 경쟁사 / 지역매출 / 리스크 / 파트너십 ── */}
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>

            {/* 경쟁사 */}
            {p.competitors?.length > 0 && (
              <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'16px' }}>
                <SectionTitle icon="bi-flag" label="주요 경쟁사" count={p.competitors.length} color="#ef4444" />
                <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
                  {p.competitors.map((c, i) => <CompetitorCard key={i} c={c} />)}
                </div>
              </div>
            )}

            {/* 지역별 매출 */}
            {p.geographies?.length > 0 && (
              <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'16px' }}>
                <SectionTitle icon="bi-geo-alt" label="지역별 매출 비중" color="#3b82f6" />
                <GeoBreakdown geographies={p.geographies} />
              </div>
            )}

            {/* 리스크 */}
            {p.risks?.length > 0 && (
              <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'16px' }}>
                <SectionTitle icon="bi-shield-exclamation" label="주요 리스크" count={p.risks.length} color="#ef4444" />
                <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
                  {p.risks.map((r, i) => <RiskCard key={i} r={r} />)}
                </div>
              </div>
            )}

            {/* 파트너십 */}
            {p.partnerships?.length > 0 && (
              <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'16px' }}>
                <SectionTitle icon="bi-link-45deg" label="주요 파트너십" count={p.partnerships.length} color="#8b5cf6" />
                <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
                  {p.partnerships.map((p2, i) => <PartnerCard key={i} p={p2} />)}
                </div>
              </div>
            )}
          </div>

          {/* 분석 시각 */}
          <div style={{ textAlign:'right', fontSize:'0.7rem', color:'var(--fg-3)' }}>
            <i className="bi bi-robot me-1" />AI 분석 기준: {data.analyzed_at} · 1시간 캐시
          </div>
        </div>
      )}

      {/* 초기 상태 */}
      {!loading && !data && !error && (
        <div style={{ textAlign:'center', padding:'80px 0', color:'var(--fg-3)' }}>
          <i className="bi bi-diagram-3" style={{ fontSize:'3rem', display:'block', marginBottom:14, opacity:0.2 }} />
          <div style={{ fontSize:'0.88rem', marginBottom:6 }}>기업을 검색하세요</div>
          <div style={{ fontSize:'0.78rem', opacity:0.7 }}>공급망 → 제품·서비스 → 고객군 + 경쟁사·리스크·파트너십 분석</div>
        </div>
      )}

    </StockLayout>
  );
}
