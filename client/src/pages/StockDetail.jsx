import React, { useState, useEffect, useRef, useCallback } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

/* ── 포맷 헬퍼 ──────────────────────────────────────────────── */
const fmt  = n => n == null ? '-' : Number(n).toLocaleString('ko');
const fmtF = (n, d = 2) => n == null || n === '' ? '-' : Number(n).toFixed(d);
const fmtB = n => {                             // 억 → 조/억 표시
  if (n == null) return '-';
  const v = Number(n);
  if (v >= 10000) return `${(v / 10000).toFixed(2)}조`;
  return `${fmt(v)}억`;
};
const sign = n => n > 0 ? '+' : '';

/* ── 52주 레인지 바 ─────────────────────────────────────────── */
function RangeBar({ low52, high52, current }) {
  if (!low52 || !high52 || !current) return null;
  const pct = Math.max(0, Math.min(100, ((current - low52) / (high52 - low52)) * 100));
  const color = pct >= 70 ? '#22c55e' : pct <= 30 ? '#ef4444' : '#f59e0b';
  return (
    <div style={{ marginTop: 4 }}>
      <div style={{ position: 'relative', height: 6, background: 'var(--line-1)', borderRadius: 4 }}>
        <div style={{ position: 'absolute', left: 0, top: 0, height: '100%', width: `${pct}%`, background: color, borderRadius: 4 }} />
        <div style={{ position: 'absolute', top: -4, left: `${pct}%`, transform: 'translateX(-50%)', width: 14, height: 14, borderRadius: '50%', background: color, border: '2px solid var(--bg-1)', boxShadow: '0 1px 4px rgba(0,0,0,0.3)' }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 5, fontSize: '0.68rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>
        <span>↓ {fmt(low52)}</span>
        <span style={{ color, fontWeight: 700 }}>{pct.toFixed(0)}%</span>
        <span>↑ {fmt(high52)}</span>
      </div>
    </div>
  );
}

/* ── ML 신호 배지 ───────────────────────────────────────────── */
const ML_META = {
  BUY:     { label: '매수', color: '#22c55e', bg: 'rgba(34,197,94,0.12)',  icon: 'bi-arrow-up-circle-fill' },
  SELL:    { label: '매도', color: '#ef4444', bg: 'rgba(239,68,68,0.12)',  icon: 'bi-arrow-down-circle-fill' },
  HOLD:    { label: '관망', color: '#f59e0b', bg: 'rgba(245,158,11,0.12)', icon: 'bi-dash-circle-fill' },
};

function MlSignal({ signal, score, predReturn, fromCache, modelType }) {
  const m = ML_META[signal] || ML_META.HOLD;
  const scorePct = score != null ? Math.round(score * 100) : null;
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ display: 'inline-flex', alignItems: 'center', gap: 10, padding: '12px 24px', background: m.bg, border: `1.5px solid ${m.color}30`, borderRadius: 'var(--r-3)', marginBottom: 16 }}>
        <i className={`bi ${m.icon}`} style={{ fontSize: '1.6rem', color: m.color }} />
        <div style={{ textAlign: 'left' }}>
          <div style={{ fontWeight: 800, fontSize: '1.3rem', color: m.color }}>{m.label}</div>
          {modelType && <div style={{ fontSize: '0.65rem', color: 'var(--fg-3)', marginTop: 1 }}>{modelType}</div>}
        </div>
      </div>
      {scorePct != null && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', marginBottom: 5 }}>
            <span style={{ color: 'var(--fg-3)' }}>매수 확률</span>
            <span style={{ fontWeight: 700, color: m.color, fontFamily: 'var(--font-mono)' }}>{scorePct}%</span>
          </div>
          <div style={{ height: 8, background: 'var(--line-1)', borderRadius: 4, overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${scorePct}%`, background: m.color, borderRadius: 4 }} />
          </div>
        </div>
      )}
      {predReturn != null && (
        <div style={{ padding: '8px 12px', background: 'var(--bg-3)', borderRadius: 'var(--r-2)', fontSize: '0.83rem' }}>
          <span style={{ color: 'var(--fg-3)' }}>예측 수익률 </span>
          <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', color: predReturn > 0 ? 'var(--up)' : predReturn < 0 ? 'var(--down)' : 'var(--fg-2)' }}>
            {sign(predReturn)}{(predReturn * 100).toFixed(2)}%
          </span>
        </div>
      )}
      {fromCache && <div style={{ fontSize: '0.65rem', color: 'var(--fg-3)', marginTop: 6 }}>캐시 (오늘 학습)</div>}
    </div>
  );
}

/* ── 지표 행 ────────────────────────────────────────────────── */
function MetricRow({ label, value, highlight }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 0', borderBottom: '1px solid var(--line-1)' }}>
      <span style={{ fontSize: '0.78rem', color: 'var(--fg-3)' }}>{label}</span>
      <span style={{ fontSize: '0.82rem', fontWeight: 600, fontFamily: 'var(--font-mono)', color: highlight || 'var(--fg-1)' }}>{value ?? '-'}</span>
    </div>
  );
}

/* ── 재무 카드 ──────────────────────────────────────────────── */
function FinCard({ label, item, color }) {
  if (!item) return null;
  const val = item.thstrm_amount || item.thstrm_add_amount;
  if (!val) return null;
  const n = parseInt(String(val).replace(/,/g, ''), 10);
  const formatted = isNaN(n) ? val : fmtB(Math.round(n / 100000000));
  return (
    <div style={{ background: 'var(--bg-3)', borderRadius: 'var(--r-2)', padding: '12px 14px', borderTop: `3px solid ${color}` }}>
      <div style={{ fontSize: '0.7rem', color: 'var(--fg-3)', marginBottom: 4 }}>{label}</div>
      <div style={{ fontWeight: 700, fontSize: '0.95rem', color, fontFamily: 'var(--font-mono)' }}>{formatted}</div>
      {item.bfefrmtrm_amount && (
        <div style={{ fontSize: '0.65rem', color: 'var(--fg-3)', marginTop: 3, fontFamily: 'var(--font-mono)' }}>
          전년 {fmtB(Math.round(parseInt(String(item.bfefrmtrm_amount).replace(/,/g, ''), 10) / 100000000))}
        </div>
      )}
    </div>
  );
}

/* ── 메인 ────────────────────────────────────────────────────── */
/* ── 공매도 미니바 차트 ───────────────────────────────────────── */
function ShortChart({ series }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!ref.current || !series?.length) return;
    const canvas = ref.current;
    const ctx = canvas.getContext('2d');
    const { width: w, height: h } = canvas;
    const vals = series.map(d => d.ratio ?? 0);
    const max = Math.max(...vals, 0.1);
    ctx.clearRect(0, 0, w, h);
    const bw = w / vals.length - 1;
    vals.forEach((v, i) => {
      const bh = (v / max) * (h - 4);
      ctx.fillStyle = v > (vals[vals.length - 1] * 1.2) ? '#ef4444' : '#8b5cf6';
      ctx.fillRect(i * (bw + 1), h - bh - 2, bw, bh);
    });
  }, [series]);
  return <canvas ref={ref} width={280} height={48} style={{ width: '100%', height: 48, marginTop: 8 }} />;
}

export default function StockDetail() {
  const [query,    setQuery]    = useState('');
  const [sugg,     setSugg]     = useState([]);
  const [selected, setSelected] = useState(null);
  const [price,    setPrice]    = useState(null);
  const [ml,       setMl]       = useState(null);
  const [research, setResearch] = useState(null);
  const [short,    setShort]    = useState(null);
  const [newsData, setNewsData] = useState(null);
  const [loading,  setLoading]  = useState(false);
  const [errors,   setErrors]   = useState({});
  const timerRef = useRef(null);
  const abortRef = useRef(null);

  /* 자동완성 */
  useEffect(() => {
    if (!query.trim()) { setSugg([]); return; }
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      abortRef.current?.abort();
      abortRef.current = new AbortController();
      api.get('/search-stock-kr', { params: { q: query }, signal: abortRef.current.signal })
        .then(r => setSugg(r.data || []))
        .catch(e => { if (e.name !== 'AbortError' && e.name !== 'CanceledError') setSugg([]); });
    }, 200);
    return () => clearTimeout(timerRef.current);
  }, [query]);
  useEffect(() => () => { clearTimeout(timerRef.current); abortRef.current?.abort(); }, []);

  const loadStock = useCallback(async (s) => {
    setSelected(s); setQuery(s.name); setSugg([]);
    setLoading(true); setPrice(null); setMl(null); setResearch(null); setShort(null); setNewsData(null); setErrors({});
    const errs = {};

    const [priceRes, mlRes, researchRes, shortRes, newsRes] = await Promise.allSettled([
      api.get(`/api/kiwoom/price/${s.code}`),
      api.get(`/ml/predict/${s.code}`, { params: { name: s.name } }),
      api.get('/api/company_research', { params: { code: s.code } }),
      api.get(`/api/stock/short/${s.code}`),
      api.get(`/api/stock/news/${s.code}`, { params: { name: s.name } }),
    ]);

    if (priceRes.status === 'fulfilled') setPrice(priceRes.value.data);
    else errs.price = priceRes.reason?.response?.data?.error || '시세 조회 실패';

    if (mlRes.status === 'fulfilled' && mlRes.value.data?.ok !== false) setMl(mlRes.value.data);
    else errs.ml = mlRes.reason?.response?.data?.error || mlRes.value?.data?.error || 'AI 예측 실패';

    if (researchRes.status === 'fulfilled') setResearch(researchRes.value.data);

    if (shortRes.status === 'fulfilled' && shortRes.value.data?.ok) setShort(shortRes.value.data);

    if (newsRes.status === 'fulfilled' && newsRes.value.data?.ok) setNewsData(newsRes.value.data);

    setErrors(errs);
    setLoading(false);
  }, []);

  const chg  = price?.rate ?? 0;
  const isUp = chg > 0, isDn = chg < 0;
  const fin  = research?.financials?.summary;
  const co   = research?.company;

  return (
    <StockLayout title="종목 상세">

      {/* 검색창 */}
      <div style={{ position: 'relative', marginBottom: 24, maxWidth: 480 }}>
        <i className="bi bi-search" style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--fg-3)', pointerEvents: 'none' }} />
        <input className="form-control" value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => e.key === 'Escape' && setSugg([])}
          placeholder="종목명 또는 코드 검색 (예: 삼성전자, 005930)"
          style={{ paddingLeft: 36, fontSize: '0.9rem' }} />
        {sugg.length > 0 && (
          <div style={{ position: 'absolute', zIndex: 20, top: '100%', left: 0, right: 0, background: 'var(--bg-1)', border: '1px solid var(--line-2)', borderRadius: 'var(--r-2)', boxShadow: 'var(--menu-shadow)', marginTop: 4, maxHeight: 260, overflowY: 'auto' }}>
            {sugg.slice(0, 8).map(s => (
              <button key={s.code} onClick={() => loadStock(s)}
                style={{ display: 'flex', alignItems: 'center', gap: 10, width: '100%', padding: '9px 14px', border: 'none', background: 'none', cursor: 'pointer' }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-3)'}
                onMouseLeave={e => e.currentTarget.style.background = 'none'}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--fg-3)', minWidth: 52 }}>{s.code}</span>
                <span style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--fg-1)', flex: 1 }}>{s.name}</span>
                {s.market && <span style={{ fontSize: '0.65rem', color: 'var(--fg-3)', background: 'var(--bg-3)', borderRadius: 4, padding: '1px 6px' }}>{s.market}</span>}
              </button>
            ))}
          </div>
        )}
      </div>

      {loading && <div style={{ textAlign: 'center', padding: '80px 0' }}><div className="spinner" style={{ margin: '0 auto' }} /></div>}

      {selected && !loading && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* ── 가격 헤더 ── */}
          <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '20px 24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                  <h2 style={{ margin: 0, fontWeight: 800, fontSize: '1.25rem', color: 'var(--fg-1)' }}>{selected.name}</h2>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', color: 'var(--fg-3)', background: 'var(--bg-3)', padding: '2px 8px', borderRadius: 'var(--r-1)' }}>{selected.code}</span>
                </div>
                {co?.induty_code && <div style={{ fontSize: '0.75rem', color: 'var(--fg-3)' }}>{co.induty_code}</div>}
                {price?.price_source && (
                  <span style={{ fontSize: '0.65rem', color: 'var(--fg-3)', background: 'var(--bg-3)', border: '1px solid var(--line-1)', borderRadius: 10, padding: '1px 7px', display: 'inline-block', marginTop: 4 }}>
                    {price.price_source}
                  </span>
                )}
              </div>
              {price && (
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '2rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: 'var(--fg-1)', lineHeight: 1 }}>
                    {fmt(price.price)}<span style={{ fontSize: '0.9rem', color: 'var(--fg-3)', marginLeft: 4 }}>원</span>
                  </div>
                  <div style={{ fontSize: '0.95rem', fontWeight: 700, fontFamily: 'var(--font-mono)', marginTop: 4, color: isUp ? 'var(--up)' : isDn ? 'var(--down)' : 'var(--fg-3)' }}>
                    {isUp ? '▲' : isDn ? '▼' : ''} {Math.abs(chg).toFixed(2)}%
                    <span style={{ fontSize: '0.82rem', marginLeft: 6 }}>({sign(price.change)}{fmt(price.change)})</span>
                  </div>
                </div>
              )}
            </div>

            {/* OHLCV + 52주 */}
            {price && (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 16 }}>
                  {[['시가', price.open], ['고가', price.high, 'var(--up)'], ['저가', price.low, 'var(--down)'], ['거래량', fmt(price.volume)]].map(([l, v, c]) => (
                    <div key={l} style={{ background: 'var(--bg-3)', borderRadius: 'var(--r-2)', padding: '8px 12px' }}>
                      <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)', marginBottom: 3 }}>{l}</div>
                      <div style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', fontSize: '0.85rem', color: c || 'var(--fg-1)' }}>
                        {l === '거래량' ? v : fmt(v)}
                      </div>
                    </div>
                  ))}
                </div>
                {price.week52_high && (
                  <div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--fg-3)', marginBottom: 4 }}>52주 범위</div>
                    <RangeBar low52={price.week52_low} high52={price.week52_high} current={price.price} />
                  </div>
                )}
              </>
            )}
            {errors.price && <div style={{ fontSize: '0.78rem', color: 'var(--down)', marginTop: 8 }}><i className="bi bi-exclamation-circle me-1" />{errors.price}</div>}
          </div>

          {/* ── 지표 + AI 예측 ── */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>

            {/* 투자 지표 */}
            <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '16px 18px' }}>
              <div style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--fg-1)', marginBottom: 12 }}>
                <i className="bi bi-bar-chart me-2" style={{ color: 'var(--accent)' }} />투자 지표
              </div>
              {price && <>
                <MetricRow label="시가총액"     value={fmtB(price.market_cap)} />
                <MetricRow label="PER"          value={fmtF(price.per)} />
                <MetricRow label="PBR"          value={fmtF(price.pbr)} />
                <MetricRow label="EPS"          value={fmt(price.eps)} />
                <MetricRow label="BPS"          value={fmt(price.bps)} />
                <MetricRow label="배당수익률"   value={price.dividend ? `${fmtF(price.dividend)}%` : '-'} />
                <MetricRow label="외국인 비중"  value={price.foreign_ratio ? `${fmtF(price.foreign_ratio)}%` : '-'} highlight={price.foreign_ratio > 50 ? 'var(--up)' : undefined} />
                <MetricRow label="52주 최고"    value={fmt(price.week52_high)} highlight="var(--up)" />
                <MetricRow label="52주 최저"    value={fmt(price.week52_low)}  highlight="var(--down)" />
              </>}
              {co?.hm_url && (
                <a href={co.hm_url.startsWith('http') ? co.hm_url : `https://${co.hm_url}`}
                  target="_blank" rel="noreferrer"
                  style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: '0.73rem', color: 'var(--accent)', textDecoration: 'none', marginTop: 12 }}>
                  <i className="bi bi-globe2" />공식 홈페이지
                </a>
              )}
            </div>

            {/* AI 예측 */}
            <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '16px 18px' }}>
              <div style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--fg-1)', marginBottom: 16 }}>
                <i className="bi bi-cpu me-2" style={{ color: 'var(--accent)' }} />AI 예측
              </div>
              {ml ? (
                <MlSignal
                  signal={ml.signal}
                  score={ml.score}
                  predReturn={ml.pred_return}
                  fromCache={ml.from_cache}
                  modelType={ml.model_type}
                />
              ) : (
                <div style={{ textAlign: 'center', padding: '30px 0', color: 'var(--fg-3)' }}>
                  <i className="bi bi-exclamation-circle" style={{ fontSize: '1.5rem', display: 'block', marginBottom: 8, opacity: 0.4 }} />
                  <div style={{ fontSize: '0.78rem' }}>{errors.ml || '예측 데이터 없음'}</div>
                  <div style={{ fontSize: '0.7rem', marginTop: 4, opacity: 0.7 }}>키움 로그인 후 정확도 향상</div>
                </div>
              )}
            </div>
          </div>

          {/* ── 공매도 잔고 + 뉴스 감성 ── */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>

            {/* 공매도 잔고 비율 */}
            <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '16px 18px' }}>
              <div style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--fg-1)', marginBottom: 12 }}>
                <i className="bi bi-graph-down-arrow me-2" style={{ color: '#8b5cf6' }} />공매도 잔고
              </div>
              {short ? (
                <>
                  <div style={{ display: 'flex', gap: 16, marginBottom: 8 }}>
                    <div>
                      <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)' }}>잔고비율</div>
                      <div style={{ fontSize: '1.1rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: '#8b5cf6' }}>
                        {short.latest_ratio != null ? `${short.latest_ratio.toFixed(2)}%` : '-'}
                      </div>
                    </div>
                    <div>
                      <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)' }}>잔고수량</div>
                      <div style={{ fontSize: '0.9rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--fg-2)' }}>
                        {short.latest_balance != null ? short.latest_balance.toLocaleString('ko') : '-'}
                      </div>
                    </div>
                  </div>
                  {short.series?.length > 1 && <ShortChart series={short.series} />}
                  <div style={{ fontSize: '0.65rem', color: 'var(--fg-3)', marginTop: 6 }}>최근 {short.series?.length ?? 0}거래일 기준</div>
                </>
              ) : (
                <div style={{ textAlign: 'center', padding: '24px 0', color: 'var(--fg-3)', fontSize: '0.78rem' }}>데이터 없음</div>
              )}
            </div>

            {/* 뉴스 감성 */}
            <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '16px 18px' }}>
              <div style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--fg-1)', marginBottom: 12 }}>
                <i className="bi bi-newspaper me-2" style={{ color: 'var(--accent)' }} />최근 뉴스
              </div>
              {newsData?.items?.length ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                  {newsData.items.slice(0, 6).map((n, i) => (
                    <a key={i} href={n.url} target="_blank" rel="noreferrer"
                      style={{ textDecoration: 'none', display: 'flex', alignItems: 'flex-start', gap: 7 }}>
                      <span style={{
                        flexShrink: 0, marginTop: 2, width: 8, height: 8, borderRadius: '50%',
                        background: n.sentiment === 'pos' ? 'var(--up)' : n.sentiment === 'neg' ? 'var(--down)' : 'var(--fg-3)',
                        display: 'inline-block',
                      }} />
                      <span style={{ fontSize: '0.75rem', color: 'var(--fg-2)', lineHeight: 1.4,
                        overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                        {n.title}
                      </span>
                    </a>
                  ))}
                  <div style={{ fontSize: '0.65rem', color: 'var(--fg-3)', marginTop: 4, display: 'flex', gap: 10 }}>
                    {['pos','neg','neu'].map(s => {
                      const cnt = newsData.items.filter(n => n.sentiment === s).length;
                      const label = s === 'pos' ? '긍정' : s === 'neg' ? '부정' : '중립';
                      const color = s === 'pos' ? 'var(--up)' : s === 'neg' ? 'var(--down)' : 'var(--fg-3)';
                      return <span key={s} style={{ color }}>{label} {cnt}</span>;
                    })}
                  </div>
                </div>
              ) : (
                <div style={{ textAlign: 'center', padding: '24px 0', color: 'var(--fg-3)', fontSize: '0.78rem' }}>뉴스 없음</div>
              )}
            </div>
          </div>

          {/* ── 재무 요약 (DART) ── */}
          {fin && (
            <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '16px 18px' }}>
              <div style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--fg-1)', marginBottom: 12 }}>
                <i className="bi bi-graph-up me-2" style={{ color: 'var(--accent)' }} />
                재무 요약
                {research?.financials?.year && <span style={{ fontWeight: 400, fontSize: '0.72rem', color: 'var(--fg-3)', marginLeft: 6 }}>{research.financials.year}년 {research.financials.fs_div === 'CFS' ? '연결' : '별도'}</span>}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 10 }}>
                <FinCard label="매출액"   item={fin.revenue}           color="#3b82f6" />
                <FinCard label="영업이익" item={fin.oper_income}        color="#22c55e" />
                <FinCard label="당기순이익" item={fin.net_income}       color="#10b981" />
                <FinCard label="자산총계" item={fin.total_assets}       color="#8b5cf6" />
                <FinCard label="자본총계" item={fin.total_equity}       color="#6366f1" />
                <FinCard label="부채총계" item={fin.total_liabilities}  color="#ef4444" />
              </div>
            </div>
          )}

        </div>
      )}

      {/* 초기 상태 */}
      {!selected && !loading && (
        <div style={{ textAlign: 'center', padding: '80px 0', color: 'var(--fg-3)' }}>
          <i className="bi bi-zoom-in" style={{ fontSize: '2.5rem', display: 'block', marginBottom: 12, opacity: 0.25 }} />
          <p style={{ fontSize: '0.85rem', margin: 0 }}>종목을 검색하여 상세 정보를 확인하세요</p>
          <p style={{ fontSize: '0.75rem', marginTop: 6, opacity: 0.7 }}>시세 · 투자지표 · AI 예측 · 재무요약 제공</p>
        </div>
      )}

    </StockLayout>
  );
}
