import React, { useState, useEffect } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

const blankParams = (action) =>
  Object.fromEntries((action?.params || []).map(p => [p.key, p.default ?? '']));

export default function Workflow() {
  const [actions,  setActions]  = useState([]);
  const [list,     setList]     = useState([]);
  const [sel,      setSel]      = useState(null);     // 편집중 워크플로 {id?, name, steps}
  const [runs,     setRuns]     = useState([]);
  const [running,  setRunning]  = useState(false);
  const [saving,   setSaving]   = useState(false);
  const [lastRun,  setLastRun]  = useState(null);
  const [msg,      setMsg]      = useState(null);

  const actionMap = Object.fromEntries(actions.map(a => [a.key, a]));

  const loadList = () => api.get('/api/workflows').then(r => setList(r.data?.workflows || [])).catch(() => {});
  const loadRuns = (id) => id && api.get(`/api/workflows/${id}/runs`).then(r => setRuns(r.data?.runs || [])).catch(() => setRuns([]));

  useEffect(() => {
    api.get('/api/workflows/actions').then(r => setActions(r.data?.actions || [])).catch(() => {});
    loadList();
  }, []);

  const openWf = (wf) => {
    setSel({ id: wf.id, name: wf.name, steps: wf.steps || [], schedule: wf.schedule || null });
    setLastRun(null); setMsg(null);
    loadRuns(wf.id);
  };
  const newWf = () => { setSel({ name: '', steps: [], schedule: null }); setRuns([]); setLastRun(null); setMsg(null); };

  // ── 단계 편집 ──
  const addStep = () => {
    const first = actions[0];
    if (!first) return;
    setSel(s => ({ ...s, steps: [...s.steps, { action: first.key, params: blankParams(first) }] }));
  };
  const setStepAction = (i, key) =>
    setSel(s => ({ ...s, steps: s.steps.map((st, idx) => idx === i ? { action: key, params: blankParams(actionMap[key]) } : st) }));
  const setStepParam = (i, pk, v) =>
    setSel(s => ({ ...s, steps: s.steps.map((st, idx) => idx === i ? { ...st, params: { ...st.params, [pk]: v } } : st) }));
  const moveStep = (i, d) => setSel(s => {
    const a = [...s.steps]; const j = i + d;
    if (j < 0 || j >= a.length) return s;
    [a[i], a[j]] = [a[j], a[i]];
    return { ...s, steps: a };
  });
  const removeStep = (i) => setSel(s => ({ ...s, steps: s.steps.filter((_, idx) => idx !== i) }));

  const save = async () => {
    if (!sel.name.trim()) { setMsg({ ok: false, t: '이름을 입력하세요.' }); return; }
    setSaving(true); setMsg(null);
    try {
      const payload = { name: sel.name, steps: sel.steps, schedule: sel.schedule };
      if (sel.id) {
        await api.put(`/api/workflows/${sel.id}`, payload);
      } else {
        const r = await api.post('/api/workflows', payload);
        setSel(s => ({ ...s, id: r.data.id }));
      }
      setMsg({ ok: true, t: '저장되었습니다.' });
      loadList();
    } catch { setMsg({ ok: false, t: '저장 실패' }); }
    setSaving(false);
  };

  const runNow = async () => {
    if (!sel?.id) { setMsg({ ok: false, t: '먼저 저장하세요.' }); return; }
    setRunning(true); setLastRun(null); setMsg(null);
    try {
      const r = await api.post(`/api/workflows/${sel.id}/run`);
      setLastRun(r.data);
      loadRuns(sel.id); loadList();
    } catch (e) { setMsg({ ok: false, t: e.response?.data?.error || '실행 실패' }); }
    setRunning(false);
  };

  const removeWf = async (id) => {
    if (!confirm('워크플로를 삭제할까요?')) return;
    await api.delete(`/api/workflows/${id}`);
    if (sel?.id === id) setSel(null);
    loadList();
  };

  const card = { background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'16px' };

  return (
    <StockLayout title="자동화 워크플로">
      <div style={{ fontSize:'0.75rem', color:'var(--fg-3)', marginBottom:14 }}>
        <i className="bi bi-diagram-3 me-1"/>액션을 코드 없이 순서대로 조합해 자동화를 만듭니다. (키움 동기화 → 월별성과 → AI 추천 → AI 요약 → 카카오 발송)
      </div>
      <div style={{ display:'grid', gridTemplateColumns:'240px 1fr', gap:16, alignItems:'start' }}>

        {/* 워크플로 목록 */}
        <div style={card}>
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:12 }}>
            <span style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)' }}>워크플로</span>
            <button onClick={newWf} style={{ background:'var(--accent)', color:'#fff', border:'none', borderRadius:'var(--r-1)', padding:'2px 8px', cursor:'pointer', fontSize:'0.78rem' }}>
              <i className="bi bi-plus-lg"/>
            </button>
          </div>
          {list.length === 0 ? (
            <div style={{ fontSize:'0.78rem', color:'var(--fg-3)', textAlign:'center', padding:'20px 0' }}>워크플로 없음</div>
          ) : list.map(wf => {
            const wfPaid = (wf.steps || []).some(s => actionMap[s.action]?.paid);
            return (
            <div key={wf.id} onClick={() => openWf(wf)}
              style={{ padding:'8px 10px', borderRadius:'var(--r-2)', cursor:'pointer',
                background: sel?.id === wf.id ? 'rgba(99,102,241,0.12)' : 'transparent' }}>
              <div style={{ display:'flex', alignItems:'center', gap:6 }}>
                <i className="bi bi-diagram-3" style={{ color: sel?.id === wf.id ? 'var(--accent)' : 'var(--fg-3)', fontSize:'0.8rem' }}/>
                <span style={{ flex:1, fontSize:'0.83rem', fontWeight: sel?.id === wf.id ? 700 : 500, color: sel?.id === wf.id ? 'var(--accent)' : 'var(--fg-1)' }}>{wf.name}</span>
                {wfPaid && <span title="Claude API 과금 단계 포함" style={{ fontSize:'0.6rem', color:'#fff', background:'#d97706', borderRadius:8, padding:'1px 5px', flexShrink:0 }}>API</span>}
                <button onClick={e => { e.stopPropagation(); removeWf(wf.id); }} style={{ background:'none', border:'none', color:'var(--fg-3)', cursor:'pointer', padding:0 }}>
                  <i className="bi bi-x"/>
                </button>
              </div>
              <div style={{ display:'flex', alignItems:'center', gap:6, marginTop:4, marginLeft:20, fontSize:'0.66rem', color:'var(--fg-3)' }}>
                <span title={wf.last_status === 'error' ? '마지막 실행 실패' : wf.last_status === 'ok' ? '마지막 실행 성공' : '아직 실행 안 됨'}
                  style={{ width:7, height:7, borderRadius:'50%', flexShrink:0,
                    background: wf.last_status === 'ok' ? 'var(--up)' : wf.last_status === 'error' ? 'var(--down)' : 'var(--line-2)' }}/>
                <span style={{ color: wf.last_status === 'error' ? 'var(--down)' : 'var(--fg-3)' }}>
                  {wf.last_status === 'error' ? '실패' : wf.last_status === 'ok' ? '성공' : '미실행'}
                </span>
                {wf.last_run_at && <span style={{ fontFamily:'var(--font-mono)' }}>{wf.last_run_at.replace('T',' ').slice(5,16)}</span>}
                <span style={{ flex:1 }}/>
                <span>{wf.steps?.length || 0}단계</span>
              </div>
            </div>
            );
          })}
        </div>

        {/* 편집기 */}
        <div style={{ display:'flex', flexDirection:'column', gap:16 }}>
          {!sel ? (
            <div style={{ ...card, textAlign:'center', padding:'60px', color:'var(--fg-3)', fontSize:'0.83rem' }}>
              <i className="bi bi-diagram-3" style={{ fontSize:'2rem', opacity:0.2, display:'block', marginBottom:12 }}/>
              왼쪽에서 워크플로를 선택하거나 <b>+</b> 로 새로 만드세요
            </div>
          ) : (
            <>
              <div style={card}>
                <div style={{ display:'flex', gap:10, alignItems:'center', marginBottom:14 }}>
                  <input className="form-control" placeholder="워크플로 이름 (예: 장마감 AI 리포트)" value={sel.name}
                    onChange={e => setSel(s => ({ ...s, name: e.target.value }))} style={{ fontSize:'0.85rem', fontWeight:600 }} />
                  <button onClick={save} disabled={saving} className="btn btn-primary btn-sm" style={{ whiteSpace:'nowrap' }}>
                    <i className="bi bi-save me-1"/>저장
                  </button>
                  <button onClick={runNow} disabled={running || !sel.id} className="btn btn-success btn-sm" style={{ whiteSpace:'nowrap' }}>
                    <i className={`bi bi-play-fill me-1${running ? ' spin' : ''}`}/>{running ? '실행 중...' : '지금 실행'}
                  </button>
                </div>

                {msg && (
                  <div style={{ fontSize:'0.78rem', marginBottom:10, color: msg.ok ? 'var(--up)' : 'var(--down)' }}>
                    <i className={`bi ${msg.ok ? 'bi-check-circle-fill' : 'bi-exclamation-triangle-fill'} me-1`}/>{msg.t}
                  </div>
                )}

                {/* 단계들 */}
                <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
                  {sel.steps.map((st, i) => {
                    const a = actionMap[st.action];
                    return (
                      <div key={i} style={{ background:'var(--bg-3)', borderRadius:'var(--r-2)', padding:'10px 12px' }}>
                        <div style={{ display:'flex', alignItems:'center', gap:8 }}>
                          <span style={{ fontFamily:'var(--font-mono)', fontSize:'0.7rem', color:'var(--fg-3)', width:18 }}>{i+1}</span>
                          <select className="form-select form-select-sm" value={st.action}
                            onChange={e => setStepAction(i, e.target.value)} style={{ flex:1, fontSize:'0.82rem' }}>
                            {actions.map(ac => <option key={ac.key} value={ac.key}>{ac.label}{ac.paid ? ' 💲 (API 과금)' : ''}</option>)}
                          </select>
                          {a?.paid && <span title="Claude API 호출 — 실행 시 과금" style={{ fontSize:'0.62rem', fontWeight:700, color:'#fff', background:'#d97706', borderRadius:8, padding:'2px 7px', whiteSpace:'nowrap', flexShrink:0 }}>💲 API 과금</span>}
                          <button onClick={() => moveStep(i,-1)} style={iconBtn}><i className="bi bi-arrow-up"/></button>
                          <button onClick={() => moveStep(i, 1)} style={iconBtn}><i className="bi bi-arrow-down"/></button>
                          <button onClick={() => removeStep(i)} style={{ ...iconBtn, color:'var(--down)' }}><i className="bi bi-trash"/></button>
                        </div>
                        {a?.description && <div style={{ fontSize:'0.68rem', color:'var(--fg-3)', margin:'4px 0 0 26px' }}>{a.description}</div>}
                        {(a?.params || []).length > 0 && (
                          <div style={{ display:'flex', gap:8, flexWrap:'wrap', margin:'8px 0 0 26px' }}>
                            {a.params.map(p => (
                              <label key={p.key} style={{ fontSize:'0.72rem', color:'var(--fg-3)' }}>
                                {p.label}{' '}
                                {p.type === 'select' ? (
                                  <select className="form-select form-select-sm" style={{ display:'inline-block', width:'auto', fontSize:'0.76rem' }}
                                    value={st.params[p.key] ?? p.default}
                                    onChange={e => setStepParam(i, p.key, e.target.value)}>
                                    {p.options.map(o => <option key={o} value={o}>{o}</option>)}
                                  </select>
                                ) : (
                                  <input className="form-control form-control-sm" type={p.type === 'number' ? 'number' : 'text'}
                                    style={{ display:'inline-block', width: p.type === 'number' ? 70 : 220, fontSize:'0.76rem' }}
                                    value={st.params[p.key] ?? ''} placeholder={p.type === 'text' ? '비우면 기본값' : ''}
                                    onChange={e => setStepParam(i, p.key, p.type === 'number' ? Number(e.target.value) : e.target.value)} />
                                )}
                              </label>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                  {sel.steps.length === 0 && <div style={{ fontSize:'0.78rem', color:'var(--fg-3)', padding:'12px 0', textAlign:'center' }}>아래에서 단계를 추가하세요</div>}
                  <button onClick={addStep} style={{ border:'1px dashed var(--line-2)', background:'none', borderRadius:'var(--r-2)', padding:'8px', color:'var(--fg-2)', cursor:'pointer', fontSize:'0.8rem' }}>
                    <i className="bi bi-plus-lg me-1"/>단계 추가
                  </button>
                </div>

                {/* 스케줄(자동 실행) */}
                <div style={{ marginTop:14, paddingTop:14, borderTop:'1px solid var(--line-1)' }}>
                  <label style={{ display:'flex', alignItems:'center', gap:8, fontSize:'0.82rem', color:'var(--fg-1)', fontWeight:600, cursor:'pointer' }}>
                    <input type="checkbox" checked={!!sel.schedule}
                      onChange={e => setSel(s => ({ ...s, schedule: e.target.checked ? { days:'mon-fri', time:'15:40' } : null }))} />
                    <i className="bi bi-clock"/> 자동 실행 (스케줄)
                  </label>
                  {sel.schedule && (
                    <div style={{ display:'flex', gap:10, alignItems:'center', marginTop:8, marginLeft:24, flexWrap:'wrap' }}>
                      <select className="form-select form-select-sm" style={{ width:'auto', fontSize:'0.8rem' }}
                        value={sel.schedule.days || 'mon-fri'}
                        onChange={e => setSel(s => ({ ...s, schedule: { ...s.schedule, days: e.target.value } }))}>
                        <option value="daily">매일</option>
                        <option value="mon-fri">평일(월~금)</option>
                        <option value="weekend">주말</option>
                        <option value="mon">월</option><option value="tue">화</option><option value="wed">수</option>
                        <option value="thu">목</option><option value="fri">금</option><option value="sat">토</option><option value="sun">일</option>
                      </select>
                      <input type="time" className="form-control form-control-sm" style={{ width:120, fontSize:'0.8rem' }}
                        value={sel.schedule.time || '15:40'}
                        onChange={e => setSel(s => ({ ...s, schedule: { ...s.schedule, time: e.target.value } }))} />
                      <span style={{ fontSize:'0.72rem', color:'var(--fg-3)' }}>저장하면 매분 디스패처가 이 시각에 자동 실행합니다</span>
                    </div>
                  )}
                </div>
              </div>

              {/* 직전 실행 결과 */}
              {lastRun && (
                <div style={card}>
                  <div style={{ fontWeight:700, fontSize:'0.83rem', marginBottom:10, color: lastRun.status === 'ok' ? 'var(--up)' : 'var(--down)' }}>
                    <i className={`bi ${lastRun.status === 'ok' ? 'bi-check-circle-fill' : 'bi-exclamation-triangle-fill'} me-1`}/>
                    실행 {lastRun.status === 'ok' ? '성공' : '실패'}
                  </div>
                  {lastRun.log?.map((L,i) => (
                    <div key={i} style={{ display:'flex', gap:8, fontSize:'0.78rem', padding:'3px 0' }}>
                      <i className={`bi ${L.ok ? 'bi-check-lg' : 'bi-x-lg'}`} style={{ color: L.ok ? 'var(--up)' : 'var(--down)' }}/>
                      <span style={{ color:'var(--fg-2)' }}>{L.label || L.action}</span>
                      <span style={{ color:'var(--fg-3)', flex:1 }}>{L.detail}</span>
                    </div>
                  ))}
                  {lastRun.message && (
                    <pre style={{ marginTop:10, background:'var(--bg-3)', borderRadius:'var(--r-2)', padding:'10px 12px', fontSize:'0.74rem', color:'var(--fg-2)', whiteSpace:'pre-wrap', fontFamily:'inherit' }}>{lastRun.message}</pre>
                  )}
                </div>
              )}

              {/* 실행 이력 */}
              {runs.length > 0 && (
                <div style={card}>
                  <div style={{ fontWeight:700, fontSize:'0.83rem', marginBottom:10, color:'var(--fg-1)' }}>
                    <i className="bi bi-clock-history me-1"/>실행 이력
                  </div>
                  {runs.map(r => (
                    <div key={r.id} style={{ display:'flex', alignItems:'center', gap:10, padding:'6px 0', borderBottom:'1px solid var(--line-1)', fontSize:'0.76rem' }}>
                      <span style={{ width:8, height:8, borderRadius:'50%', flexShrink:0, background: r.status === 'ok' ? 'var(--up)' : 'var(--down)' }}/>
                      <span style={{ fontFamily:'var(--font-mono)', color:'var(--fg-3)' }}>{(r.started_at || '').replace('T',' ').slice(5,16)}</span>
                      <span style={{ color:'var(--fg-3)' }}>{r.trigger}</span>
                      <span style={{ flex:1, color:'var(--fg-2)' }}>
                        {(r.log || []).map(l => l.ok ? '●' : '○').join(' ')} · {(r.log || []).filter(l => l.ok).length}/{(r.log || []).length} 단계
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </StockLayout>
  );
}

const iconBtn = { background:'none', border:'1px solid var(--line-2)', borderRadius:'var(--r-1)', color:'var(--fg-3)', cursor:'pointer', padding:'2px 6px', fontSize:'0.72rem' };
