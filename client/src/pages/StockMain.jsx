import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import StockLayout from '../layouts/StockLayout.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import api from '../api/index.js';

function StatCard({ title, value, sub, icon, color }) {
  return (
    <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'16px 18px' }}>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:10 }}>
        <span style={{ fontSize:'0.75rem', fontWeight:600, color:'var(--fg-3)', fontFamily:'var(--font-mono)', textTransform:'uppercase' }}>{title}</span>
        <i className={`bi ${icon}`} style={{ fontSize:'1rem', color: color || 'var(--accent)' }}/>
      </div>
      <div style={{ fontSize:'1.4rem', fontWeight:800, color:'var(--fg-1)', fontFamily:'var(--font-mono)' }}>{value}</div>
      {sub && <div style={{ fontSize:'0.72rem', color:'var(--fg-3)', marginTop:4 }}>{sub}</div>}
    </div>
  );
}

function condenseSummary(raw) {
  if (!raw) return '';
  const lines = raw.split('\n')
    .map(l => l.trim())
    .filter(l => l && !l.startsWith('📰') && !/^[─\-=*_]+$/.test(l));
  const text = lines.join(' ').replace(/[#>*`]/g, '').replace(/\s+/g, ' ').trim();
  if (text.length <= 160) return text;
  const cut = text.slice(0, 160);
  const lastPunct = Math.max(cut.lastIndexOf('. '), cut.lastIndexOf('다 '), cut.lastIndexOf('다. '));
  return (lastPunct > 80 ? cut.slice(0, lastPunct + 1) : cut).trim() + '…';
}

const NAV_SHORTCUTS = [
  { to:'/recommend',          icon:'bi-stars',           label:'AI 추천',      color:'#a78bfa' },
  { to:'/stock_portfolio_kr', icon:'bi-briefcase',       label:'포트폴리오',   color:'#60a5fa' },
  { to:'/backtest',           icon:'bi-skip-backward',   label:'백테스트',     color:'#34d399' },
  { to:'/quant',              icon:'bi-bar-chart-steps', label:'퀀트',         color:'#f59e0b' },
  { to:'/stock_live',         icon:'bi-globe2',          label:'거시지표',     color:'#38bdf8' },
  { to:'/dart_alert',         icon:'bi-bell',            label:'공시 알림',    color:'#f472b6' },
];

export default function StockMain() {
  const { user } = useAuth();
  const [recommend, setRecommend] = useState([]);
  const [holdings,  setHoldings]  = useState([]);
  const [aiSummary, setAiSummary] = useState(null);

  useEffect(() => {
    api.get('/recommend/json').then(r => {
      const daily = r.data?.daily;
      setRecommend(Array.isArray(daily) ? daily.slice(0, 5) : []);
    }).catch(() => {});
    if (user) api.get('/stock/holdings').then(r => setHoldings(r.data?.holdings || [])).catch(() => {});
    api.get('/reports/latest').then(r => { if (r.data?.ok) setAiSummary(r.data); }).catch(() => {});
  }, [user]);

  const totalValue = holdings.reduce((s, h) => s + (h.eval_amount || h.avg_price * h.quantity || 0), 0);
  const totalProfit = holdings.reduce((s, h) => s + (h.profit || 0), 0);

  return (
    <StockLayout title="홈 대시보드">
      <div style={{ marginBottom:24 }}>
        <h2 style={{ fontSize:'1.1rem', fontWeight:700, color:'var(--fg-1)', marginBottom:4 }}>
          안녕하세요{user ? `, ${user.user_name}님` : ''} 👋
        </h2>
        <p style={{ fontSize:'0.83rem', color:'var(--fg-3)', margin:0 }}>오늘의 주식 현황을 확인하세요.</p>
      </div>

      {user && holdings.length > 0 && (
        <div style={{ display:'grid', gap:12, gridTemplateColumns:'repeat(auto-fill, minmax(180px,1fr))', marginBottom:24 }}>
          <StatCard title="총 평가금액" value={`₩${totalValue.toLocaleString('ko')}`} icon="bi-wallet2" color="var(--accent)"/>
          <StatCard title="총 손익" value={`${totalProfit >= 0 ? '+' : ''}₩${totalProfit.toLocaleString('ko')}`}
            icon="bi-graph-up" color={totalProfit >= 0 ? 'var(--up)' : 'var(--down)'}/>
          <StatCard title="보유 종목" value={holdings.length} sub="종목" icon="bi-briefcase"/>
        </div>
      )}

      {/* 빠른 이동 */}
      <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'18px 20px', marginBottom:20 }}>
        <div style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)', marginBottom:14 }}>빠른 이동</div>
        <div style={{ display:'grid', gap:8, gridTemplateColumns:'repeat(auto-fill, minmax(130px,1fr))' }}>
          {NAV_SHORTCUTS.map(n => (
            <Link key={n.to} to={n.to} style={{ textDecoration:'none', background:'var(--bg-3)', border:'1px solid var(--line-1)', borderRadius:'var(--r-2)', padding:'10px 12px', display:'flex', alignItems:'center', gap:8, transition:'border-color 0.15s' }}>
              <i className={`bi ${n.icon}`} style={{ fontSize:'1rem', color: n.color }}/>
              <span style={{ fontSize:'0.8rem', fontWeight:600, color:'var(--fg-1)' }}>{n.label}</span>
            </Link>
          ))}
        </div>
      </div>

      {/* AI 시장 요약 */}
      {aiSummary && (
        <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'18px 20px', marginBottom:20 }}>
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:10 }}>
            <span style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)' }}>
              <i className="bi bi-robot" style={{ marginRight:6, color:'var(--accent)' }}/>AI 시장 요약
            </span>
            <Link to="/market_reports" style={{ fontSize:'0.75rem', color:'var(--accent)', textDecoration:'none' }}>전체 보고서 →</Link>
          </div>
          <div style={{ fontSize:'0.72rem', color:'var(--fg-3)', marginBottom:8, fontFamily:'var(--font-mono)' }}>
            {aiSummary.report_date} · {aiSummary.report_type === 'daily' ? '일간' : aiSummary.report_type === 'weekly' ? '주간' : '월간'} 보고서
          </div>
          <p style={{ fontSize:'0.82rem', color:'var(--fg-2)', margin:0, lineHeight:1.6,
            overflow:'hidden', display:'-webkit-box', WebkitLineClamp:2, WebkitBoxOrient:'vertical' }}>
            {condenseSummary(aiSummary.summary || aiSummary.content)}
          </p>
        </div>
      )}

      {/* AI 추천 미리보기 */}
      {recommend.length > 0 && (
        <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'18px 20px' }}>
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:14 }}>
            <span style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)' }}>
              <i className="bi bi-stars" style={{ marginRight:6, color:'var(--accent)' }}/>오늘의 AI 추천
            </span>
            <Link to="/recommend" style={{ fontSize:'0.75rem', color:'var(--accent)', textDecoration:'none' }}>전체보기 →</Link>
          </div>
          <div style={{ display:'grid', gap:6 }}>
            {recommend.map((r, i) => (
              <div key={r.code} style={{ display:'flex', alignItems:'center', gap:12, padding:'8px 10px', background:'var(--bg-3)', borderRadius:'var(--r-2)' }}>
                <span style={{ width:20, height:20, borderRadius:'50%', background:'var(--accent)', color:'#fff', fontSize:'0.68rem', fontWeight:800, display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0 }}>{i+1}</span>
                <div style={{ flex:1 }}>
                  <div style={{ fontWeight:700, fontSize:'0.83rem', color:'var(--fg-1)' }}>{r.name}</div>
                  <div style={{ fontSize:'0.7rem', color:'var(--fg-3)', fontFamily:'var(--font-mono)' }}>{r.code}</div>
                </div>
                {r.score != null && <span style={{ fontSize:'0.72rem', fontFamily:'var(--font-mono)', fontWeight:700, color:'var(--accent)' }}>{r.score.toFixed(2)}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </StockLayout>
  );
}
