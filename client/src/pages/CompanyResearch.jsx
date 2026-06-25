import React, { useState, useEffect, useRef, useCallback } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

const ADVISOR_COST = 500;

/* ── 포맷 헬퍼 ────────────────────────────────────────────── */
const fmt  = n => (n == null || n === '') ? '-' : Number(n).toLocaleString('ko');
const fmtF = (n, d = 2) => (n == null || n === '') ? '-' : Number(n).toFixed(d);
const fmtB = n => {
  if (!n) return '-';
  const v = Number(n);
  if (v >= 10000) return `${(v / 10000).toFixed(2)}조`;
  return `${fmt(v)}억`;
};
const sign = n => (n > 0 ? '+' : '');

/* ── 키움 시세 카드 ──────────────────────────────────────── */
function KiwoomCard({ kw }) {
  if (!kw) return null;
  const up = kw.rate > 0, dn = kw.rate < 0;
  const dir = up ? 'var(--up)' : dn ? 'var(--down)' : 'var(--fg-3)';
  return (
    <div style={{ background: 'var(--bg-3)', borderRadius: 'var(--r-2)', padding: '12px 14px', marginBottom: 10 }}>
      <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)', marginBottom: 6 }}>실시간 시세 ({kw.price_source || 'KRX'})</div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontWeight: 800, fontSize: '1.1rem', fontFamily: 'var(--font-mono)' }}>{fmt(kw.price)}원</span>
        <span style={{ fontSize: '0.82rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: dir }}>
          {up ? '▲' : dn ? '▼' : ''} {Math.abs(kw.rate ?? 0).toFixed(2)}%
        </span>
      </div>
      <div style={{ marginTop: 8, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 12px', fontSize: '0.73rem' }}>
        {[
          ['시가총액', fmtB(kw.market_cap)],
          ['거래량', fmt(kw.volume)],
          ['PER',    fmtF(kw.per) + '배'],
          ['PBR',    fmtF(kw.pbr) + '배'],
          ['ROE',    kw.roe ? fmtF(kw.roe) + '%' : '-'],
          ['외국인', kw.foreign_ratio ? fmtF(kw.foreign_ratio) + '%' : '-'],
          ['52주 고', fmt(kw.week52_high)],
          ['52주 저', fmt(kw.week52_low)],
        ].map(([l, v]) => (
          <div key={l} style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: 'var(--fg-3)' }}>{l}</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--fg-1)' }}>{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── ML 신호 카드 ────────────────────────────────────────── */
function MlCard({ ml }) {
  if (!ml) return null;
  const sig = ml.signal || ml.action;
  if (!sig) return null;
  const meta = {
    BUY:  { label: '매수', color: '#22c55e', bg: 'rgba(34,197,94,0.12)' },
    SELL: { label: '매도', color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
    HOLD: { label: '관망', color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
  }[sig] || { label: sig, color: 'var(--fg-2)', bg: 'var(--bg-3)' };
  const score = ml.score ?? ml.confidence ?? (ml.prob_up != null ? ml.prob_up / 100 : null);
  const pret  = ml.pred_return ?? ml.predicted_return;
  return (
    <div style={{ background: meta.bg, border: `1px solid ${meta.color}30`, borderRadius: 'var(--r-2)', padding: '10px 14px', marginBottom: 10 }}>
      <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)', marginBottom: 5 }}>AI 예측 (ML)</div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontWeight: 800, fontSize: '1.05rem', color: meta.color }}>{meta.label}</span>
        {score != null && (
          <span style={{ fontSize: '0.78rem', fontFamily: 'var(--font-mono)', color: meta.color }}>
            확률 {Math.round(score * 100)}%
          </span>
        )}
      </div>
      {pret != null && (
        <div style={{ fontSize: '0.73rem', marginTop: 4, fontFamily: 'var(--font-mono)', color: pret > 0 ? 'var(--up)' : pret < 0 ? 'var(--down)' : 'var(--fg-3)' }}>
          예측 수익률 {sign(pret)}{(pret * 100).toFixed(2)}%
        </div>
      )}
    </div>
  );
}

/* ── 컨센서스 카드 ───────────────────────────────────────── */
function ConsensusCard({ consensus }) {
  if (!consensus) return null;
  const tp  = consensus.target_price;
  const br  = consensus.buy_ratio;
  const cnt = consensus.total_count;
  if (!tp && !br) return null;
  const brPct = br > 1 ? Math.round(br) : Math.round((br ?? 0) * 100);
  return (
    <div style={{ background: 'var(--bg-3)', borderRadius: 'var(--r-2)', padding: '10px 14px', marginBottom: 10 }}>
      <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)', marginBottom: 5 }}>증권사 컨센서스 {cnt ? `(${cnt}개)` : ''}</div>
      {tp && <div style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', fontSize: '0.9rem' }}>목표가 {fmt(tp)}원</div>}
      {br != null && (
        <div style={{ marginTop: 5 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', marginBottom: 3 }}>
            <span style={{ color: 'var(--fg-3)' }}>매수 의견</span>
            <span style={{ color: '#22c55e', fontWeight: 700 }}>{brPct}%</span>
          </div>
          <div style={{ height: 5, background: 'var(--line-1)', borderRadius: 3, overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${brPct}%`, background: '#22c55e', borderRadius: 3 }} />
          </div>
        </div>
      )}
    </div>
  );
}

/* ── DART 재무 카드 ──────────────────────────────────────── */
function DartCard({ dart }) {
  if (!dart?.financials) return null;
  const fin = dart.financials;
  if (!fin.year) return null;
  return (
    <div style={{ background: 'var(--bg-3)', borderRadius: 'var(--r-2)', padding: '10px 14px', marginBottom: 10 }}>
      <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)', marginBottom: 5 }}>DART 재무 ({fin.year}년)</div>
      {[
        ['매출액',    fin.revenue,          '#3b82f6'],
        ['영업이익',  fin.operating_income, '#22c55e'],
        ['당기순이익', fin.net_income,       '#10b981'],
      ].map(([l, v, c]) => v != null && (
        <div key={l} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.73rem', marginBottom: 3 }}>
          <span style={{ color: 'var(--fg-3)' }}>{l}</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: c }}>{fmtB(Math.round(v / 100000000))}</span>
        </div>
      ))}
      {fin.debt_ratio != null && (
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.73rem' }}>
          <span style={{ color: 'var(--fg-3)' }}>부채비율</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: fin.debt_ratio > 200 ? 'var(--down)' : 'var(--fg-1)' }}>{fmtF(fin.debt_ratio)}%</span>
        </div>
      )}
    </div>
  );
}

/* ── 메인 ─────────────────────────────────────────────────── */
export default function CompanyResearch() {
  const [query,    setQuery]    = useState('');
  const [sugg,     setSugg]     = useState([]);
  const [selected, setSelected] = useState(null);
  const [text,     setText]     = useState('');
  const [meta,     setMeta]     = useState(null);
  const [cost,     setCost]     = useState(null);
  const [balance,  setBalance]  = useState(null);
  const [error,    setError]    = useState('');
  const [loading,  setLoading]  = useState(false);
  const timerRef = useRef(null);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  /* 자동완성 */
  const onQueryChange = useCallback(v => {
    setQuery(v); setSugg([]);
    if (!v.trim()) return;
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      api.get('/search-stock-kr', { params: { q: v } })
        .then(r => setSugg(r.data || []))
        .catch(() => {});
    }, 200);
  }, []);

  const pick = useCallback(s => { setSelected(s); setQuery(s.name); setSugg([]); }, []);

  const analyze = useCallback(async () => {
    if (!selected || loading) return;
    setLoading(true); setText(''); setMeta(null); setError(''); setCost(null); setBalance(null);
    try {
      const r = await api.post('/stock/advisor/analyze', { code: selected.code, name: selected.name });
      setText(r.data.analysis || '');
      setMeta(r.data);
      setCost(r.data.cost); setBalance(r.data.balance);
    } catch (e) {
      const d = e.response?.data;
      if (e.response?.status === 402)
        setError(`${d?.error || '크레딧이 부족합니다.'} (보유 ${d?.balance ?? 0}C / 필요 ${d?.cost ?? 0}C)`);
      else
        setError(d?.error || 'AI 분석에 실패했습니다.');
    }
    setLoading(false);
  }, [selected, loading]);

  const hasSidebar = meta?.kiwoom || meta?.ml || meta?.consensus || meta?.dart;

  return (
    <StockLayout title="기업 리서치">
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>

      {/* 검색 + 실행 */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 20, position: 'relative', maxWidth: 600 }}>
        <div style={{ flex: 1, position: 'relative' }}>
          <i className="bi bi-search" style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--fg-3)', pointerEvents: 'none' }} />
          <input className="form-control" value={query}
            onChange={e => onQueryChange(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && selected) analyze(); if (e.key === 'Escape') setSugg([]); }}
            placeholder="종목명 또는 코드 (예: 삼성전자, 005930)"
            style={{ paddingLeft: 32, fontSize: '0.9rem' }} />
          {sugg.length > 0 && (
            <div style={{ position: 'absolute', zIndex: 20, top: '100%', left: 0, right: 0, background: 'var(--bg-1)', border: '1px solid var(--line-2)', borderRadius: 'var(--r-2)', boxShadow: 'var(--menu-shadow)', marginTop: 4, maxHeight: 240, overflowY: 'auto' }}>
              {sugg.slice(0, 8).map(s => (
                <button key={s.code} onClick={() => pick(s)}
                  style={{ display: 'flex', alignItems: 'center', gap: 10, width: '100%', padding: '8px 14px', border: 'none', background: 'none', cursor: 'pointer', textAlign: 'left' }}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-3)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'none'}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.73rem', color: 'var(--fg-3)', minWidth: 50 }}>{s.code}</span>
                  <span style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--fg-1)', flex: 1 }}>{s.name}</span>
                  {s.market && <span style={{ fontSize: '0.63rem', background: 'var(--bg-3)', borderRadius: 4, padding: '1px 5px', color: 'var(--fg-3)' }}>{s.market}</span>}
                </button>
              ))}
            </div>
          )}
        </div>
        <button className="btn btn-primary" onClick={analyze} disabled={loading || !selected}
          style={{ whiteSpace: 'nowrap', minWidth: 140 }}>
          {loading
            ? <><div style={{ display: 'inline-block', width: 13, height: 13, border: '2px solid rgba(255,255,255,0.3)', borderTopColor: '#fff', borderRadius: '50%', animation: 'spin 0.8s linear infinite', marginRight: 6, verticalAlign: 'middle' }} />분석 중...</>
            : <><i className="bi bi-robot me-1" />AI 종목분석 ({ADVISOR_COST}C)</>}
        </button>
      </div>

      {/* 에러 */}
      {error && (
        <div style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 'var(--r-2)', padding: '10px 14px', marginBottom: 16, fontSize: '0.82rem', color: '#ef4444', display: 'flex', gap: 8, alignItems: 'flex-start' }}>
          <i className="bi bi-exclamation-triangle-fill" style={{ marginTop: 1, flexShrink: 0 }} />
          <span>{error}</span>
        </div>
      )}

      {/* 로딩 */}
      {loading && (
        <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--fg-3)', fontSize: '0.83rem' }}>
          <div className="spinner" style={{ margin: '0 auto 12px' }} />
          키움 · DART · 거시 데이터를 수집하고 AI가 리포트를 작성하고 있습니다... (30초~1분 소요)
        </div>
      )}

      {/* 본문 + 사이드바 */}
      {!loading && (text || hasSidebar) && (
        <div style={{ display: 'grid', gridTemplateColumns: hasSidebar ? '1fr 260px' : '1fr', gap: 16, alignItems: 'start' }}>

          {/* 분석 텍스트 */}
          <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '20px 22px' }}>
            <pre style={{ margin: 0, fontFamily: 'inherit', fontSize: '0.85rem', lineHeight: 1.85, color: 'var(--fg-1)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              {text}
            </pre>
            {cost != null && (
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12, marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--line-1)', fontSize: '0.72rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>
                <span>사용 {cost}C</span>
                <span>잔액 {balance}C</span>
              </div>
            )}
          </div>

          {/* 사이드바 데이터 패널 */}
          {hasSidebar && (
            <div>
              <div style={{ fontWeight: 700, fontSize: '0.78rem', color: 'var(--fg-3)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.06em' }}>분석 근거 데이터</div>
              <KiwoomCard kw={meta.kiwoom} />
              <MlCard ml={meta.ml} />
              <ConsensusCard consensus={meta.consensus} />
              <DartCard dart={meta.dart} />
            </div>
          )}
        </div>
      )}

      {/* 초기 상태 */}
      {!text && !loading && !error && (
        <div style={{ textAlign: 'center', padding: '80px 0', color: 'var(--fg-3)' }}>
          <i className="bi bi-cpu" style={{ fontSize: '2.5rem', display: 'block', marginBottom: 12, opacity: 0.2 }} />
          <p style={{ margin: 0, fontSize: '0.85rem' }}>종목을 검색하고 AI 종목분석 버튼을 눌러주세요.</p>
          <p style={{ fontSize: '0.74rem', marginTop: 6, opacity: 0.7 }}>
            키움 API · DART · 기술적 지표 · 거시경제 데이터를 종합하여<br/>Claude AI가 매수/매도 의견과 목표가를 제시합니다.
          </p>
          <div style={{ marginTop: 16, fontSize: '0.75rem', background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-2)', padding: '8px 14px', display: 'inline-block' }}>
            <i className="bi bi-coin me-1" />분석 1회당 {ADVISOR_COST}C가 차감됩니다.
          </div>
        </div>
      )}
    </StockLayout>
  );
}
