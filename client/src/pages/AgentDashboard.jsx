import React, { useState, useEffect, useCallback, useMemo } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

// ─────────────────────────────────────────────────────────────────
// 상수
// ─────────────────────────────────────────────────────────────────
const SIGNAL_STYLE = {
  호재:          { color: '#10b981', bg: 'rgba(16,185,129,0.1)',  border: 'rgba(16,185,129,0.3)' },
  악재:          { color: '#ef4444', bg: 'rgba(239,68,68,0.1)',   border: 'rgba(239,68,68,0.3)'  },
  중립:          { color: '#6b7280', bg: 'rgba(107,114,128,0.1)', border: 'rgba(107,114,128,0.3)'},
  어닝서프라이즈: { color: '#10b981', bg: 'rgba(16,185,129,0.1)',  border: 'rgba(16,185,129,0.3)' },
  어닝쇼크:      { color: '#ef4444', bg: 'rgba(239,68,68,0.1)',   border: 'rgba(239,68,68,0.3)'  },
  실적중립:      { color: '#6b7280', bg: 'rgba(107,114,128,0.1)', border: 'rgba(107,114,128,0.3)'},
};

const IMP_STYLE = {
  high:   { color: '#ef4444', label: '높음' },
  medium: { color: '#f59e0b', label: '중간' },
  low:    { color: '#6b7280', label: '낮음' },
};

const REC_TYPE = {
  daily: { label: '단기(3일)',  color: '#3b82f6' },
  short: { label: '중기(5일)',  color: '#8b5cf6' },
  swing: { label: '스윙(14일)', color: '#10b981' },
};

// 잡 예상 실행 주기(분) — freshness bar 기준
const EXPECTED_MIN = {
  report_daily:      1440,
  report_weekly:     7 * 1440,
  report_monthly:    28 * 1440,
  agent_performance: 1440,
  agent_anomaly:     180,
  agent_events:      1440,
  agent_dart:        60,
  agent_flow:        1440,
  agent_earnings:    1440,
  agent_rebalance:   1440,
};

// ─────────────────────────────────────────────────────────────────
// 공통 컴포넌트
// ─────────────────────────────────────────────────────────────────
function Badge({ text, style }) {
  return (
    <span style={{
      fontSize: '0.65rem', fontWeight: 700, padding: '2px 7px', borderRadius: 20,
      background: style?.bg, color: style?.color, border: `1px solid ${style?.border}`,
      whiteSpace: 'nowrap',
    }}>{text}</span>
  );
}

function SectionTitle({ icon, title, count }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
      <i className={`bi ${icon}`} style={{ color: 'var(--accent)', fontSize: '1rem' }} />
      <span style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--fg-1)' }}>{title}</span>
      {count != null && (
        <span style={{ fontSize: '0.72rem', color: 'var(--fg-3)', background: 'var(--bg-3)', borderRadius: 10, padding: '1px 7px' }}>
          {count}건
        </span>
      )}
    </div>
  );
}

function EmptyState({ text }) {
  return (
    <div style={{ textAlign: 'center', padding: '32px 0', color: 'var(--fg-3)', fontSize: '0.82rem' }}>
      <i className="bi bi-inbox" style={{ fontSize: '1.8rem', display: 'block', marginBottom: 8, opacity: 0.3 }} />
      {text}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// 신선도 바
// ─────────────────────────────────────────────────────────────────
function FreshnessBar({ lastRunAt, jobId }) {
  if (!lastRunAt) {
    return <div style={{ height: 3, background: 'var(--line-1)', borderRadius: 2, marginTop: 6 }} title="실행 기록 없음" />;
  }
  const minsAgo  = (Date.now() - new Date(lastRunAt).getTime()) / 60000;
  const expected = EXPECTED_MIN[jobId] || 1440;
  const ratio    = minsAgo / expected;
  const barPct   = Math.min(100, ratio * 100);
  const color    = ratio < 0.6 ? '#10b981' : ratio < 1.0 ? '#f59e0b' : '#ef4444';
  const timeStr  = minsAgo < 60
    ? `${Math.round(minsAgo)}분 전`
    : minsAgo < 1440
    ? `${Math.round(minsAgo / 60)}시간 전`
    : `${Math.round(minsAgo / 1440)}일 전`;
  return (
    <div style={{ height: 3, background: 'var(--line-1)', borderRadius: 2, marginTop: 6 }}
         title={`마지막 실행: ${timeStr}`}>
      <div style={{ height: '100%', width: `${barPct}%`, background: color, borderRadius: 2, transition: 'width 0.4s' }} />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// 스케줄 카드
// ─────────────────────────────────────────────────────────────────
function JobCard({ job, notifySettings, onRun, onNotifyToggle, running }) {
  const isRunning  = running === job.id;
  const lastStatus = job.last_status;
  const dotColor   = lastStatus === 'success' ? '#10b981'
                   : lastStatus === 'failed'  ? '#ef4444'
                   : 'var(--line-2)';

  const fmtNext = (raw) => {
    if (!raw || raw === '-') return '정보 없음';
    try {
      return new Date(raw).toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
    } catch { return raw; }
  };

  const ns      = notifySettings[job.id] || {};
  const kakaoOn = ns.kakao !== false;
  const emailOn = ns.email === true;

  return (
    <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '12px 14px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {/* 상태 점 */}
        <div style={{
          width: 8, height: 8, borderRadius: '50%', flexShrink: 0, background: dotColor,
          boxShadow: lastStatus === 'success' ? `0 0 5px ${dotColor}80` : 'none',
        }} />
        {/* 아이콘 */}
        <div style={{
          width: 32, height: 32, borderRadius: 8, flexShrink: 0,
          background: 'var(--bg-3)', display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <i className={`bi ${job.icon}`} style={{ color: 'var(--accent)', fontSize: '0.9rem' }} />
        </div>
        {/* 이름 + 다음 실행 */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: '0.83rem', color: 'var(--fg-1)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{job.name}</div>
          <div style={{ fontSize: '0.67rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>
            <i className="bi bi-clock me-1" />다음: {fmtNext(job.next_run)}
          </div>
        </div>
        {/* 알림 토글 */}
        <div style={{ display: 'flex', gap: 3, flexShrink: 0 }}>
          <button
            onClick={() => onNotifyToggle(job.id, 'kakao', !kakaoOn)}
            title={`카카오 알림 ${kakaoOn ? '켜짐 (클릭하여 끄기)' : '꺼짐 (클릭하여 켜기)'}`}
            style={{
              width: 22, height: 22, borderRadius: 5, border: 'none', cursor: 'pointer', padding: 0,
              background: kakaoOn ? '#FEE500' : 'var(--bg-3)',
              color: kakaoOn ? '#333' : 'var(--fg-3)',
              fontSize: '0.6rem', display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
            <i className="bi bi-chat-fill" />
          </button>
          <button
            onClick={() => onNotifyToggle(job.id, 'email', !emailOn)}
            title={`이메일 알림 ${emailOn ? '켜짐 (클릭하여 끄기)' : '꺼짐 (클릭하여 켜기)'}`}
            style={{
              width: 22, height: 22, borderRadius: 5, border: 'none', cursor: 'pointer', padding: 0,
              background: emailOn ? 'var(--accent)' : 'var(--bg-3)',
              color: emailOn ? '#fff' : 'var(--fg-3)',
              fontSize: '0.6rem', display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
            <i className="bi bi-envelope-fill" />
          </button>
        </div>
        {/* 실행 버튼 */}
        <button
          onClick={() => onRun(job.id, job.name)}
          disabled={isRunning}
          style={{
            padding: '5px 10px', borderRadius: 'var(--r-2)', border: '1px solid var(--line-2)',
            background: isRunning ? 'var(--bg-3)' : 'var(--bg-2)',
            color: isRunning ? 'var(--fg-3)' : 'var(--accent)',
            cursor: isRunning ? 'not-allowed' : 'pointer',
            fontSize: '0.72rem', fontWeight: 600, whiteSpace: 'nowrap', flexShrink: 0,
          }}>
          <i className={`bi ${isRunning ? 'bi-arrow-clockwise spin' : 'bi-play-fill'} me-1`} />
          {isRunning ? '실행 중' : '실행'}
        </button>
      </div>
      {/* 신선도 바 */}
      <FreshnessBar lastRunAt={job.last_run_at} jobId={job.id} />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// 탭: 피드
// ─────────────────────────────────────────────────────────────────
const FEED_TYPE_META = {
  run:     { icon: 'bi-play-circle-fill',         label: '실행', color: '#3b82f6' },
  dart:    { icon: 'bi-file-earmark-text',         label: '공시', color: '#8b5cf6' },
  anomaly: { icon: 'bi-exclamation-triangle-fill', label: '이상', color: '#ef4444' },
  event:   { icon: 'bi-calendar-event',            label: '이벤트', color: '#10b981' },
};

function FeedTab({ items, jobNameMap }) {
  if (!items.length) return <EmptyState text="최근 활동이 없습니다." />;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {items.map((item, i) => {
        const m       = FEED_TYPE_META[item.type] || FEED_TYPE_META.run;
        const isFail  = item.status === 'failed';
        const iconCls = isFail ? 'bi-x-circle-fill' : m.icon;
        const icolor  = isFail ? '#ef4444' : m.color;
        const headline = item.job_id ? (jobNameMap[item.job_id] || item.job_id)
                       : (item.title || '');
        const content  = item.summary || item.signals || (item.explanation ? item.explanation.slice(0, 100) : '');
        const tsStr    = item.ts ? item.ts.toString().slice(0, 16).replace('T', ' ') : '';
        return (
          <div key={i} style={{
            display: 'flex', alignItems: 'flex-start', gap: 10,
            background: 'var(--bg-2)', border: '1px solid var(--line-1)',
            borderRadius: 'var(--r-2)', padding: '10px 14px',
            borderLeft: `3px solid ${isFail ? '#ef4444' : m.color}`,
          }}>
            <i className={`bi ${iconCls}`} style={{ color: icolor, fontSize: '0.88rem', marginTop: 2, flexShrink: 0 }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2, flexWrap: 'wrap' }}>
                <span style={{
                  fontSize: '0.63rem', background: `${m.color}18`, color: m.color,
                  border: `1px solid ${m.color}40`, borderRadius: 10, padding: '1px 7px', fontWeight: 700,
                }}>{m.label}</span>
                <span style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--fg-1)' }}>{headline}</span>
              </div>
              {content && (
                <div style={{ fontSize: '0.75rem', color: 'var(--fg-2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {content}
                </div>
              )}
              {item.error_msg && (
                <div style={{ fontSize: '0.71rem', color: '#ef4444', marginTop: 2 }}>{item.error_msg.slice(0, 100)}</div>
              )}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0, marginTop: 2 }}>
              <span style={{ fontSize: '0.63rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap' }}>
                {tsStr}
              </span>
              {item.type === 'dart' && /^\d{14}$/.test(item.rcept_no || '') && (
                <a href={`https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${item.rcept_no}`}
                   target="_blank" rel="noreferrer" title="DART 원문 보기"
                   style={{
                     display: 'flex', alignItems: 'center', justifyContent: 'center',
                     width: 20, height: 20, borderRadius: 4,
                     background: 'var(--bg-3)', color: 'var(--accent)',
                     border: '1px solid var(--line-2)', textDecoration: 'none', fontSize: '0.65rem',
                   }}>
                  <i className="bi bi-box-arrow-up-right" />
                </a>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// 탭: 추천 성과
// ─────────────────────────────────────────────────────────────────
function PerformanceTab({ data }) {
  if (!data.length) return <EmptyState text="아직 평가된 추천이 없습니다." />;

  const done    = data.filter(r => r.exit_price != null);
  const pending = data.filter(r => r.exit_price == null);
  const wins    = done.filter(r => r.return_pct >= 0).length;
  const winRate = done.length ? (wins / done.length * 100).toFixed(1) : null;
  const avgRet  = done.length ? (done.reduce((s, r) => s + r.return_pct, 0) / done.length).toFixed(2) : null;

  return (
    <div>
      {done.length > 0 && (
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
          {[
            { label: '평가 완료',   val: `${done.length}건` },
            { label: '승률',        val: `${winRate}%`,      color: Number(winRate) >= 50 ? '#10b981' : '#ef4444' },
            { label: '평균 수익률', val: `${avgRet > 0 ? '+' : ''}${avgRet}%`, color: avgRet >= 0 ? '#10b981' : '#ef4444' },
            { label: '평가 대기',   val: `${pending.length}건` },
          ].map(s => (
            <div key={s.label} style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-2)', padding: '10px 16px', minWidth: 90, textAlign: 'center' }}>
              <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)', marginBottom: 4 }}>{s.label}</div>
              <div style={{ fontSize: '1rem', fontWeight: 700, color: s.color || 'var(--fg-1)', fontFamily: 'var(--font-mono)' }}>{s.val}</div>
            </div>
          ))}
        </div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {data.slice(0, 30).map(r => {
          const rt     = REC_TYPE[r.recommend_type] || {};
          const isDone = r.exit_price != null;
          const ret    = r.return_pct;
          return (
            <div key={r.id} style={{
              display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
              background: 'var(--bg-2)', border: '1px solid var(--line-1)',
              borderRadius: 'var(--r-2)', padding: '10px 14px',
            }}>
              <Badge text={rt.label || r.recommend_type} style={{ bg: `${rt.color}18`, color: rt.color, border: `1px solid ${rt.color}40` }} />
              <span style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--fg-1)' }}>{r.name}</span>
              <span style={{ fontSize: '0.72rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>{r.recommend_date?.slice(0, 10)}</span>
              <span style={{ fontSize: '0.78rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)', marginLeft: 'auto' }}>
                진입 {Number(r.entry_price)?.toLocaleString()}
              </span>
              {isDone ? (
                <span style={{ fontSize: '0.85rem', fontWeight: 700, color: ret >= 0 ? '#10b981' : '#ef4444', fontFamily: 'var(--font-mono)', minWidth: 60, textAlign: 'right' }}>
                  {ret >= 0 ? '▲' : '▼'}{Math.abs(ret).toFixed(2)}%
                </span>
              ) : (
                <span style={{ fontSize: '0.72rem', color: 'var(--fg-3)', background: 'var(--bg-3)', borderRadius: 10, padding: '2px 8px' }}>대기 중</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// 탭: 공시 요약
// ─────────────────────────────────────────────────────────────────
function DartTab({ data }) {
  if (!data.length) return <EmptyState text="요약된 공시가 없습니다." />;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {data.map(r => {
        const sig     = SIGNAL_STYLE[r.signal] || SIGNAL_STYLE['중립'];
        // DART 접수번호는 14자리 숫자 (예: 20240523000123)
        const dartUrl = /^\d{14}$/.test(r.rcept_no || '')
          ? `https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${r.rcept_no}`
          : null;
        return (
          <div key={r.id} style={{
            display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
            background: 'var(--bg-2)', border: '1px solid var(--line-1)',
            borderRadius: 'var(--r-2)', padding: '10px 14px',
          }}>
            <Badge text={r.signal} style={sig} />
            <span style={{ fontWeight: 600, fontSize: '0.82rem', color: 'var(--fg-1)', flexShrink: 0 }}>{r.corp_name}</span>
            <span style={{ fontSize: '0.78rem', color: 'var(--fg-2)', flex: 1 }}>{r.summary}</span>
            <span style={{ fontSize: '0.68rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)', flexShrink: 0 }}>
              {r.created_at?.slice(0, 16)?.replace('T', ' ')}
            </span>
            {dartUrl && (
              <a href={dartUrl} target="_blank" rel="noreferrer"
                title={`DART 원문 보기: ${r.report_nm || r.corp_name}`}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  width: 26, height: 26, borderRadius: 6, flexShrink: 0,
                  background: 'var(--bg-3)', color: 'var(--accent)',
                  border: '1px solid var(--line-2)', textDecoration: 'none', fontSize: '0.75rem',
                }}>
                <i className="bi bi-box-arrow-up-right" />
              </a>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// 탭: 이상 감지
// ─────────────────────────────────────────────────────────────────
function AnomalyTab({ data }) {
  if (!data.length) return <EmptyState text="최근 이상 감지 기록이 없습니다." />;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {data.map(r => {
        const isUp = parseFloat(r.price_chg) >= 0;
        return (
          <div key={r.id} style={{
            background: 'var(--bg-2)', border: '1px solid var(--line-1)',
            borderRadius: 'var(--r-2)', padding: '12px 14px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 6 }}>
              <span style={{ fontWeight: 700, fontSize: '0.87rem', color: 'var(--fg-1)' }}>{r.name}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--fg-3)' }}>{r.ticker}</span>
              <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: '0.82rem', fontWeight: 700, color: isUp ? '#10b981' : '#ef4444' }}>
                {isUp ? '▲' : '▼'}{Math.abs(parseFloat(r.price_chg)).toFixed(1)}%
              </span>
              <span style={{ fontSize: '0.72rem', color: '#f59e0b', fontFamily: 'var(--font-mono)' }}>
                거래량 {parseFloat(r.vol_ratio).toFixed(1)}배
              </span>
            </div>
            {r.signals && (
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 6 }}>
                {r.signals.split(', ').map(s => (
                  <span key={s} style={{
                    fontSize: '0.64rem', background: 'rgba(239,68,68,0.1)', color: '#ef4444',
                    border: '1px solid rgba(239,68,68,0.3)', borderRadius: 10, padding: '2px 8px', fontWeight: 600,
                  }}>{s}</span>
                ))}
              </div>
            )}
            {r.explanation && (
              <div style={{
                fontSize: '0.76rem', color: 'var(--fg-2)', borderTop: '1px solid var(--line-1)',
                paddingTop: 6, marginTop: 4, lineHeight: 1.55,
              }}>
                {r.explanation.slice(0, 280)}
              </div>
            )}
            <div style={{ fontSize: '0.63rem', color: 'var(--fg-3)', marginTop: 6, fontFamily: 'var(--font-mono)' }}>
              {r.detected_at?.slice(0, 16)?.replace('T', ' ')}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// 탭: 이벤트 캘린더
// ─────────────────────────────────────────────────────────────────
function EventsTab({ data }) {
  if (!data.length) return (
    <div style={{ textAlign: 'center', padding: '32px 0', color: 'var(--fg-3)', fontSize: '0.82rem' }}>
      <i className="bi bi-calendar-x" style={{ fontSize: '1.8rem', display: 'block', marginBottom: 8, opacity: 0.3 }} />
      등록된 이벤트가 없습니다.
    </div>
  );

  const today = new Date().toISOString().slice(0, 10);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {data.map(e => {
        const imp    = IMP_STYLE[e.importance] || IMP_STYLE.medium;
        const isPast = e.event_date < today;
        return (
          <div key={e.id} style={{
            display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
            background: 'var(--bg-2)', border: '1px solid var(--line-1)',
            borderRadius: 'var(--r-2)', padding: '10px 14px',
            opacity: isPast ? 0.5 : 1,
          }}>
            <span style={{ fontSize: '0.72rem', fontWeight: 700, color: imp.color, flexShrink: 0, minWidth: 30 }}>{imp.label}</span>
            <span style={{ fontSize: '0.72rem', background: 'var(--bg-3)', borderRadius: 4, padding: '2px 7px', fontFamily: 'var(--font-mono)', color: 'var(--fg-3)', flexShrink: 0 }}>{e.country}</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', color: 'var(--fg-3)', flexShrink: 0 }}>{e.event_date}</span>
            <span style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--fg-1)', flex: 1 }}>{e.title}</span>
            {e.notified
              ? <span style={{ fontSize: '0.68rem', color: '#10b981' }}><i className="bi bi-check-circle me-1" />발송됨</span>
              : isPast ? null
              : <span style={{ fontSize: '0.68rem', color: 'var(--fg-3)' }}><i className="bi bi-clock me-1" />대기</span>
            }
          </div>
        );
      })}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// 탭: 실행 이력
// ─────────────────────────────────────────────────────────────────
function RunLogTab({ logs, jobNameMap }) {
  const [filterJob, setFilterJob] = useState('');

  const jobIds  = useMemo(() => [...new Set(logs.map(l => l.job_id))], [logs]);
  const visible = filterJob ? logs.filter(l => l.job_id === filterJob) : logs;

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <select
          value={filterJob}
          onChange={e => setFilterJob(e.target.value)}
          style={{
            fontSize: '0.78rem', padding: '5px 10px', borderRadius: 'var(--r-2)',
            border: '1px solid var(--line-2)', background: 'var(--bg-2)', color: 'var(--fg-1)',
          }}>
          <option value="">전체 잡</option>
          {jobIds.map(id => <option key={id} value={id}>{jobNameMap[id] || id}</option>)}
        </select>
      </div>

      {!visible.length ? <EmptyState text="실행 이력이 없습니다." /> : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {visible.map(log => {
            const isOk   = log.status === 'success';
            const isFail = log.status === 'failed';
            const dur    = log.finished_at
              ? Math.round((new Date(log.finished_at) - new Date(log.started_at)) / 1000)
              : null;
            const bColor = isOk ? '#10b981' : isFail ? '#ef4444' : '#f59e0b';
            return (
              <div key={log.id} style={{
                display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
                background: 'var(--bg-2)', border: '1px solid var(--line-1)',
                borderRadius: 'var(--r-2)', padding: '10px 14px',
                borderLeft: `3px solid ${bColor}`,
              }}>
                <i className={`bi ${isOk ? 'bi-check-circle-fill' : isFail ? 'bi-x-circle-fill' : 'bi-circle-half'}`}
                   style={{ color: bColor, fontSize: '0.88rem', flexShrink: 0 }} />
                <span style={{ fontWeight: 600, fontSize: '0.82rem', color: 'var(--fg-1)', minWidth: 90, flexShrink: 0 }}>
                  {jobNameMap[log.job_id] || log.job_id}
                </span>
                <span style={{
                  fontSize: '0.68rem', borderRadius: 10, padding: '1px 7px', flexShrink: 0,
                  background: log.triggered_by === 'manual' ? 'rgba(99,102,241,0.12)' : 'var(--bg-3)',
                  color: log.triggered_by === 'manual' ? 'var(--accent)' : 'var(--fg-3)',
                }}>
                  {log.triggered_by === 'manual' ? '수동' : '자동'}
                </span>
                <span style={{ fontSize: '0.73rem', color: 'var(--fg-2)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {isOk ? (log.summary || '완료') : (log.error_msg ? log.error_msg.slice(0, 80) : '')}
                </span>
                {dur != null && (
                  <span style={{ fontSize: '0.65rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)', flexShrink: 0 }}>{dur}s</span>
                )}
                <span style={{ fontSize: '0.65rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)', flexShrink: 0, whiteSpace: 'nowrap' }}>
                  {log.started_at?.slice(0, 16)?.replace('T', ' ')}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// 메인 페이지
// ─────────────────────────────────────────────────────────────────
export default function AgentDashboard() {
  const [jobs,           setJobs]           = useState([]);
  const [perfData,       setPerfData]       = useState([]);
  const [dartData,       setDartData]       = useState([]);
  const [eventsData,     setEventsData]     = useState([]);
  const [anomalyData,    setAnomalyData]    = useState([]);
  const [feedData,       setFeedData]       = useState([]);
  const [runLogs,        setRunLogs]        = useState([]);
  const [notifySettings, setNotifySettings] = useState({});
  const [activeTab,      setActiveTab]      = useState('feed');
  const [running,        setRunning]        = useState('');
  const [runMsg,         setRunMsg]         = useState('');
  const [loading,        setLoading]        = useState(true);

  const jobNameMap = useMemo(
    () => Object.fromEntries(jobs.map(j => [j.id, j.name])),
    [jobs]
  );

  const fetchAll = useCallback(async () => {
    setLoading(true);
    const [s, p, d, e, a, f, l, n] = await Promise.allSettled([
      api.get('/api/agent/status'),
      api.get('/api/agent/performance?limit=30'),
      api.get('/api/agent/dart?limit=20'),
      api.get('/api/agent/events'),
      api.get('/api/agent/anomaly?limit=20'),
      api.get('/api/agent/feed?limit=30'),
      api.get('/api/agent/run-log?limit=50'),
      api.get('/api/agent/notify-settings'),
    ]);
    const v = r => r.status === 'fulfilled' ? r.value : null;
    if (v(s)) setJobs(v(s).data?.jobs || []);
    if (v(p)) setPerfData(v(p).data?.data || []);
    if (v(d)) setDartData(v(d).data?.data || []);
    if (v(e)) setEventsData(v(e).data?.events || []);
    if (v(a)) setAnomalyData(v(a).data?.data || []);
    if (v(f)) setFeedData(v(f).data?.items || []);
    if (v(l)) setRunLogs(v(l).data?.logs || []);
    if (v(n)) setNotifySettings(v(n).data?.settings || {});
    setLoading(false);
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const handleRun = async (jobId, jobName) => {
    setRunning(jobId);
    setRunMsg('');
    try {
      const r = await api.post(`/api/agent/run?job_id=${jobId}`);
      setRunMsg(`✅ ${r.data?.message || `${jobName} 실행 시작`}`);
      setTimeout(fetchAll, 6000);
    } catch (e) {
      setRunMsg(`❌ 실행 실패: ${e.response?.data?.detail || e.message}`);
    }
    setRunning('');
  };

  const handleNotifyToggle = async (jobId, channel, enabled) => {
    setNotifySettings(prev => ({
      ...prev,
      [jobId]: { ...(prev[jobId] || {}), [channel]: enabled },
    }));
    try {
      await api.post('/api/agent/notify-settings', { job_id: jobId, channel, enabled });
    } catch (_) {
      // 실패 시 롤백
      setNotifySettings(prev => ({
        ...prev,
        [jobId]: { ...(prev[jobId] || {}), [channel]: !enabled },
      }));
    }
  };

  const reportJobs = jobs.filter(j => j.group === 'report');
  const agentJobs  = jobs.filter(j => j.group === 'agent');

  const TABS = [
    { key: 'feed',        label: '피드',      icon: 'bi-broadcast',            badge: feedData.length },
    { key: 'performance', label: '추천 성과',  icon: 'bi-graph-up',             badge: perfData.length },
    { key: 'dart',        label: '공시 요약',  icon: 'bi-file-earmark-text',    badge: dartData.length },
    { key: 'anomaly',     label: '이상 감지',  icon: 'bi-exclamation-triangle', badge: anomalyData.length },
    { key: 'events',      label: '이벤트',    icon: 'bi-calendar-event',        badge: eventsData.length },
    { key: 'runlog',      label: '실행 이력',  icon: 'bi-clock-history',        badge: runLogs.length },
  ];

  return (
    <StockLayout title="에이전트 모니터">
      {loading ? (
        <div style={{ textAlign: 'center', padding: '60px 0' }}>
          <div className="spinner" style={{ margin: '0 auto' }} />
        </div>
      ) : (
        <>
          {/* 실행 메시지 */}
          {runMsg && (
            <div style={{
              marginBottom: 16, padding: '10px 14px', borderRadius: 'var(--r-2)',
              background: runMsg.startsWith('✅') ? 'rgba(16,185,129,0.08)' : 'rgba(239,68,68,0.08)',
              border: `1px solid ${runMsg.startsWith('✅') ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}`,
              fontSize: '0.82rem', color: runMsg.startsWith('✅') ? '#10b981' : '#ef4444',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            }}>
              <span>{runMsg}</span>
              <button onClick={() => setRunMsg('')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--fg-3)', padding: '0 4px' }}>×</button>
            </div>
          )}

          {/* 보고서 잡 */}
          <div style={{ marginBottom: 20 }}>
            <SectionTitle icon="bi-journal-richtext" title="보고서" />
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 8 }}>
              {reportJobs.map(j => (
                <JobCard key={j.id} job={j} notifySettings={notifySettings}
                  onRun={handleRun} onNotifyToggle={handleNotifyToggle} running={running} />
              ))}
            </div>
          </div>

          {/* 에이전트 잡 */}
          <div style={{ marginBottom: 20 }}>
            <SectionTitle icon="bi-robot" title="에이전트" />
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 8 }}>
              {agentJobs.map(j => (
                <JobCard key={j.id} job={j} notifySettings={notifySettings}
                  onRun={handleRun} onNotifyToggle={handleNotifyToggle} running={running} />
              ))}
            </div>
          </div>

          {/* 새로고침 */}
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 20 }}>
            <button onClick={fetchAll} style={{
              display: 'flex', alignItems: 'center', gap: 5, padding: '7px 14px',
              borderRadius: 'var(--r-2)', border: '1px solid var(--line-1)',
              background: 'var(--bg-2)', color: 'var(--fg-3)', cursor: 'pointer', fontSize: '0.78rem',
            }}>
              <i className="bi bi-arrow-clockwise" />새로고침
            </button>
          </div>

          {/* 탭 헤더 */}
          <div style={{ display: 'flex', gap: 0, marginBottom: 16, borderBottom: '1px solid var(--line-1)', overflowX: 'auto' }}>
            {TABS.map(t => (
              <button key={t.key} onClick={() => setActiveTab(t.key)} style={{
                display: 'flex', alignItems: 'center', gap: 5, padding: '10px 14px',
                border: 'none', background: 'none', cursor: 'pointer', fontSize: '0.8rem',
                fontWeight: activeTab === t.key ? 700 : 400,
                color: activeTab === t.key ? 'var(--accent)' : 'var(--fg-3)',
                borderBottom: activeTab === t.key ? '2px solid var(--accent)' : '2px solid transparent',
                marginBottom: -1, whiteSpace: 'nowrap', flexShrink: 0,
              }}>
                <i className={`bi ${t.icon}`} />
                {t.label}
                <span style={{ fontSize: '0.63rem', background: 'var(--bg-3)', borderRadius: 10, padding: '1px 6px', color: 'var(--fg-3)' }}>
                  {t.badge}
                </span>
              </button>
            ))}
          </div>

          {/* 탭 컨텐츠 */}
          <div style={{ paddingTop: 4 }}>
            {activeTab === 'feed'        && <FeedTab        items={feedData}    jobNameMap={jobNameMap} />}
            {activeTab === 'performance' && <PerformanceTab data={perfData} />}
            {activeTab === 'dart'        && <DartTab        data={dartData} />}
            {activeTab === 'anomaly'     && <AnomalyTab     data={anomalyData} />}
            {activeTab === 'events'      && <EventsTab      data={eventsData} />}
            {activeTab === 'runlog'      && <RunLogTab      logs={runLogs}     jobNameMap={jobNameMap} />}
          </div>
        </>
      )}

      <style>{`.spin { animation: spin 1s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </StockLayout>
  );
}
