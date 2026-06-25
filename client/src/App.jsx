import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext.jsx';
import { ThemeProvider } from './context/ThemeContext.jsx';

const Login           = lazy(() => import('./pages/Login.jsx'));
const Register        = lazy(() => import('./pages/Register.jsx'));
const FindAccount     = lazy(() => import('./pages/FindAccount.jsx'));
const ResetPassword   = lazy(() => import('./pages/ResetPassword.jsx'));
const MyPage          = lazy(() => import('./pages/MyPage.jsx'));
const StockDashboard  = lazy(() => import('./pages/StockDashboard.jsx'));
const StockLive       = lazy(() => import('./pages/StockLive.jsx'));
const StockDetail     = lazy(() => import('./pages/StockDetail.jsx'));
const StockCompareV2  = lazy(() => import('./pages/StockCompareV2.jsx'));
const Financial       = lazy(() => import('./pages/Financial.jsx'));
const StockPortfolioKr= lazy(() => import('./pages/StockPortfolioKr.jsx'));
const PortfolioOpt    = lazy(() => import('./pages/PortfolioOpt.jsx'));
const PortfolioPerf   = lazy(() => import('./pages/PortfolioPerf.jsx'));
const RiskDashboard   = lazy(() => import('./pages/RiskDashboard.jsx'));
const PaperTrading    = lazy(() => import('./pages/PaperTrading.jsx'));
const StockFilter     = lazy(() => import('./pages/StockFilter.jsx'));
const StockKiwoomFilter= lazy(() => import('./pages/StockKiwoomFilter.jsx'));
const StockThemeFilter= lazy(() => import('./pages/StockThemeFilter.jsx'));
const Recommend       = lazy(() => import('./pages/Recommend.jsx'));
const RecommendAbs    = lazy(() => import('./pages/RecommendAbs.jsx'));
const RecommendHistory= lazy(() => import('./pages/RecommendHistory.jsx'));
const Backtest        = lazy(() => import('./pages/Backtest.jsx'));
const Quant           = lazy(() => import('./pages/Quant.jsx'));
const News            = lazy(() => import('./pages/News.jsx'));
const MorningNews     = lazy(() => import('./pages/MorningNews.jsx'));
const DartAlert       = lazy(() => import('./pages/DartAlert.jsx'));
const PriceAlert      = lazy(() => import('./pages/PriceAlert.jsx'));
const AlertConfig     = lazy(() => import('./pages/AlertConfig.jsx'));
const Tax             = lazy(() => import('./pages/Tax.jsx'));
const NotifyHistory   = lazy(() => import('./pages/NotifyHistory.jsx'));
const TrainReport     = lazy(() => import('./pages/TrainReport.jsx'));
const Pipeline        = lazy(() => import('./pages/Pipeline.jsx'));
const TradeStats      = lazy(() => import('./pages/TradeStats.jsx'));
const Reports         = lazy(() => import('./pages/Reports.jsx'));
const ReportDetail    = lazy(() => import('./pages/ReportDetail.jsx'));
const AgentDashboard  = lazy(() => import('./pages/AgentDashboard.jsx'));
const SectorHeatmap   = lazy(() => import('./pages/SectorHeatmap.jsx'));
const DividendCalendar= lazy(() => import('./pages/DividendCalendar.jsx'));
const Watchlist       = lazy(() => import('./pages/Watchlist.jsx'));
const Screener52Week  = lazy(() => import('./pages/Screener52Week.jsx'));
const EarningsCalendar= lazy(() => import('./pages/EarningsCalendar.jsx'));
const Workflow        = lazy(() => import('./pages/Workflow.jsx'));

function PageFallback() {
  return (
    <div style={{ display:'flex', alignItems:'center', justifyContent:'center', minHeight:'60vh', color:'var(--fg-3)', fontSize:'0.85rem' }}>
      <div style={{ textAlign:'center' }}>
        <div className="spinner" style={{ margin:'0 auto 12px' }}/>
        Loading...
      </div>
    </div>
  );
}

function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <PageFallback />;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <Suspense fallback={<PageFallback />}>
            <Routes>
              <Route path="/login"        element={<Login />} />
              <Route path="/register"    element={<Register />} />
              <Route path="/find-account" element={<FindAccount />} />
              <Route path="/reset-password" element={<ResetPassword />} />
              <Route path="/my-page"     element={<ProtectedRoute><MyPage /></ProtectedRoute>} />

              {/* Public pages */}
              <Route path="/stock_dashboard"   element={<StockDashboard />} />
              <Route path="/stock_live"        element={<StockLive />} />
              <Route path="/stock_detail"      element={<StockDetail />} />
              <Route path="/stock_compare"     element={<Navigate to="/stock_compare_v2" replace />} />
              <Route path="/stock_compare_v2"  element={<StockCompareV2 />} />
              <Route path="/financial"         element={<Financial />} />
              <Route path="/trade_stats"       element={<TradeStats />} />
              <Route path="/macro_dashboard"   element={<Navigate to="/stock_live" replace />} />
              <Route path="/news"              element={<News />} />

              {/* Protected pages */}
              <Route path="/stock_portfolio_kr" element={<ProtectedRoute><StockPortfolioKr /></ProtectedRoute>} />
              <Route path="/portfolio_opt"      element={<ProtectedRoute><PortfolioOpt /></ProtectedRoute>} />
              <Route path="/portfolio_perf"     element={<ProtectedRoute><PortfolioPerf /></ProtectedRoute>} />
              <Route path="/risk"               element={<ProtectedRoute><RiskDashboard /></ProtectedRoute>} />
              <Route path="/paper_trading"      element={<ProtectedRoute><PaperTrading /></ProtectedRoute>} />
              <Route path="/stock_filter"       element={<ProtectedRoute><StockFilter /></ProtectedRoute>} />
              <Route path="/stock_kiwoom_filter" element={<ProtectedRoute><StockKiwoomFilter /></ProtectedRoute>} />
              <Route path="/stock_theme_filter" element={<ProtectedRoute><StockThemeFilter /></ProtectedRoute>} />
              <Route path="/recommend"          element={<ProtectedRoute><Recommend /></ProtectedRoute>} />
              <Route path="/recommend_abs"      element={<ProtectedRoute><Recommend /></ProtectedRoute>} />
              <Route path="/stock_recommend_history" element={<ProtectedRoute><RecommendHistory /></ProtectedRoute>} />
              <Route path="/stock_ai_performance" element={<Navigate to="/train_report" replace />} />
              <Route path="/backtest"           element={<ProtectedRoute><Backtest /></ProtectedRoute>} />
              <Route path="/quant"              element={<ProtectedRoute><Quant /></ProtectedRoute>} />
              <Route path="/morning_news"       element={<Navigate to="/news" replace />} />
              <Route path="/dart_alert"         element={<ProtectedRoute><DartAlert /></ProtectedRoute>} />
              <Route path="/price_alert"        element={<ProtectedRoute><PriceAlert /></ProtectedRoute>} />
              <Route path="/alert_config"       element={<ProtectedRoute><AlertConfig /></ProtectedRoute>} />
              <Route path="/tax"                element={<ProtectedRoute><Tax /></ProtectedRoute>} />
              <Route path="/notify_history"     element={<ProtectedRoute><NotifyHistory /></ProtectedRoute>} />
              <Route path="/train_report"       element={<ProtectedRoute><TrainReport /></ProtectedRoute>} />
              <Route path="/pipeline"           element={<ProtectedRoute><Pipeline /></ProtectedRoute>} />
              <Route path="/market_reports"     element={<ProtectedRoute><Reports /></ProtectedRoute>} />
              <Route path="/market_reports/:id" element={<ProtectedRoute><ReportDetail /></ProtectedRoute>} />
              <Route path="/agent_dashboard"   element={<ProtectedRoute><AgentDashboard /></ProtectedRoute>} />
              <Route path="/sector_heatmap"   element={<SectorHeatmap />} />
              <Route path="/dividend"         element={<ProtectedRoute><DividendCalendar /></ProtectedRoute>} />
              <Route path="/watchlist"        element={<ProtectedRoute><Watchlist /></ProtectedRoute>} />
              <Route path="/screener_52week"  element={<ProtectedRoute><Screener52Week /></ProtectedRoute>} />
              <Route path="/earnings_calendar" element={<ProtectedRoute><EarningsCalendar /></ProtectedRoute>} />
              <Route path="/workflows"        element={<ProtectedRoute><Workflow /></ProtectedRoute>} />

              <Route path="/" element={<Navigate to="/stock_live" replace />} />
              <Route path="*" element={<Navigate to="/stock_live" replace />} />
            </Routes>
          </Suspense>
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
}
