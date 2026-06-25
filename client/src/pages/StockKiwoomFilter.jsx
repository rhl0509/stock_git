import React, { useState, useEffect } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

/* ── 등락률 색상 ──────────────────────────────────────────── */
const rateColor = r => r > 0 ? 'var(--up)' : r < 0 ? 'var(--down)' : 'var(--fg-3)';
const rateLabel = r => r == null ? '-' : `${r > 0 ? '▲' : r < 0 ? '▼' : ''}${Math.abs(r).toFixed(2)}%`;

export default function StockKiwoomFilter() {
  const [conditions,   setConditions]   = useState([]);
  const [selected,     setSelected]     = useState(null);
  const [results,      setResults]      = useState([]);
  const [loading,      setLoading]      = useState(false);
  const [listLoading,  setListLoading]  = useState(true);
  const [error,        setError]        = useState('');
  const [condError,    setCondError]    = useState('');
  const [codeCount,    setCodeCount]    = useState(null);

  useEffect(() => {
    api.get('/api/kiwoom/conditions')
      .then(r => setConditions(r.data?.conditions || []))
      .catch(e => setCondError(e.response?.data?.error || '조건식 목록 조회 실패'))
      .finally(() => setListLoading(false));
  }, []);

  const run = async cond => {
    setSelected(cond); setLoading(true); setResults([]); setError(''); setCodeCount(null);
    try {
      const r = await api.post('/api/kiwoom/condition/run', { condition_name: cond.name });
      setResults(r.data?.results || []);
      setCodeCount(r.data?.code_count ?? null);
    } catch (e) {
      setError(e.response?.data?.error || '조건검색 실패');
    }
    setLoading(false);
  };

  return (
    <StockLayout title="키움 조건검색">
      <div style={{ display: 'grid', gap: 16, gridTemplateColumns: '240px 1fr' }}>

        {/* 조건식 목록 */}
        <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'hidden', height: 'fit-content' }}>
          <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--line-1)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontWeight: 700, fontSize: '0.83rem', color: 'var(--fg-1)' }}>저장된 조건식</span>
            {conditions.length > 0 && <span style={{ fontSize: '0.68rem', color: 'var(--fg-3)', background: 'var(--bg-3)', borderRadius: 10, padding: '1px 7px' }}>{conditions.length}개</span>}
          </div>

          {condError && (
            <div style={{ padding: '12px 14px', fontSize: '0.75rem', color: '#ef4444', background: 'rgba(239,68,68,0.05)' }}>
              <i className="bi bi-exclamation-triangle me-1" />{condError}
            </div>
          )}

          {listLoading ? (
            <div style={{ padding: '30px 14px', textAlign: 'center', color: 'var(--fg-3)' }}>
              <div className="spinner" style={{ margin: '0 auto 8px' }} />
              <div style={{ fontSize: '0.78rem' }}>로딩 중...</div>
            </div>
          ) : (
            <div style={{ maxHeight: 520, overflowY: 'auto' }}>
              {conditions.map(c => {
                const isActive = selected?.index === c.index;
                return (
                  <button key={c.index} onClick={() => run(c)}
                    style={{ width: '100%', padding: '10px 14px', textAlign: 'left',
                      background: isActive ? 'var(--lime-soft)' : 'transparent',
                      border: 'none', borderBottom: '1px solid var(--line-1)', cursor: 'pointer', transition: 'background 0.1s' }}
                    onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = 'var(--bg-3)'; }}
                    onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}>
                    <span style={{ display: 'block', fontWeight: 700, fontSize: '0.82rem', color: isActive ? 'var(--accent)' : 'var(--fg-1)' }}>{c.name}</span>
                    <span style={{ fontSize: '0.68rem', fontFamily: 'var(--font-mono)', color: 'var(--fg-3)' }}>#{c.index}</span>
                  </button>
                );
              })}
              {!conditions.length && !condError && (
                <div style={{ padding: '30px 14px', textAlign: 'center', color: 'var(--fg-3)', fontSize: '0.8rem' }}>
                  <i className="bi bi-sliders" style={{ display: 'block', fontSize: '1.5rem', marginBottom: 8, opacity: 0.3 }} />
                  조건식 없음<br />
                  <span style={{ fontSize: '0.72rem', marginTop: 4, display: 'block' }}>키움 HTS에서 조건식을 저장하세요</span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* 결과 영역 */}
        <div>
          {loading && (
            <div style={{ textAlign: 'center', padding: '80px 0', color: 'var(--fg-3)' }}>
              <div className="spinner" style={{ margin: '0 auto 12px' }} />
              <div style={{ fontSize: '0.85rem' }}>「{selected?.name}」 조건검색 실행 중...</div>
              <div style={{ fontSize: '0.72rem', marginTop: 6, opacity: 0.7 }}>종목 수에 따라 10~30초 소요됩니다</div>
            </div>
          )}

          {!loading && error && (
            <div style={{ padding: '12px 16px', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 'var(--r-2)', fontSize: '0.82rem', color: '#ef4444', marginBottom: 16 }}>
              <i className="bi bi-exclamation-triangle me-1" />{error}
            </div>
          )}

          {!loading && selected && (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
                <div style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--fg-1)' }}>「{selected.name}」</div>
                <div style={{ fontSize: '0.78rem', color: 'var(--fg-3)' }}>
                  {codeCount != null && <span>조건 통과 {codeCount}개 중 </span>}
                  <span style={{ color: 'var(--accent)', fontWeight: 700 }}>{results.length}개</span> 조회 완료
                </div>
              </div>

              {results.length > 0 ? (
                <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'hidden' }}>
                  <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                      <thead>
                        <tr style={{ background: 'var(--bg-3)', borderBottom: '1px solid var(--line-1)' }}>
                          {['종목', '코드', '현재가', '등락률', '시가', '고가', '저가', '거래량'].map(h => (
                            <th key={h} style={{ padding: '9px 12px', fontWeight: 600, color: 'var(--fg-2)', textAlign: h === '종목' ? 'left' : 'right', whiteSpace: 'nowrap' }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {results.map((s, i) => (
                          <tr key={s.code || i} style={{ borderBottom: '1px solid var(--line-1)', background: i % 2 === 0 ? 'transparent' : 'var(--bg-1)' }}>
                            <td style={{ padding: '9px 12px', fontWeight: 700, color: 'var(--fg-1)' }}>{s.name || s.code}</td>
                            <td style={{ padding: '9px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)', color: 'var(--fg-3)', fontSize: '0.75rem' }}>{s.code}</td>
                            <td style={{ padding: '9px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>
                              {s.price?.toLocaleString('ko') ?? '-'}
                            </td>
                            <td style={{ padding: '9px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 600, color: rateColor(s.rate) }}>
                              {rateLabel(s.rate)}
                            </td>
                            <td style={{ padding: '9px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)', color: 'var(--fg-2)' }}>{s.open?.toLocaleString('ko') ?? '-'}</td>
                            <td style={{ padding: '9px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)', color: 'var(--up)' }}>{s.high?.toLocaleString('ko') ?? '-'}</td>
                            <td style={{ padding: '9px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)', color: 'var(--down)' }}>{s.low?.toLocaleString('ko') ?? '-'}</td>
                            <td style={{ padding: '9px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)', color: 'var(--fg-2)' }}>{s.volume?.toLocaleString('ko') ?? '-'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                !error && (
                  <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--fg-3)' }}>
                    <i className="bi bi-inbox" style={{ fontSize: '2rem', display: 'block', marginBottom: 8, opacity: 0.3 }} />
                    조건에 해당하는 종목이 없습니다.
                  </div>
                )
              )}
            </>
          )}

          {!loading && !selected && !error && (
            <div style={{ textAlign: 'center', padding: '80px 0', color: 'var(--fg-3)' }}>
              <i className="bi bi-sliders" style={{ fontSize: '2.5rem', display: 'block', marginBottom: 12, opacity: 0.25 }} />
              <p style={{ margin: 0, fontSize: '0.85rem' }}>좌측에서 조건식을 선택하면 바로 검색됩니다.</p>
              <p style={{ fontSize: '0.74rem', marginTop: 6, opacity: 0.7 }}>키움 API 로그인이 필요합니다</p>
            </div>
          )}
        </div>
      </div>
    </StockLayout>
  );
}
