import React, { useState, useEffect } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

const STRATEGIES = [
  { key: 'rsi',      label: 'RSI 역추세',      desc: 'RSI < 30 과매도 구간 매수' },
  { key: 'macd',     label: 'MACD 크로스',      desc: 'MACD 골든크로스 진입' },
  { key: 'ma',       label: '이동평균 크로스',   desc: 'MA5 > MA20 골든크로스 진입' },
  { key: 'volume',   label: '거래량 급등',       desc: '20일 평균 거래량 2배 이상' },
  { key: 'bollinger',label: '볼린저 밴드',       desc: '하단 밴드 이탈 반등 매수' },
];

const PERIODS = [
  { label: '6개월', months: 6 },
  { label: '1년',   months: 12 },
  { label: '2년',   months: 24 },
  { label: '3년',   months: 36 },
];

function MetricCard({ label, value, sub, good }) {
  return (
    <div style={{ background: 'var(--bg-3)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-2)', padding: '12px 14px' }}>
      <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: '1.15rem', fontWeight: 800, fontFamily: 'var(--font-mono)',
        color: good == null ? 'var(--fg-1)' : good ? 'var(--up)' : 'var(--down)' }}>{value}</div>
      {sub && <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)', marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

export default function Backtest() {
  const [code,      setCode]      = useState('005930');
  const [strategy,  setStrategy]  = useState('ma');
  const [sl,        setSl]        = useState(5);
  const [tp,        setTp]        = useState(10);
  const [period,    setPeriod]    = useState(24);
  const [result,    setResult]    = useState(null);
  const [loading,   setLoading]   = useState(false);
  const [error,     setError]     = useState('');
  const [codes,     setCodes]     = useState([]);
  const [codeInput, setCodeInput] = useState('005930');

  useEffect(() => {
    api.get('/backtest/codes')
      .then(r => setCodes(r.data || []))
      .catch(() => {});
  }, []);

  const run = async () => {
    const c = codeInput.trim();
    if (!c) return;
    setCode(c);
    setLoading(true); setError(''); setResult(null);

    const end   = new Date();
    const start = new Date();
    start.setMonth(start.getMonth() - period);

    try {
      const r = await api.post('/backtest/run', {
        code: c,
        strategy,
        stop_pct: sl,
        target_pct: tp,
        start: start.toISOString().slice(0, 10),
        end:   end.toISOString().slice(0, 10),
      });
      setResult(r.data);
    } catch (e) {
      setError(e.response?.data?.error || '백테스트 실패');
    }
    setLoading(false);
  };

  const m   = result?.metrics;
  const strat = STRATEGIES.find(s => s.key === strategy);

  return (
    <StockLayout title="백테스트">

      {/* 설정 패널 */}
      <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '20px', marginBottom: 20 }}>
        <div style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--fg-1)', marginBottom: 16 }}>백테스트 설정</div>

        <div style={{ display: 'grid', gap: 14, gridTemplateColumns: '1fr 1fr 1fr' }}>
          {/* 종목 코드 */}
          <div>
            <label style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--fg-2)', display: 'block', marginBottom: 5 }}>종목 코드</label>
            <div style={{ display: 'flex', gap: 6 }}>
              <input className="form-control" value={codeInput} onChange={e => setCodeInput(e.target.value)}
                placeholder="예: 005930" onKeyDown={e => e.key === 'Enter' && run()}
                list="code-list" style={{ flex: 1 }} />
              <datalist id="code-list">
                {codes.slice(0, 100).map(c => <option key={c} value={c} />)}
              </datalist>
            </div>
            <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)', marginTop: 3 }}>
              {codes.length > 0 ? `${codes.length}개 종목 데이터 있음` : '데이터 로딩 중...'}
            </div>
          </div>

          {/* 전략 선택 */}
          <div>
            <label style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--fg-2)', display: 'block', marginBottom: 5 }}>전략</label>
            <select className="form-select" value={strategy} onChange={e => setStrategy(e.target.value)}>
              {STRATEGIES.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
            {strat && <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)', marginTop: 3 }}>{strat.desc}</div>}
          </div>

          {/* 기간 */}
          <div>
            <label style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--fg-2)', display: 'block', marginBottom: 5 }}>백테스트 기간</label>
            <div style={{ display: 'flex', gap: 5 }}>
              {PERIODS.map(p => (
                <button key={p.months} onClick={() => setPeriod(p.months)}
                  style={{ flex: 1, padding: '5px 4px', fontSize: '0.75rem', border: `1px solid ${period === p.months ? 'var(--accent)' : 'var(--line-2)'}`,
                    background: period === p.months ? 'var(--accent)' : 'var(--bg-3)',
                    color: period === p.months ? '#fff' : 'var(--fg-2)',
                    borderRadius: 'var(--r-1)', cursor: 'pointer', fontWeight: period === p.months ? 700 : 400 }}>
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* 손절 */}
          <div>
            <label style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--fg-2)', display: 'block', marginBottom: 5 }}>
              손절 기준 <span style={{ color: 'var(--down)', fontFamily: 'var(--font-mono)' }}>{sl}%</span>
            </label>
            <input type="range" min={1} max={20} value={sl} onChange={e => setSl(+e.target.value)}
              style={{ width: '100%', accentColor: 'var(--down)' }} />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.65rem', color: 'var(--fg-3)', marginTop: 2 }}>
              <span>1%</span><span>20%</span>
            </div>
          </div>

          {/* 익절 */}
          <div>
            <label style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--fg-2)', display: 'block', marginBottom: 5 }}>
              익절 기준 <span style={{ color: 'var(--up)', fontFamily: 'var(--font-mono)' }}>{tp}%</span>
            </label>
            <input type="range" min={2} max={50} value={tp} onChange={e => setTp(+e.target.value)}
              style={{ width: '100%', accentColor: 'var(--up)' }} />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.65rem', color: 'var(--fg-3)', marginTop: 2 }}>
              <span>2%</span><span>50%</span>
            </div>
          </div>

          {/* 실행 버튼 */}
          <div style={{ display: 'flex', alignItems: 'flex-end' }}>
            <button className="btn btn-primary w-100" onClick={run} disabled={loading || !codeInput.trim()}>
              {loading
                ? <><span className="spinner-border spinner-border-sm me-2" role="status" />실행 중...</>
                : <><i className="bi bi-play-fill me-2" />백테스트 실행</>}
            </button>
          </div>
        </div>

        {error && (
          <div style={{ marginTop: 14, padding: '10px 14px', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 'var(--r-2)', fontSize: '0.82rem', color: '#ef4444' }}>
            <i className="bi bi-exclamation-triangle me-1" />{error}
          </div>
        )}
      </div>

      {/* 결과 */}
      {m && (
        <>
          {/* 요약 배너 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, padding: '10px 14px', background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-2)' }}>
            <div style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--fg-1)' }}>
              {code} — {strat?.label}
            </div>
            <div style={{ fontSize: '0.78rem', color: 'var(--fg-3)' }}>
              {period}개월 / 손절 {sl}% / 익절 {tp}%
            </div>
            <div style={{ marginLeft: 'auto', fontSize: '0.78rem', color: 'var(--fg-3)' }}>
              Buy&Hold: <span style={{ fontWeight: 700, color: (result.benchmark ?? 0) >= 0 ? 'var(--up)' : 'var(--down)' }}>
                {result.benchmark >= 0 ? '+' : ''}{result.benchmark?.toFixed(2)}%
              </span>
            </div>
          </div>

          {/* 메트릭 카드 */}
          <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', marginBottom: 20 }}>
            <MetricCard label="총 수익률" value={`${(m.total_return ?? 0) >= 0 ? '+' : ''}${m.total_return?.toFixed(2)}%`} good={(m.total_return ?? 0) >= 0} sub={`B&H ${result.benchmark >= 0 ? '+' : ''}${result.benchmark?.toFixed(2)}%`} />
            <MetricCard label="평균 수익률" value={`${(m.avg_return ?? 0) >= 0 ? '+' : ''}${m.avg_return?.toFixed(2)}%`} good={(m.avg_return ?? 0) >= 0} />
            <MetricCard label="최대 낙폭" value={`${m.max_drawdown != null ? m.max_drawdown.toFixed(2) : '-'}%`} good={false} />
            <MetricCard label="승률" value={`${m.win_rate != null ? m.win_rate.toFixed(1) : '-'}%`} good={(m.win_rate ?? 0) >= 50} />
            <MetricCard label="총 거래 수" value={m.n_trades} />
          </div>

          {/* 거래 내역 */}
          {result.trades?.length > 0 ? (
            <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'hidden' }}>
              <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--line-1)', fontWeight: 700, fontSize: '0.87rem', color: 'var(--fg-1)' }}>
                거래 내역 ({result.trades.length}건)
              </div>
              <div style={{ overflowX: 'auto', maxHeight: 400 }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                  <thead>
                    <tr style={{ background: 'var(--bg-3)', position: 'sticky', top: 0 }}>
                      {['#', '매수일', '매도일', '매수가', '매도가', '수익률', '사유'].map(h => (
                        <th key={h} style={{ padding: '8px 12px', fontWeight: 600, color: 'var(--fg-2)', textAlign: h === '#' || h === '사유' ? 'center' : 'right', whiteSpace: 'nowrap' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.trades.map((t, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid var(--line-1)', background: i % 2 ? 'var(--bg-1)' : 'transparent' }}>
                        <td style={{ padding: '7px 12px', textAlign: 'center', color: 'var(--fg-3)', fontSize: '0.72rem', fontFamily: 'var(--font-mono)' }}>{i + 1}</td>
                        <td style={{ padding: '7px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{t.entry_date}</td>
                        <td style={{ padding: '7px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{t.exit_date}</td>
                        <td style={{ padding: '7px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{t.entry_price?.toLocaleString('ko')}</td>
                        <td style={{ padding: '7px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{t.exit_price?.toLocaleString('ko')}</td>
                        <td style={{ padding: '7px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 700,
                          color: t.return_pct >= 0 ? 'var(--up)' : 'var(--down)' }}>
                          {t.return_pct >= 0 ? '+' : ''}{t.return_pct?.toFixed(2)}%
                        </td>
                        <td style={{ padding: '7px 12px', textAlign: 'center', color: 'var(--fg-3)', fontSize: '0.75rem' }}>
                          {t.exit_reason === 'target' ? '✓ 익절' : t.exit_reason === 'stop' ? '✗ 손절' : t.exit_reason === 'force' ? '강제' : '타임아웃'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div style={{ padding: '28px 24px', border: '1px solid var(--line-1)', borderRadius: 'var(--r-2)', background: 'var(--bg-2)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
                <i className="bi bi-exclamation-circle" style={{ fontSize: '1.2rem', color: 'var(--fg-3)', opacity: 0.5 }} />
                <span style={{ fontWeight: 600, fontSize: '0.88rem', color: 'var(--fg-2)' }}>
                  {period}개월 기간 중 진입 신호가 없습니다.
                </span>
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--fg-3)', lineHeight: 1.7 }}>
                {strategy === 'rsi' && (
                  <p style={{ margin: '0 0 6px' }}>
                    <strong>RSI 역추세</strong> 전략은 RSI&lt;30 과매도 구간에서만 매수 신호가 발생합니다.
                    최근 상승장에서는 RSI가 30 아래로 내려가지 않아 신호가 없을 수 있습니다.
                  </p>
                )}
                {strategy === 'bollinger' && (
                  <p style={{ margin: '0 0 6px' }}>
                    <strong>볼린저 밴드</strong> 전략은 하단 밴드(-2σ) 이탈 시에만 신호가 발생합니다.
                    추세가 강한 구간에서는 신호가 드뭅니다.
                  </p>
                )}
                <p style={{ margin: 0 }}>
                  <strong>권장:</strong>&nbsp;
                  {period < 24 && <span onClick={() => setPeriod(24)} style={{ cursor: 'pointer', color: 'var(--accent)', textDecoration: 'underline' }}>기간을 2년으로 늘리거나&nbsp;</span>}
                  {strategy !== 'ma' && <span onClick={() => setStrategy('ma')} style={{ cursor: 'pointer', color: 'var(--accent)', textDecoration: 'underline' }}>이동평균 크로스 전략을 시도해보세요.</span>}
                  {strategy === 'ma' && period >= 24 && <span>다른 종목 코드를 입력해보세요.</span>}
                </p>
              </div>
            </div>
          )}
        </>
      )}

      {!result && !loading && (
        <div style={{ textAlign: 'center', padding: '80px 0', color: 'var(--fg-3)' }}>
          <i className="bi bi-skip-backward" style={{ fontSize: '2.5rem', display: 'block', marginBottom: 12, opacity: 0.3 }} />
          <p style={{ fontSize: '0.85rem', margin: 0 }}>종목 코드와 전략을 선택하고 백테스트를 실행하세요.</p>
          <p style={{ fontSize: '0.75rem', marginTop: 6, opacity: 0.7 }}>
            {codes.length > 0 ? `${codes.length}개 종목의 과거 OHLCV 데이터 기반 시뮬레이션` : 'OHLCV 데이터 로딩 중...'}
          </p>
        </div>
      )}
    </StockLayout>
  );
}
