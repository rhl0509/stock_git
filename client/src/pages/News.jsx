import React, { useState, useEffect, useRef } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

const strip = html => {
  if (!html) return '';
  return html
    .replace(/<[^>]*>?/gm, '')
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&#039;/g, "'").replace(/&nbsp;/g, ' ')
    .trim();
};

const safeUrl = url => {
  if (!url) return '#';
  try { const { protocol } = new URL(url); return ['http:', 'https:'].includes(protocol) ? url : '#'; }
  catch { return '#'; }
};

const fmtDate = str => {
  if (!str) return '';
  const d = new Date(str);
  if (isNaN(d)) return str?.slice(0, 10) || '';
  const now = new Date();
  const diff = Math.floor((now - d) / 60000);
  if (diff < 60)  return `${diff}분 전`;
  if (diff < 1440) return `${Math.floor(diff / 60)}시간 전`;
  return d.toLocaleDateString('ko-KR', { month: 'long', day: 'numeric' });
};

// ── 뉴스 카드 ─────────────────────────────────────────────────────────────────
function NewsCard({ title, description, link, pubDate, pub_date, keyword, url }) {
  const href = safeUrl(link || url);
  const date = pubDate || pub_date || '';
  return (
    <a href={href} target="_blank" rel="noreferrer"
      style={{ textDecoration: 'none', display: 'block',
               background: 'var(--bg-2)', border: '1px solid var(--line-1)',
               borderLeft: keyword ? '3px solid var(--accent)' : '1px solid var(--line-1)',
               borderRadius: 'var(--r-3)', padding: '14px 16px',
               transition: 'box-shadow 0.15s, border-color 0.15s' }}
      onMouseEnter={e => e.currentTarget.style.boxShadow = 'var(--card-shadow)'}
      onMouseLeave={e => e.currentTarget.style.boxShadow = 'none'}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, marginBottom: 6 }}>
        <div style={{ fontWeight: 700, fontSize: '0.88rem', color: 'var(--fg-1)', lineHeight: 1.45, flex: 1 }}>
          {strip(title)}
        </div>
        {keyword && (
          <span style={{ flexShrink: 0, fontSize: '0.65rem', fontWeight: 700, padding: '2px 7px',
                         borderRadius: 12, background: 'var(--lime-soft)',
                         border: '1px solid var(--lime-border)', color: 'var(--accent)',
                         fontFamily: 'var(--font-mono)' }}>
            {keyword}
          </span>
        )}
      </div>
      {description && (
        <div style={{ fontSize: '0.78rem', color: 'var(--fg-3)', lineHeight: 1.55, marginBottom: 8,
                      display: '-webkit-box', WebkitLineClamp: 2,
                      WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
          {strip(description)}
        </div>
      )}
      <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>
        {fmtDate(date)}
      </div>
    </a>
  );
}

// ── 검색 탭 ───────────────────────────────────────────────────────────────────
function SearchTab() {
  const [query,   setQuery]   = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const search = async e => {
    e?.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    try {
      const r = await api.get('/api/news/search', { params: { q: query } });
      setResults(r.data?.items || r.data || []);
    } catch { setResults([]); }
    setLoading(false);
  };

  return (
    <div>
      <form onSubmit={search} style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        <input ref={inputRef} className="form-control" value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="종목명, 키워드로 검색 (예: 삼성전자, 금리, 코스피)"
          style={{ flex: 1, fontSize: '0.9rem' }} />
        <button className="btn btn-primary" type="submit" disabled={loading}
          style={{ whiteSpace: 'nowrap', padding: '8px 20px' }}>
          {loading
            ? <><span className="spinner-border spinner-border-sm me-1" role="status" />검색 중</>
            : <><i className="bi bi-search me-1" />검색</>}
        </button>
      </form>

      {results.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--fg-3)', marginBottom: 4 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--fg-2)' }}>{results.length}</span>개 결과
          </div>
          {results.map((item, i) => <NewsCard key={i} {...item} />)}
        </div>
      )}

      {!loading && !results.length && query && (
        <div style={{ textAlign: 'center', padding: '80px 0', color: 'var(--fg-3)' }}>
          <i className="bi bi-search" style={{ fontSize: '2.2rem', display: 'block', marginBottom: 12, opacity: 0.2 }} />
          <p style={{ margin: 0, fontSize: '0.85rem' }}>검색 결과가 없습니다.</p>
        </div>
      )}

      {!query && (
        <div style={{ textAlign: 'center', padding: '80px 0', color: 'var(--fg-3)' }}>
          <i className="bi bi-newspaper" style={{ fontSize: '2.2rem', display: 'block', marginBottom: 12, opacity: 0.2 }} />
          <p style={{ margin: 0, fontSize: '0.85rem' }}>종목명, 키워드로 뉴스를 검색하세요.</p>
        </div>
      )}
    </div>
  );
}

// ── 개장전 탭 ─────────────────────────────────────────────────────────────────
function MorningTab() {
  const [news,     setNews]     = useState([]);
  const [keywords, setKeywords] = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [crawling, setCrawling] = useState(false);
  const [newKw,    setNewKw]    = useState('');
  const [error,    setError]    = useState('');
  const [filter,   setFilter]   = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get('/api/morning_news');
      setNews(r.data?.items || []);
      setKeywords(r.data?.keywords || []);
    } catch (err) {
      setError(err.response?.data?.error || '데이터를 불러올 수 없습니다.');
    }
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const crawl = async () => {
    setCrawling(true); setError('');
    try {
      const r = await api.post('/api/morning_news/run');
      await load();
      if (r.data?.saved === 0) setError('새 뉴스가 없습니다. (기존 수집 항목과 동일)');
    } catch (err) {
      setError(err.response?.data?.error || '뉴스 수집 실패');
    }
    setCrawling(false);
  };

  const addKeyword = async () => {
    const trimmed = newKw?.trim() || '';
    if (!trimmed || trimmed.length > 50 || /[/\\?#]/.test(trimmed)) {
      setError('키워드는 50자 이하, 특수문자 없이 입력하세요.'); return;
    }
    try { await api.post('/api/morning_news/keywords', { keyword: trimmed }); setNewKw(''); load(); }
    catch (err) { setError(err.response?.data?.error || '추가 실패'); }
  };

  const delKeyword = async kw => {
    if (!kw || kw.length > 50 || /[/\\?#]/.test(kw)) return;
    try { await api.delete(`/api/morning_news/keywords/${encodeURIComponent(kw)}`); load(); }
    catch (err) { setError(err.response?.data?.error || '삭제 실패'); }
  };

  const filtered = filter ? news.filter(n => n.keyword === filter) : news;

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 260px', gap: 20, alignItems: 'start' }}>
      {/* 뉴스 피드 */}
      <div>
        {error && (
          <div style={{ marginBottom: 12, padding: '8px 12px', fontSize: '0.8rem', color: '#ef4444',
                        background: 'rgba(239,68,68,0.07)', border: '1px solid rgba(239,68,68,0.2)',
                        borderRadius: 'var(--r-2)' }}>
            <i className="bi bi-exclamation-circle me-1" />{error}
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
          <button className="btn btn-primary btn-sm" onClick={crawl} disabled={crawling}
            style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <i className={`bi bi-arrow-clockwise${crawling ? ' spin' : ''}`} />
            {crawling ? '수집 중...' : '뉴스 수집'}
          </button>
          <span style={{ fontSize: '0.75rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>
            {news.length}개 기사
          </span>
          {filter && (
            <button onClick={() => setFilter('')}
              style={{ marginLeft: 'auto', fontSize: '0.72rem', background: 'var(--lime-soft)',
                       border: '1px solid var(--lime-border)', borderRadius: 12, padding: '2px 10px',
                       color: 'var(--accent)', cursor: 'pointer', fontWeight: 700, display: 'flex', gap: 4 }}>
              {filter} <span style={{ opacity: 0.6 }}>×</span>
            </button>
          )}
        </div>

        {loading ? (
          <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--fg-3)' }}>
            <div className="spinner" style={{ margin: '0 auto 10px' }} />로딩 중...
          </div>
        ) : filtered.length ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {filtered.map(n => <NewsCard key={n.id} {...n} />)}
          </div>
        ) : (
          <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--fg-3)' }}>
            <i className="bi bi-sun" style={{ fontSize: '2.2rem', display: 'block', marginBottom: 12, opacity: 0.2 }} />
            <p style={{ margin: 0, fontSize: '0.85rem' }}>
              {news.length ? '해당 키워드 기사 없음' : '수집 버튼을 눌러 뉴스를 가져오세요.'}
            </p>
          </div>
        )}
      </div>

      {/* 키워드 사이드패널 */}
      <div style={{ position: 'sticky', top: 80 }}>
        <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)',
                      borderRadius: 'var(--r-3)', padding: '16px 18px' }}>
          <div style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--fg-1)', marginBottom: 14 }}>
            <i className="bi bi-tags me-2" style={{ color: 'var(--accent)' }} />수집 키워드
          </div>
          <div style={{ display: 'flex', gap: 6, marginBottom: 14 }}>
            <input className="form-control" value={newKw} onChange={e => setNewKw(e.target.value)}
              placeholder="키워드 추가" style={{ fontSize: '0.82rem' }}
              onKeyDown={e => e.key === 'Enter' && addKeyword()} />
            <button className="btn btn-primary btn-sm" onClick={addKeyword}
              style={{ flexShrink: 0, padding: '0 12px' }}>+</button>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {keywords.map(k => (
              <button key={k} onClick={() => setFilter(f => f === k ? '' : k)}
                style={{ display: 'flex', alignItems: 'center', gap: 4,
                         background: filter === k ? 'var(--accent)' : 'var(--lime-soft)',
                         border: `1px solid ${filter === k ? 'var(--accent)' : 'var(--lime-border)'}`,
                         borderRadius: 20, padding: '4px 10px', fontSize: '0.75rem',
                         color: filter === k ? '#fff' : 'var(--accent)',
                         fontWeight: 700, cursor: 'pointer' }}>
                {k}
                <span onClick={e => { e.stopPropagation(); delKeyword(k); }}
                  style={{ opacity: 0.6, fontSize: '0.7rem', lineHeight: 1 }}>×</span>
              </button>
            ))}
            {!keywords.length && (
              <span style={{ fontSize: '0.78rem', color: 'var(--fg-3)' }}>키워드 없음</span>
            )}
          </div>

          {/* 키워드별 기사 수 */}
          {keywords.length > 0 && news.length > 0 && (
            <div style={{ marginTop: 16, borderTop: '1px solid var(--line-1)', paddingTop: 14 }}>
              <div style={{ fontSize: '0.72rem', color: 'var(--fg-3)', marginBottom: 8, fontWeight: 600 }}>키워드별 기사 수</div>
              {keywords.map(k => {
                const cnt = news.filter(n => n.keyword === k).length;
                return (
                  <div key={k} style={{ display: 'flex', justifyContent: 'space-between',
                                        fontSize: '0.75rem', color: 'var(--fg-2)', padding: '3px 0' }}>
                    <span>{k}</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--accent)' }}>{cnt}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── 메인 ──────────────────────────────────────────────────────────────────────
export default function News({ initialTab }) {
  const [tab, setTab] = useState(initialTab || 'search');

  const TAB_BTN = (key, icon, label) => (
    <button onClick={() => setTab(key)}
      style={{ display: 'flex', alignItems: 'center', gap: 6,
               padding: '7px 16px', borderRadius: 'var(--r-2)', border: 'none', cursor: 'pointer',
               fontSize: '0.83rem', fontWeight: tab === key ? 700 : 500,
               background: tab === key ? 'var(--accent)' : 'var(--bg-3)',
               color: tab === key ? '#fff' : 'var(--fg-2)',
               transition: 'background 0.15s, color 0.15s' }}>
      <i className={`bi ${icon}`} />{label}
    </button>
  );

  return (
    <StockLayout title="뉴스">
      <div style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
        {TAB_BTN('search',  'bi-search', '뉴스 검색')}
        {TAB_BTN('morning', 'bi-sun',    '개장전 뉴스')}
      </div>

      {tab === 'search'  && <SearchTab />}
      {tab === 'morning' && <MorningTab />}
    </StockLayout>
  );
}
