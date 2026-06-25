import React, { useState, useEffect, useCallback, useRef } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

function StockSearch({ onAdd, loading }) {
  const [query,       setQuery]       = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [selected,    setSelected]    = useState(null); // {code, name}
  const [open,        setOpen]        = useState(false);
  const [searching,   setSearching]   = useState(false);
  const ref   = useRef(null);
  const timer = useRef(null);

  useEffect(() => {
    const handler = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleChange = (e) => {
    const v = e.target.value;
    setQuery(v);
    setSelected(null);
    clearTimeout(timer.current);
    if (!v.trim()) { setSuggestions([]); setOpen(false); return; }
    timer.current = setTimeout(async () => {
      setSearching(true);
      try {
        const r = await api.get(`/search-stock-kr?q=${encodeURIComponent(v.trim())}`);
        setSuggestions(r.data || []);
        setOpen((r.data || []).length > 0);
      } catch { setSuggestions([]); }
      setSearching(false);
    }, 280);
  };

  const pick = (s) => {
    setSelected(s);
    setQuery(`${s.name} (${s.code})`);
    setSuggestions([]);
    setOpen(false);
  };

  const handleAdd = () => {
    if (!selected) return;
    onAdd(selected.code, selected.name);
    setQuery(''); setSelected(null); setSuggestions([]);
  };

  return (
    <div ref={ref} style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 14, paddingBottom: 14, borderBottom: '1px solid var(--line-1)', position: 'relative' }}>
      <div style={{ position: 'relative' }}>
        <input
          className="form-control form-control-sm"
          value={query}
          onChange={handleChange}
          onFocus={() => suggestions.length > 0 && setOpen(true)}
          onKeyDown={e => { if (e.key === 'Enter' && selected) handleAdd(); if (e.key === 'Escape') setOpen(false); }}
          placeholder="종목명 또는 코드 입력 (예: 삼성전자, 005930)"
          style={{ paddingRight: 28 }}
        />
        {searching && (
          <i className="bi bi-arrow-clockwise spin" style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)', color: 'var(--fg-3)', fontSize: '0.78rem', pointerEvents: 'none' }} />
        )}
        {open && suggestions.length > 0 && (
          <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50, background: 'var(--bg-1)', border: '1px solid var(--line-2)', borderRadius: 'var(--r-2)', boxShadow: 'var(--menu-shadow)', marginTop: 2, maxHeight: 200, overflowY: 'auto' }}>
            {suggestions.map(s => (
              <button key={s.code} onMouseDown={() => pick(s)}
                style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '8px 12px', border: 'none', background: 'none', cursor: 'pointer', textAlign: 'left' }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-3)'}
                onMouseLeave={e => e.currentTarget.style.background = 'none'}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--fg-3)', minWidth: 52 }}>{s.code}</span>
                <span style={{ fontSize: '0.83rem', fontWeight: 600, color: 'var(--fg-1)', flex: 1 }}>{s.name}</span>
                {s.market && <span style={{ fontSize: '0.65rem', color: 'var(--fg-3)', background: 'var(--bg-3)', borderRadius: 4, padding: '1px 5px' }}>{s.market}</span>}
              </button>
            ))}
          </div>
        )}
      </div>
      <button className="btn btn-primary btn-sm" onClick={handleAdd} disabled={loading || !selected}>
        {loading ? '추가 중...' : <><i className="bi bi-plus-lg me-1" />추가</>}
      </button>
    </div>
  );
}

const CAT_META = {
  positive: { label: '호재', color: '#22c55e', bg: 'rgba(34,197,94,0.1)',   border: 'rgba(34,197,94,0.25)',  icon: 'bi-graph-up-arrow' },
  negative: { label: '악재', color: '#ef4444', bg: 'rgba(239,68,68,0.1)',   border: 'rgba(239,68,68,0.25)',  icon: 'bi-graph-down-arrow' },
  neutral:  { label: '일반', color: '#94a3b8', bg: 'rgba(148,163,184,0.1)', border: 'rgba(148,163,184,0.25)', icon: 'bi-file-text' },
};

function CatBadge({ cat }) {
  const m = CAT_META[cat] || CAT_META.neutral;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: '0.68rem', fontWeight: 700, padding: '2px 7px', borderRadius: 20, background: m.bg, color: m.color, border: `1px solid ${m.border}`, whiteSpace: 'nowrap' }}>
      <i className={`bi ${m.icon}`} />{m.label}
    </span>
  );
}

function fmtDate(raw) {
  if (!raw) return '-';
  if (raw.length === 8) return `${raw.slice(0,4)}-${raw.slice(4,6)}-${raw.slice(6)}`;
  return raw.slice(0, 10);
}

function dartLink(rcept_no) {
  if (!rcept_no) return null;
  return `https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${rcept_no}`;
}

export default function DartAlert() {
  const [watchlist,   setWatchlist]   = useState([]);
  const [disclosures, setDisclosures] = useState([]);
  const [loading,     setLoading]     = useState(true);
  const [checking,    setChecking]    = useState(false);
  const [checkResult, setCheckResult] = useState(null);
  const [error,       setError]       = useState('');
  const [addLoading,  setAddLoading]  = useState(false);
  const [filterCat,   setFilterCat]   = useState('all');
  const [filterCode,  setFilterCode]  = useState('all');
  const [days,        setDays]        = useState(30);

  const loadWatchlist = useCallback(async () => {
    const r = await api.get('/api/dart_alert/watchlist');
    return r.data?.watchlist || [];
  }, []);

  const loadDisclosures = useCallback(async (d = days) => {
    const r = await api.get(`/api/dart_alert/watchlist_history?days=${d}`);
    return r.data?.items || [];
  }, [days]);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [wl, disc] = await Promise.all([loadWatchlist(), loadDisclosures()]);
      setWatchlist(wl);
      setDisclosures(disc);
    } catch (e) {
      setError(e.response?.data?.error || '데이터 로드 실패');
    }
    setLoading(false);
  }, [loadWatchlist, loadDisclosures]);

  useEffect(() => { load(); }, [load]);

  const handleCheck = async () => {
    setChecking(true); setCheckResult(null);
    try {
      const r = await api.post('/api/dart_alert/run');
      setCheckResult({ new: r.data?.new ?? 0, at: r.data?.run_at });
      await load();
    } catch (e) {
      setError(e.response?.data?.error || '공시 확인 실패');
    }
    setChecking(false);
  };

  const handleAdd = async (code, name) => {
    setAddLoading(true);
    try {
      await api.post('/api/dart_alert/watchlist', { code, name });
      const wl = await loadWatchlist();
      setWatchlist(wl);
    } catch (e) {
      setError(e.response?.data?.error || '추가 실패');
    }
    setAddLoading(false);
  };

  const handleDelete = async (code) => {
    try {
      await api.delete(`/api/dart_alert/watchlist/${code}`);
      setWatchlist(p => p.filter(w => w.code !== code));
      setDisclosures(p => p.filter(d => d.code !== code));
    } catch (e) {
      setError(e.response?.data?.error || '삭제 실패');
    }
  };

  const handleDaysChange = async (d) => {
    setDays(d);
    setLoading(true);
    try {
      const disc = await loadDisclosures(d);
      setDisclosures(disc);
    } catch (e) { setError('로드 실패'); }
    setLoading(false);
  };

  const filtered = disclosures.filter(d =>
    (filterCat  === 'all' || d.category === filterCat) &&
    (filterCode === 'all' || d.code     === filterCode)
  );

  const catCounts = { positive: 0, negative: 0, neutral: 0 };
  disclosures.forEach(d => { if (catCounts[d.category] != null) catCounts[d.category]++; });

  return (
    <StockLayout title="공시 알림">
      {error && (
        <div style={{ padding: '9px 14px', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 'var(--r-2)', fontSize: '0.82rem', color: 'var(--down)', marginBottom: 14, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span><i className="bi bi-exclamation-triangle me-2" />{error}</span>
          <button onClick={() => setError('')} style={{ background: 'none', border: 'none', color: 'var(--down)', cursor: 'pointer' }}><i className="bi bi-x" /></button>
        </div>
      )}

      {loading ? (
        <div style={{ textAlign: 'center', padding: '80px 0' }}><div className="spinner" style={{ margin: '0 auto' }} /></div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 260px', gap: 16, alignItems: 'start' }}>

          {/* ── 좌측: 공시 목록 ── */}
          <div>
            {/* 툴바 */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
              <span style={{ fontWeight: 700, fontSize: '0.88rem', color: 'var(--fg-1)' }}>
                최근 공시
                <span style={{ fontWeight: 400, color: 'var(--fg-3)', fontSize: '0.78rem', marginLeft: 6 }}>({filtered.length}건)</span>
              </span>

              {/* 기간 선택 */}
              <select className="form-select form-select-sm" value={days} onChange={e => handleDaysChange(+e.target.value)} style={{ width: 90 }}>
                {[7, 14, 30, 60, 90].map(d => <option key={d} value={d}>{d}일</option>)}
              </select>

              {/* 카테고리 필터 */}
              <div style={{ display: 'flex', gap: 4 }}>
                {[['all', '전체'], ['positive', '호재'], ['negative', '악재'], ['neutral', '일반']].map(([key, label]) => (
                  <button key={key} onClick={() => setFilterCat(key)} style={{ padding: '3px 10px', borderRadius: 20, border: filterCat === key ? `1.5px solid ${key === 'all' ? 'var(--accent)' : CAT_META[key]?.color}` : '1.5px solid var(--line-1)', background: filterCat === key ? `${key === 'all' ? 'var(--accent)' : CAT_META[key]?.color}18` : 'transparent', color: filterCat === key ? (key === 'all' ? 'var(--accent)' : CAT_META[key]?.color) : 'var(--fg-3)', fontSize: '0.72rem', fontWeight: 600, cursor: 'pointer' }}>
                    {label}{key !== 'all' && catCounts[key] > 0 && ` (${catCounts[key]})`}
                  </button>
                ))}
              </div>

              {/* 종목 필터 */}
              {watchlist.length > 0 && (
                <select className="form-select form-select-sm" value={filterCode} onChange={e => setFilterCode(e.target.value)} style={{ width: 120, marginLeft: 'auto' }}>
                  <option value="all">전체 종목</option>
                  {watchlist.map(w => <option key={w.code} value={w.code}>{w.name}</option>)}
                </select>
              )}

              <button onClick={handleCheck} disabled={checking} style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 12px', borderRadius: 'var(--r-2)', border: '1px solid var(--line-1)', background: 'var(--bg-2)', color: 'var(--fg-2)', cursor: checking ? 'not-allowed' : 'pointer', fontSize: '0.78rem', whiteSpace: 'nowrap' }}>
                <i className={`bi bi-arrow-clockwise${checking ? ' spin' : ''}`} />
                {checking ? '확인 중...' : '지금 확인'}
              </button>
            </div>

            {/* 확인 결과 */}
            {checkResult && (
              <div style={{ padding: '8px 14px', background: checkResult.new > 0 ? 'rgba(34,197,94,0.08)' : 'var(--bg-2)', border: `1px solid ${checkResult.new > 0 ? 'rgba(34,197,94,0.3)' : 'var(--line-1)'}`, borderRadius: 'var(--r-2)', fontSize: '0.78rem', color: checkResult.new > 0 ? 'var(--up)' : 'var(--fg-3)', marginBottom: 10 }}>
                <i className={`bi ${checkResult.new > 0 ? 'bi-bell-fill' : 'bi-bell'} me-2`} />
                {checkResult.new > 0 ? `신규 공시 ${checkResult.new}건 — 카카오톡 알림 발송` : '새 공시 없음'}
                <span style={{ marginLeft: 8, opacity: 0.6 }}>{checkResult.at}</span>
              </div>
            )}

            {/* 공시 카드 목록 */}
            {filtered.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--fg-3)' }}>
                <i className="bi bi-file-text" style={{ fontSize: '2rem', display: 'block', marginBottom: 10, opacity: 0.3 }} />
                <p style={{ margin: 0, fontSize: '0.85rem' }}>
                  {watchlist.length === 0 ? '감시 종목을 먼저 추가하세요.' : '해당 기간 내 공시가 없습니다.'}
                </p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {filtered.map((d, i) => {
                  const m = CAT_META[d.category] || CAT_META.neutral;
                  const link = dartLink(d.rcept_no);
                  return (
                    <div key={`${d.code}-${d.disclose_date}-${i}`} style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '12px 16px', borderLeft: `3px solid ${m.color}` }}>
                      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 6 }}>
                        <CatBadge cat={d.category} />
                        <span style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--fg-1)', flex: 1, lineHeight: 1.4 }}>{d.title}</span>
                        {link && (
                          <a href={link} target="_blank" rel="noreferrer" style={{ flexShrink: 0, color: 'var(--accent)', fontSize: '0.72rem', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 3 }}>
                            <i className="bi bi-box-arrow-up-right" />DART
                          </a>
                        )}
                      </div>
                      <div style={{ display: 'flex', gap: 12, fontSize: '0.72rem', color: 'var(--fg-3)' }}>
                        <span style={{ fontWeight: 600, color: 'var(--fg-2)' }}>{d.name || d.code}</span>
                        <span style={{ fontFamily: 'var(--font-mono)' }}>{d.code}</span>
                        <span style={{ fontFamily: 'var(--font-mono)' }}>{fmtDate(d.disclose_date)}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* ── 우측: 감시 종목 ── */}
          <div style={{ position: 'sticky', top: 80 }}>
            <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '16px' }}>
              <div style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--fg-1)', marginBottom: 12 }}>
                <i className="bi bi-eye me-2" style={{ color: 'var(--accent)' }} />감시 종목
                <span style={{ fontWeight: 400, color: 'var(--fg-3)', fontSize: '0.75rem', marginLeft: 4 }}>({watchlist.length}개)</span>
              </div>

              {/* 추가 폼 */}
              <StockSearch onAdd={handleAdd} loading={addLoading} />

              {/* 감시 종목 목록 */}
              {watchlist.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '20px 0', color: 'var(--fg-3)', fontSize: '0.78rem' }}>감시 종목 없음</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 5, maxHeight: 400, overflowY: 'auto' }}>
                  {watchlist.map(w => {
                    const cnt = disclosures.filter(d => d.code === w.code).length;
                    return (
                      <div key={w.code} style={{ display: 'flex', alignItems: 'center', gap: 8, background: filterCode === w.code ? 'var(--accent-bg, rgba(99,102,241,0.08))' : 'var(--bg-3)', border: `1px solid ${filterCode === w.code ? 'var(--accent)' : 'transparent'}`, borderRadius: 'var(--r-2)', padding: '7px 10px', cursor: 'pointer' }}
                        onClick={() => setFilterCode(c => c === w.code ? 'all' : w.code)}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontWeight: 600, fontSize: '0.82rem', color: 'var(--fg-1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{w.name}</div>
                          <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>{w.code}</div>
                        </div>
                        {cnt > 0 && <span style={{ fontSize: '0.65rem', fontWeight: 700, color: 'var(--accent)', background: 'rgba(99,102,241,0.12)', borderRadius: 10, padding: '1px 6px', flexShrink: 0 }}>{cnt}</span>}
                        <button onClick={e => { e.stopPropagation(); handleDelete(w.code); }} style={{ background: 'none', border: 'none', color: 'var(--fg-3)', cursor: 'pointer', padding: '0 2px', flexShrink: 0, fontSize: '0.85rem' }}>
                          <i className="bi bi-trash" />
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}

              <div style={{ marginTop: 14, padding: '9px 10px', background: 'var(--bg-3)', borderRadius: 'var(--r-2)', fontSize: '0.7rem', color: 'var(--fg-3)', lineHeight: 1.5 }}>
                <i className="bi bi-info-circle me-1" />
                공시는 평일 09:00~15:30 매 30분마다 자동 확인 후 카카오톡으로 알림 발송됩니다.
              </div>
            </div>
          </div>

        </div>
      )}
    </StockLayout>
  );
}
