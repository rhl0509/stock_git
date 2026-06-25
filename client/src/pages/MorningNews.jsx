import React, { useState, useEffect } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

export default function MorningNews() {
  const [news,     setNews]     = useState([]);
  const [keywords, setKeywords] = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [crawling, setCrawling] = useState(false);
  const [newKw,    setNewKw]    = useState('');
  const [error,    setError]    = useState('');

  const safeUrl = url => {
    if (!url) return '#';
    try {
      const { protocol } = new URL(url);
      return ['http:', 'https:'].includes(protocol) ? url : '#';
    } catch { return '#'; }
  };

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
    setCrawling(true);
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
      setError('키워드는 50자 이하, 특수문자(/,\\,?,#) 없이 입력하세요.');
      return;
    }
    try {
      await api.post('/api/morning_news/keywords', { keyword: trimmed });
      setNewKw(''); load();
    } catch (err) { setError(err.response?.data?.error || '데이터를 불러올 수 없습니다.'); }
  };

  const delKeyword = async kw => {
    if (!kw || typeof kw !== 'string' || kw.length > 50 || /[/\\?#]/.test(kw)) {
      return; // silently skip invalid keywords
    }
    try {
      await api.delete(`/api/morning_news/keywords/${encodeURIComponent(kw)}`);
      load();
    } catch (err) { setError(err.response?.data?.error || '데이터를 불러올 수 없습니다.'); }
  };

  return (
    <StockLayout title="개장전 뉴스">
      {error && <div className="alert alert-danger" style={{fontSize:'0.83rem',padding:'10px 14px',marginBottom:12}}>{error}</div>}
      <div style={{ display:'grid', gap:16, gridTemplateColumns:'1fr 280px' }}>
        <div>
          <div style={{ display:'flex', gap:10, marginBottom:16, alignItems:'center', flexWrap:'wrap' }}>
            <button className="btn btn-primary btn-sm" onClick={crawl} disabled={crawling}>
              {crawling ? '수집 중...' : <><i className="bi bi-arrow-clockwise me-1"/>뉴스 수집</>}
            </button>
            <span style={{ fontSize:'0.78rem', color:'var(--fg-3)' }}>{news.length}개 기사</span>
          </div>

          {loading ? (
            <div style={{ textAlign:'center', padding:'60px 0', color:'var(--fg-3)' }}><div className="spinner" style={{ margin:'0 auto 10px' }}/>로딩 중...</div>
          ) : (
            <div style={{ display:'grid', gap:8 }}>
              {news.map(n => (
                <a key={n.id} href={safeUrl(n.link || n.url)} target="_blank" rel="noreferrer"
                  style={{ textDecoration:'none', background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'13px 15px', display:'block' }}>
                  <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', gap:8, marginBottom:6 }}>
                    <div style={{ fontWeight:700, fontSize:'0.86rem', color:'var(--fg-1)', lineHeight:1.4 }}>{n.title}</div>
                    <span style={{ fontSize:'0.68rem', background:'var(--bg-3)', border:'1px solid var(--line-1)', borderRadius:3, padding:'2px 6px', color:'var(--accent)', fontFamily:'var(--font-mono)', flexShrink:0 }}>{n.keyword}</span>
                  </div>
                  <div style={{ fontSize:'0.68rem', color:'var(--fg-3)', marginTop:4, fontFamily:'var(--font-mono)' }}>
                    {n.pub_date?.slice(0,10)}
                  </div>
                </a>
              ))}
              {!news.length && <div style={{ textAlign:'center', padding:'60px 0', color:'var(--fg-3)' }}>뉴스가 없습니다. 수집 버튼을 눌러 뉴스를 가져오세요.</div>}
            </div>
          )}
        </div>

        {/* 키워드 관리 */}
        <div>
          <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'16px', position:'sticky', top:80 }}>
            <div style={{ fontWeight:700, fontSize:'0.85rem', color:'var(--fg-1)', marginBottom:12 }}>수집 키워드</div>
            <div style={{ display:'flex', gap:6, marginBottom:12 }}>
              <input className="form-control" value={newKw} onChange={e => setNewKw(e.target.value)}
                placeholder="키워드 추가" style={{ fontSize:'0.82rem' }} onKeyDown={e => e.key==='Enter'&&addKeyword()} />
              <button className="btn btn-primary btn-sm" onClick={addKeyword}>+</button>
            </div>
            <div style={{ display:'flex', flexWrap:'wrap', gap:6 }}>
              {keywords.map(k => (
                <span key={k} style={{ display:'flex', alignItems:'center', gap:4, background:'var(--lime-soft)', border:'1px solid var(--lime-border)', borderRadius:20, padding:'3px 10px', fontSize:'0.76rem', color:'var(--accent)', fontWeight:600 }}>
                  {k}
                  <button onClick={() => delKeyword(k)} style={{ background:'none', border:'none', color:'var(--fg-3)', cursor:'pointer', padding:0, lineHeight:1, fontSize:'0.7rem' }}>×</button>
                </span>
              ))}
              {!keywords.length && <span style={{ fontSize:'0.78rem', color:'var(--fg-3)' }}>키워드 없음</span>}
            </div>
          </div>
        </div>
      </div>
    </StockLayout>
  );
}
