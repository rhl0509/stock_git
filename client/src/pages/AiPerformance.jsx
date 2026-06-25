import React, { useState, useEffect } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

const LABEL_META = {
  daily:  { kr: '일봉', color: '#3b82f6', icon: 'bi-calendar-day'   },
  short:  { kr: '단기', color: '#8b5cf6', icon: 'bi-calendar-week'  },
  swing:  { kr: '스윙', color: '#f59e0b', icon: 'bi-calendar-month' },
};

function aucGrade(auc) {
  if (auc >= 0.72) return { label: '우수', color: 'var(--up)'   };
  if (auc >= 0.65) return { label: '양호', color: '#f59e0b'     };
  return              { label: '미흡', color: 'var(--down)'  };
}

function fmt(dt) {
  if (!dt) return '-';
  return dt.slice(0, 16).replace('T', ' ');
}

function TrendArrow({ cur, prev }) {
  if (cur == null || prev == null) return null;
  const diff = cur - prev;
  if (Math.abs(diff) < 0.0005) return <span style={{ color: 'var(--fg-3)', fontSize: '0.7rem' }}>±0</span>;
  return diff > 0
    ? <span style={{ color: 'var(--up)',   fontSize: '0.7rem' }}>▲ +{(diff * 100).toFixed(2)}%p</span>
    : <span style={{ color: 'var(--down)', fontSize: '0.7rem' }}>▼ {(diff * 100).toFixed(2)}%p</span>;
}

export default function AiPerformance() {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState('');
  const [activeLabel, setActiveLabel] = useState('daily');

  const fetchData = () => {
    setLoading(true);
    setError('');
    api.get('/api/ai_performance')
      .then(r => setHistory(r.data?.history || []))
      .catch(e => setError(e.response?.data?.error || '성과 데이터 없음'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchData(); }, []);

  if (loading) return (
    <StockLayout title="ML 성과 이력">
      <div style={{ textAlign: 'center', padding: '80px 0' }}><div className="spinner" style={{ margin: '0 auto' }} /></div>
    </StockLayout>
  );

  if (error || !history.length) return (
    <StockLayout title="ML 성과 이력">
      <div style={{ textAlign: 'center', padding: '80px 0', color: 'var(--fg-3)' }}>
        <i className="bi bi-graph-up-arrow" style={{ fontSize: '2.5rem', display: 'block', marginBottom: 12, opacity: 0.3 }} />
        <p style={{ margin: 0, fontSize: '0.85rem' }}>{error || '이력 없음'}</p>
        <p style={{ margin: '8px 0 0', fontSize: '0.78rem' }}>XGBoost 모델을 학습하면 여기에 기록이 쌓입니다.</p>
      </div>
    </StockLayout>
  );

  const latest = history[0];
  const meta = LABEL_META[activeLabel] || {};

  // 선택된 라벨의 이력만 추출
  const labelHistory = history
    .map((h, i) => ({ ...h, idx: i, lb: h.labels?.[activeLabel] || {} }))
    .filter(h => h.lb.cv_auc != null);

  // 최고 AUC 기록
  const bestAuc = Math.max(...labelHistory.map(h => h.lb.cv_auc || 0));
  const bestIdx = labelHistory.findIndex(h => h.lb.cv_auc === bestAuc);

  return (
    <StockLayout title="ML 성과 이력">

      {/* 헤더 액션 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--fg-3)' }}>총 <strong style={{ color: 'var(--fg-1)' }}>{history.length}회</strong> 학습 기록 · 최근 100회 보관</span>
        </div>
        <button onClick={fetchData} disabled={loading} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 13px', background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-2)', cursor: 'pointer', fontSize: '0.8rem', color: 'var(--fg-2)' }}>
          <i className={`bi bi-arrow-clockwise${loading ? ' spin' : ''}`} />
          새로고침
        </button>
      </div>

      {/* 최신 학습 요약 */}
      <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '14px 18px', marginBottom: 16, display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center', fontSize: '0.82rem' }}>
        <span style={{ color: 'var(--fg-3)' }}><i className="bi bi-clock me-1" />최근 학습</span>
        <strong style={{ color: 'var(--fg-1)' }}>{fmt(latest.trained_at)}</strong>
        <span style={{ color: 'var(--fg-3)' }}>종목 <strong style={{ color: 'var(--fg-1)' }}>{latest.n_tickers?.toLocaleString('ko')}개</strong></span>
        <span style={{ color: 'var(--fg-3)' }}>샘플 <strong style={{ color: 'var(--fg-1)' }}>{latest.n_samples?.toLocaleString('ko')}행</strong></span>
        <span style={{ color: 'var(--fg-3)' }}>피처 <strong style={{ color: 'var(--fg-1)' }}>{latest.n_features}개</strong></span>
      </div>

      {/* 라벨 탭 */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
        {Object.entries(LABEL_META).map(([key, m]) => {
          const lb = latest.labels?.[key] || {};
          const g = lb.cv_auc != null ? aucGrade(lb.cv_auc) : null;
          const isActive = activeLabel === key;
          return (
            <button key={key} onClick={() => setActiveLabel(key)} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '9px 18px', borderRadius: 'var(--r-3)', border: isActive ? `2px solid ${m.color}` : '2px solid var(--line-1)', background: isActive ? `${m.color}18` : 'var(--bg-2)', cursor: 'pointer' }}>
              <i className={`bi ${m.icon}`} style={{ color: isActive ? m.color : 'var(--fg-3)' }} />
              <div style={{ textAlign: 'left' }}>
                <div style={{ fontSize: '0.85rem', fontWeight: isActive ? 700 : 500, color: isActive ? 'var(--fg-1)' : 'var(--fg-2)' }}>{m.kr} 모델</div>
                {g && <div style={{ fontSize: '0.68rem', color: g.color, fontFamily: 'var(--font-mono)' }}>최신 AUC {lb.cv_auc.toFixed(4)} · {g.label}</div>}
              </div>
            </button>
          );
        })}
      </div>

      {/* AUC 시각화 바 (히스토리) */}
      {labelHistory.length > 0 && (
        <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '18px 20px', marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
            <i className="bi bi-graph-up" style={{ color: meta.color }} />
            <span style={{ fontWeight: 700, fontSize: '0.88rem', color: 'var(--fg-1)' }}>AUC 변화 추이 — {meta.kr} 모델</span>
            <span style={{ fontSize: '0.72rem', color: 'var(--fg-3)', marginLeft: 4 }}>최신순 · 0.5 = 랜덤, 0.7+ = 양호</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            {labelHistory.slice(0, 30).map((h, i) => {
              const auc = h.lb.cv_auc;
              const g = aucGrade(auc);
              const pct = Math.max(0, Math.min(100, ((auc - 0.5) / 0.3) * 100));
              const isBest = i === bestIdx;
              return (
                <div key={h.idx} style={{ display: 'grid', gridTemplateColumns: '120px 1fr 52px 40px', gap: 8, alignItems: 'center' }}>
                  <span style={{ fontSize: '0.72rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>{fmt(h.trained_at)}</span>
                  <div style={{ height: 10, background: 'var(--line-1)', borderRadius: 5, overflow: 'hidden', position: 'relative' }}>
                    <div style={{ width: `${pct}%`, height: '100%', background: g.color, borderRadius: 5, opacity: i === 0 ? 1 : 0.6 }} />
                  </div>
                  <span style={{ fontSize: '0.78rem', fontFamily: 'var(--font-mono)', color: g.color, fontWeight: i === 0 ? 700 : 400 }}>{auc.toFixed(4)}</span>
                  {isBest
                    ? <span style={{ fontSize: '0.62rem', color: '#f59e0b', fontWeight: 700, textAlign: 'center' }}>최고</span>
                    : i === 0
                    ? <span style={{ fontSize: '0.62rem', color: 'var(--accent)', fontWeight: 700, textAlign: 'center' }}>최신</span>
                    : null}
                </div>
              );
            })}
            {labelHistory.length > 30 && (
              <div style={{ fontSize: '0.72rem', color: 'var(--fg-3)', textAlign: 'center', paddingTop: 4 }}>+ {labelHistory.length - 30}건 더...</div>
            )}
          </div>
        </div>
      )}

      {/* 전체 이력 테이블 */}
      <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'hidden' }}>
        <div style={{ padding: '13px 18px', borderBottom: '1px solid var(--line-1)', fontWeight: 700, fontSize: '0.87rem', color: 'var(--fg-1)' }}>
          전체 학습 이력
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
            <thead>
              <tr style={{ background: 'var(--bg-3)' }}>
                {['#', '학습 일시', '종목', '샘플',
                  '일봉 AUC', '일봉 정확도',
                  '단기 AUC', '단기 정확도',
                  '스윙 AUC', '스윙 정확도',
                ].map(h => (
                  <th key={h} style={{ padding: '8px 12px', fontWeight: 600, color: 'var(--fg-2)', textAlign: h === '#' ? 'center' : 'left', whiteSpace: 'nowrap', fontSize: '0.75rem' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {history.map((item, i) => {
                const prev = history[i + 1];
                return (
                  <tr key={i} style={{ borderBottom: '1px solid var(--line-1)', background: i === 0 ? 'var(--accent-bg, var(--bg-2))' : 'transparent' }}>
                    <td style={{ padding: '8px 12px', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)', textAlign: 'center', fontSize: '0.72rem' }}>{history.length - i}</td>
                    <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap', color: i === 0 ? 'var(--fg-1)' : 'var(--fg-2)', fontWeight: i === 0 ? 700 : 400 }}>{fmt(item.trained_at)}</td>
                    <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)' }}>{item.n_tickers?.toLocaleString('ko')}</td>
                    <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)' }}>{item.n_samples?.toLocaleString('ko')}</td>
                    {['daily', 'short', 'swing'].map(lk => {
                      const lb  = item.labels?.[lk] || {};
                      const plb = prev?.labels?.[lk] || {};
                      const g   = lb.cv_auc != null ? aucGrade(lb.cv_auc) : null;
                      return (
                        <React.Fragment key={lk}>
                          <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)' }}>
                            {lb.cv_auc != null ? (
                              <span style={{ color: g.color, fontWeight: 600 }}>
                                {lb.cv_auc.toFixed(4)}
                                <span style={{ marginLeft: 4 }}><TrendArrow cur={lb.cv_auc} prev={plb.cv_auc} /></span>
                              </span>
                            ) : '-'}
                          </td>
                          <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)', color: 'var(--fg-2)' }}>
                            {lb.cv_acc != null ? `${(lb.cv_acc * 100).toFixed(2)}%` : '-'}
                          </td>
                        </React.Fragment>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

    </StockLayout>
  );
}
