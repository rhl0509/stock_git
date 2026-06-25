import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

const TYPE_META = {
  daily:   { label: '일간', color: '#3b82f6', bg: 'rgba(59,130,246,0.1)',   border: 'rgba(59,130,246,0.3)',  icon: 'bi-calendar-day',   desc: '평일 09:00 자동 생성' },
  weekly:  { label: '주간', color: '#10b981', bg: 'rgba(16,185,129,0.1)',   border: 'rgba(16,185,129,0.3)',  icon: 'bi-calendar-week',  desc: '금요일 18:30 자동 생성' },
  monthly: { label: '월간', color: '#8b5cf6', bg: 'rgba(139,92,246,0.1)',   border: 'rgba(139,92,246,0.3)',  icon: 'bi-calendar-month', desc: '매월 말일 20:30 자동 생성' },
};

function TypeBadge({ type, size = 'sm' }) {
  const m = TYPE_META[type] || {};
  return (
    <span style={{
      fontSize: size === 'sm' ? '0.68rem' : '0.75rem', fontWeight: 700,
      padding: size === 'sm' ? '2px 8px' : '3px 10px',
      borderRadius: 20, background: m.bg, color: m.color,
      border: `1px solid ${m.border}`, whiteSpace: 'nowrap',
      fontFamily: 'var(--font-mono)',
    }}>{m.label}</span>
  );
}

function ReportCard({ report, onClick }) {
  const m = TYPE_META[report.report_type] || {};
  const date = report.report_date?.slice(0, 10) || '-';
  return (
    <div onClick={onClick} style={{
      background: 'var(--bg-2)', border: '1px solid var(--line-1)',
      borderRadius: 'var(--r-3)', padding: '16px 20px', cursor: 'pointer',
      transition: 'transform 0.12s, box-shadow 0.12s',
      borderLeft: `3px solid ${m.color}`,
    }}
    onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 4px 16px rgba(0,0,0,0.1)'; }}
    onMouseLeave={e => { e.currentTarget.style.transform = ''; e.currentTarget.style.boxShadow = ''; }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <TypeBadge type={report.report_type} />
        <span style={{ fontSize: '0.78rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>{date}</span>
        <i className="bi bi-chevron-right" style={{ marginLeft: 'auto', color: 'var(--fg-3)', fontSize: '0.75rem' }} />
      </div>
      <div style={{ fontWeight: 600, fontSize: '0.9rem', color: 'var(--fg-1)', marginBottom: report.summary ? 8 : 0 }}>
        {report.title}
      </div>
      {report.summary && (
        <div style={{
          fontSize: '0.78rem', color: 'var(--fg-3)', lineHeight: 1.55,
          display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
          overflow: 'hidden', whiteSpace: 'pre-line',
        }}>{report.summary}</div>
      )}
    </div>
  );
}

export default function Reports() {
  const navigate = useNavigate();
  const [reports, setReports]     = useState([]);
  const [schedules, setSchedules] = useState([]);
  const [loading, setLoading]     = useState(true);
  const [genStatus, setGenStatus] = useState('');
  const [genLoading, setGenLoading] = useState('');
  const [activeTab, setActiveTab] = useState('all');

  const fetchReports = useCallback(() => {
    setLoading(true);
    api.get('/reports/json?limit=50')
      .then(r => setReports(r.data?.reports || []))
      .catch(() => setReports([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchReports();
    api.get('/reports/schedule')
      .then(r => setSchedules(r.data?.schedules || []))
      .catch(() => {});
  }, [fetchReports]);

  const generate = async (type) => {
    setGenLoading(type);
    setGenStatus(`${TYPE_META[type].label} 보고서 생성 요청 중...`);
    try {
      const r = await api.post(`/reports/generate?report_type=${type}`);
      setGenStatus(`✅ ${r.data?.message || '생성 시작됨'} — 수 분 후 새로고침하세요.`);
      setTimeout(fetchReports, 8000);
    } catch (e) {
      setGenStatus(`❌ 생성 실패: ${e.response?.data?.detail || e.message}`);
    }
    setGenLoading('');
  };

  const filtered = activeTab === 'all'
    ? reports
    : reports.filter(r => r.report_type === activeTab);

  // 스케줄 다음 실행 시간 포맷
  const fmtSchedule = (id, next) => {
    const m = { report_daily: '일간', report_weekly: '주간', report_monthly: '월간' };
    const dt = next ? next.replace('T', ' ').slice(0, 16) : '-';
    return `${m[id] || id}: ${dt}`;
  };

  return (
    <StockLayout title="시장 보고서">

      {/* 스케줄 상태 */}
      {schedules.length > 0 && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
          <span style={{ fontSize: '0.72rem', color: 'var(--fg-3)', alignSelf: 'center' }}>
            <i className="bi bi-clock me-1" />다음 자동 생성
          </span>
          {schedules.map(s => (
            <span key={s.id} style={{ fontSize: '0.72rem', background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-2)', padding: '3px 10px', color: 'var(--fg-2)', fontFamily: 'var(--font-mono)' }}>
              {fmtSchedule(s.id, s.next_run)}
            </span>
          ))}
        </div>
      )}

      {/* 수동 생성 버튼 */}
      <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '14px 18px', marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--fg-2)', marginRight: 4 }}>즉시 생성</span>
          {Object.entries(TYPE_META).map(([type, m]) => (
            <button key={type} onClick={() => generate(type)} disabled={!!genLoading}
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 'var(--r-2)', border: `1px solid ${m.border}`, background: m.bg, color: m.color, cursor: genLoading ? 'not-allowed' : 'pointer', fontSize: '0.8rem', fontWeight: 700, opacity: genLoading && genLoading !== type ? 0.5 : 1 }}>
              <i className={`bi ${genLoading === type ? 'bi-arrow-clockwise spin' : m.icon}`} />
              {genLoading === type ? '생성 중...' : `${m.label} 생성`}
            </button>
          ))}
          <button onClick={fetchReports} style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '7px 12px', borderRadius: 'var(--r-2)', border: '1px solid var(--line-1)', background: 'transparent', color: 'var(--fg-3)', cursor: 'pointer', fontSize: '0.78rem' }}>
            <i className="bi bi-arrow-clockwise" />새로고침
          </button>
        </div>
        {genStatus && (
          <div style={{ marginTop: 10, fontSize: '0.78rem', color: genStatus.startsWith('✅') ? 'var(--up)' : genStatus.startsWith('❌') ? 'var(--down)' : 'var(--fg-3)' }}>
            {genStatus}
          </div>
        )}
        <div style={{ marginTop: 10, fontSize: '0.72rem', color: 'var(--fg-3)', borderTop: '1px solid var(--line-1)', paddingTop: 8 }}>
          <i className="bi bi-info-circle me-1" />
          보고서는 Ollama 로컬 LLM이 시장 데이터를 분석해 자동 작성합니다. 생성에 1~3분 소요됩니다.
        </div>
      </div>

      {/* 탭 */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
        {[['all', '전체', 'bi-grid'], ...Object.entries(TYPE_META).map(([k, m]) => [k, m.label, m.icon])].map(([key, label, icon]) => {
          const count = key === 'all' ? reports.length : reports.filter(r => r.report_type === key).length;
          return (
            <button key={key} onClick={() => setActiveTab(key)} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px', borderRadius: 'var(--r-3)', border: activeTab === key ? `2px solid ${key === 'all' ? 'var(--accent)' : TYPE_META[key]?.color}` : '2px solid var(--line-1)', background: activeTab === key ? `${key === 'all' ? 'var(--accent)' : TYPE_META[key]?.color}15` : 'var(--bg-2)', cursor: 'pointer', fontSize: '0.82rem', fontWeight: activeTab === key ? 700 : 400, color: activeTab === key ? (key === 'all' ? 'var(--accent)' : TYPE_META[key]?.color) : 'var(--fg-2)' }}>
              <i className={`bi ${icon}`} />
              {label}
              <span style={{ fontSize: '0.68rem', opacity: 0.7 }}>({count})</span>
            </button>
          );
        })}
      </div>

      {/* 보고서 목록 */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: '60px 0' }}><div className="spinner" style={{ margin: '0 auto' }} /></div>
      ) : filtered.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--fg-3)' }}>
          <i className="bi bi-journal-text" style={{ fontSize: '2.5rem', display: 'block', marginBottom: 12, opacity: 0.3 }} />
          <p style={{ margin: 0, fontSize: '0.85rem' }}>보고서가 없습니다.</p>
          <p style={{ margin: '8px 0 0', fontSize: '0.78rem' }}>위 버튼으로 첫 번째 보고서를 생성하거나, Ollama가 실행 중인지 확인하세요.</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {filtered.map(r => (
            <ReportCard key={r.id} report={r} onClick={() => navigate(`/market_reports/${r.id}`)} />
          ))}
        </div>
      )}

    </StockLayout>
  );
}
