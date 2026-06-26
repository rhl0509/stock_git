import React, { useRef, useEffect } from 'react';
import { NavLink, useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';
import { useTheme } from '../context/ThemeContext.jsx';
import api from '../api/index.js';

export default function Sidebar({ open, onClose }) {
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [kiwoomConnected, setKiwoomConnected] = React.useState(false);
  const [kiwoomLoading, setKiwoomLoading]     = React.useState(false);
  const [kiwoomError, setKiwoomError]         = React.useState('');
  const [recPassActive, setRecPassActive]     = React.useState(false);
  const [recGate, setRecGate]                 = React.useState(false);
  const menuRef = useRef(null);

  // 추천 등급(premium) 사용 가능 여부. ai_access 가 없으면(구버전 응답) 허용해 서버 판정에 맡긴다.
  const canRecommend = !user?.ai_access || user.ai_access.recommend_pass !== false;

  useEffect(() => {
    if (!menuOpen) return;
    const handler = e => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [menuOpen]);

  useEffect(() => {
    if (!user) return;
    api.get('/api/kiwoom/status').then(r => setKiwoomConnected(r.data.connected)).catch(() => {});
  }, [user]);

  useEffect(() => {
    if (!user) { setRecPassActive(false); return; }
    const load = () => api.get('/api/recommend-pass/status')
      .then(r => setRecPassActive(!!r.data.active)).catch(() => {});
    load();
    document.addEventListener('recommendPassChanged', load);
    return () => document.removeEventListener('recommendPassChanged', load);
  }, [user]);

  const handleKiwoomLogin = async () => {
    setKiwoomLoading(true);
    setKiwoomError('');
    try {
      await api.post('/api/kiwoom/login', {}, { timeout: 120_000 });
      const r = await api.get('/api/kiwoom/status');
      setKiwoomConnected(r.data.connected);
      if (!r.data.connected) setKiwoomError('연결됐으나 상태 확인 실패');
    } catch (err) {
      const msg = err.response?.data?.error || err.message || '로그인 실패';
      setKiwoomError(msg);
    }
    setKiwoomLoading(false);
  };

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  const claudeBadge = (
    <span style={{
      marginLeft: 'auto', fontSize: '0.58rem', fontWeight: 700,
      background: 'linear-gradient(135deg,#8b5cf6,#6366f1)',
      color: '#fff', borderRadius: 4, padding: '1px 5px',
      letterSpacing: '0.03em', flexShrink: 0,
    }}>AI</span>
  );

  const link = (to, icon, label, useClaude = false) => (
    <li key={to}>
      <NavLink to={to} className={({ isActive }) => 'sidebar-nav-link' + (isActive ? ' active' : '')} onClick={onClose}>
        <i className={`bi ${icon}`}></i>{label}{useClaude && claudeBadge}
      </NavLink>
    </li>
  );

  return (
    <>
      <aside className={`sidebar${open ? ' active' : ''}`} id="sidebar">
        <NavLink to="/stock_main" className="sidebar-logo" onClick={onClose}>
          <div className="logo-mark">주</div>
          <div>
            <div className="logo-text">GAGYE</div>
            <div className="logo-sub">주식 시장</div>
          </div>
        </NavLink>

        <div className="nav-section">
          <span className="nav-section-label">시장</span>
          <ul className="list-unstyled mb-0">
            {link('/stock_live',         'bi-graph-up-arrow','실시간 시세')}
            {link('/trade_stats',        'bi-boxes',         '수출입 동향')}
          </ul>
          <span className="nav-section-label" style={{ marginTop: 14 }}>종목</span>
          <ul className="list-unstyled mb-0">
            {link('/stock_detail',   'bi-zoom-in',       '종목 상세')}
            {link('/financial',      'bi-graph-up',      '기업실적분석')}
            {link('/stock_compare_v2','bi-bar-chart-steps','종목 비교')}
          </ul>

          {user && (<>
            <span className="nav-section-label" style={{ marginTop: 14 }}>포트폴리오</span>
            <ul className="list-unstyled mb-0">
              {link('/stock_portfolio_kr','bi-briefcase',      '포트폴리오')}
              {link('/watchlist',         'bi-bookmark-star',  '관심 종목')}
              {link('/paper_trading',     'bi-bullseye',       '가상매매')}
              {link('/portfolio_perf',    'bi-bar-chart-fill', '월별 성과')}
              {link('/dividend',          'bi-calendar2-check','배당 캘린더')}
              {link('/portfolio_opt',     'bi-pie-chart',      '포트폴리오 최적화')}
              {link('/risk',              'bi-shield-check',   '리스크 분석')}
            </ul>
            <span className="nav-section-label" style={{ marginTop: 14 }}>스크리닝</span>
            <ul className="list-unstyled mb-0">
              {link('/stock_filter',        'bi-funnel',       '종목 필터')}
              {link('/stock_theme_filter',  'bi-tags',         '테마 필터')}
              {link('/sector_heatmap',      'bi-grid-3x3',     '섹터 히트맵')}
              {link('/screener_52week',     'bi-bullseye',     '52주 신고가/신저가')}
              {link('/stock_kiwoom_filter', 'bi-sliders',      '키움 조건검색')}
            </ul>
            <span className="nav-section-label" style={{ marginTop: 14 }}>AI · 전략</span>
            <ul className="list-unstyled mb-0">
              {canRecommend ? (
                <li key="/recommend">
                  <NavLink to="/recommend" className={({ isActive }) => 'sidebar-nav-link' + (isActive ? ' active' : '')} onClick={onClose}>
                    <i className="bi bi-stars"></i><span>AI 추천</span>
                    {recPassActive && <span title="오늘 활성" style={{ marginLeft: 'auto', width: 7, height: 7, borderRadius: '50%', background: 'var(--up)', flexShrink: 0 }} />}
                  </NavLink>
                </li>
              ) : (
                <li key="/recommend">
                  <button type="button" className="sidebar-nav-link" onClick={() => setRecGate(true)}>
                    <i className="bi bi-stars"></i><span>AI 추천</span>
                    <i className="bi bi-lock-fill" style={{ marginLeft: 'auto', fontSize: '0.7rem', opacity: 0.55, flexShrink: 0 }} />
                  </button>
                </li>
              )}
              <li>
                <button className="sidebar-nav-link" onClick={() => { document.dispatchEvent(new CustomEvent('openAdvisor')); onClose?.(); }}>
                  <i className="bi bi-lightbulb"></i><span>매수/매도 분석</span>{claudeBadge}
                </button>
              </li>
              {link('/backtest',            'bi-skip-backward',   '백테스트')}
              {link('/quant',               'bi-bar-chart-steps', '퀀트 트레이딩')}
              {link('/workflows',           'bi-lightning-charge','자동화 워크플로')}
              {link('/train_report',        'bi-clipboard-data',  '학습 리포트')}
              {link('/pipeline',            'bi-diagram-3',       '파이프라인')}
            </ul>
            <span className="nav-section-label" style={{ marginTop: 14 }}>리서치 · 알림</span>
            <ul className="list-unstyled mb-0">
              {link('/news',                'bi-newspaper',        '뉴스')}
              {link('/market_reports',      'bi-journal-richtext', '시장 보고서')}
              {link('/earnings_calendar',   'bi-calendar-event',   '실적 캘린더')}
              {link('/price_alert',         'bi-bell-fill',        '가격 알림')}
              {link('/dart_alert',          'bi-bell',             '공시 알림')}
            </ul>
          </>)}
        </div>

        <div className="sidebar-user" style={{ position: 'relative' }} ref={menuRef}>
          {user ? (
            <>
              {menuOpen && (
                <div style={{ position: 'absolute', bottom: '100%', left: 10, right: 10,
                              background: 'var(--bg-2)', border: '1px solid var(--line-2)',
                              borderRadius: 'var(--r-3)', padding: '4px 0',
                              boxShadow: 'var(--menu-shadow)', zIndex: 10, marginBottom: 6 }}>
                  <Link to="/my-page" onClick={() => { setMenuOpen(false); onClose?.(); }}
                    style={{ display:'flex', alignItems:'center', gap:9, padding:'9px 13px', fontSize:'0.82rem', fontWeight:500, color:'var(--fg-2)', textDecoration:'none', width:'100%' }}
                    className="session-menu-item">
                    <i className="bi bi-person-gear"></i>
                    <span>내 정보 수정</span>
                  </Link>
                  <button className="session-menu-item" disabled={kiwoomLoading}
                    style={{ display:'flex', flexDirection:'column', alignItems:'flex-start', gap:9, padding:'9px 13px', fontSize:'0.82rem', fontWeight:500, color: kiwoomConnected ? 'var(--up)' : kiwoomError ? 'var(--down)' : 'var(--fg-2)', cursor:'pointer', border:'none', background:'transparent', width:'100%', textAlign:'left', opacity: kiwoomLoading ? 0.6 : 1 }}
                    onClick={handleKiwoomLogin}>
                    <div style={{ display:'flex', alignItems:'center', gap:9 }}>
                      <i className={`bi ${kiwoomConnected ? 'bi-plug-fill' : kiwoomError ? 'bi-plug' : 'bi-plug'}`}></i>
                      <span>{kiwoomLoading ? '연결 중 (팝업 확인)...' : kiwoomConnected ? '키움 API 연결됨' : '키움 API 로그인'}</span>
                    </div>
                    {kiwoomError && <div style={{ fontSize:'0.7rem', color:'var(--down)', marginLeft:22, marginTop:2, wordBreak:'break-all', whiteSpace:'pre-wrap' }}>{kiwoomError}</div>}
                  </button>
                  <button className="session-menu-item" style={{ display:'flex', alignItems:'center', gap:9, padding:'9px 13px', fontSize:'0.82rem', fontWeight:500, color:'var(--fg-2)', cursor:'pointer', border:'none', background:'transparent', width:'100%', textAlign:'left' }} onClick={toggle}>
                    <i className={`bi ${theme === 'dark' ? 'bi-sun' : 'bi-moon'}`}></i>
                    <span>{theme === 'dark' ? '라이트 모드' : '다크 모드'}</span>
                  </button>
                  <Link to="/alert_config" onClick={() => { setMenuOpen(false); onClose?.(); }}
                    style={{ display:'flex', alignItems:'center', gap:9, padding:'9px 13px', fontSize:'0.82rem', fontWeight:500, color:'var(--fg-2)', textDecoration:'none', width:'100%' }}
                    className="session-menu-item">
                    <i className="bi bi-gear"></i>
                    <span>알림 설정</span>
                  </Link>
                  <div style={{ height: 1, background: 'var(--line-1)', margin: '3px 0' }}/>
                  <button className="session-menu-item" style={{ display:'flex', alignItems:'center', gap:9, padding:'9px 13px', fontSize:'0.82rem', fontWeight:500, color:'#f87171', cursor:'pointer', border:'none', background:'transparent', width:'100%', textAlign:'left' }} onClick={handleLogout}>
                    <i className="bi bi-box-arrow-right"></i> 로그아웃
                  </button>
                </div>
              )}
              <button className="user-card" style={{ border:'none' }} onClick={() => setMenuOpen(v => !v)}>
                <div className="user-avatar">{user.user_name?.[0] || '사'}</div>
                <div className="user-info">
                  <div className="user-name">{user.user_name}님</div>
                  <div className="user-role">personal · account</div>
                </div>
                <i className={`bi bi-chevron-${menuOpen ? 'down' : 'up'}`} style={{ color:'var(--fg-3)', fontSize:'0.75rem' }}></i>
              </button>
            </>
          ) : (
            <NavLink to="/login" className="user-card" onClick={onClose}>
              <div className="user-avatar" style={{ background:'var(--bg-3)', borderColor:'var(--line-2)' }}>
                <i className="bi bi-person" style={{ fontSize:'0.9rem', color:'var(--fg-3)' }}></i>
              </div>
              <div className="user-info">
                <div className="user-name">로그인이 필요해요</div>
                <div className="user-role">click to sign in</div>
              </div>
              <i className="bi bi-chevron-right" style={{ color:'var(--fg-3)', fontSize:'0.75rem' }}></i>
            </NavLink>
          )}
        </div>
      </aside>

      {recGate && (
        <div onClick={() => setRecGate(false)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 2000,
                   display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div onClick={e => e.stopPropagation()}
            style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)',
                     padding: 24, maxWidth: 380, width: '100%', boxShadow: 'var(--menu-shadow, 0 8px 30px rgba(0,0,0,0.2))' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
              <i className="bi bi-stars" style={{ fontSize: '1.3rem', color: 'var(--accent)' }} />
              <div style={{ fontSize: '1rem', fontWeight: 800, color: 'var(--fg-1)' }}>프리미엄 등급 기능</div>
            </div>
            <div style={{ fontSize: '0.86rem', color: 'var(--fg-2)', lineHeight: 1.65, marginBottom: 12 }}>
              <b style={{ color: 'var(--fg-1)' }}>AI 추천</b>은 <b style={{ color: 'var(--accent)' }}>프리미엄</b> 등급부터 이용할 수 있어요.
            </div>
            <div style={{ fontSize: '0.78rem', color: 'var(--fg-3)', lineHeight: 1.65, marginBottom: 18,
                          padding: '10px 12px', background: 'var(--bg-3)', borderRadius: 'var(--r-2)' }}>
              프리미엄 구독 시 이용할 수 있어요. (구독 기능 준비 중)
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="button" className="btn" onClick={() => setRecGate(false)}
                style={{ flex: 1, background: 'var(--bg-3)', border: '1px solid var(--line-1)', color: 'var(--fg-2)' }}>
                닫기
              </button>
              <button type="button" className="btn btn-primary"
                onClick={() => { setRecGate(false); onClose?.(); navigate('/my-page'); }}
                style={{ flex: 1 }}>
                내 정보로 이동
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
