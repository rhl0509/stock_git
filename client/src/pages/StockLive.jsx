import React, { useState, useEffect, useRef } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

function useDebounce(v, ms) {
  const [dv, setDv] = useState(v);
  useEffect(() => { const t = setTimeout(() => setDv(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return dv;
}

const fmt억 = v => {
  if (v == null) return '-';
  const abs = Math.abs(v);
  const str = abs >= 10000
    ? `${(abs / 10000).toFixed(1)}조`
    : `${Math.round(abs).toLocaleString('ko')}억`;
  return (v > 0 ? '+' : v < 0 ? '-' : '') + str;
};

// ── 거시지표 미니차트 ──────────────────────────────────────────────────────────
function MiniChart({ data, color }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!ref.current || !data?.length) return;
    const canvas = ref.current;
    const ctx = canvas.getContext('2d');
    // 고해상도(레티나) 대응: CSS 크기 × devicePixelRatio로 백버퍼 설정
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 200;
    const h = 36;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);
    const vals = data.map(d => d.value ?? d);
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const range = max - min || 1;
    ctx.clearRect(0, 0, w, h);
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    vals.forEach((v, i) => {
      const x = (i / (vals.length - 1)) * w;
      const y = h - ((v - min) / range) * (h - 4) - 2;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();
  }, [data, color]);
  return (
    <canvas ref={ref}
      style={{ width: '100%', height: 36, marginTop: 8, display: 'block' }} />
  );
}

function MacroCard({ name, price, change_pct, series, showChart }) {
  const clr = change_pct > 0 ? 'var(--up)' : change_pct < 0 ? 'var(--down)' : 'var(--fg-3)';
  const fmtPrice = v => {
    if (v == null) return null;
    return v >= 1000 ? v.toLocaleString('ko', { maximumFractionDigits: 2 }) : v.toFixed(2);
  };
  const priceStr = fmtPrice(price);
  return (
    <div style={{
      background: 'var(--bg-3)', border: '1px solid var(--line-1)',
      borderRadius: 'var(--r-2)', padding: '12px 14px', minWidth: 0,
    }}>
      <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', marginBottom: 4 }}>
        {name}
      </div>
      {priceStr && (
        <div style={{ fontSize: '1.05rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: 'var(--fg-1)', lineHeight: 1.2 }}>
          {priceStr}
        </div>
      )}
      {change_pct != null && (
        <div style={{ fontSize: priceStr ? '0.78rem' : '1.05rem', fontWeight: priceStr ? 600 : 800, fontFamily: 'var(--font-mono)', color: clr, marginTop: priceStr ? 2 : 0 }}>
          {change_pct > 0 ? '+' : ''}{change_pct.toFixed(2)}%
        </div>
      )}
      {showChart && series?.length > 1 && (
        <MiniChart data={series} color={(change_pct ?? 0) >= 0 ? '#22c55e' : '#ef4444'} />
      )}
    </div>
  );
}

// ── 투자자 동향 컴포넌트 ──────────────────────────────────────────────────────
function InvestorBadge({ value }) {
  if (value == null) return <span style={{ color: 'var(--fg-3)' }}>-</span>;
  const pos = value > 0;
  const neg = value < 0;
  return (
    <span style={{
      color: pos ? 'var(--up)' : neg ? 'var(--down)' : 'var(--fg-2)',
      fontWeight: 700, fontFamily: 'var(--font-mono)', fontSize: '0.85rem',
    }}>
      {fmt억(value)}
      <span style={{ fontSize: '0.68rem', fontWeight: 400, marginLeft: 2, color: 'var(--fg-3)' }}>원</span>
    </span>
  );
}

function MarketRow({ label, data, isLast = false }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 0', borderBottom: isLast ? 'none' : '1px solid var(--line-1)' }}>
      <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--fg-2)', width: 64, flexShrink: 0 }}>{label}</span>
      <div style={{ display: 'flex', gap: 18, flex: 1, flexWrap: 'wrap' }}>
        {[['외국인', 'foreign'], ['기관', 'institution'], ['개인', 'individual']].map(([lbl, key]) => (
          <div key={key} style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 2 }}>
            <span style={{ fontSize: '0.68rem', color: 'var(--fg-3)' }}>{lbl}</span>
            <InvestorBadge value={data?.[key]} />
          </div>
        ))}
      </div>
    </div>
  );
}

function StockRankList({ items, type }) {
  if (!items?.length) return (
    <div style={{ textAlign: 'center', padding: '20px 0', color: 'var(--fg-3)', fontSize: '0.8rem' }}>데이터 없음</div>
  );
  const isBuy = type === 'buy';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {items.map((s, i) => (
        <div key={s.code} style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '7px 8px', borderRadius: 'var(--r-2)',
          background: i % 2 === 0 ? 'transparent' : 'var(--bg-2)',
        }}>
          <span style={{ width: 20, textAlign: 'center', fontSize: '0.72rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)', flexShrink: 0 }}>{i + 1}</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: '0.83rem', fontWeight: 600, color: 'var(--fg-1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</div>
            <div style={{ fontSize: '0.7rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>{s.code}</div>
          </div>
          <div style={{ fontSize: '0.82rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--fg-2)', flexShrink: 0 }}>
            {s.price?.toLocaleString('ko')}
          </div>
          <span style={{
            fontSize: '0.68rem', padding: '2px 6px', borderRadius: 10, fontWeight: 700, flexShrink: 0,
            background: isBuy ? 'var(--up-soft,#f0fdf4)' : 'var(--down-soft,#fef2f2)',
            color: isBuy ? 'var(--up)' : 'var(--down)',
            border: `1px solid ${isBuy ? 'var(--up)' : 'var(--down)'}`,
          }}>
            {isBuy ? '순매수' : '순매도'}
          </span>
        </div>
      ))}
    </div>
  );
}

function PriceCard({ s }) {
  const chg = s.change_pct ?? 0;
  const cls = chg > 0 ? 'up' : chg < 0 ? 'down' : 'flat';
  return (
    <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--fg-1)' }}>{s.name}</div>
          <div style={{ fontSize: '0.72rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>{s.code}</div>
        </div>
        <span className={`badge-${cls}`} style={{ fontSize: '0.72rem', padding: '2px 7px', borderRadius: 4, fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
          {chg > 0 ? '+' : ''}{chg?.toFixed(2)}%
        </span>
      </div>
      <div style={{ fontSize: '1.15rem', fontWeight: 800, color: 'var(--fg-1)', fontFamily: 'var(--font-mono)' }}>
        {s.price?.toLocaleString('ko')}
        <span style={{ fontSize: '0.72rem', fontWeight: 400, color: 'var(--fg-3)', marginLeft: 4 }}>원</span>
      </div>
      {s.volume && <div style={{ fontSize: '0.72rem', color: 'var(--fg-3)' }}>거래량 {s.volume?.toLocaleString('ko')}</div>}
    </div>
  );
}

const INVESTOR_TABS = [
  { key: 'foreignBuy', label: '외국인 순매수', type: 'buy' },
  { key: 'foreignSell', label: '외국인 순매도', type: 'sell' },
  { key: 'institutionBuy', label: '기관 순매수', type: 'buy' },
  { key: 'institutionSell', label: '기관 순매도', type: 'sell' },
];

// ── 거시지표 카드 정의 (응답 object 형식 → 카드 변환 규칙) ──────────────────────
// price: [우선순위 키...], ret: [{ key, scope: 'macro'|'global', pct?: ×100 여부 }]
const MACRO_CARDS = [
  { name: 'KOSPI',    series: 'kospi',  rets: [{ k: 'kospi_ret_1d', s: 'macro' }, { k: 'kospi_ret_20d', s: 'macro', pct: true }] },
  { name: 'KOSDAQ',   series: 'kosdaq', rets: [{ k: 'kosdaq_ret_1d', s: 'macro' }] },
  { name: 'USD/KRW',  series: 'usdkrw', rets: [{ k: 'usdkrw_ret_1d', s: 'macro' }, { k: 'usdkrw_ret_20d', s: 'macro', pct: true }] },
  { name: '국채 3년',  series: 'bond_3y', rets: [{ k: 'bond_3y_ret_1d', s: 'macro' }] },
  { name: 'VIX',      series: 'vix',    price: 'vix_level',    rets: [{ k: 'vix_ret_1d', s: 'global' }] },
  { name: 'S&P500',   series: 'sp500',  price: 'sp500_price',  rets: [{ k: 'sp500_ret_1d', s: 'global', pct: true }] },
  { name: '나스닥',    series: 'nasdaq', price: 'nasdaq_price', rets: [{ k: 'nasdaq_ret_1d', s: 'global', pct: true }] },
  { name: '유가',      series: 'oil',    price: 'oil_price',    rets: [{ k: 'oil_ret_20d', s: 'global', pct: true }] },
  { name: '미국 10Y',  series: 'us10y',  price: 'us_10y',       rets: [{ k: 'us_10y_ret_1d', s: 'global' }] },
];

function buildMacroCards(d) {
  if (Array.isArray(d)) return d;
  if (!d?.series) return [];
  const s = d.series || {}, m = d.macro || {}, g = d.global || {};
  const last = arr => arr?.length ? (arr[arr.length - 1]?.value ?? arr[arr.length - 1]) : null;
  return MACRO_CARDS.flatMap(cfg => {
    const series = s[cfg.series] ?? [];
    const rawPrice = cfg.price != null ? g[cfg.price] : null;
    if (!series.length && rawPrice == null) return [];
    let change_pct = null;
    for (const { k, s: scope, pct } of cfg.rets) {
      const v = (scope === 'global' ? g : m)[k];
      if (v != null) { change_pct = +((pct ? v * 100 : v).toFixed(2)); break; }
    }
    const price = rawPrice != null ? +(+rawPrice).toFixed(2) : last(series);
    return [{ name: cfg.name, price, change_pct, series }];
  });
}

// ── 메인 페이지 ───────────────────────────────────────────────────────────────
export default function StockLive() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [movers, setMovers] = useState({ rising: [], falling: [] });
  const [investor, setInvestor] = useState(null);
  const [macro, setMacro] = useState([]);
  const [loading, setLoading] = useState(false);
  const [moversLoading, setMoversLoading] = useState(true);
  const [moversError, setMoversError] = useState(false);
  const [investorLoading, setInvestorLoading] = useState(true);
  const [investorRefreshing, setInvestorRefreshing] = useState(false);
  const [macroLoading, setMacroLoading] = useState(true);
  const [macroError, setMacroError] = useState(false);
  const [moverTab, setMoverTab] = useState('rising');
  const [showCharts, setShowCharts] = useState(false);
  const dq = useDebounce(query, 250);
  const refreshRef = useRef(null);

  const fetchInvestor = (background = false) => {
    if (!background) setInvestorLoading(true);
    else setInvestorRefreshing(true);
    api.get('/api/market/investor')
      .then(r => { setInvestor(r.data); })
      .catch(() => { })
      .finally(() => {
        if (!background) setInvestorLoading(false);
        else setInvestorRefreshing(false);
      });
  };

  useEffect(() => {
    api.get('/api/market/movers')
      .then(r => { setMovers(r.data); setMoversError(false); })
      .catch(() => setMoversError(true))
      .finally(() => setMoversLoading(false));

    fetchInvestor();
    // 탭이 백그라운드일 땐 폴링 스킵 (불필요한 요청 방지)
    refreshRef.current = setInterval(() => {
      if (document.visibilityState === 'visible') fetchInvestor(true);
    }, 60000);

    api.get('/api/macro_dashboard')
      .then(r => { setMacro(buildMacroCards(r.data)); setMacroError(false); })
      .catch(() => setMacroError(true))
      .finally(() => setMacroLoading(false));

    return () => clearInterval(refreshRef.current);
  }, []);

  useEffect(() => {
    if (!dq.trim()) { setResults([]); return; }
    setLoading(true);
    const controller = new AbortController();
    api.get('/search-stock-kr', { params: { q: dq }, signal: controller.signal })
      .then(r => setResults(r.data || []))
      .catch(err => { if (err.name !== 'CanceledError' && err.name !== 'AbortError') setResults([]); })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [dq]);

  const card = { background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '20px', marginBottom: 20 };
  const sectionTitle = (icon, text, extra) => (
    <div style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--fg-1)', marginBottom: 14, display: 'flex', alignItems: 'center', gap: 6 }}>
      <i className={`bi ${icon}`} style={{ color: 'var(--accent)' }} />{text}
      {extra}
    </div>
  );

  return (
    <StockLayout title="시장 현황">

      {/* ── 거시지표 요약 ── */}
      <div style={card}>
        {sectionTitle('bi-globe2', '거시지표',
          <button
            onClick={() => setShowCharts(v => !v)}
            style={{
              marginLeft: 'auto', background: 'none', border: '1px solid var(--line-2)',
              borderRadius: 'var(--r-1)', padding: '2px 10px', fontSize: '0.72rem',
              color: 'var(--fg-3)', cursor: 'pointer',
            }}>
            {showCharts ? '차트 숨기기' : '차트 보기'}
          </button>
        )}
        {macroLoading ? (
          <div style={{ textAlign: 'center', padding: '20px 0', color: 'var(--fg-3)', fontSize: '0.83rem' }}>
            <div className="spinner" style={{ margin: '0 auto 8px' }} /> 로딩 중...
          </div>
        ) : macroError ? (
          <div style={{ textAlign: 'center', padding: '20px 0', color: 'var(--down)', fontSize: '0.83rem' }}>
            거시지표를 불러오지 못했습니다. 잠시 후 새로고침해주세요.
          </div>
        ) : macro.length ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 10 }}>
            {macro.map(c => <MacroCard key={c.name} {...c} showChart={showCharts} />)}
          </div>
        ) : (
          <div style={{ textAlign: 'center', padding: '20px 0', color: 'var(--fg-3)', fontSize: '0.83rem' }}>데이터 없음</div>
        )}
      </div>

      {/* ── 투자자별 순매수/매도 ── */}
      <div style={card}>
        {sectionTitle('bi-people-fill', '투자자별 동향',
          <button onClick={() => fetchInvestor(true)} disabled={investorRefreshing}
            style={{ marginLeft: 'auto', background: 'none', border: '1px solid var(--line-2)',
                     borderRadius: 'var(--r-1)', padding: '2px 10px', fontSize: '0.72rem',
                     color: 'var(--fg-3)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
            <i className={`bi bi-arrow-clockwise${investorRefreshing ? ' spin' : ''}`} />
            {investorRefreshing ? '갱신 중...' : '새로고침'}
          </button>
        )}
        {investorLoading ? (
          <div style={{ textAlign: 'center', padding: '20px 0', color: 'var(--fg-3)', fontSize: '0.83rem' }}>
            <div className="spinner" style={{ margin: '0 auto 8px' }} /> 로딩 중...
          </div>
        ) : investor ? (<>
          <div style={{ background: 'var(--bg-3)', borderRadius: 'var(--r-2)', padding: '4px 12px', marginBottom: 14 }}>
            <MarketRow label="KOSPI" data={investor.kospi} />
            <MarketRow label="KOSDAQ" data={investor.kosdaq} isLast />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, calc(25% - 9px))', gap: 12 }}>
            {INVESTOR_TABS.map(t => (
              <div key={t.key} style={{ background: 'var(--bg-3)', borderRadius: 'var(--r-2)', padding: '10px 12px' }}>
                <div style={{
                  fontSize: '0.78rem', fontWeight: 700, marginBottom: 8,
                  color: t.type === 'buy' ? 'var(--up)' : 'var(--down)',
                  borderBottom: `2px solid ${t.type === 'buy' ? 'var(--up)' : 'var(--down)'}`,
                  paddingBottom: 6,
                }}>{t.label}</div>
                <StockRankList items={investor[t.key]} type={t.type} />
              </div>
            ))}
          </div>
          <div style={{ fontSize: '0.7rem', color: 'var(--fg-3)', marginTop: 10, textAlign: 'right' }}>
            {(() => {
              if (!investor.updatedAt) return '';
              const d = new Date(investor.updatedAt);
              if (isNaN(d)) return '';
              const now = new Date();
              const isToday = d.toDateString() === now.toDateString();
              const dateStr = d.toLocaleDateString('ko-KR', { month: 'long', day: 'numeric' });
              const timeStr = d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
              return isToday
                ? `기준: ${timeStr} • 5분마다 갱신 (15~20분 지연)`
                : `기준: ${dateStr} 장 마감 (전일 데이터) • 외국인=등락률, 기관=거래대금 순`;
            })()}
          </div>
        </>) : (
          <div style={{ textAlign: 'center', padding: '20px 0', color: 'var(--fg-3)', fontSize: '0.83rem' }}>데이터를 불러올 수 없습니다</div>
        )}
      </div>

      {/* ── 종목 검색 ── */}
      <div style={card}>
        {sectionTitle('bi-search', '종목 검색')}
        <div style={{ position: 'relative' }}>
          <input className="form-control" value={query} onChange={e => setQuery(e.target.value)}
            placeholder="종목명 또는 코드 검색 (예: 삼성전자, 005930)" />
          {loading && (
            <div style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)' }}>
              <div className="spinner" style={{ width: 16, height: 16, border: '2px solid var(--line-2)', borderTopColor: 'var(--accent)' }} />
            </div>
          )}
        </div>
        {results.length > 0 && (
          <div style={{ marginTop: 10, display: 'grid', gap: 8, gridTemplateColumns: 'repeat(auto-fill, minmax(200px,1fr))' }}>
            {results.slice(0, 12).map(s => <PriceCard key={s.code} s={s} />)}
          </div>
        )}
      </div>

      {/* ── 시장 모버 ── */}
      <div style={{ ...card, marginBottom: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <span style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--fg-1)' }}>
            <i className="bi bi-graph-up-arrow" style={{ marginRight: 6, color: 'var(--accent)' }} />시장 모버
          </span>
          <div className="btn-group">
            {['rising', 'falling'].map(t => (
              <button key={t} onClick={() => setMoverTab(t)}
                className={`btn btn-sm ${moverTab === t ? 'btn-primary' : 'btn-outline-secondary'}`}>
                {t === 'rising' ? '상승' : '하락'}
              </button>
            ))}
          </div>
        </div>
        {moversLoading ? (
          <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--fg-3)' }}>
            <div className="spinner" style={{ margin: '0 auto 8px' }} />로딩 중...
          </div>
        ) : moversError ? (
          <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--down)', fontSize: '0.83rem' }}>
            시장 모버를 불러오지 못했습니다. 잠시 후 새로고침해주세요.
          </div>
        ) : (
          <div style={{ display: 'grid', gap: 8, gridTemplateColumns: 'repeat(auto-fill, minmax(200px,1fr))' }}>
            {(movers[moverTab] || []).map(s => <PriceCard key={s.code} s={s} />)}
          </div>
        )}
      </div>

    </StockLayout>
  );
}
