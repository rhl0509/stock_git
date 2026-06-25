import React, { useState, useEffect } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

const MONTHS = ['1월','2월','3월','4월','5월','6월','7월','8월','9월','10월','11월','12월'];

const EMPTY_FORM = { stock_code:'', stock_name:'', ex_div_date:'', pay_date:'', dividend_per_share:'', quantity:'', total_amount:'', memo:'' };

export default function DividendCalendar() {
  const [records,  setRecords]  = useState([]);
  const [summary,  setSummary]  = useState([]);
  const [showAdd,  setShowAdd]  = useState(false);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [sugg,     setSugg]     = useState([]);      // 종목 검색 자동완성
  const [divHist,  setDivHist]  = useState([]);      // 최근 배당 이력 칩
  const [filling,  setFilling]  = useState(false);

  // ── 키움 연동 ──
  const [kw,        setKw]        = useState(null);   // preview 응답
  const [kwLoading, setKwLoading] = useState(false);
  const [kwError,   setKwError]   = useState('');
  const [checked,   setChecked]   = useState({});     // `${code}|${ex_div_date}` → bool
  const [importing, setImporting] = useState(false);

  const loadKiwoom = async () => {
    if (kw) { setKw(null); return; }                  // 토글 닫기
    setKwLoading(true); setKwError('');
    try {
      const r = await api.get('/api/dividend/kiwoom/preview');
      const d = r.data;
      setKw(d);
      // 미기록 후보는 기본 선택
      const init = {};
      (d.candidates || []).forEach(c => { if (!c.already) init[`${c.code}|${c.ex_div_date}`] = true; });
      setChecked(init);
    } catch (err) {
      setKwError(err.response?.data?.error || '키움 연동 조회에 실패했습니다.');
    }
    setKwLoading(false);
  };

  const handleImport = async () => {
    const records = (kw?.candidates || []).filter(c => !c.already && checked[`${c.code}|${c.ex_div_date}`]);
    if (!records.length) return;
    setImporting(true);
    try {
      const r = await api.post('/api/dividend/kiwoom/import', { records });
      alert(`${r.data.inserted}건 기록 완료${r.data.skipped ? ` (중복 ${r.data.skipped}건 제외)` : ''}`);
      setKw(null);
      load();
    } catch (err) {
      alert(err.response?.data?.error || '가져오기 실패');
    }
    setImporting(false);
  };

  const checkedCount = (kw?.candidates || []).filter(c => !c.already && checked[`${c.code}|${c.ex_div_date}`]).length;

  // 종목 검색 (이름/코드)
  const searchStock = async v => {
    setForm(p => ({ ...p, stock_code: v }));
    if (!v.trim()) { setSugg([]); return; }
    const r = await api.get('/search-stock-kr', { params: { q: v } }).catch(() => ({ data: [] }));
    setSugg((r.data || []).slice(0, 8));
  };

  // 종목 선택 → 나머지 필드 자동 채움
  const pickStock = async s => {
    setSugg([]);
    setFilling(true);
    setForm(p => ({ ...p, stock_code: s.code, stock_name: s.name }));
    try {
      const r = await api.get(`/api/dividend/autofill/${s.code}`);
      const d = r.data || {};
      setDivHist(d.history || []);
      const latest = d.latest;
      setForm(p => {
        const qty = d.quantity || p.quantity;
        const dps = latest?.dividend_per_share ?? p.dividend_per_share;
        return {
          ...p,
          stock_name: d.name || s.name,
          quantity: qty || '',
          dividend_per_share: dps || '',
          ex_div_date: latest?.ex_div_date || p.ex_div_date,
          pay_date: latest?.pay_date_est || p.pay_date,
          total_amount: dps && qty ? Math.round(dps * qty) : p.total_amount,
        };
      });
    } catch { /* 자동완성 실패해도 수동 입력 가능 */ }
    setFilling(false);
  };

  // 배당 이력 칩 선택 → 해당 회차로 날짜/금액 변경
  const pickHistory = h => {
    setForm(p => {
      const qty = +p.quantity || 0;
      return {
        ...p,
        ex_div_date: h.ex_div_date,
        pay_date: h.pay_date_est,
        dividend_per_share: h.dividend_per_share,
        total_amount: qty ? Math.round(h.dividend_per_share * qty) : p.total_amount,
      };
    });
  };

  const [calendar, setCalendar] = useState(null);   // 월별 현금흐름

  const load = () => {
    setLoading(true);
    setError(null);
    Promise.all([
      api.get('/api/dividend'),
      api.get('/api/dividend/summary'),
    ]).then(([r1, r2]) => {
      setRecords(r1.data?.records || []);
      setSummary(r2.data?.by_year || []);
    }).catch(() => setError('배당 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.'))
      .finally(() => setLoading(false));
    // 월별 현금흐름 (보유종목 예상 포함 — 별도 로딩, 실패해도 본문 영향 없음)
    api.get('/api/dividend/calendar').then(r => setCalendar(r.data)).catch(() => {});
  };
  useEffect(load, []);

  const handleAdd = async e => {
    e.preventDefault();
    // 종목코드 검증 — 검색창에 이름만 입력하고 제안을 안 고른 경우 차단
    const code = String(form.stock_code || '').trim().padStart(6, '0').slice(0, 6);
    if (!/^\d{6}$/.test(code)) {
      alert('종목을 검색 목록에서 선택해 주세요. (종목코드 6자리)');
      return;
    }
    const dps = +form.dividend_per_share || 0;
    const qty = +form.quantity || 0;
    const total = form.total_amount ? +form.total_amount : Math.round(dps * qty);
    // 전부 빈값(금액 0 + 날짜 없음)이면 의미 없는 기록 → 차단
    if (total <= 0 && dps <= 0 && !form.ex_div_date && !form.pay_date) {
      alert('주당배당금·수령금액·날짜 중 최소 하나는 입력해야 합니다.');
      return;
    }
    const body = { ...form, stock_code: code, dividend_per_share: dps, quantity: qty, total_amount: total };
    try {
      await api.post('/api/dividend', body);
    } catch (err) {
      alert(err.response?.data?.error || '저장에 실패했습니다.');
      return;
    }
    setShowAdd(false);
    setForm(EMPTY_FORM);
    setDivHist([]);
    load();
  };

  const handleDelete = async id => {
    if (!confirm('삭제할까요?')) return;
    await api.delete(`/api/dividend/${id}`);
    load();
  };

  const totalEver = records.reduce((s, r) => s + (+r.total_amount || 0), 0);
  const thisYear  = new Date().getFullYear();
  const totalYear = records.filter(r => r.pay_date?.startsWith(String(thisYear))).reduce((s, r) => s + (+r.total_amount || 0), 0);

  const card = { background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'20px', marginBottom:16 };

  return (
    <StockLayout title="배당 캘린더">

      {/* 요약 */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(180px,1fr))', gap:12, marginBottom:16 }}>
        {[
          { label:`${thisYear}년 수령`, value:`₩${totalYear.toLocaleString('ko')}`, icon:'bi-calendar-check', color:'var(--up)' },
          { label:'누적 수령', value:`₩${totalEver.toLocaleString('ko')}`,          icon:'bi-piggy-bank',    color:'var(--accent)' },
          { label:'기록 수',  value:`${records.length}건`,                           icon:'bi-list-check',    color:'var(--fg-2)' },
        ].map(s => (
          <div key={s.label} style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'14px 16px' }}>
            <div style={{ display:'flex', justifyContent:'space-between', marginBottom:6 }}>
              <span style={{ fontSize:'0.72rem', color:'var(--fg-3)', fontWeight:600 }}>{s.label}</span>
              <i className={`bi ${s.icon}`} style={{ color: s.color }} />
            </div>
            <div style={{ fontSize:'1.2rem', fontWeight:800, fontFamily:'var(--font-mono)', color: s.color }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* ── 월별 현금흐름 캘린더 (실수령 + 예상) ── */}
      {calendar?.months?.length > 0 && (calendar.total_received > 0 || calendar.total_expected > 0) && (
        <div style={card}>
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'baseline', marginBottom:14, flexWrap:'wrap', gap:8 }}>
            <span style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)' }}>
              <i className="bi bi-cash-stack me-2" style={{ color:'var(--accent)' }}/>월별 배당 현금흐름
            </span>
            <span style={{ fontSize:'0.72rem', color:'var(--fg-3)' }}>
              최근 수령 ₩{(calendar.total_received||0).toLocaleString('ko')} ·
              향후 예상 <span style={{ color:'var(--accent)', fontWeight:700 }}>₩{(calendar.total_expected||0).toLocaleString('ko')}</span>
              <span style={{ marginLeft:6 }}>(작년 패턴 기반 추정)</span>
            </span>
          </div>
          {(() => {
            const max = Math.max(...calendar.months.map(m => Math.max(m.received, m.expected)), 1);
            const nowYm = new Date().toISOString().slice(0, 7);
            return (
              <div style={{ display:'grid', gridTemplateColumns:'repeat(12, 1fr)', gap:6, alignItems:'end' }}>
                {calendar.months.map(m => {
                  const isFuture = m.ym > nowYm;
                  const val = isFuture ? m.expected : m.received;
                  const h = Math.max(4, Math.round(val / max * 72));
                  return (
                    <div key={m.ym} style={{ textAlign:'center' }}>
                      <div style={{ fontSize:'0.62rem', fontFamily:'var(--font-mono)', fontWeight:700,
                                    color: val ? (isFuture ? 'var(--accent)' : 'var(--up)') : 'var(--fg-3)', marginBottom:3, minHeight:14 }}>
                        {val ? (val >= 10000 ? `${Math.round(val/1000).toLocaleString('ko')}천` : val.toLocaleString('ko')) : ''}
                      </div>
                      <div style={{ height:76, display:'flex', alignItems:'flex-end', justifyContent:'center' }}>
                        <div style={{
                          width:'70%', height:h, borderRadius:'3px 3px 0 0',
                          background: !val ? 'var(--bg-3)'
                                    : isFuture ? 'repeating-linear-gradient(45deg, var(--accent), var(--accent) 3px, transparent 3px, transparent 6px)'
                                    : 'var(--up)',
                          opacity: val ? (isFuture ? 0.75 : 0.9) : 1,
                          border: isFuture && val ? '1px dashed var(--accent)' : 'none',
                        }}/>
                      </div>
                      <div style={{ fontSize:'0.65rem', color: m.ym === nowYm ? 'var(--fg-1)' : 'var(--fg-3)',
                                    fontWeight: m.ym === nowYm ? 800 : 400, fontFamily:'var(--font-mono)', marginTop:4 }}>
                        {parseInt(m.ym.slice(5), 10)}월
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })()}
          <div style={{ fontSize:'0.68rem', color:'var(--fg-3)', marginTop:10, textAlign:'right' }}>
            <span style={{ color:'var(--up)' }}>■</span> 실수령&nbsp;&nbsp;
            <span style={{ color:'var(--accent)' }}>▨</span> 예상 (보유종목 × 작년 배당, 지급월 추정)
          </div>
        </div>
      )}

      {/* ── 키움 연동: 보유종목 배당 현황 ── */}
      <div style={card}>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
          <span style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)' }}>
            <i className="bi bi-link-45deg me-2" style={{ color:'var(--accent)' }}/>키움 보유종목 배당 현황
          </span>
          <button onClick={loadKiwoom} disabled={kwLoading}
            style={{ background: kw ? 'var(--bg-3)' : 'var(--accent)', color: kw ? 'var(--fg-2)' : '#fff',
                     border: kw ? '1px solid var(--line-2)' : 'none', borderRadius:'var(--r-2)',
                     padding:'6px 14px', fontSize:'0.78rem', fontWeight:700, cursor:'pointer',
                     display:'flex', alignItems:'center', gap:5 }}>
            {kwLoading ? <><span className="spinner" style={{ width:12, height:12, borderWidth:2 }}/>조회 중...</>
                       : kw ? <><i className="bi bi-chevron-up"/>닫기</>
                            : <><i className="bi bi-arrow-repeat"/>키움 연동 조회</>}
          </button>
        </div>

        {kwError && (
          <div style={{ marginTop:12, background:'rgba(244,63,94,0.1)', border:'1px solid var(--down)', borderRadius:'var(--r-2)', padding:'10px 14px', color:'var(--down)', fontSize:'0.8rem' }}>
            <i className="bi bi-exclamation-triangle-fill me-2"/>{kwError}
          </div>
        )}

        {kw && (
          <div style={{ marginTop:14 }}>
            {/* 예상 연간 배당 요약 */}
            <div style={{ display:'flex', gap:16, alignItems:'baseline', flexWrap:'wrap', marginBottom:12 }}>
              <span style={{ fontSize:'0.75rem', color:'var(--fg-3)' }}>
                보유 {kw.holdings_count}종목 기준 예상 연간 배당
                <span style={{ marginLeft:6, fontSize:'0.65rem', padding:'2px 6px', borderRadius:8, background:'var(--bg-3)', color:'var(--fg-3)' }}>
                  {kw.source === 'kiwoom' ? '키움 실시간' : 'DB 보유종목'}
                </span>
              </span>
              <span style={{ fontSize:'1.3rem', fontWeight:800, fontFamily:'var(--font-mono)', color:'var(--up)' }}>
                ₩{(kw.total_annual_est || 0).toLocaleString('ko')}
              </span>
            </div>

            {/* 종목별 예상 테이블 */}
            <div style={{ overflowX:'auto', marginBottom:18 }}>
              <table style={{ width:'100%', borderCollapse:'collapse', fontSize:'0.8rem' }}>
                <thead>
                  <tr style={{ borderBottom:'2px solid var(--line-2)' }}>
                    {['종목','보유','연간 주당(TTM)','연간 예상','시가배당률','연 횟수','다음 배당락 예상'].map(h => (
                      <th key={h} style={{ padding:'7px 10px', textAlign:h==='종목'?'left':'right', color:'var(--fg-3)', fontWeight:600, fontSize:'0.7rem', whiteSpace:'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {kw.expected.map(e => (
                    <tr key={e.code} style={{ borderBottom:'1px solid var(--line-1)' }}>
                      <td style={{ padding:'8px 10px' }}>
                        <span style={{ fontWeight:700 }}>{e.name}</span>
                        <span style={{ fontSize:'0.68rem', color:'var(--fg-3)', marginLeft:6, fontFamily:'var(--font-mono)' }}>{e.code}</span>
                      </td>
                      <td style={{ padding:'8px 10px', textAlign:'right', fontFamily:'var(--font-mono)' }}>{e.quantity.toLocaleString('ko')}주</td>
                      <td style={{ padding:'8px 10px', textAlign:'right', fontFamily:'var(--font-mono)' }}>{e.ttm_dps ? `₩${e.ttm_dps.toLocaleString('ko')}` : '-'}</td>
                      <td style={{ padding:'8px 10px', textAlign:'right', fontFamily:'var(--font-mono)', fontWeight:700, color:'var(--up)' }}>
                        {e.annual_est ? `₩${e.annual_est.toLocaleString('ko')}` : '-'}
                      </td>
                      <td style={{ padding:'8px 10px', textAlign:'right', fontFamily:'var(--font-mono)' }}>{e.yield_pct != null ? `${e.yield_pct}%` : '-'}</td>
                      <td style={{ padding:'8px 10px', textAlign:'right', color:'var(--fg-3)' }}>{e.pay_count_1y}회</td>
                      <td style={{ padding:'8px 10px', textAlign:'right', fontFamily:'var(--font-mono)', fontSize:'0.75rem', color:'var(--fg-3)' }}>{e.next_ex_est || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* 자동 기록 후보 */}
            {kw.candidates.length > 0 && (
              <>
                <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:8 }}>
                  <span style={{ fontSize:'0.78rem', fontWeight:700, color:'var(--fg-2)' }}>
                    최근 12개월 배당 자동 기록 <span style={{ color:'var(--fg-3)', fontWeight:400 }}>(<span style={{ color:'var(--up)', fontWeight:700 }}>확정</span>=KIS 실제 지급일 · <span style={{ fontWeight:700 }}>추정</span>=배당락+1개월)</span>
                  </span>
                  <button onClick={handleImport} disabled={!checkedCount || importing}
                    style={{ background: checkedCount ? 'var(--up)' : 'var(--bg-3)', color: checkedCount ? '#fff' : 'var(--fg-3)',
                             border:'none', borderRadius:'var(--r-2)', padding:'5px 14px', fontSize:'0.75rem', fontWeight:700,
                             cursor: checkedCount ? 'pointer' : 'default' }}>
                    {importing ? '저장 중...' : `선택 ${checkedCount}건 기록하기`}
                  </button>
                </div>
                <div style={{ maxHeight:260, overflowY:'auto', border:'1px solid var(--line-1)', borderRadius:'var(--r-2)' }}>
                  {kw.candidates.map(c => {
                    const key = `${c.code}|${c.ex_div_date}`;
                    return (
                      <label key={key} style={{ display:'flex', alignItems:'center', gap:10, padding:'7px 12px',
                                                borderBottom:'1px solid var(--line-1)', fontSize:'0.78rem',
                                                opacity: c.already ? 0.45 : 1, cursor: c.already ? 'default' : 'pointer' }}>
                        <input type="checkbox" disabled={c.already}
                          checked={c.already ? false : !!checked[key]}
                          onChange={e => setChecked(p => ({ ...p, [key]: e.target.checked }))} />
                        <span style={{ fontFamily:'var(--font-mono)', color:'var(--fg-3)', flexShrink:0 }}>{c.ex_div_date}</span>
                        <span style={{ fontWeight:600, flex:1 }}>{c.name}</span>
                        <span title={c.confirmed ? `KIS 확정 지급일 ${c.pay_date_est}` : '작년 패턴 기반 추정 (지급일 = 배당락+1개월)'}
                          style={{ fontSize:'0.62rem', fontWeight:700, padding:'2px 7px', borderRadius:8, flexShrink:0,
                                   color: c.confirmed ? 'var(--up)' : 'var(--fg-3)',
                                   background: c.confirmed ? 'rgba(34,197,94,0.12)' : 'var(--bg-3)',
                                   border: `1px solid ${c.confirmed ? 'var(--up)' : 'var(--line-2)'}` }}>
                          {c.confirmed ? '확정' : '추정'}
                        </span>
                        <span style={{ fontFamily:'var(--font-mono)' }}>₩{c.dividend_per_share.toLocaleString('ko')} × {c.quantity.toLocaleString('ko')}주</span>
                        <span style={{ fontFamily:'var(--font-mono)', fontWeight:700, color:'var(--up)', minWidth:90, textAlign:'right' }}>
                          ₩{c.total_amount.toLocaleString('ko')}
                        </span>
                        {c.already && <span style={{ fontSize:'0.65rem', color:'var(--fg-3)' }}>기록됨</span>}
                      </label>
                    );
                  })}
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* 연도별 합계 */}
      {summary.length > 0 && (
        <div style={card}>
          <div style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)', marginBottom:12 }}>
            <i className="bi bi-bar-chart me-2" style={{ color:'var(--accent)' }}/>연도별 배당 수령
          </div>
          <div style={{ display:'flex', gap:16, flexWrap:'wrap' }}>
            {summary.map(y => (
              <div key={y.yr} style={{ textAlign:'center', background:'var(--bg-3)', borderRadius:'var(--r-2)', padding:'10px 18px' }}>
                <div style={{ fontSize:'0.7rem', color:'var(--fg-3)' }}>{y.yr}년</div>
                <div style={{ fontWeight:800, fontFamily:'var(--font-mono)', color:'var(--up)' }}>₩{(+y.total).toLocaleString('ko')}</div>
                <div style={{ fontSize:'0.65rem', color:'var(--fg-3)' }}>{y.cnt}건</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 목록 */}
      <div style={card}>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:14 }}>
          <span style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)' }}>
            <i className="bi bi-calendar2-week me-2" style={{ color:'var(--accent)' }}/>배당 기록
          </span>
          <button onClick={() => setShowAdd(v => !v)}
            style={{ background:'var(--accent)', color:'#fff', border:'none', borderRadius:'var(--r-2)', padding:'6px 14px', fontSize:'0.78rem', fontWeight:700, cursor:'pointer', display:'flex', alignItems:'center', gap:5 }}>
            <i className="bi bi-plus-lg"/>추가
          </button>
        </div>

        {showAdd && (
          <form onSubmit={handleAdd} style={{ background:'var(--bg-3)', borderRadius:'var(--r-2)', padding:'16px', marginBottom:16, display:'grid', gap:10 }}>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:10 }}>
              {/* 종목 검색 → 선택 시 나머지 자동 채움 */}
              <div style={{ position:'relative' }}>
                <label style={{ fontSize:'0.72rem', color:'var(--fg-3)', display:'block', marginBottom:4 }}>
                  종목 검색 {filling && <span style={{ color:'var(--accent)' }}>(자동 채우는 중...)</span>}
                </label>
                <input className="form-control" required placeholder="종목명 또는 코드 (예: 삼성전자)"
                  value={form.stock_code} onChange={e => searchStock(e.target.value)} autoComplete="off" />
                {sugg.length > 0 && (
                  <div style={{ position:'absolute', zIndex:10, top:'100%', left:0, right:0, background:'var(--bg-2)', border:'1px solid var(--line-2)', borderRadius:'var(--r-2)', maxHeight:220, overflowY:'auto', boxShadow:'0 4px 12px rgba(0,0,0,0.15)' }}>
                    {sugg.map(s => (
                      <div key={s.code} onClick={() => pickStock(s)}
                        style={{ padding:'8px 12px', cursor:'pointer', fontSize:'0.8rem', borderBottom:'1px solid var(--line-1)' }}>
                        <span style={{ fontWeight:600 }}>{s.name}</span>
                        <span style={{ fontSize:'0.7rem', color:'var(--fg-3)', marginLeft:8, fontFamily:'var(--font-mono)' }}>{s.code}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div>
                <label style={{ fontSize:'0.72rem', color:'var(--fg-3)', display:'block', marginBottom:4 }}>종목명</label>
                <input className="form-control" value={form.stock_name} onChange={e => setForm(p => ({...p,stock_name:e.target.value}))} />
              </div>
              {/* 최근 배당 이력 칩 — 클릭으로 회차 선택 */}
              {divHist.length > 0 && (
                <div style={{ gridColumn:'1 / -1' }}>
                  <label style={{ fontSize:'0.72rem', color:'var(--fg-3)', display:'block', marginBottom:4 }}>
                    최근 배당 이력 (클릭하면 해당 회차로 채워집니다 · 지급일은 배당락+1개월 추정)
                  </label>
                  <div style={{ display:'flex', gap:6, flexWrap:'wrap' }}>
                    {divHist.map(h => (
                      <button key={h.ex_div_date} type="button" onClick={() => pickHistory(h)}
                        style={{
                          background: form.ex_div_date === h.ex_div_date ? 'var(--accent)' : 'var(--bg-2)',
                          color: form.ex_div_date === h.ex_div_date ? '#fff' : 'var(--fg-2)',
                          border:'1px solid var(--line-2)', borderRadius:12, padding:'4px 10px',
                          fontSize:'0.72rem', cursor:'pointer', fontFamily:'var(--font-mono)',
                        }}>
                        {h.ex_div_date} · ₩{h.dividend_per_share.toLocaleString('ko')}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {[['ex_div_date','배당락일','date'],['pay_date','지급일','date'],['dividend_per_share','주당배당금','number'],['quantity','수량','number'],['total_amount','수령금액(자동계산)','number']].map(([k,l,t]) => (
                <div key={k}>
                  <label style={{ fontSize:'0.72rem', color:'var(--fg-3)', display:'block', marginBottom:4 }}>{l}</label>
                  <input className="form-control" type={t} value={form[k]} onChange={e => setForm(p => {
                    const next = { ...p, [k]: e.target.value };
                    // 주당배당금·수량 변경 시 수령금액 자동 재계산
                    if (k === 'dividend_per_share' || k === 'quantity') {
                      const dps = +(k === 'dividend_per_share' ? e.target.value : p.dividend_per_share) || 0;
                      const qty = +(k === 'quantity' ? e.target.value : p.quantity) || 0;
                      if (dps && qty) next.total_amount = Math.round(dps * qty);
                    }
                    return next;
                  })} />
                </div>
              ))}
              <div>
                <label style={{ fontSize:'0.72rem', color:'var(--fg-3)', display:'block', marginBottom:4 }}>메모</label>
                <input className="form-control" value={form.memo} onChange={e => setForm(p => ({...p,memo:e.target.value}))} />
              </div>
            </div>
            <div style={{ display:'flex', gap:8 }}>
              <button type="submit" style={{ background:'var(--accent)', color:'#fff', border:'none', borderRadius:'var(--r-2)', padding:'7px 18px', fontSize:'0.8rem', fontWeight:700, cursor:'pointer' }}>저장</button>
              <button type="button" onClick={() => setShowAdd(false)} style={{ background:'var(--bg-2)', color:'var(--fg-2)', border:'1px solid var(--line-2)', borderRadius:'var(--r-2)', padding:'7px 14px', fontSize:'0.8rem', cursor:'pointer' }}>취소</button>
            </div>
          </form>
        )}

        {error && (
          <div style={{ background:'rgba(244,63,94,0.1)', border:'1px solid var(--down)', borderRadius:'var(--r-2)', padding:'12px 16px', marginBottom:12, color:'var(--down)', fontSize:'0.82rem', display:'flex', alignItems:'center', gap:8 }}>
            <i className="bi bi-exclamation-triangle-fill"/>{error}
          </div>
        )}
        {loading ? (
          <div style={{ textAlign:'center', padding:'40px', color:'var(--fg-3)' }}><div className="spinner" style={{ margin:'0 auto 8px' }}/> 로딩 중...</div>
        ) : records.length === 0 ? (
          <div style={{ textAlign:'center', padding:'40px', color:'var(--fg-3)', fontSize:'0.83rem' }}>배당 기록이 없습니다. 추가 버튼을 눌러 기록하세요.</div>
        ) : (
          <div style={{ overflowX:'auto' }}>
            <table style={{ width:'100%', borderCollapse:'collapse', fontSize:'0.82rem' }}>
              <thead>
                <tr style={{ borderBottom:'2px solid var(--line-2)' }}>
                  {['종목','배당락일','지급일','주당','수량','수령금액','메모',''].map(h => (
                    <th key={h} style={{ padding:'8px 10px', textAlign: h === '수령금액' ? 'right' : 'left', color:'var(--fg-3)', fontWeight:600, fontSize:'0.72rem', whiteSpace:'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {records.map(r => (
                  <tr key={r.id} style={{ borderBottom:'1px solid var(--line-1)' }}>
                    <td style={{ padding:'9px 10px' }}>
                      <div style={{ fontWeight:700 }}>{r.stock_name || r.stock_code}</div>
                      <div style={{ fontSize:'0.68rem', color:'var(--fg-3)', fontFamily:'var(--font-mono)' }}>{r.stock_code}</div>
                    </td>
                    <td style={{ padding:'9px 10px', fontFamily:'var(--font-mono)', fontSize:'0.78rem', color:'var(--fg-3)' }}>{r.ex_div_date?.slice(0,10) || '-'}</td>
                    <td style={{ padding:'9px 10px', fontFamily:'var(--font-mono)', fontSize:'0.78rem' }}>{r.pay_date?.slice(0,10) || '-'}</td>
                    <td style={{ padding:'9px 10px', fontFamily:'var(--font-mono)' }}>{r.dividend_per_share ? `₩${(+r.dividend_per_share).toLocaleString('ko')}` : '-'}</td>
                    <td style={{ padding:'9px 10px', fontFamily:'var(--font-mono)' }}>{r.quantity?.toLocaleString('ko') || '-'}</td>
                    <td style={{ padding:'9px 10px', fontFamily:'var(--font-mono)', textAlign:'right', fontWeight:700, color:'var(--up)' }}>₩{(+r.total_amount||0).toLocaleString('ko')}</td>
                    <td style={{ padding:'9px 10px', color:'var(--fg-3)', fontSize:'0.75rem' }}>{r.memo}</td>
                    <td style={{ padding:'9px 10px' }}>
                      <button onClick={() => handleDelete(r.id)} style={{ background:'transparent', border:'none', color:'var(--down)', cursor:'pointer' }}>
                        <i className="bi bi-trash"/>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </StockLayout>
  );
}
