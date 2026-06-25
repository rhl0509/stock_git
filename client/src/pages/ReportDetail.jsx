import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

const TYPE_META = {
  daily:   { label: '일간', color: '#3b82f6', bg: 'rgba(59,130,246,0.1)', border: 'rgba(59,130,246,0.3)' },
  weekly:  { label: '주간', color: '#10b981', bg: 'rgba(16,185,129,0.1)', border: 'rgba(16,185,129,0.3)' },
  monthly: { label: '월간', color: '#8b5cf6', bg: 'rgba(139,92,246,0.1)', border: 'rgba(139,92,246,0.3)' },
};

// 간단한 마크다운 → HTML 변환 (외부 라이브러리 없이)
function renderMarkdown(text) {
  if (!text) return '';
  const lines = text.split('\n');
  const result = [];
  let inUl = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (line.startsWith('## ')) {
      if (inUl) { result.push('</ul>'); inUl = false; }
      result.push(`<h2>${escHtml(line.slice(3))}</h2>`);
    } else if (line.startsWith('### ')) {
      if (inUl) { result.push('</ul>'); inUl = false; }
      result.push(`<h3>${escHtml(line.slice(4))}</h3>`);
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      if (!inUl) { result.push('<ul>'); inUl = true; }
      result.push(`<li>${escHtml(line.slice(2))}</li>`);
    } else if (line.startsWith('**') && line.endsWith('**') && line.length > 4) {
      if (inUl) { result.push('</ul>'); inUl = false; }
      result.push(`<p><strong>${escHtml(line.slice(2, -2))}</strong></p>`);
    } else if (line.trim() === '') {
      if (inUl) { result.push('</ul>'); inUl = false; }
      result.push('<br/>');
    } else {
      if (inUl) { result.push('</ul>'); inUl = false; }
      // 인라인 볼드 처리
      const processed = escHtml(line).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      result.push(`<p>${processed}</p>`);
    }
  }
  if (inUl) result.push('</ul>');
  return result.join('\n');
}

function escHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

export default function ReportDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api.get(`/reports/json/${id}`)
      .then(r => setReport(r.data?.report || null))
      .catch(e => setError(e.response?.data?.detail || '보고서를 불러올 수 없습니다.'))
      .finally(() => setLoading(false));
  }, [id]);

  const handleCopy = () => {
    if (!report?.content) return;
    navigator.clipboard.writeText(report.content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const m = report ? (TYPE_META[report.report_type] || {}) : {};

  return (
    <StockLayout title="보고서 상세">
      {/* 뒤로가기 */}
      <button onClick={() => navigate('/market_reports')} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginBottom: 16, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--fg-3)', fontSize: '0.82rem', padding: 0 }}>
        <i className="bi bi-arrow-left" />목록으로
      </button>

      {loading && <div style={{ textAlign: 'center', padding: '60px 0' }}><div className="spinner" style={{ margin: '0 auto' }} /></div>}

      {error && (
        <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--fg-3)' }}>
          <i className="bi bi-exclamation-circle" style={{ fontSize: '2rem', display: 'block', marginBottom: 10, opacity: 0.4 }} />
          <p style={{ margin: 0 }}>{error}</p>
        </div>
      )}

      {report && (
        <>
          {/* 메타 헤더 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.75rem', fontWeight: 700, padding: '3px 10px', borderRadius: 20, background: m.bg, color: m.color, border: `1px solid ${m.border}`, fontFamily: 'var(--font-mono)' }}>
              {m.label}
            </span>
            <span style={{ fontSize: '0.82rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>
              {report.report_date?.slice(0, 10)}
            </span>
            <span style={{ fontSize: '0.72rem', color: 'var(--fg-3)' }}>
              생성: {report.created_at?.slice(0, 16)?.replace('T', ' ')}
            </span>
            <button onClick={handleCopy} style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6, padding: '6px 14px', borderRadius: 'var(--r-2)', border: '1px solid var(--line-1)', background: 'var(--bg-2)', color: copied ? 'var(--up)' : 'var(--fg-2)', cursor: 'pointer', fontSize: '0.78rem', fontWeight: 600 }}>
              <i className={`bi ${copied ? 'bi-check' : 'bi-clipboard'}`} />
              {copied ? '복사됨' : '전체 복사'}
            </button>
          </div>

          {/* 제목 */}
          <h1 style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--fg-1)', marginBottom: 20, paddingBottom: 12, borderBottom: `2px solid ${m.color}` }}>
            {report.title}
          </h1>

          {/* 본문 */}
          <div className="rpt-content" style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '28px 32px', lineHeight: 1.8, color: 'var(--fg-1)', fontSize: '0.9rem' }}
            dangerouslySetInnerHTML={{ __html: renderMarkdown(report.content) }} />

          {/* 스타일 */}
          <style>{`
            .rpt-content h2 { font-size:1.05rem; font-weight:700; margin:24px 0 10px; padding-bottom:6px; border-bottom:2px solid ${m.color || 'var(--accent)'}; color:var(--fg-1); }
            .rpt-content h3 { font-size:0.95rem; font-weight:600; margin:16px 0 6px; color:var(--fg-1); }
            .rpt-content p  { margin:6px 0; }
            .rpt-content ul { padding-left:1.4em; margin:6px 0; }
            .rpt-content li { margin:3px 0; }
            .rpt-content br { display:block; content:''; margin:4px 0; }
          `}</style>
        </>
      )}
    </StockLayout>
  );
}
