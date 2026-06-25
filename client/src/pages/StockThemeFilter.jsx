import React, { useState, useEffect, useMemo, useCallback } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

/* ── 등락률 헬퍼 ──────────────────────────────────────────── */
const rateColor = r => r > 0 ? 'var(--up)' : r < 0 ? 'var(--down)' : 'var(--fg-3)';
const rateLabel = r => r == null ? '-' : `${r > 0 ? '▲' : r < 0 ? '▼' : ''}${Math.abs(Number(r)).toFixed(2)}%`;
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

/* ── 등락 배지 ───────────────────────────────────────────── */
function RateBadge({ rate }) {
  if (rate == null) return null;
  const v = Number(rate);
  const color = v > 0 ? '#22c55e' : v < 0 ? '#ef4444' : '#64748b';
  const bg    = v > 0 ? 'rgba(34,197,94,0.1)' : v < 0 ? 'rgba(239,68,68,0.1)' : 'rgba(100,116,139,0.1)';
  return (
    <span style={{ fontSize: '0.63rem', fontWeight: 700, padding: '1px 6px', borderRadius: 4,
      background: bg, color, fontFamily: 'var(--font-mono)', flexShrink: 0 }}>
      {signLabel(rate)}
    </span>
  );
}

/* ── 종목 미니 테이블 ────────────────────────────────────── */
function StockTable({ stocks }) {
  if (!stocks.length) return (
    <div style={{ padding: '20px', textAlign: 'center', color: 'var(--fg-3)', fontSize: '0.8rem' }}>종목 없음</div>
  );
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
        <thead>
          <tr style={{ background: 'var(--bg-3)' }}>
            {['종목', '코드', '현재가', '등락률', '고가', '저가', '거래량'].map(h => (
              <th key={h} style={{ padding: '7px 10px', fontWeight: 600, color: 'var(--fg-2)', textAlign: h === '종목' ? 'left' : 'right', whiteSpace: 'nowrap' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {stocks.map((s, i) => (
            <tr key={s.code || i} style={{ borderBottom: '1px solid var(--line-1)', background: i % 2 ? 'var(--bg-1)' : 'transparent' }}>
              <td style={{ padding: '7px 10px', fontWeight: 700 }}>{s.name || s.code}</td>
              <td style={{ padding: '7px 10px', textAlign: 'right', fontFamily: 'var(--font-mono)', color: 'var(--fg-3)', fontSize: '0.7rem' }}>{s.code}</td>
              <td style={{ padding: '7px 10px', textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{s.price?.toLocaleString('ko') ?? '-'}</td>
              <td style={{ padding: '7px 10px', textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 600, color: rateColor(s.rate) }}>{rateLabel(s.rate)}</td>
              <td style={{ padding: '7px 10px', textAlign: 'right', fontFamily: 'var(--font-mono)', color: 'var(--up)' }}>{s.high?.toLocaleString('ko') ?? '-'}</td>
              <td style={{ padding: '7px 10px', textAlign: 'right', fontFamily: 'var(--font-mono)', color: 'var(--down)' }}>{s.low?.toLocaleString('ko') ?? '-'}</td>
              <td style={{ padding: '7px 10px', textAlign: 'right', fontFamily: 'var(--font-mono)', color: 'var(--fg-2)' }}>{s.volume?.toLocaleString('ko') ?? '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── 네이버 테마명 → 키움 테마 퍼지 매핑 ────────────────── */
function findKiwoomTheme(naverName, kiwoomThemes) {
  if (!naverName || !kiwoomThemes?.length) return null;
  // 1. 정확 매칭
  const exact = kiwoomThemes.find(t => t.theme_name === naverName);
  if (exact) return exact;
  // 2. 키움명(언더스코어→공백)이 네이버명과 일치
  const normMatch = kiwoomThemes.find(t =>
    t.theme_name.replace(/_/g, ' ') === naverName
  );
  if (normMatch) return normMatch;
  // 3. 첫 번째 키워드 포함 매칭
  const firstKw = naverName.split(/[\s(（/]/)[0];
  if (firstKw.length >= 2) {
    const partial = kiwoomThemes.find(t =>
      t.theme_name.replace(/_/g, ' ').includes(firstKw)
    );
    if (partial) return partial;
  }
  return null;
}

/* ══ 메인 ════════════════════════════════════════════════ */
export default function StockThemeFilter() {
  // 데이터
  const [naverThemes,  setNaverThemes]  = useState([]);   // 히트맵/랭킹용 (네이버 265개)
  const [kiwoomThemes, setKiwoomThemes] = useState([]);   // 종목검색용 (키움 142개)
  const [naverLoad,    setNaverLoad]    = useState(true);
  const [kiwoomLoad,   setKiwoomLoad]   = useState(true);
  const [naverErr,     setNaverErr]     = useState('');
  const [kiwoomErr,    setKiwoomErr]    = useState('');

  // UI 상태
  const [view,      setView]      = useState('heatmap');
  const [query,     setQuery]     = useState('');
  const [selected,  setSelected]  = useState(null);      // 선택된 키움 테마
  const [stocks,    setStocks]    = useState([]);
  const [codeCount, setCodeCount] = useState(null);
  const [loading,   setLoading]   = useState(false);
  const [error,     setError]     = useState('');
  const [expanded,  setExpanded]  = useState({});         // 랭킹 탭 펼침

  useEffect(() => {
    // 네이버 테마 (히트맵/랭킹)
    api.get('/api/naver/themes')
      .then(r => setNaverThemes(r.data?.themes || []))
      .catch(e => setNaverErr(e.response?.data?.error || '네이버 테마 조회 실패'))
      .finally(() => setNaverLoad(false));

    // 키움 테마 (종목검색)
    api.get('/api/kiwoom/themes', { params: { sort: 0 } })
      .then(r => setKiwoomThemes(r.data?.themes || []))
      .catch(e => setKiwoomErr(e.response?.data?.error || '키움 테마 조회 실패'))
      .finally(() => setKiwoomLoad(false));
  }, []);

  /* 종목 조회 (키움 theme_code 필요) */
  const fetchStocks = useCallback(async theme => {
    const r = await api.post('/api/kiwoom/theme/stocks', {
      theme_code: theme.theme_code,
      theme_name: theme.theme_name,
      limit: 30,
      supplement: true,
    });
    return { results: r.data?.results || [], code_count: r.data?.code_count ?? null };
  }, []);

  /* 키움 테마 선택 */
  const pick = useCallback(async theme => {
    setSelected(theme); setLoading(true); setStocks([]); setError(''); setCodeCount(null);
    try {
      const d = await fetchStocks(theme);
      setStocks(d.results); setCodeCount(d.code_count);
    } catch (e) { setError(e.response?.data?.error || '테마 종목 조회 실패'); }
    setLoading(false);
  }, [fetchStocks]);

  /* 히트맵 클릭: 네이버 테마 → 종목검색 탭으로 이동 */
  const heatClick = useCallback(naverTheme => {
    setView('search');
    setQuery(naverTheme.theme_name);
    // 키움 테마에서 유사 매칭 시도 → 자동 선택
    const match = findKiwoomTheme(naverTheme.theme_name, kiwoomThemes);
    if (match) pick(match);
    else { setSelected(null); setStocks([]); setError(''); }
  }, [kiwoomThemes, pick]);

  /* 랭킹 탭 행 펼치기 (네이버 테마 → 키움 매핑 시도) */
  const toggleExpand = useCallback(async naverTheme => {
    const key = naverTheme.theme_name;
    if (expanded[key]) { setExpanded(v => ({ ...v, [key]: null })); return; }

    const kMatch = findKiwoomTheme(naverTheme.theme_name, kiwoomThemes);
    if (!kMatch) {
      setExpanded(v => ({ ...v, [key]: { loading: false, stocks: [], noMatch: true } }));
      return;
    }
    setExpanded(v => ({ ...v, [key]: { loading: true, stocks: [], noMatch: false } }));
    try {
      const d = await fetchStocks(kMatch);
      setExpanded(v => ({ ...v, [key]: { loading: false, stocks: d.results, noMatch: false } }));
    } catch {
      setExpanded(v => ({ ...v, [key]: { loading: false, stocks: [], noMatch: false } }));
    }
  }, [expanded, kiwoomThemes, fetchStocks]);

  /* 파생 데이터 */
  const sorted = useMemo(() =>
    [...naverThemes].sort((a, b) => (Number(b.rate) || 0) - (Number(a.rate) || 0)),
  [naverThemes]);

  const topN    = useMemo(() => sorted.filter(t => Number(t.rate) > 0).slice(0, 10), [sorted]);
  const botN    = useMemo(() => sorted.filter(t => Number(t.rate) < 0).slice(-10).reverse(), [sorted]);
  const maxAbs  = useMemo(() => sorted.length ? Math.max(...sorted.map(t => Math.abs(Number(t.rate) || 0)), 0.01) : 0.01, [sorted]);

  const filteredSearch = useMemo(() =>
    kiwoomThemes.filter(t => !query || t.theme_name?.includes(query)),
  [kiwoomThemes, query]);

  const listLoad = naverLoad || kiwoomLoad;

  /* ── 탭 ── */
  const TAB = [
    { key: 'heatmap', label: '히트맵',   icon: 'bi-grid-3x3' },
    { key: 'ranking', label: '랭킹',     icon: 'bi-bar-chart-steps' },
    { key: 'search',  label: '종목검색', icon: 'bi-search' },
  ];

  return (
    <StockLayout title="테마 필터">

      {/* 탭 */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20, borderBottom: '1px solid var(--line-1)', paddingBottom: 0 }}>
        {TAB.map(t => (
          <button key={t.key} onClick={() => setView(t.key)}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px', border: 'none', background: 'none', cursor: 'pointer',
              borderBottom: view === t.key ? '2px solid var(--accent)' : '2px solid transparent',
              color: view === t.key ? 'var(--accent)' : 'var(--fg-3)',
              fontWeight: view === t.key ? 700 : 400, fontSize: '0.85rem', marginBottom: -1, transition: 'all 0.15s' }}>
            <i className={`bi ${t.icon}`} />
            {t.label}
            {t.key === 'heatmap' && naverThemes.length > 0 && (
              <span style={{ fontSize: '0.68rem', background: 'var(--bg-3)', borderRadius: 10, padding: '1px 7px', color: 'var(--fg-3)' }}>{naverThemes.length}</span>
            )}
          </button>
        ))}
        {(naverErr || kiwoomErr) && (
          <div style={{ marginLeft: 'auto', fontSize: '0.75rem', color: '#ef4444', alignSelf: 'center' }}>
            <i className="bi bi-exclamation-triangle me-1" />{naverErr || kiwoomErr}
          </div>
        )}
        {/* 데이터 출처 뱃지 */}
        {view !== 'search' && (
          <div style={{ marginLeft: 'auto', alignSelf: 'center', fontSize: '0.68rem', color: 'var(--fg-3)', background: 'var(--bg-3)', borderRadius: 10, padding: '2px 8px', border: '1px solid var(--line-1)' }}>
            데이터: 네이버 증권
          </div>
        )}
        {view === 'search' && (
          <div style={{ marginLeft: 'auto', alignSelf: 'center', fontSize: '0.68rem', color: 'var(--fg-3)', background: 'var(--bg-3)', borderRadius: 10, padding: '2px 8px', border: '1px solid var(--line-1)' }}>
            데이터: 키움 API
          </div>
        )}
      </div>

      {listLoad && (
        <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--fg-3)' }}>
          <div className="spinner" style={{ margin: '0 auto 10px' }} />
          <div style={{ fontSize: '0.82rem' }}>테마 데이터 로딩 중...</div>
        </div>
      )}

      {/* ══ 히트맵 탭 ══ */}
      {!listLoad && view === 'heatmap' && (
        <div>
          <div style={{ fontSize: '0.75rem', color: 'var(--fg-3)', marginBottom: 14 }}>
            테마 블록 클릭 → 종목검색 탭으로 이동. 색상 강도 = 등락률. 네이버 기준 {naverThemes.length}개 테마.
          </div>

          {/* 상위 (양수 테마) */}
          {topN.length > 0 && (
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#22c55e', marginBottom: 8 }}>
                <i className="bi bi-arrow-up-circle-fill me-1" />상승 테마 ({topN.length}개)
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: 8 }}>
                {topN.map(t => {
                  const { bg, text, border } = heatBg(t.rate);
                  return (
                    <button key={t.theme_name} onClick={() => heatClick(t)}
                      style={{ background: bg, border: `1px solid ${border}`, borderRadius: 'var(--r-2)', padding: '12px 10px', cursor: 'pointer', textAlign: 'center', transition: 'transform 0.1s, box-shadow 0.1s' }}
                      onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.2)'; }}
                      onMouseLeave={e => { e.currentTarget.style.transform = ''; e.currentTarget.style.boxShadow = ''; }}>
                      <div style={{ fontSize: '0.72rem', fontWeight: 700, color: text, marginBottom: 5, lineHeight: 1.3, wordBreak: 'keep-all' }}>{t.theme_name}</div>
                      <div style={{ fontSize: '0.9rem', fontWeight: 800, color: text, fontFamily: 'var(--font-mono)' }}>{signLabel(t.rate)}</div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* 전체 그리드 */}
          <div>
            <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--fg-3)', marginBottom: 8 }}>
              전체 테마 ({sorted.length}개)
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(110px, 1fr))', gap: 6 }}>
              {sorted.map(t => {
                const { bg, text, border } = heatBg(t.rate);
                return (
                  <button key={t.theme_name} onClick={() => heatClick(t)}
                    style={{ background: bg, border: `1px solid ${border}`, borderRadius: 'var(--r-1)', padding: '8px 7px', cursor: 'pointer', textAlign: 'center', transition: 'transform 0.1s' }}
                    onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-1px)'; }}
                    onMouseLeave={e => { e.currentTarget.style.transform = ''; }}>
                    <div style={{ fontSize: '0.65rem', fontWeight: 600, color: text, marginBottom: 3, lineHeight: 1.3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={t.theme_name}>{t.theme_name}</div>
                    <div style={{ fontSize: '0.75rem', fontWeight: 800, color: text, fontFamily: 'var(--font-mono)' }}>{signLabel(t.rate)}</div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* 하위 (음수 테마 TOP 10) */}
          {botN.length > 0 && (
            <div style={{ marginTop: 20 }}>
              <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#ef4444', marginBottom: 8 }}>
                <i className="bi bi-arrow-down-circle-fill me-1" />하락 테마 Top 10
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: 8 }}>
                {botN.map(t => {
                  const { bg, text, border } = heatBg(t.rate);
                  return (
                    <button key={t.theme_name} onClick={() => heatClick(t)}
                      style={{ background: bg, border: `1px solid ${border}`, borderRadius: 'var(--r-2)', padding: '12px 10px', cursor: 'pointer', textAlign: 'center', transition: 'transform 0.1s, box-shadow 0.1s' }}
                      onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.2)'; }}
                      onMouseLeave={e => { e.currentTarget.style.transform = ''; e.currentTarget.style.boxShadow = ''; }}>
                      <div style={{ fontSize: '0.72rem', fontWeight: 700, color: text, marginBottom: 5, lineHeight: 1.3, wordBreak: 'keep-all' }}>{t.theme_name}</div>
                      <div style={{ fontSize: '0.9rem', fontWeight: 800, color: text, fontFamily: 'var(--font-mono)' }}>{signLabel(t.rate)}</div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ══ 랭킹 탭 ══ */}
      {!listLoad && view === 'ranking' && (
        <div>
          <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
              <thead>
                <tr style={{ background: 'var(--bg-3)', borderBottom: '1px solid var(--line-1)' }}>
                  <th style={{ padding: '9px 12px', fontWeight: 600, color: 'var(--fg-2)', width: 40 }}>#</th>
                  <th style={{ padding: '9px 12px', fontWeight: 600, color: 'var(--fg-2)', textAlign: 'left' }}>테마명</th>
                  <th style={{ padding: '9px 12px', fontWeight: 600, color: 'var(--fg-2)', width: 220 }}>등락률</th>
                  <th style={{ padding: '9px 12px', fontWeight: 600, color: 'var(--fg-2)', width: 60 }}></th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((t, i) => {
                  const pct    = Number(t.rate) || 0;
                  const isUp   = pct > 0;
                  const barW   = Math.min(Math.abs(pct) / maxAbs * 100, 100);
                  const barColor = isUp ? '#22c55e' : pct < 0 ? '#ef4444' : 'var(--fg-3)';
                  const key    = t.theme_name;
                  const exp    = expanded[key];
                  const isOpen = !!exp;

                  return (
                    <React.Fragment key={key}>
                      <tr style={{ borderBottom: isOpen ? 'none' : '1px solid var(--line-1)', background: isOpen ? 'var(--lime-soft)' : i % 2 ? 'var(--bg-1)' : 'transparent' }}>
                        <td style={{ padding: '9px 12px', fontFamily: 'var(--font-mono)', color: 'var(--fg-3)', fontSize: '0.72rem', textAlign: 'center' }}>{i + 1}</td>
                        <td style={{ padding: '9px 12px', fontWeight: isOpen ? 700 : 500, color: isOpen ? 'var(--accent)' : 'var(--fg-1)' }}>
                          {t.theme_name}
                        </td>
                        <td style={{ padding: '9px 14px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <div style={{ flex: 1, height: 6, background: 'var(--line-1)', borderRadius: 3, overflow: 'hidden', direction: isUp ? 'ltr' : 'rtl' }}>
                              <div style={{ height: '100%', width: `${barW}%`, background: barColor, borderRadius: 3 }} />
                            </div>
                            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '0.8rem', color: barColor, minWidth: 60, textAlign: 'right' }}>
                              {signLabel(pct)}
                            </span>
                          </div>
                        </td>
                        <td style={{ padding: '9px 12px', textAlign: 'center' }}>
                          <button onClick={() => toggleExpand(t)}
                            style={{ background: isOpen ? 'var(--accent)' : 'var(--bg-3)', border: `1px solid ${isOpen ? 'var(--accent)' : 'var(--line-2)'}`, borderRadius: 'var(--r-1)', padding: '3px 8px', cursor: 'pointer', color: isOpen ? '#fff' : 'var(--fg-2)', fontSize: '0.72rem', fontWeight: 600, transition: 'all 0.15s', whiteSpace: 'nowrap' }}>
                            {isOpen ? '닫기' : '종목'}
                          </button>
                        </td>
                      </tr>
                      {isOpen && (
                        <tr style={{ borderBottom: '1px solid var(--line-1)' }}>
                          <td colSpan={4} style={{ padding: 0, background: 'var(--bg-1)' }}>
                            {exp.loading ? (
                              <div style={{ padding: '16px', textAlign: 'center', color: 'var(--fg-3)', fontSize: '0.78rem' }}>
                                <div className="spinner" style={{ display: 'inline-block', width: 14, height: 14, marginRight: 6, border: '2px solid var(--line-2)', borderTopColor: 'var(--accent)', borderRadius: '50%', animation: 'spin 0.8s linear infinite', verticalAlign: 'middle' }} />
                                종목 조회 중...
                              </div>
                            ) : exp.noMatch ? (
                              <div style={{ padding: '14px 16px', fontSize: '0.78rem', color: 'var(--fg-3)' }}>
                                <i className="bi bi-info-circle me-1" />
                                키움 API에서 해당 테마를 찾을 수 없습니다.
                                <button onClick={() => { setView('search'); setQuery(t.theme_name); }}
                                  style={{ marginLeft: 8, fontSize: '0.72rem', background: 'var(--bg-3)', border: '1px solid var(--line-2)', borderRadius: 'var(--r-1)', padding: '2px 8px', cursor: 'pointer', color: 'var(--fg-2)' }}>
                                  종목검색 탭에서 찾기
                                </button>
                              </div>
                            ) : (
                              <StockTable stocks={exp.stocks} />
                            )}
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ══ 종목검색 탭 ══ */}
      {!listLoad && view === 'search' && (
        <div style={{ display: 'grid', gap: 16, gridTemplateColumns: '260px 1fr' }}>

          {/* 키움 테마 목록 */}
          <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'hidden', height: 'fit-content' }}>
            <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--line-1)' }}>
              <div style={{ position: 'relative' }}>
                <i className="bi bi-search" style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', color: 'var(--fg-3)', fontSize: '0.78rem', pointerEvents: 'none' }} />
                <input className="form-control" value={query} onChange={e => setQuery(e.target.value)}
                  placeholder="테마 검색" style={{ fontSize: '0.8rem', paddingLeft: 26 }} />
              </div>
              <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)', marginTop: 5 }}>
                {filteredSearch.length}개 (키움 기준 총 {kiwoomThemes.length}개)
              </div>
            </div>
            {kiwoomErr ? (
              <div style={{ padding: '14px', fontSize: '0.78rem', color: '#ef4444' }}>
                <i className="bi bi-exclamation-triangle me-1" />{kiwoomErr}
              </div>
            ) : (
              <div style={{ maxHeight: 560, overflowY: 'auto' }}>
                {filteredSearch.map(t => {
                  const isActive = selected?.theme_code === t.theme_code;
                  return (
                    <button key={t.theme_code} onClick={() => pick(t)}
                      style={{ width: '100%', padding: '8px 12px', textAlign: 'left', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6,
                        background: isActive ? 'var(--lime-soft)' : 'transparent',
                        border: 'none', borderBottom: '1px solid var(--line-1)', cursor: 'pointer', transition: 'background 0.1s' }}
                      onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = 'var(--bg-3)'; }}
                      onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}>
                      <span style={{ fontSize: '0.8rem', fontWeight: isActive ? 700 : 400, color: isActive ? 'var(--accent)' : 'var(--fg-2)', flex: 1 }}>
                        {t.theme_name}
                      </span>
                    </button>
                  );
                })}
                {!filteredSearch.length && (
                  <div style={{ padding: '30px 14px', textAlign: 'center', color: 'var(--fg-3)', fontSize: '0.8rem' }}>
                    {query ? '검색 결과 없음' : '테마 없음'}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* 종목 패널 */}
          <div>
            {loading && (
              <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--fg-3)' }}>
                <div className="spinner" style={{ margin: '0 auto 12px' }} />
                <div style={{ fontSize: '0.85rem' }}>「{selected?.theme_name}」 종목 조회 중...</div>
              </div>
            )}
            {!loading && error && (
              <div style={{ padding: '12px 16px', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 'var(--r-2)', fontSize: '0.82rem', color: '#ef4444', marginBottom: 12 }}>
                <i className="bi bi-exclamation-triangle me-1" />{error}
              </div>
            )}
            {!loading && selected && (
              <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'hidden' }}>
                <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--line-1)', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontWeight: 700, fontSize: '0.88rem' }}>「{selected.theme_name}」</span>
                  <span style={{ fontSize: '0.75rem', color: 'var(--fg-3)' }}>
                    {codeCount != null && `전체 ${codeCount}개 중 `}{stocks.length}개 조회
                  </span>
                </div>
                <StockTable stocks={stocks} />
              </div>
            )}
            {!loading && !selected && !error && (
              <div style={{ textAlign: 'center', padding: '80px 0', color: 'var(--fg-3)' }}>
                <i className="bi bi-tags" style={{ fontSize: '2.5rem', display: 'block', marginBottom: 12, opacity: 0.25 }} />
                <p style={{ margin: 0, fontSize: '0.85rem' }}>좌측에서 테마를 선택하세요.</p>
                <p style={{ fontSize: '0.74rem', marginTop: 6, opacity: 0.7 }}>히트맵/랭킹에서 클릭해도 자동 이동됩니다.</p>
              </div>
            )}
          </div>
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </StockLayout>
  );
}
