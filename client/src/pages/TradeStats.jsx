import React, { useState, useEffect, useRef } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

// ── 날짜 포맷 ──
function fmtYM(ym) {
  if (!ym || ym.length < 6) return ym;
  return `${ym.slice(0, 4)}.${ym.slice(4, 6)}`;
}

// 백만달러 → "$XB" 또는 "$XM"
function fmtBillion(v) {
  if (v == null) return '-';
  const b = Math.abs(v) / 1000;
  const sign = v < 0 ? '-' : '';
  if (b >= 1) return `${sign}$${b.toFixed(1)}B`;
  return `${sign}$${Math.abs(v).toFixed(0)}M`;
}

// 천달러 → "$XB"
function fmtKUsd(v) {
  if (v == null) return '-';
  const b = v / 1_000_000;
  return `$${b.toFixed(1)}B`;
}

// ── 등락 뱃지 ──
function DeltaBadge({ pct, prefix = '' }) {
  if (pct == null) return null;
  const up = pct >= 0;
  return (
    <span style={{
      fontSize: '0.7rem', fontFamily: 'var(--font-mono)',
      color: up ? '#4ade80' : '#f87171', marginLeft: 5,
    }}>
      {up ? '▲' : '▼'} {prefix}{Math.abs(pct).toFixed(1)}%
    </span>
  );
}

// ── 요약 카드 ──
function SummaryCard({ label, value, yoy, mom, sub, color }) {
  return (
    <div style={{
      background: 'var(--bg-2)', border: '1px solid var(--line-1)',
      borderRadius: 'var(--r-3)', padding: '14px 16px',
    }}>
      <div style={{ fontSize: '0.7rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)', marginBottom: 6 }}>
        {label}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 2, flexWrap: 'wrap' }}>
        <span style={{ fontWeight: 800, fontSize: '1.1rem', fontFamily: 'var(--font-mono)', color: color || 'var(--fg-1)' }}>
          {value}
        </span>
        <DeltaBadge pct={yoy} />
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 4, flexWrap: 'wrap' }}>
        {mom != null && (
          <span style={{ fontSize: '0.68rem', color: 'var(--fg-3)', display: 'flex', alignItems: 'center', gap: 2 }}>
            MoM<DeltaBadge pct={mom} />
          </span>
        )}
        {sub && <span style={{ fontSize: '0.68rem', color: 'var(--fg-3)' }}>{sub}</span>}
      </div>
    </div>
  );
}

// ── 월별 추이 캔버스 차트 ──
function TrendChart({ series }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !series?.length) return;
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth, H = canvas.clientHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    const PAD = { top: 28, bottom: 36, left: 52, right: 16 };
    const cW = W - PAD.left - PAD.right;
    const cH = H - PAD.top - PAD.bottom;

    const allVals = series.flatMap(s => [s.exports, s.imports].filter(v => v != null));
    const maxVal  = Math.max(...allVals) * 1.1 || 1;
    const xPos    = i => PAD.left + (i / Math.max(series.length - 1, 1)) * cW;
    const yPos    = v => PAD.top + cH - (v / maxVal) * cH;

    ctx.clearRect(0, 0, W, H);

    // 그리드
    for (let i = 0; i <= 4; i++) {
      const y = PAD.top + (i / 4) * cH;
      ctx.strokeStyle = 'rgba(120,120,120,0.12)';
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(W - PAD.right, y); ctx.stroke();
      const v = maxVal * (1 - i / 4);
      ctx.fillStyle = '#666'; ctx.font = '9px monospace'; ctx.textAlign = 'right';
      ctx.fillText(`$${(v / 1000).toFixed(0)}B`, PAD.left - 4, y + 3);
    }

    // 무역수지 바
    series.forEach((s, i) => {
      if (s.tradeBalance == null) return;
      const x = xPos(i), bW = Math.max(2, cW / series.length * 0.5);
      const pos = s.tradeBalance >= 0;
      const bH = Math.max(1, (Math.abs(s.tradeBalance) / maxVal) * cH);
      const zeroY = yPos(0);
      ctx.fillStyle = pos ? 'rgba(74,222,128,0.2)' : 'rgba(248,113,113,0.2)';
      ctx.fillRect(x - bW / 2, pos ? zeroY - bH : zeroY, bW, bH);
    });

    function drawLine(key, color) {
      ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.lineJoin = 'round';
      ctx.beginPath();
      let started = false;
      series.forEach((s, i) => {
        if (s[key] == null) return;
        const x = xPos(i), y = yPos(s[key]);
        if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }
    drawLine('exports', '#38bdf8');
    drawLine('imports', '#f97316');

    // X축 레이블
    ctx.fillStyle = '#888'; ctx.font = '9px monospace'; ctx.textAlign = 'center';
    series.forEach((s, i) => {
      if (i % 4 !== 0 && i !== series.length - 1) return;
      ctx.fillText(fmtYM(s.date), xPos(i), H - 6);
    });

    // 범례
    [{ color: '#38bdf8', label: '수출' }, { color: '#f97316', label: '수입' }, { color: 'rgba(74,222,128,0.6)', label: '무역수지' }].forEach(({ color, label }, i) => {
      ctx.fillStyle = color;
      ctx.fillRect(PAD.left + i * 68, 8, 10, 6);
      ctx.fillStyle = '#aaa'; ctx.textAlign = 'left'; ctx.font = '9px monospace';
      ctx.fillText(label, PAD.left + i * 68 + 13, 15);
    });
  }, [series]);

  return (
    <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'hidden', marginBottom: 16 }}>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--line-1)', fontWeight: 700, fontSize: '0.87rem', color: 'var(--fg-1)' }}>
        월별 수출입 추이 <span style={{ fontSize: '0.72rem', color: 'var(--fg-3)', fontWeight: 400 }}>단위: 백만 USD · BOP 기준 (301Y013)</span>
      </div>
      <canvas ref={canvasRef} style={{ width: '100%', height: 220, display: 'block', padding: '8px 16px 4px', boxSizing: 'border-box' }} />
    </div>
  );
}

// ── 국가별 추이 (다중 라인) ──
const COUNTRY_COLORS = ['#38bdf8', '#f97316', '#a78bfa', '#4ade80', '#fb923c'];

function CountryTrendChart({ data, countries, title }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data?.length || !countries?.length) return;
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth, H = canvas.clientHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    const PAD = { top: 28, bottom: 36, left: 52, right: 16 };
    const cW = W - PAD.left - PAD.right;
    const cH = H - PAD.top - PAD.bottom;

    const codes = countries.map(c => c.code);
    const allVals = data.flatMap(d => codes.map(c => d[c]).filter(v => v != null));
    const maxVal = Math.max(...allVals) * 1.1 || 1;
    const xPos = i => PAD.left + (i / Math.max(data.length - 1, 1)) * cW;
    const yPos = v => PAD.top + cH - (v / maxVal) * cH;

    ctx.clearRect(0, 0, W, H);

    for (let i = 0; i <= 4; i++) {
      const y = PAD.top + (i / 4) * cH;
      ctx.strokeStyle = 'rgba(120,120,120,0.12)'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(W - PAD.right, y); ctx.stroke();
      const v = maxVal * (1 - i / 4);
      ctx.fillStyle = '#666'; ctx.font = '9px monospace'; ctx.textAlign = 'right';
      ctx.fillText(`$${(v / 1_000_000).toFixed(1)}B`, PAD.left - 4, y + 3);
    }

    codes.forEach((code, ci) => {
      ctx.strokeStyle = COUNTRY_COLORS[ci % COUNTRY_COLORS.length];
      ctx.lineWidth = 2; ctx.lineJoin = 'round';
      ctx.beginPath();
      let started = false;
      data.forEach((d, i) => {
        if (d[code] == null) return;
        const x = xPos(i), y = yPos(d[code]);
        if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
      });
      ctx.stroke();
    });

    ctx.fillStyle = '#888'; ctx.font = '9px monospace'; ctx.textAlign = 'center';
    data.forEach((d, i) => {
      if (i % 3 !== 0 && i !== data.length - 1) return;
      ctx.fillText(fmtYM(d.date), xPos(i), H - 6);
    });

    countries.slice(0, 5).forEach(({ name }, ci) => {
      const x = PAD.left + ci * 72;
      ctx.fillStyle = COUNTRY_COLORS[ci % COUNTRY_COLORS.length];
      ctx.fillRect(x, 8, 10, 6);
      ctx.fillStyle = '#aaa'; ctx.textAlign = 'left'; ctx.font = '9px monospace';
      ctx.fillText(name, x + 13, 15);
    });
  }, [data, countries]);

  return (
    <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'hidden', marginBottom: 16 }}>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--line-1)', fontWeight: 700, fontSize: '0.87rem', color: 'var(--fg-1)' }}>
        {title} <span style={{ fontSize: '0.72rem', color: 'var(--fg-3)', fontWeight: 400 }}>단위: 천 USD · 통관기준 (901Y121)</span>
      </div>
      <canvas ref={canvasRef} style={{ width: '100%', height: 200, display: 'block', padding: '8px 16px 4px', boxSizing: 'border-box' }} />
    </div>
  );
}

// ── 섹터별 수출입 바 차트 ──
function SectorBar({ title, data, color }) {
  if (!data?.length) return null;
  const maxVal = Math.max(...data.map(d => d.value_mn_usd || 0));
  const hasReal = data.some(d => d.real);

  return (
    <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'hidden', marginBottom: 16 }}>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--line-1)', fontWeight: 700, fontSize: '0.87rem', color: 'var(--fg-1)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>{title}</span>
        {hasReal && <span style={{ fontSize: '0.68rem', color: '#4ade80', fontWeight: 400, background: 'rgba(74,222,128,0.1)', border: '1px solid rgba(74,222,128,0.3)', borderRadius: 4, padding: '1px 6px' }}>관세청 실제</span>}
      </div>
      <div style={{ padding: '10px 16px' }}>
        {data.map((item, i) => (
          <div key={item.id} style={{ marginBottom: i < data.length - 1 ? 9 : 0 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', fontSize: '0.78rem', marginBottom: 3 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 0, flexWrap: 'wrap' }}>
                <span style={{ color: 'var(--fg-3)', fontFamily: 'var(--font-mono)', fontSize: '0.67rem', marginRight: 5, minWidth: 14, textAlign: 'right' }}>{i + 1}</span>
                <span style={{ color: 'var(--fg-1)', fontWeight: 500 }}>{item.name}</span>
                {/* 관세청 실제 YoY */}
                {item.real && item.yoy != null && (
                  <span style={{ fontSize: '0.67rem', marginLeft: 5, color: item.yoy >= 0 ? '#4ade80' : '#f87171', fontFamily: 'var(--font-mono)' }}>
                    {item.yoy >= 0 ? '▲' : '▼'}{Math.abs(item.yoy).toFixed(1)}%
                  </span>
                )}
                {/* BOK 수출물가지수 YoY */}
                {item.price_yoy != null && (
                  <span style={{ fontSize: '0.67rem', marginLeft: 5, color: item.price_yoy >= 0 ? '#a78bfa' : '#fb923c', fontFamily: 'var(--font-mono)' }}>
                    물가{item.price_yoy >= 0 ? '▲' : '▼'}{Math.abs(item.price_yoy).toFixed(1)}%
                  </span>
                )}
                {/* 추정값 태그 */}
                {item.real === false && (
                  <span style={{ fontSize: '0.62rem', marginLeft: 5, color: 'var(--fg-3)', border: '1px solid var(--line-1)', borderRadius: 3, padding: '0 3px' }}>추정</span>
                )}
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                <span style={{ fontSize: '0.68rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>{item.share2024}%</span>
                {item.value_mn_usd != null && (
                  <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--fg-2)', fontSize: '0.75rem' }}>{fmtBillion(item.value_mn_usd)}</span>
                )}
              </div>
            </div>
            <div style={{ background: 'var(--bg-3)', borderRadius: 3, height: 5, overflow: 'hidden' }}>
              <div style={{ width: `${maxVal ? (item.value_mn_usd || 0) / maxVal * 100 : item.share2024 / data[0].share2024 * 100}%`, height: '100%', background: item.real === false ? 'rgba(148,163,184,0.4)' : color, borderRadius: 3, transition: 'width 0.6s ease' }} />
            </div>
          </div>
        ))}
      </div>
      <div style={{ padding: '4px 16px 8px', fontSize: '0.67rem', color: 'var(--fg-3)', textAlign: 'right' }}>
        녹색 YoY = 관세청 실제 · 보라 물가YoY = BOK 402Y015 · 추정 = BOK 총액 × KITA 비중
      </div>
    </div>
  );
}

// ── 국가별 바 차트 ──
function CountryBar({ title, data, color, dateLabel }) {
  if (!data?.length) return (
    <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'hidden', marginBottom: 16, padding: '40px 0', textAlign: 'center', color: 'var(--fg-3)', fontSize: '0.82rem' }}>
      국가별 데이터 없음
    </div>
  );
  const max = data[0].value;
  return (
    <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'hidden', marginBottom: 16 }}>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--line-1)', fontWeight: 700, fontSize: '0.87rem', color: 'var(--fg-1)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>{title}</span>
        {dateLabel && <span style={{ fontSize: '0.72rem', color: 'var(--fg-3)', fontWeight: 400 }}>{fmtYM(dateLabel)} 기준</span>}
      </div>
      <div style={{ padding: '10px 16px' }}>
        {data.map((item, i) => (
          <div key={item.code} style={{ marginBottom: i < data.length - 1 ? 9 : 0 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', fontSize: '0.78rem', marginBottom: 3 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 0 }}>
                <span style={{ color: 'var(--fg-3)', fontFamily: 'var(--font-mono)', fontSize: '0.67rem', marginRight: 5, minWidth: 14, textAlign: 'right' }}>
                  {i + 1}
                </span>
                <span style={{ color: 'var(--fg-1)', fontWeight: 500 }}>{item.name}</span>
                <DeltaBadge pct={item.yoy} />
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                {item.share_pct != null && (
                  <span style={{ fontSize: '0.68rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>
                    {item.share_pct}%
                  </span>
                )}
                <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--fg-2)', fontSize: '0.75rem' }}>
                  {fmtKUsd(item.value)}
                </span>
              </div>
            </div>
            <div style={{ background: 'var(--bg-3)', borderRadius: 3, height: 5, overflow: 'hidden' }}>
              <div style={{ width: `${(item.value / max) * 100}%`, height: '100%', background: color, borderRadius: 3, transition: 'width 0.6s ease' }} />
            </div>
          </div>
        ))}
      </div>
      <div style={{ padding: '4px 16px 8px', fontSize: '0.67rem', color: 'var(--fg-3)', textAlign: 'right' }}>
        단위: 천 USD · 통관기준 (BOK ECOS 901Y121) · YoY=전년 동월 대비
      </div>
    </div>
  );
}

// ── 메인 페이지 ──
export default function TradeStats() {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState('');

  useEffect(() => {
    api.get('/api/trade/summary')
      .then(r => setData(r.data))
      .catch(e => setError(e.response?.data?.error || '데이터 로드 실패'))
      .finally(() => setLoading(false));
  }, []);

  const lat  = data?.latest  || {};
  const ct   = data?.countryTrend || {};

  return (
    <StockLayout title="수출입 동향">
      {error && (
        <div className="alert alert-danger" style={{ fontSize: '0.83rem', padding: '10px 14px', marginBottom: 16 }}>
          {error}
        </div>
      )}

      {loading && (
        <div style={{ textAlign: 'center', padding: '80px 0' }}>
          <div className="spinner" style={{ margin: '0 auto' }} />
          <p style={{ color: 'var(--fg-3)', marginTop: 16, fontSize: '0.85rem' }}>한국은행 ECOS 데이터 조회 중...</p>
        </div>
      )}

      {data && !loading && (
        <>
          {/* 기준 월 */}
          {lat.date && (
            <div style={{ fontSize: '0.78rem', color: 'var(--fg-3)', marginBottom: 14 }}>
              기준: {fmtYM(lat.date)} &nbsp;·&nbsp; 출처: 한국은행 ECOS (301Y013 경상수지 / 901Y121 국가별 수출입)
            </div>
          )}

          {/* 요약 카드 */}
          <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fill,minmax(155px,1fr))', marginBottom: 18 }}>
            <SummaryCard
              label="상품 수출"
              value={fmtBillion(lat.exports)}
              yoy={lat.yoy?.exports}
              mom={lat.mom?.exports}
              sub="백만달러 BOP기준"
              color="#38bdf8"
            />
            <SummaryCard
              label="상품 수입"
              value={fmtBillion(lat.imports)}
              yoy={lat.yoy?.imports}
              mom={lat.mom?.imports}
              sub="백만달러 BOP기준"
              color="#f97316"
            />
            <SummaryCard
              label="무역수지"
              value={fmtBillion(lat.tradeBalance)}
              yoy={lat.yoy?.tradeBalance}
              mom={lat.mom?.tradeBalance}
              sub={lat.tradeBalance != null ? (lat.tradeBalance >= 0 ? '흑자' : '적자') : ''}
              color={lat.tradeBalance >= 0 ? '#4ade80' : '#f87171'}
            />
            <SummaryCard
              label="경상수지"
              value={fmtBillion(lat.currentAccount)}
              sub={lat.currentAccount != null ? (lat.currentAccount >= 0 ? '흑자' : '적자') : ''}
              color={lat.currentAccount >= 0 ? '#4ade80' : '#f87171'}
            />
          </div>

          {/* 월별 추이 */}
          <TrendChart series={data.series} />

          {/* 국가별 수출/수입 */}
          <div style={{ display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fill,minmax(300px,1fr))', marginBottom: 16 }}>
            <CountryBar
              title="주요국 수출 현황 (Top 10)"
              data={data.globalExports}
              color="rgba(56,189,248,0.65)"
              dateLabel={data.globalExports?.[0]?.date}
            />
            <CountryBar
              title="주요국 수입 현황 (Top 10)"
              data={data.globalImports}
              color="rgba(249,115,22,0.65)"
              dateLabel={data.globalImports?.[0]?.date}
            />
          </div>

          {/* 주요국 추이 차트 */}
          {ct.exports?.length > 0 && ct.countries?.length > 0 && (
            <div style={{ display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fill,minmax(400px,1fr))', marginBottom: 16 }}>
              <CountryTrendChart
                title="주요 수출 대상국 추이"
                data={ct.exports}
                countries={ct.countries}
              />
              <CountryTrendChart
                title="주요 수입 출처국 추이"
                data={ct.imports}
                countries={ct.countries}
              />
            </div>
          )}

          {/* 섹터별 수출입 */}
          {(data.sectors?.exports?.length > 0 || data.sectors?.imports?.length > 0) && (
            <>
              <div style={{ fontWeight: 700, fontSize: '0.87rem', color: 'var(--fg-1)', marginBottom: 10, marginTop: 4 }}>
                섹터별 수출입 현황
                <span style={{ fontSize: '0.72rem', color: 'var(--fg-3)', fontWeight: 400, marginLeft: 8 }}>
                  {data.sectors.latest_ym ? `관세청 ${fmtYM(data.sectors.latest_ym)}` : `추정 · ${fmtYM(lat.date)}`}
                </span>
              </div>
              <div style={{ display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fill,minmax(300px,1fr))', marginBottom: 16 }}>
                <SectorBar
                  title="수출 섹터별 (Top 10)"
                  data={data.sectors.exports}
                  color="rgba(56,189,248,0.65)"
                  totalMn={lat.exports}
                />
                <SectorBar
                  title="수입 섹터별 (Top 10)"
                  data={data.sectors.imports}
                  color="rgba(249,115,22,0.65)"
                  totalMn={lat.imports}
                />
              </div>
            </>
          )}

          {/* 데이터 출처 */}
          <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '12px 16px', fontSize: '0.76rem', color: 'var(--fg-3)' }}>
            <strong style={{ color: 'var(--fg-2)' }}>데이터 출처</strong><br />
            · 수출·수입·무역수지·경상수지: 한국은행 ECOS 301Y013 (BOP 기준, 백만 USD)<br />
            · 국가별 수출입: 한국은행 ECOS 901Y121 (통관기준, 천 USD) — T002=수출금액, T004=수입금액<br />
            · 섹터별: 관세청 품목별수출입통계 (HS 코드, USD) — 복잡 섹터는 BOK 총액 × KITA 2024 비중 추정<br />
            · 섹터 물가 YoY: 한국은행 ECOS 402Y015 수출물가지수 (최신 약 6~12개월 지연)<br />
            · YoY = 전년 동월 대비, MoM = 전월 대비 · 6시간 캐시
          </div>
        </>
      )}
    </StockLayout>
  );
}
