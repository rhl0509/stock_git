import React, { useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import Sidebar from '../components/Sidebar.jsx';
import IndexBar from '../components/IndexBar.jsx';
import AdvisorPanel from '../components/AdvisorPanel.jsx';
import api from '../api/index.js';

const HOUSEHOLD_URL = import.meta.env.VITE_HOUSEHOLD_URL || 'http://localhost:3010';

const BOTTOM_TABS = [
  { to: '/stock_live',        icon: 'bi-graph-up-arrow', label: '시세' },
  { to: '/stock_portfolio_kr',icon: 'bi-briefcase',      label: '포폴' },
  { to: '/news',              icon: 'bi-newspaper',      label: '뉴스' },
];

const AI_TAB = { to: '/recommend', icon: 'bi-stars', label: 'AI' };

export default function StockLayout({ title, children }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [advisorOpen, setAdvisorOpen] = useState(false);
  const [recPassActive, setRecPassActive] = useState(false);
  const location = useLocation();

  React.useEffect(() => {
    const h = () => setAdvisorOpen(true);
    document.addEventListener('openAdvisor', h);
    return () => document.removeEventListener('openAdvisor', h);
  }, []);

  React.useEffect(() => {
    const load = () => api.get('/api/recommend-pass/status')
      .then(r => setRecPassActive(!!r.data.active)).catch(() => {});
    load();
    document.addEventListener('recommendPassChanged', load);
    return () => document.removeEventListener('recommendPassChanged', load);
  }, []);

  const bottomTabs = recPassActive
    ? [BOTTOM_TABS[0], AI_TAB, ...BOTTOM_TABS.slice(1)]
    : BOTTOM_TABS;

  return (
    <div>
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className={`overlay${sidebarOpen ? ' active' : ''}`} onClick={() => setSidebarOpen(false)} />

      <AdvisorPanel open={advisorOpen} onClose={() => setAdvisorOpen(false)} />

      {/* 상단 NavBar */}
      <nav className="navbar-top" style={{ width:'100%' }}>
        <div style={{ display:'flex', alignItems:'center', gap:8, flex:1 }}>
          <button className="toggle-btn d-lg-none" onClick={() => setSidebarOpen(v => !v)}>
            <i className="bi bi-list"/>
          </button>
          <span className="page-title">{title || '주식 현황'}</span>
        </div>
        <div style={{ marginLeft:'auto', display:'flex', alignItems:'center', gap:8 }}>
          <a href={HOUSEHOLD_URL} style={{ textDecoration:'none', background:'var(--accent)', color:'#fff', border:'none', borderRadius:'var(--r-2)', fontSize:'0.78rem', fontWeight:700, padding:'6px 12px', display:'flex', alignItems:'center', gap:4, fontFamily:'var(--font-mono)' }}>
            <i className="bi bi-wallet2"/> 가계부
          </a>
        </div>
      </nav>

      <IndexBar />

      <div className="main-wrapper">
        <main className="main-content">
          <div className="row justify-content-center">
            <div className="col-12 col-xl-10">
              {children}
            </div>
          </div>
        </main>
      </div>

      {/* 모바일 하단 탭바 */}
      <nav className="bottom-tab">
        {bottomTabs.map(t => (
          <NavLink key={t.to} to={t.to} className={({ isActive }) => `bottom-tab-link${isActive ? ' active' : ''}`}>
            <i className={`bi ${t.icon}`}/>
            <div>{t.label}</div>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
