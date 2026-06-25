import React, { useState, useEffect, useRef } from 'react';
import api from '../api/index.js';

const ADVISOR_COST = 500;

export default function AdvisorPanel({ open, onClose }) {
  const [query, setQuery]       = useState('');
  const [suggestions, setSugg]  = useState([]);
  const [selected, setSelected] = useState(null);
  const [period, setPeriod]     = useState('중기(1~3개월)');
  const [hold, setHold]         = useState('미보유');
  const [avgPrice, setAvgPrice] = useState('');
  const [holdQty, setHoldQty]   = useState('');
  const [stopLoss, setStopLoss] = useState(10);
  const [buyType, setBuyType]   = useState('일괄매수');
  const [extra, setExtra]       = useState('');
  const [result, setResult]     = useState('');
  const [cost, setCost]         = useState(null);
  const [balance, setBalance]   = useState(null);
  const [err, setErr]           = useState('');
  const [loading, setLoading]   = useState(false);
  const resultRef = useRef(null);

  useEffect(() => {
    if (!query.trim()) { setSugg([]); return; }
    const t = setTimeout(() =>
      api.get('/search-stock-kr', { params: { q: query } })
        .then(r => setSugg(r.data || [])).catch(() => {}), 200);
    return () => clearTimeout(t);
  }, [query]);

  const runAdvisor = async () => {
    if (!selected || loading) return;
    setLoading(true); setResult(''); setErr(''); setCost(null); setBalance(null);
    try {
      const r = await api.post('/stock/advisor/analyze', {
        code: selected.code, name: selected.name,
        user_input: {
          period,
          hold_type: hold,
          holding: { avg_price: Number(avgPrice) || 0, quantity: Number(holdQty) || 0 },
          stop_loss_pct: Number(stopLoss),
          buy_type: buyType,
          extra,
        },
      });
      setResult(r.data.analysis || '');
      setCost(r.data.cost); setBalance(r.data.balance);
    } catch (e) {
      const d = e.response?.data;
      if (e.response?.status === 402)
        setErr(`${d?.error || '크레딧이 부족합니다.'} (보유 ${d?.balance ?? 0}C / 필요 ${d?.cost ?? 0}C)`);
      else
        setErr(d?.error || 'AI 분석에 실패했습니다.');
    }
    setLoading(false);
  };

  const toggle = (val, setter) => setter(val);

  return (
    <>
      <div className={`advisor-overlay${open ? ' open' : ''}`} onClick={onClose}/>
      <div className={`advisor-panel${open ? ' open' : ''}`}>
        <div style={{ padding:'14px 16px', borderBottom:'1px solid var(--line-1)', display:'flex', alignItems:'center', justifyContent:'space-between', flexShrink:0 }}>
          <h6 style={{ margin:0, fontWeight:700, fontSize:'0.9rem', color:'var(--fg-1)', display:'flex', alignItems:'center', gap:8 }}>
            <i className="bi bi-lightbulb" style={{ color:'var(--accent)' }}></i>매수/매도 분석
          </h6>
          <button onClick={onClose} style={{ width:28, height:28, borderRadius:'var(--r-2)', border:'1px solid var(--line-2)', background:'transparent', color:'var(--fg-2)', cursor:'pointer', display:'flex', alignItems:'center', justifyContent:'center' }}>
            <i className="bi bi-x"/>
          </button>
        </div>

        <div style={{ flex:1, overflowY:'auto', padding:'14px 16px' }}>
          {/* 검색 */}
          <div style={{ display:'flex', gap:8, marginBottom:12, position:'relative' }}>
            <div style={{ flex:1, position:'relative' }}>
              <input className="form-control" style={{ fontSize:'0.83rem' }}
                placeholder="종목명 또는 코드 (예: 삼성전자)"
                value={query} onChange={e => setQuery(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && runAdvisor()} />
              {suggestions.length > 0 && (
                <div className="autocomplete-list" style={{ display:'block' }}>
                  {suggestions.map(s => (
                    <div key={s.code} className="autocomplete-item"
                      onClick={() => { setSelected(s); setQuery(s.name); setSugg([]); }}>
                      <span style={{ fontSize:'0.88rem', fontWeight:600, color:'var(--fg-1)' }}>{s.name}</span>
                      <span style={{ fontSize:'0.75rem', color:'var(--fg-3)', fontFamily:'monospace' }}>{s.code}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <button className="btn btn-primary" onClick={runAdvisor} disabled={loading || !selected} style={{ whiteSpace:'nowrap', fontSize:'0.8rem', fontFamily:'var(--font-mono)' }}>
              {loading ? <span className="spinner" style={{ width:14, height:14, border:'2px solid rgba(255,255,255,0.3)', borderTopColor:'#fff' }}/> : `분석 (${ADVISOR_COST}C)`}
            </button>
          </div>

          {/* 보유 여부 */}
          <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-2)', padding:12, marginBottom:10 }}>
            <div style={{ fontSize:'0.7rem', fontWeight:600, color:'var(--fg-3)', marginBottom:9, fontFamily:'var(--font-mono)', textTransform:'uppercase', letterSpacing:'0.06em' }}>
              보유 현황
            </div>
            <div style={{ display:'flex', gap:5, marginBottom: hold === '보유중' ? 9 : 0 }}>
              {['미보유', '보유중'].map(item => (
                <button key={item} onClick={() => toggle(item, setHold)}
                  style={{ padding:'5px 11px', borderRadius:'var(--r-2)', fontSize:'0.76rem', fontWeight:500,
                           border:`1px solid ${hold === item ? 'var(--lime-border)' : 'var(--line-2)'}`,
                           background: hold === item ? 'var(--lime-soft)' : 'var(--bg-3)',
                           color: hold === item ? 'var(--accent)' : 'var(--fg-2)', cursor:'pointer' }}>
                  {item}
                </button>
              ))}
            </div>
            {hold === '보유중' && (
              <div style={{ display:'flex', gap:8 }}>
                <input className="form-control" type="number" value={avgPrice} onChange={e => setAvgPrice(e.target.value)}
                  placeholder="평균단가" style={{ fontSize:'0.78rem' }} />
                <input className="form-control" type="number" value={holdQty} onChange={e => setHoldQty(e.target.value)}
                  placeholder="보유수량" style={{ fontSize:'0.78rem' }} />
              </div>
            )}
          </div>

          {/* 설정 섹션들 */}
          {[
            { title: '투자 기간', items: ['단기(1~2주)', '중기(1~3개월)', '장기(6개월 이상)'], val: period, setter: setPeriod },
            { title: '매수 방식', items: ['일괄매수', '2회 분할매수', '3회 분할매수'], val: buyType, setter: setBuyType },
          ].map(sec => (
            <div key={sec.title} style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-2)', padding:12, marginBottom:10 }}>
              <div style={{ fontSize:'0.7rem', fontWeight:600, color:'var(--fg-3)', marginBottom:9, fontFamily:'var(--font-mono)', textTransform:'uppercase', letterSpacing:'0.06em' }}>
                {sec.title}
              </div>
              <div style={{ display:'flex', flexWrap:'wrap', gap:5 }}>
                {sec.items.map(item => (
                  <button key={item} onClick={() => toggle(item, sec.setter)}
                    style={{ padding:'5px 11px', borderRadius:'var(--r-2)', fontSize:'0.76rem', fontWeight:500,
                             border:`1px solid ${sec.val === item ? 'var(--lime-border)' : 'var(--line-2)'}`,
                             background: sec.val === item ? 'var(--lime-soft)' : 'var(--bg-3)',
                             color: sec.val === item ? 'var(--accent)' : 'var(--fg-2)', cursor:'pointer' }}>
                    {item}
                  </button>
                ))}
              </div>
            </div>
          ))}

          {/* 최대 손실 슬라이더 */}
          <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-2)', padding:12, marginBottom:10 }}>
            <div style={{ fontSize:'0.7rem', fontWeight:600, color:'var(--fg-3)', marginBottom:6, fontFamily:'var(--font-mono)', textTransform:'uppercase' }}>
              최대 허용 손실
            </div>
            <div style={{ display:'flex', alignItems:'center', gap:8 }}>
              <input type="range" min={3} max={20} value={stopLoss} onChange={e => setStopLoss(e.target.value)}
                style={{ flex:1, accentColor:'var(--accent)' }} />
              <span style={{ fontSize:'0.78rem', fontWeight:700, color:'var(--accent)', minWidth:36, fontFamily:'var(--font-mono)' }}>{stopLoss}%</span>
            </div>
          </div>

          {/* 추가 정보 */}
          <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-2)', padding:12, marginBottom:10 }}>
            <div style={{ fontSize:'0.7rem', fontWeight:600, color:'var(--fg-3)', marginBottom:6, fontFamily:'var(--font-mono)', textTransform:'uppercase' }}>
              최근 이슈 / 추가 정보
            </div>
            <textarea className="form-control" rows={3} value={extra} onChange={e => setExtra(e.target.value)}
              placeholder="예) 다음달 실적 발표 예정, 최근 대규모 수주 공시…"
              maxLength={500}
              style={{ resize:'none', fontSize:'0.78rem' }} />
          </div>

          {/* 에러 */}
          {err && (
            <div style={{ background:'rgba(239,68,68,0.08)', border:'1px solid rgba(239,68,68,0.2)', borderRadius:'var(--r-2)', padding:'10px 12px', marginBottom:10, fontSize:'0.8rem', color:'var(--down)' }}>
              <i className="bi bi-exclamation-triangle me-1"/>{err}
            </div>
          )}

          {/* 결과 */}
          {!result && !loading && !err && (
            <div style={{ textAlign:'center', padding:'32px 0', color:'var(--fg-3)', fontSize:'0.82rem' }}>
              <i className="bi bi-lightbulb" style={{ fontSize:'1.8rem', display:'block', marginBottom:10, color:'var(--accent)', opacity:0.4 }}/>
              종목 검색 후 분석 버튼을 누르세요.<br/>
              <span style={{ fontSize:'0.72rem', opacity:0.8 }}>분석 1회당 {ADVISOR_COST}C가 차감됩니다.</span>
            </div>
          )}
          {loading && !result && (
            <div style={{ textAlign:'center', padding:'32px 0', color:'var(--fg-3)', fontSize:'0.82rem' }}>
              <div className="spinner" style={{ margin:'0 auto 10px' }}/>
              AI 분석 중... (30초~1분 소요)
            </div>
          )}
          {result && (
            <>
              <div ref={resultRef} style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-2)', padding:13, fontSize:'0.82rem', lineHeight:1.7, color:'var(--fg-1)', whiteSpace:'pre-wrap', wordBreak:'break-word' }}>
                {result}
              </div>
              {cost != null && (
                <div style={{ display:'flex', justifyContent:'flex-end', gap:12, marginTop:10, fontSize:'0.7rem', color:'var(--fg-3)', fontFamily:'var(--font-mono)' }}>
                  <span>사용 {cost}C</span>
                  <span>잔액 {balance}C</span>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
