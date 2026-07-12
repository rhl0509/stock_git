import React, { useState, useEffect } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

const MODES = [
  { key: 'norm', label: '정규화 추천', icon: 'bi-graph-up',  desc: '세션 내 상대 비교 — 신뢰도 0~100% 정규화' },
  { key: 'abs',  label: '절대값 추천', icon: 'bi-bullseye',  desc: '모델 원시(raw) 확률 — 절대 신뢰도 비교' },
];

const CATEGORIES_NORM = [
  { key: 'daily',  label: '당일', icon: 'bi-stars',            desc: '5일 단기 급등 + 거래량' },
  { key: 'short',  label: '단기', icon: 'bi-lightning',        desc: '20일 모멘텀 + 수급' },
  { key: 'swing',  label: '스윙', icon: 'bi-arrow-left-right', desc: '90일 추세 + 펀더멘털' },
];

const CATEGORIES_ABS = [
  { key: 'triple', label: '강력 추천', icon: 'bi-fire' },
  ...CATEGORIES_NORM,
];

function ConfBar({ value, raw = false }) {
  const pct   = Math.min(100, Math.max(0, (value ?? 0) * 100));
  const color = pct >= (raw ? 75 : 70) ? '#22c55e' : pct >= (raw ? 60 : 55) ? '#f59e0b' : '#94a3b8';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{ width: 50, height: 4, background: 'var(--line-1)', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color }} />
      </div>
      <span style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', fontWeight: 700, color, minWidth: 44 }}>
        {pct.toFixed(raw ? 2 : 1)}%
      </span>
    </div>
  );
}

function FactorChips({ factors, detailed = false }) {
  if (!factors) return null;
  const items = detailed
    ? [['모멘텀', factors.momentum], ['수급', factors.flow], ['EPS', factors.eps], ['유동성', factors.liquidity]]
    : [['모멘텀', factors.momentum], ['수급', factors.flow], ['EPS', factors.eps]];
  return (
    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
      {items.map(([lbl, val]) => {
        const pct   = Math.round((val ?? 0) * 100);
        const color = pct >= 70 ? '#22c55e' : pct >= 50 ? '#f59e0b' : '#94a3b8';
        return (
          <span key={lbl} style={{ fontSize: '0.65rem', padding: '1px 5px', borderRadius: 3,
            fontFamily: 'var(--font-mono)', fontWeight: 700, whiteSpace: 'nowrap',
            background: `${color}22`, color, border: `1px solid ${color}44` }}>
            {lbl} {pct}
          </span>
        );
      })}
    </div>
  );
}

function SourceBadge({ source, absMode }) {
  const isModel = source === 'model';
  const color   = isModel ? (absMode ? '#7c3aed' : '#3b82f6') : '#f59e0b';
  return (
    <span style={{ fontSize: '0.68rem', padding: '2px 6px', borderRadius: 3, fontWeight: 700,
      background: `${color}22`, color, border: `1px solid ${color}44` }}>
      {isModel ? 'MODEL' : 'FACTOR'}
    </span>
  );
}

// 횡단면 상대순위 배지 — 순수 모델 점수의 유동성 유니버스 내 퍼센타일(model_rank_pct, 1=최상위).
// 홀드아웃 검증상 edge 는 절대 신뢰도가 아니라 이 상대순위에 있다(상위%로 표시).
function RankBadge({ pct }) {
  if (pct == null) return <span style={{ color: 'var(--fg-3)', fontSize: '0.75rem' }}>-</span>;
  const top   = Math.max(1, Math.round((1 - pct) * 100));  // 상위 X%
  const color = top <= 10 ? '#22c55e' : top <= 30 ? '#f59e0b' : '#94a3b8';
  return (
    <span title="유동성 유니버스 내 순수 모델 점수의 횡단면 순위 (검증상 edge 지표)"
      style={{ fontSize: '0.7rem', padding: '2px 6px', borderRadius: 3, fontFamily: 'var(--font-mono)',
        fontWeight: 700, whiteSpace: 'nowrap', background: `${color}22`, color, border: `1px solid ${color}44` }}>
      상위 {top}%
    </span>
  );
}

function StockTable({ items, isAbs, loading }) {
  const fmtP = v => v ? v.toLocaleString('ko') : '-';
  const fmtR = v => v != null ? `${v > 0 ? '+' : ''}${(v * 100).toFixed(2)}%` : '-';

  if (loading) return (
    <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--fg-3)' }}>
      <span className="spinner-border spinner-border-sm me-2" role="status" />AI 추천 로딩 중...
    </div>
  );

  return (
    <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.81rem', minWidth: 840 }}>
        <thead>
          <tr style={{ background: 'var(--bg-3)', borderBottom: '2px solid var(--line-1)' }}>
            {['#', '종목', '코드', '출처', isAbs ? '원시 신뢰도' : '신뢰도', '순위', '진입가', '목표가', '손절가', '예상수익', '팩터'].map(h => (
              <th key={h} style={{ padding: '10px 12px', fontWeight: 600, color: 'var(--fg-2)', textAlign: 'left', fontFamily: 'var(--font-mono)', fontSize: '0.71rem', whiteSpace: 'nowrap' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((s, i) => (
            <tr key={`${s.code}-${i}`} style={{ borderBottom: '1px solid var(--line-1)' }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-3)'}
              onMouseLeave={e => e.currentTarget.style.background = ''}>
              <td style={{ padding: '9px 12px', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)', fontSize: '0.71rem' }}>{i + 1}</td>
              <td style={{ padding: '9px 12px', fontWeight: 700, color: 'var(--fg-1)', whiteSpace: 'nowrap' }}>
                {s.name}
                {s.multi_signal === 3 && (
                  <span style={{ marginLeft: 5, fontSize: '0.62rem', padding: '1px 4px', borderRadius: 3,
                    background: '#f59e0b22', color: '#f59e0b', fontWeight: 700, border: '1px solid #f59e0b44' }}>
                    ★ 강력
                  </span>
                )}
              </td>
              <td style={{ padding: '9px 12px', fontFamily: 'var(--font-mono)', color: 'var(--fg-3)', fontSize: '0.75rem' }}>{s.code}</td>
              <td style={{ padding: '9px 12px' }}><SourceBadge source={s.source} absMode={isAbs} /></td>
              <td style={{ padding: '9px 12px' }}><ConfBar value={s.confidence} raw={isAbs} /></td>
              <td style={{ padding: '9px 12px' }}><RankBadge pct={s.model_rank_pct} /></td>
              <td style={{ padding: '9px 12px', fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>{fmtP(s.entry)}</td>
              <td style={{ padding: '9px 12px', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--up)', fontWeight: 600 }}>{fmtP(s.target)}</td>
              <td style={{ padding: '9px 12px', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--down)' }}>{fmtP(s.stop)}</td>
              <td style={{ padding: '9px 12px', fontFamily: 'var(--font-mono)', fontWeight: 700,
                color: (s.expected_return ?? 0) > 0 ? 'var(--up)' : 'var(--fg-3)' }}>
                {fmtR(s.expected_return)}
              </td>
              <td style={{ padding: '6px 12px' }}><FactorChips factors={s.factors} detailed={isAbs} /></td>
            </tr>
          ))}
          {!items.length && (
            <tr><td colSpan={11} style={{ textAlign: 'center', padding: '48px', color: 'var(--fg-3)' }}>
              추천 데이터가 없습니다. <code>python -m XGBoost_v2.daily_recommend</code> 를 실행해주세요.
            </td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export default function Recommend() {
  const [mode, setMode]         = useState('norm');
  const [category, setCategory] = useState('daily');
  const [normData, setNormData] = useState({});
  const [normMeta, setNormMeta] = useState(null);
  const [absData, setAbsData]   = useState(null);
  const [loading, setLoading]     = useState(false);
  const [limit, setLimit]         = useState(20);
  const [passRequired, setPassRequired] = useState(false);
  const [fetchKey, setFetchKey]   = useState(0);

  const isAbs = mode === 'abs';
  const CATS  = isAbs ? CATEGORIES_ABS : CATEGORIES_NORM;

  const handleRefresh = () => {
    setNormData({});
    setNormMeta(null);
    setAbsData(null);
    setPassRequired(false);
    setFetchKey(k => k + 1);
  };

  // 모드 전환 시 카테고리 초기화
  const handleModeChange = (m) => {
    setMode(m);
    setCategory(m === 'abs' ? 'triple' : 'daily');
    setLimit(20);
  };

  // 정규화: fetchKey 변경 시 전체 JSON 로드 → 메타 포함
  useEffect(() => {
    if (isAbs) return;
    let cancelled = false;
    setLoading(true);
    setPassRequired(false);
    api.get('/recommend/json')
      .then(r => {
        if (cancelled) return;
        const data = r.data || {};
        setNormData({
          daily: data.daily || [],
          short: data.short || [],
          swing: data.swing || [],
        });
        const bd   = data.base_date;
        const tm   = data.generated_at?.slice(11, 16);
        const date = (bd ? `${bd.slice(0,4)}-${bd.slice(4,6)}-${bd.slice(6,8)}` : data.generated_at?.slice(0,10))
                   + (tm ? ` ${tm}` : '');
        setNormMeta({ date, model_used: data.model_used, min_conf: data.min_conf, n_total: data.n_total });
      })
      .catch(e => { if (!cancelled && e?.response?.status === 402 && e.response.data?.pass_required) setPassRequired(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [isAbs, fetchKey]);

  // 절대값: isAbs 또는 fetchKey 변경 시 fetch (올바른 URL)
  useEffect(() => {
    if (!isAbs) return;
    setLoading(true);
    setAbsData(null);
    setPassRequired(false);
    api.get('/recommend_abs/json')
      .then(r => setAbsData(r.data?.ok === false ? {} : (r.data || {})))
      .catch(e => {
        if (e?.response?.status === 402 && e.response.data?.pass_required) setPassRequired(true);
        setAbsData({});
      })
      .finally(() => setLoading(false));
  }, [isAbs, fetchKey]);

  const currentItems = (() => {
    if (isAbs) return (absData?.[category] || []).slice(0, limit);
    return (normData[category] || []).slice(0, limit);
  })();

  const totalCount = isAbs
    ? (absData?.[category] || []).length
    : (normData[category] || []).length;

  const meta = isAbs ? (absData ? (() => {
    const bd = absData.base_date;
    const tm = absData.generated_at?.slice(11, 16);
    return {
      date:       (bd ? `${bd.slice(0,4)}-${bd.slice(4,6)}-${bd.slice(6,8)}` : absData.generated_at?.slice(0,10))
                + (tm ? ` ${tm}` : ''),
      model_used: absData.model_used,
      min_conf:   absData.min_conf,
      n_total:    absData.n_total,
      n_buy:      absData.n_buy,
    };
  })() : null) : normMeta;

  return (
    <StockLayout title="AI 추천 종목">

      {/* 모드 토글 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 6, background: 'var(--bg-3)', padding: 4, borderRadius: 'var(--r-3)' }}>
          {MODES.map(m => (
            <button key={m.key} onClick={() => handleModeChange(m.key)}
              style={{
                padding: '7px 18px', borderRadius: 'var(--r-2)', fontSize: '0.83rem', fontWeight: 700,
                border: 'none', cursor: 'pointer', transition: 'all 0.15s',
                background: mode === m.key ? (m.key === 'abs' ? '#7c3aed' : 'var(--accent)') : 'transparent',
                color: mode === m.key ? '#fff' : 'var(--fg-3)',
                boxShadow: mode === m.key ? '0 1px 4px #0003' : 'none',
              }}>
              <i className={`bi ${m.icon} me-1`} />{m.label}
            </button>
          ))}
        </div>

        <button onClick={handleRefresh} title="데이터 새로고침"
          style={{ padding: '7px 12px', borderRadius: 'var(--r-2)', fontSize: '0.88rem',
            border: '1px solid var(--line-2)', background: 'var(--bg-2)',
            color: 'var(--fg-3)', cursor: 'pointer' }}>
          <i className="bi bi-arrow-clockwise" />
        </button>
      </div>

      {/* AI 추천받기 OFF 안내 */}
      {passRequired && (
        <div style={{
          padding: '16px 18px', borderRadius: 'var(--r-3)', marginBottom: 16, fontSize: '0.84rem',
          background: 'var(--bg-2)', border: '1px solid var(--accent)', color: 'var(--fg-1)',
          display: 'flex', alignItems: 'center', gap: 12,
        }}>
          <i className="bi bi-lock-fill" style={{ fontSize: '1.3rem', color: 'var(--accent)', flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 700, marginBottom: 2 }}>AI 추천받기가 꺼져 있습니다.</div>
            <div style={{ fontSize: '0.78rem', color: 'var(--fg-3)' }}>
              내 정보 → 크레딧/충전 탭에서 AI 추천받기를 켜면 오늘 하루 추천을 열람할 수 있습니다.
            </div>
          </div>
          <a href="/my-page" style={{
            flexShrink: 0, textDecoration: 'none', padding: '8px 16px', borderRadius: 'var(--r-2)',
            background: 'var(--accent)', color: '#fff', fontSize: '0.8rem', fontWeight: 700,
          }}>
            내 정보로 이동
          </a>
        </div>
      )}

      {/* 모드 설명 */}
      <div style={{ background: isAbs ? '#7c3aed11' : 'var(--lime-soft)', border: `1px solid ${isAbs ? '#7c3aed44' : 'var(--lime-border)'}`, borderRadius: 'var(--r-2)', padding: '9px 14px', marginBottom: 16, fontSize: '0.78rem', color: 'var(--fg-2)' }}>
        <i className={`bi ${isAbs ? 'bi-bullseye' : 'bi-info-circle'} me-1`} style={{ color: isAbs ? '#7c3aed' : undefined }} />
        {MODES.find(m => m.key === mode)?.desc}
      </div>

      {/* 카테고리 탭 */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap' }}>
        {CATS.map(c => {
          const isActive = category === c.key;
          const isTriple = c.key === 'triple';
          return (
            <button key={c.key} onClick={() => { setCategory(c.key); setLimit(20); }}
              style={{
                padding: '6px 14px', borderRadius: 'var(--r-2)', fontSize: '0.82rem', fontWeight: 600,
                border: isActive
                  ? `1px solid ${isTriple ? '#f59e0b' : isAbs ? '#7c3aed' : 'var(--accent)'}`
                  : '1px solid var(--line-2)',
                background: isActive
                  ? (isTriple ? '#f59e0b' : isAbs ? '#7c3aed' : 'var(--accent)')
                  : 'var(--bg-2)',
                color: isActive ? '#fff' : 'var(--fg-2)', cursor: 'pointer',
              }}>
              <i className={`bi ${c.icon} me-1`} />{c.label}
              {isTriple && absData?.triple?.length > 0 && (
                <span style={{ marginLeft: 4, fontSize: '0.65rem', background: '#fff4', padding: '0 4px', borderRadius: 8 }}>
                  {absData.triple.length}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* 메타 정보 */}
      {meta && (
        <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-2)', padding: '9px 14px', marginBottom: 16, fontSize: '0.78rem', color: 'var(--fg-2)', display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          {meta.date      && <span><i className="bi bi-calendar3 me-1" />기준일: <b>{meta.date}</b></span>}
          <span>
            <i className="bi bi-cpu me-1" />모델: <b style={{ color: meta.model_used ? (isAbs ? '#7c3aed' : 'var(--up)') : 'var(--fg-3)' }}>
              {meta.model_used ? '앙상블(XGB+LGB+메타)' : '팩터 스코어'}
            </b>
          </span>
          {meta.min_conf  != null && <span><i className="bi bi-sliders me-1" />최소 신뢰도: <b>{(meta.min_conf * 100).toFixed(0)}%</b></span>}
          {meta.n_buy     != null && <span><i className="bi bi-list-check me-1" />전체 추천: <b>{meta.n_buy}</b>종목</span>}
          {meta.n_total   != null && <span><i className="bi bi-buildings me-1" />유니버스: <b>{meta.n_total}</b>종목</span>}
        </div>
      )}

      {/* 테이블 */}
      <StockTable items={currentItems} isAbs={isAbs} loading={loading && !currentItems.length} />

      {limit < totalCount && (
        <div style={{ textAlign: 'center', marginTop: 14 }}>
          <button className="btn btn-outline-secondary btn-sm" onClick={() => setLimit(l => l + 20)}>
            더 보기 ({limit} / {totalCount})
          </button>
        </div>
      )}
    </StockLayout>
  );
}
