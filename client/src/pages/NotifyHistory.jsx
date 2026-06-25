import React, { useState, useEffect } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

const CHANNEL_LABEL = { kakao: '카카오', telegram: '텔레그램', test: '테스트' };
const CHANNEL_COLOR = { kakao: '#f59e0b', telegram: '#60a5fa', test: '#94a3b8' };
const PER_PAGE = 50;

export default function NotifyHistory() {
  const [rows,    setRows]    = useState([]);
  const [total,   setTotal]   = useState(0);
  const [stats,   setStats]   = useState(null);
  const [loading, setLoading] = useState(true);
  const [more,    setMore]    = useState(false);
  const [error,   setError]   = useState('');

  const load = (offset) => {
    const first = offset === 0;
    first ? setLoading(true) : setMore(true);
    api.get(`/api/notify/history?limit=${PER_PAGE}&offset=${offset}`)
      .then(r => {
        const next = r.data?.rows || [];
        setRows(prev => first ? next : [...prev, ...next]);
        setTotal(r.data?.total ?? 0);
        setError('');
      })
      .catch(err => setError(err.response?.data?.error || '데이터를 불러올 수 없습니다.'))
      .finally(() => { setLoading(false); setMore(false); });
  };

  useEffect(() => {
    load(0);
    api.get('/api/notify/history/stats')
      .then(r => setStats(r.data?.stats || null))
      .catch(() => {});
  }, []);

  const num = (v) => Number(v || 0);
  const rate = stats && num(stats.total) > 0
    ? Math.round(num(stats.success) / num(stats.total) * 100) : null;

  const card = (label, value, sub, color, valueSize = '1.45rem') => (
    <div style={{ flex: 1, minWidth: 130, padding: '14px 16px', borderRadius: 'var(--r-3)',
      background: 'var(--bg-2)', border: '1px solid var(--line-1)', boxShadow: 'var(--card-shadow)' }}>
      <div style={{ fontSize: '0.74rem', color: 'var(--fg-3)' }}>{label}</div>
      <div style={{ fontSize: valueSize, fontWeight: 700, marginTop: 3, fontFamily: 'var(--font-mono)',
        color: color || 'var(--fg-1)' }}>{value}</div>
      <div style={{ fontSize: '0.72rem', color: 'var(--fg-3)', marginTop: 1, minHeight: '1em' }}>{sub || ''}</div>
    </div>
  );

  return (
    <StockLayout title="알림 발송 이력">
      {error && <div className="alert alert-danger" style={{ fontSize: '0.83rem', padding: '10px 14px', marginBottom: 12 }}>{error}</div>}
      {loading ? (
        <div style={{ textAlign: 'center', padding: '80px 0', color: 'var(--fg-3)' }}>
          <div className="spinner" style={{ margin: '0 auto 10px' }} />로딩 중...
        </div>
      ) : (
        <>
          {stats && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 16 }}>
              {card('전체 발송', num(stats.total).toLocaleString() + '건')}
              {card('성공', num(stats.success).toLocaleString() + '건',
                rate != null ? `성공률 ${rate}%` : '', 'var(--up)')}
              {card('실패', num(stats.failure).toLocaleString() + '건', '', 'var(--down)')}
              {card('마지막 발송', stats.last_sent || '-', '', null, '0.95rem')}
            </div>
          )}
          <div style={{ fontSize: '0.78rem', color: 'var(--fg-3)', marginBottom: 8 }}>
            총 {total.toLocaleString()}건
          </div>
          <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'hidden', marginBottom: 16 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
              <thead>
                <tr style={{ background: 'var(--bg-3)' }}>
                  {['시간', '채널', '내용', '상태'].map(h => (
                    <th key={h} style={{ padding: '9px 12px', fontWeight: 600, color: 'var(--fg-2)', textAlign: 'left' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map(n => (
                  <tr key={n.id} style={{ borderBottom: '1px solid var(--line-1)' }}>
                    <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)', color: 'var(--fg-3)', fontSize: '0.75rem', whiteSpace: 'nowrap' }}>
                      {n.sent_at?.slice(0, 16)}
                    </td>
                    <td style={{ padding: '8px 12px' }}>
                      <span style={{
                        fontSize: '0.7rem', fontWeight: 700, padding: '2px 7px', borderRadius: 3,
                        background: (CHANNEL_COLOR[n.channel] || '#94a3b8') + '22',
                        color: CHANNEL_COLOR[n.channel] || 'var(--fg-3)',
                      }}>
                        {CHANNEL_LABEL[n.channel] || n.channel}
                      </span>
                    </td>
                    <td title={n.message}
                      style={{ padding: '8px 12px', color: 'var(--fg-1)', maxWidth: 460, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.78rem' }}>
                      {n.message}
                    </td>
                    <td style={{ padding: '8px 12px' }}>
                      <span title={n.ok ? '' : (n.error_msg || '')}
                        style={{ fontSize: '0.7rem', fontWeight: 700, color: n.ok ? 'var(--up)' : 'var(--down)' }}>
                        {n.ok ? '성공' : '실패'}
                      </span>
                    </td>
                  </tr>
                ))}
                {!rows.length && (
                  <tr><td colSpan={4} style={{ textAlign: 'center', padding: '48px', color: 'var(--fg-3)' }}>발송 이력 없음</td></tr>
                )}
              </tbody>
            </table>
          </div>
          {rows.length < total && (
            <div style={{ textAlign: 'center' }}>
              <button className="btn btn-outline-secondary btn-sm" disabled={more} onClick={() => load(rows.length)}>
                {more ? '불러오는 중…' : `더 보기 (${rows.length}/${total})`}
              </button>
            </div>
          )}
        </>
      )}
    </StockLayout>
  );
}
