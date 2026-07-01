import React, { useState, useEffect, useMemo } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

/* ── 등락률 헬퍼 ──────────────────────────────────────────── */
const signLabel = r => r == null ? '-' : `${r > 0 ? '+' : ''}${Number(r).toFixed(2)}%`;

/* ── 히트맵 색상 (8단계) ─────────────────────────────────── */
function heatBg(rate) {
  const v = Number(rate) || 0;
  if (v >=  3)   return { bg: '#14532d', text: '#bbf7d0', border: '#166534' };
  if (v >=  1.5) return { bg: '#166534', text: '#dcfce7', border: '#15803d' };
  if (v >=  0.5) return { bg: '#16a34a', text: '#f0fdf4', border: '#22c55e' };
  if (v >=  0.1) return { bg: '#4ade80', text: '#052e16', border: '#22c55e' };
  if (v > -0.1)  return { bg: 'var(--bg-3)', text: 'var(--fg-2)', border: 'var(--line-2)' };
  if (v > -0.5)  return { bg: '#fca5a5', text: '#450a0a', border: '#ef4444' };
  if (v > -1.5)  return { bg: '#dc2626', text: '#fff1f2', border: '#b91c1c' };
  if (v > -3)    return { bg: '#b91c1c', text: '#fecaca', border: '#991b1b' };
  return               { bg: '#7f1d1d', text: '#fee2e2', border: '#991b1b' };
}

/* ══ 메인 ════════════════════════════════════════════════ */
export default function StockThemeFilter() {
  const [themes, setThemes] = useState([]);   // 네이버 테마 (등락률)
  const [load,   setLoad]   = useState(true);
  const [err,    setErr]    = useState('');
  const [view,   setView]   = useState('heatmap');

  useEffect(() => {
    api.get('/api/naver/themes')
      .then(r => setThemes(r.data?.themes || []))
      .catch(e => setErr(e.response?.data?.error || '네이버 테마 조회 실패'))
      .finally(() => setLoad(false));
  }, []);

  const sorted = useMemo(() =>
    [...themes].sort((a, b) => (Number(b.rate) || 0) - (Number(a.rate) || 0)),
  [themes]);

  const topN   = useMemo(() => sorted.filter(t => Number(t.rate) > 0).slice(0, 10), [sorted]);
  const botN   = useMemo(() => sorted.filter(t => Number(t.rate) < 0).slice(-10).reverse(), [sorted]);
  const maxAbs = useMemo(() => sorted.length ? Math.max(...sorted.map(t => Math.abs(Number(t.rate) || 0)), 0.01) : 0.01, [sorted]);

  const TAB = [
    { key: 'heatmap', label: '히트맵', icon: 'bi-grid-3x3' },
    { key: 'ranking', label: '랭킹',   icon: 'bi-bar-chart-steps' },
  ];

  const Block = ({ t, big }) => {
    const { bg, text, border } = heatBg(t.rate);
    return (
      <div key={t.theme_name}
        style={{ background: bg, border: `1px solid ${border}`, borderRadius: big ? 'var(--r-2)' : 'var(--r-1)', padding: big ? '12px 10px' : '8px 7px', textAlign: 'center' }}>
        <div style={{ fontSize: big ? '0.72rem' : '0.65rem', fontWeight: big ? 700 : 600, color: text, marginBottom: big ? 5 : 3, lineHeight: 1.3, wordBreak: 'keep-all', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: big ? 'normal' : 'nowrap' }} title={t.theme_name}>{t.theme_name}</div>
        <div style={{ fontSize: big ? '0.9rem' : '0.75rem', fontWeight: 800, color: text, fontFamily: 'var(--font-mono)' }}>{signLabel(t.rate)}</div>
      </div>
    );
  };

  return (
    <StockLayout title="테마 필터">

      {/* 탭 */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20, borderBottom: '1px solid var(--line-1)' }}>
        {TAB.map(t => (
          <button key={t.key} onClick={() => setView(t.key)}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px', border: 'none', background: 'none', cursor: 'pointer',
              borderBottom: view === t.key ? '2px solid var(--accent)' : '2px solid transparent',
              color: view === t.key ? 'var(--accent)' : 'var(--fg-3)',
              fontWeight: view === t.key ? 700 : 400, fontSize: '0.85rem', marginBottom: -1, transition: 'all 0.15s' }}>
            <i className={`bi ${t.icon}`} />
            {t.label}
            {t.key === 'heatmap' && themes.length > 0 && (
              <span style={{ fontSize: '0.68rem', background: 'var(--bg-3)', borderRadius: 10, padding: '1px 7px', color: 'var(--fg-3)' }}>{themes.length}</span>
            )}
          </button>
        ))}
        {err && (
          <div style={{ marginLeft: 'auto', fontSize: '0.75rem', color: '#ef4444', alignSelf: 'center' }}>
            <i className="bi bi-exclamation-triangle me-1" />{err}
          </div>
        )}
        {!err && (
          <div style={{ marginLeft: 'auto', alignSelf: 'center', fontSize: '0.68rem', color: 'var(--fg-3)', background: 'var(--bg-3)', borderRadius: 10, padding: '2px 8px', border: '1px solid var(--line-1)' }}>
            데이터: 네이버 증권
          </div>
        )}
      </div>

      {load && (
        <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--fg-3)' }}>
          <div className="spinner" style={{ margin: '0 auto 10px' }} />
          <div style={{ fontSize: '0.82rem' }}>테마 데이터 로딩 중...</div>
        </div>
      )}

      {/* ══ 히트맵 탭 ══ */}
      {!load && view === 'heatmap' && (
        <div>
          <div style={{ fontSize: '0.75rem', color: 'var(--fg-3)', marginBottom: 14 }}>
            색상 강도 = 등락률. 네이버 기준 {themes.length}개 테마.
          </div>

          {topN.length > 0 && (
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#22c55e', marginBottom: 8 }}>
                <i className="bi bi-arrow-up-circle-fill me-1" />상승 테마 ({topN.length}개)
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: 8 }}>
                {topN.map(t => <Block key={t.theme_name} t={t} big />)}
              </div>
            </div>
          )}

          <div>
            <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--fg-3)', marginBottom: 8 }}>
              전체 테마 ({sorted.length}개)
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(110px, 1fr))', gap: 6 }}>
              {sorted.map(t => <Block key={t.theme_name} t={t} />)}
            </div>
          </div>

          {botN.length > 0 && (
            <div style={{ marginTop: 20 }}>
              <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#ef4444', marginBottom: 8 }}>
                <i className="bi bi-arrow-down-circle-fill me-1" />하락 테마 Top 10
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: 8 }}>
                {botN.map(t => <Block key={t.theme_name} t={t} big />)}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ══ 랭킹 탭 ══ */}
      {!load && view === 'ranking' && (
        <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
            <thead>
              <tr style={{ background: 'var(--bg-3)', borderBottom: '1px solid var(--line-1)' }}>
                <th style={{ padding: '9px 12px', fontWeight: 600, color: 'var(--fg-2)', width: 40 }}>#</th>
                <th style={{ padding: '9px 12px', fontWeight: 600, color: 'var(--fg-2)', textAlign: 'left' }}>테마명</th>
                <th style={{ padding: '9px 12px', fontWeight: 600, color: 'var(--fg-2)', width: 220 }}>등락률</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((t, i) => {
                const pct   = Number(t.rate) || 0;
                const isUp  = pct > 0;
                const barW  = Math.min(Math.abs(pct) / maxAbs * 100, 100);
                const color = isUp ? '#22c55e' : pct < 0 ? '#ef4444' : 'var(--fg-3)';
                return (
                  <tr key={t.theme_name} style={{ borderBottom: '1px solid var(--line-1)', background: i % 2 ? 'var(--bg-1)' : 'transparent' }}>
                    <td style={{ padding: '9px 12px', fontFamily: 'var(--font-mono)', color: 'var(--fg-3)', fontSize: '0.72rem', textAlign: 'center' }}>{i + 1}</td>
                    <td style={{ padding: '9px 12px', fontWeight: 500, color: 'var(--fg-1)' }}>{t.theme_name}</td>
                    <td style={{ padding: '9px 14px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <div style={{ flex: 1, height: 6, background: 'var(--line-1)', borderRadius: 3, overflow: 'hidden', direction: isUp ? 'ltr' : 'rtl' }}>
                          <div style={{ height: '100%', width: `${barW}%`, background: color, borderRadius: 3 }} />
                        </div>
                        <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '0.8rem', color, minWidth: 60, textAlign: 'right' }}>
                          {signLabel(pct)}
                        </span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

    </StockLayout>
  );
}
