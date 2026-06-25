import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

const TAB = { info: 'info', pw: 'pw', credit: 'credit' };

const CHARGE_AMOUNTS = [5000, 10000, 30000, 50000, 100000];

// 포트원 V2 브라우저 SDK를 필요할 때만(실결제 모드) 동적 로드한다.
function loadPortOne() {
  return new Promise((resolve, reject) => {
    if (window.PortOne) return resolve(window.PortOne);
    const s = document.createElement('script');
    s.src = 'https://cdn.portone.io/v2/browser-sdk.js';
    s.onload = () => resolve(window.PortOne);
    s.onerror = () => reject(new Error('결제 모듈을 불러오지 못했습니다.'));
    document.head.appendChild(s);
  });
}

function Field({ label, children }) {
  return (
    <div className="mb-3">
      <label className="form-label" style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--fg-2)' }}>{label}</label>
      {children}
    </div>
  );
}

function Alert({ type, msg }) {
  if (!msg) return null;
  const isOk = type === 'success';
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '10px 14px', borderRadius: 'var(--r-2)', marginBottom: 16, fontSize: '0.83rem',
      background: isOk ? 'var(--lime-soft, #f0fdf4)' : 'var(--down-soft, #fef2f2)',
      border: `1px solid ${isOk ? 'var(--lime-border, #86efac)' : 'var(--down, #f87171)'}`,
      color: isOk ? 'var(--up)' : 'var(--down)',
    }}>
      <i className={`bi ${isOk ? 'bi-check-circle' : 'bi-exclamation-triangle'}`}/>
      {msg}
    </div>
  );
}

export default function MyPage() {
  const { user } = useAuth();
  const navigate  = useNavigate();
  const [tab, setTab] = useState(TAB.info);

  // 기본 정보
  const [profile, setProfile] = useState({ user_id: '', name: '', email: '', created_at: '' });
  const [infoLoading, setInfoLoading] = useState(true);
  const [infoMsg, setInfoMsg] = useState({ type: '', text: '' });
  const [infoSaving, setInfoSaving] = useState(false);

  // 비밀번호
  const [pw, setPw] = useState({ current_password: '', new_password: '', confirm: '' });
  const [pwMsg, setPwMsg] = useState({ type: '', text: '' });
  const [pwSaving, setPwSaving] = useState(false);
  const [showPw, setShowPw] = useState({ cur: false, nw: false, cf: false });

  // 크레딧/충전
  const [balance, setBalance] = useState(null);
  const [txns, setTxns] = useState([]);
  const [creditMock, setCreditMock] = useState(false);
  const [selAmount, setSelAmount] = useState(10000);
  const [charging, setCharging] = useState(false);
  const [creditLoading, setCreditLoading] = useState(false);
  const [creditMsg, setCreditMsg] = useState({ type: '', text: '' });

  // AI 챗봇
  const [chatEnabled, setChatEnabled] = useState(false);
  const [chatCost, setChatCost] = useState(0);
  const [chatInput, setChatInput] = useState('');
  const [chatSending, setChatSending] = useState(false);
  const [chatLog, setChatLog] = useState([]); // {role:'user'|'bot', text}

  // AI 추천 데이 패스
  const [pass, setPass] = useState(null); // {active, paid_today, cost, expires_at}
  const [passBusy, setPassBusy] = useState(false);
  const [showPassModal, setShowPassModal] = useState(false);

  useEffect(() => {
    api.get('/auth/profile')
      .then(r => setProfile(r.data))
      .catch(() => setInfoMsg({ type: 'error', text: '정보를 불러오지 못했습니다.' }))
      .finally(() => setInfoLoading(false));
  }, []);

  const loadCredit = async () => {
    setCreditLoading(true);
    try {
      const [b, t, p] = await Promise.all([
        api.get('/api/credits/balance'),
        api.get('/api/credits/transactions'),
        api.get('/api/recommend-pass/status').catch(() => null),
      ]);
      setBalance(b.data.balance);
      setCreditMock(b.data.mock);
      setChatEnabled(!!b.data.chat_enabled);
      setChatCost(b.data.chat_cost || 0);
      setTxns(t.data.transactions || []);
      if (p) setPass(p.data);
    } catch {
      setCreditMsg({ type: 'error', text: '크레딧 정보를 불러오지 못했습니다.' });
    }
    setCreditLoading(false);
  };

  const enablePass = async () => {
    setShowPassModal(false);
    setPassBusy(true);
    setCreditMsg({ type: '', text: '' });
    try {
      const r = (await api.post('/api/recommend-pass/enable')).data;
      setPass(r);
      if (typeof r.balance === 'number') setBalance(r.balance);
      document.dispatchEvent(new CustomEvent('recommendPassChanged'));
      const t = await api.get('/api/credits/transactions');
      setTxns(t.data.transactions || []);
      setCreditMsg({
        type: 'success',
        text: r.charged ? `AI 추천받기를 켰습니다. (${Number(r.charged).toLocaleString()} C 차감)`
                        : 'AI 추천받기를 다시 켰습니다. (오늘 이미 결제됨)',
      });
    } catch (err) {
      setCreditMsg({ type: 'error', text: err.response?.data?.error || 'AI 추천받기를 켜지 못했습니다.' });
    }
    setPassBusy(false);
  };

  const disablePass = async () => {
    setPassBusy(true);
    setCreditMsg({ type: '', text: '' });
    try {
      const r = (await api.post('/api/recommend-pass/disable')).data;
      setPass(r);
      document.dispatchEvent(new CustomEvent('recommendPassChanged'));
      setCreditMsg({ type: 'success', text: 'AI 추천받기를 껐습니다. (오늘 다시 켜도 재차감되지 않습니다)' });
    } catch (err) {
      setCreditMsg({ type: 'error', text: err.response?.data?.error || 'AI 추천받기를 끄지 못했습니다.' });
    }
    setPassBusy(false);
  };

  const onTogglePass = () => {
    if (passBusy) return;
    if (pass?.active) return disablePass();
    if (pass?.paid_today) return enablePass(); // 오늘 이미 결제 → 모달 없이 켜기
    setShowPassModal(true);                     // 신규 결제 → 경고 모달
  };

  useEffect(() => {
    if (tab === TAB.credit && balance === null) loadCredit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const charge = async () => {
    setCreditMsg({ type: '', text: '' });
    setCharging(true);
    try {
      const prep = (await api.post('/api/credits/charge/prepare', { amount: selAmount })).data;
      if (!prep.mock) {
        const PortOne = await loadPortOne();
        const res = await PortOne.requestPayment({
          storeId:     prep.store_id,
          channelKey:  prep.channel_key,
          paymentId:   prep.payment_id,
          orderName:   prep.order_name,
          totalAmount: prep.amount,
          currency:    'CURRENCY_KRW',
          payMethod:   'CARD',
        });
        if (res?.code != null) throw new Error(res.message || '결제가 취소되었습니다.');
      }
      const ver = (await api.post('/api/credits/charge/verify', { payment_id: prep.payment_id })).data;
      if (ver.status === 'paid') {
        setCreditMsg({ type: 'success', text: `${selAmount.toLocaleString()}원이 충전되었습니다.` });
        await loadCredit();
      } else {
        setCreditMsg({ type: 'error', text: '결제가 완료되지 않았습니다.' });
      }
    } catch (err) {
      setCreditMsg({ type: 'error', text: err.response?.data?.error || err.message || '충전에 실패했습니다.' });
    }
    setCharging(false);
  };

  const sendChat = async () => {
    const q = chatInput.trim();
    if (!q || chatSending) return;
    setChatInput('');
    setChatLog(l => [...l, { role: 'user', text: q }]);
    setChatSending(true);
    try {
      const r = (await api.post('/api/chat/ask', { message: q })).data;
      if (r.ok) {
        setChatLog(l => [...l, { role: 'bot', text: r.answer, cost: r.cost }]);
        if (typeof r.balance === 'number') setBalance(r.balance);
        const t = await api.get('/api/credits/transactions');
        setTxns(t.data.transactions || []);
      } else {
        setChatLog(l => [...l, { role: 'bot', text: '⚠ ' + (r.error || '답변 생성 실패'), error: true }]);
        if (typeof r.balance === 'number') setBalance(r.balance);
      }
    } catch (err) {
      setChatLog(l => [...l, { role: 'bot', text: '⚠ ' + (err.response?.data?.error || '오류가 발생했습니다.'), error: true }]);
    }
    setChatSending(false);
  };

  const saveInfo = async e => {
    e.preventDefault();
    setInfoMsg({ type: '', text: '' }); setInfoSaving(true);
    try {
      await api.put('/auth/profile', { name: profile.name, email: profile.email });
      setInfoMsg({ type: 'success', text: '정보가 수정되었습니다.' });
    } catch (err) {
      setInfoMsg({ type: 'error', text: err.response?.data?.error || '수정에 실패했습니다.' });
    }
    setInfoSaving(false);
  };

  const changePw = async e => {
    e.preventDefault();
    if (pw.new_password !== pw.confirm)
      return setPwMsg({ type: 'error', text: '새 비밀번호가 일치하지 않습니다.' });
    if (pw.new_password.length < 6)
      return setPwMsg({ type: 'error', text: '새 비밀번호는 6자 이상이어야 합니다.' });
    setPwMsg({ type: '', text: '' }); setPwSaving(true);
    try {
      await api.put('/auth/change-password', {
        current_password: pw.current_password,
        new_password: pw.new_password,
      });
      setPwMsg({ type: 'success', text: '비밀번호가 변경되었습니다. 다음 로그인부터 적용됩니다.' });
      setPw({ current_password: '', new_password: '', confirm: '' });
    } catch (err) {
      setPwMsg({ type: 'error', text: err.response?.data?.error || '변경에 실패했습니다.' });
    }
    setPwSaving(false);
  };

  const eye = (key) => (
    <button type="button" onClick={() => setShowPw(v => ({ ...v, [key]: !v[key] }))}
      style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', color: 'var(--fg-3)', cursor: 'pointer', padding: 0 }}>
      <i className={`bi bi-eye${showPw[key] ? '-slash' : ''}`}/>
    </button>
  );

  const card = { background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '24px' };

  return (
    <StockLayout title="내 정보">
      <div style={{ maxWidth: 520, margin: '0 auto' }}>

        {/* 프로필 헤더 */}
        <div style={{ ...card, marginBottom: 20, display: 'flex', alignItems: 'center', gap: 16 }}>
          <div style={{
            width: 56, height: 56, borderRadius: '50%',
            background: 'var(--accent)', color: '#fff',
            fontSize: '1.4rem', fontWeight: 800,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            flexShrink: 0,
          }}>
            {user?.user_name?.[0] || '?'}
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--fg-1)' }}>{user?.user_name}님</div>
            <div style={{ fontSize: '0.78rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>{profile.user_id}</div>
            {profile.created_at && (
              <div style={{ fontSize: '0.72rem', color: 'var(--fg-3)', marginTop: 2 }}>
                가입일 {String(profile.created_at).slice(0, 10)}
              </div>
            )}
          </div>
        </div>

        {/* 탭 */}
        <div style={{ display: 'flex', gap: 0, marginBottom: 16, background: 'var(--bg-3)', borderRadius: 'var(--r-2)', padding: 3 }}>
          {[{ key: TAB.info, label: '기본 정보', icon: 'bi-person' }, { key: TAB.pw, label: '비밀번호 변경', icon: 'bi-lock' }, { key: TAB.credit, label: '크레딧/충전', icon: 'bi-coin' }].map(t => (
            <button key={t.key} onClick={() => { setTab(t.key); setInfoMsg({ type:'',text:'' }); setPwMsg({ type:'',text:'' }); setCreditMsg({ type:'',text:'' }); }}
              style={{
                flex: 1, padding: '8px 0', border: 'none', borderRadius: 'var(--r-2)',
                fontSize: '0.85rem', fontWeight: 600, cursor: 'pointer', transition: 'all 0.15s',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                background: tab === t.key ? 'var(--bg-2)' : 'transparent',
                color: tab === t.key ? 'var(--accent)' : 'var(--fg-3)',
                boxShadow: tab === t.key ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
              }}>
              <i className={`bi ${t.icon}`}/>{t.label}
            </button>
          ))}
        </div>

        {/* ── 기본 정보 탭 ── */}
        {tab === TAB.info && (
          <div style={card}>
            {infoLoading ? (
              <div style={{ textAlign: 'center', padding: '40px 0' }}>
                <div className="spinner" style={{ margin: '0 auto' }}/>
              </div>
            ) : (
              <form onSubmit={saveInfo}>
                <Alert type={infoMsg.type} msg={infoMsg.text}/>
                <Field label="아이디 (변경 불가)">
                  <input className="form-control" value={profile.user_id} disabled
                    style={{ background: 'var(--bg-3)', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}/>
                </Field>
                <Field label="이름">
                  <input className="form-control" value={profile.name} maxLength={50}
                    onChange={e => setProfile(p => ({ ...p, name: e.target.value }))} required/>
                </Field>
                <Field label="이메일">
                  <input className="form-control" type="email" value={profile.email} maxLength={100}
                    onChange={e => setProfile(p => ({ ...p, email: e.target.value }))} required/>
                </Field>
                <button className="btn btn-primary w-100 mt-2" type="submit" disabled={infoSaving}>
                  {infoSaving ? '저장 중...' : '정보 저장'}
                </button>
              </form>
            )}
          </div>
        )}

        {/* ── 비밀번호 변경 탭 ── */}
        {tab === TAB.pw && (
          <div style={card}>
            <form onSubmit={changePw}>
              <Alert type={pwMsg.type} msg={pwMsg.text}/>
              <Field label="현재 비밀번호">
                <div style={{ position: 'relative' }}>
                  <input className="form-control" type={showPw.cur ? 'text' : 'password'}
                    value={pw.current_password} placeholder="현재 비밀번호 입력"
                    onChange={e => setPw(p => ({ ...p, current_password: e.target.value }))} required
                    style={{ paddingRight: 40 }}/>
                  {eye('cur')}
                </div>
              </Field>
              <Field label="새 비밀번호">
                <div style={{ position: 'relative' }}>
                  <input className="form-control" type={showPw.nw ? 'text' : 'password'}
                    value={pw.new_password} placeholder="6자 이상 입력"
                    onChange={e => setPw(p => ({ ...p, new_password: e.target.value }))} required
                    style={{ paddingRight: 40 }}/>
                  {eye('nw')}
                </div>
                {pw.new_password.length > 0 && (
                  <div style={{ marginTop: 6, display: 'flex', gap: 4 }}>
                    {[
                      { ok: pw.new_password.length >= 6, label: '6자 이상' },
                      { ok: /[A-Za-z]/.test(pw.new_password), label: '영문 포함' },
                      { ok: /[0-9]/.test(pw.new_password), label: '숫자 포함' },
                    ].map(({ ok, label }) => (
                      <span key={label} style={{
                        fontSize: '0.7rem', padding: '2px 7px', borderRadius: 10,
                        background: ok ? 'var(--lime-soft, #f0fdf4)' : 'var(--bg-3)',
                        color: ok ? 'var(--up)' : 'var(--fg-3)',
                        border: `1px solid ${ok ? 'var(--lime-border, #86efac)' : 'var(--line-1)'}`,
                      }}>{ok ? '✓' : '·'} {label}</span>
                    ))}
                  </div>
                )}
              </Field>
              <Field label="새 비밀번호 확인">
                <div style={{ position: 'relative' }}>
                  <input className="form-control" type={showPw.cf ? 'text' : 'password'}
                    value={pw.confirm} placeholder="새 비밀번호 재입력"
                    onChange={e => setPw(p => ({ ...p, confirm: e.target.value }))} required
                    style={{
                      paddingRight: 40,
                      borderColor: pw.confirm && pw.confirm !== pw.new_password ? 'var(--down)' : undefined,
                    }}/>
                  {eye('cf')}
                </div>
                {pw.confirm && pw.confirm !== pw.new_password && (
                  <div style={{ fontSize: '0.75rem', color: 'var(--down)', marginTop: 4 }}>
                    비밀번호가 일치하지 않습니다.
                  </div>
                )}
              </Field>
              <button className="btn btn-primary w-100 mt-2" type="submit"
                disabled={pwSaving || (pw.confirm && pw.confirm !== pw.new_password)}>
                {pwSaving ? '변경 중...' : '비밀번호 변경'}
              </button>
            </form>
          </div>
        )}

        {/* ── 크레딧/충전 탭 ── */}
        {tab === TAB.credit && (
          <div>
            {/* 잔액 */}
            <div style={{ ...card, marginBottom: 16, textAlign: 'center', position: 'relative' }}>
              <div style={{ fontSize: '0.78rem', color: 'var(--fg-3)', marginBottom: 6 }}>보유 크레딧</div>
              <div style={{ fontSize: '2rem', fontWeight: 800, color: 'var(--accent)', fontFamily: 'var(--font-mono)' }}>
                {balance === null ? '—' : balance.toLocaleString()}
                <span style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--fg-3)', marginLeft: 4 }}>C</span>
              </div>
              <div style={{ fontSize: '0.72rem', color: 'var(--fg-3)', marginTop: 4 }}>1원 = 1크레딧</div>
            </div>

            {/* 충전 */}
            <div style={{ ...card, marginBottom: 16 }}>
              <Alert type={creditMsg.type} msg={creditMsg.text}/>
              {creditMock && (
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: '10px 14px', borderRadius: 'var(--r-2)', marginBottom: 16, fontSize: '0.8rem',
                  background: 'var(--bg-3)', border: '1px dashed var(--line-1)', color: 'var(--fg-3)',
                }}>
                  <i className="bi bi-info-circle"/>
                  테스트(mock) 모드입니다. 실제 결제 없이 즉시 충전됩니다.
                </div>
              )}
              <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--fg-2)', marginBottom: 10 }}>충전 금액 선택</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 16 }}>
                {CHARGE_AMOUNTS.map(a => (
                  <button key={a} type="button" onClick={() => setSelAmount(a)}
                    style={{
                      padding: '12px 0', borderRadius: 'var(--r-2)', cursor: 'pointer',
                      fontSize: '0.85rem', fontWeight: 700, transition: 'all 0.15s',
                      background: selAmount === a ? 'var(--accent)' : 'var(--bg-3)',
                      color: selAmount === a ? '#fff' : 'var(--fg-2)',
                      border: `1px solid ${selAmount === a ? 'var(--accent)' : 'var(--line-1)'}`,
                    }}>
                    {a.toLocaleString()}원
                  </button>
                ))}
              </div>
              <button className="btn btn-primary w-100" type="button" onClick={charge} disabled={charging}>
                {charging ? '처리 중...' : `${selAmount.toLocaleString()}원 충전하기`}
              </button>
            </div>

            {/* AI 추천받기 데이 패스 */}
            <div style={{ ...card, marginBottom: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--fg-1)' }}>
                    <i className="bi bi-stars" style={{ marginRight: 6, color: 'var(--accent)' }}/>AI 추천받기
                  </div>
                  <div style={{ fontSize: '0.74rem', color: 'var(--fg-3)', marginTop: 4, lineHeight: 1.5 }}>
                    하루 {Number(pass?.cost ?? 1000).toLocaleString()} C로 AI 추천 종목을 열람합니다.
                    <br/>기준 시각 한국시간 07:00 · 같은 날 껐다 켜도 재차감 없음
                  </div>
                  {pass?.active && pass?.expires_at && (
                    <div style={{ fontSize: '0.72rem', color: 'var(--up)', marginTop: 4, fontWeight: 600 }}>
                      <i className="bi bi-check-circle" style={{ marginRight: 4 }}/>{pass.expires_at} 까지 활성
                    </div>
                  )}
                </div>
                <button type="button" onClick={onTogglePass} disabled={passBusy || pass === null}
                  aria-pressed={!!pass?.active}
                  style={{
                    flexShrink: 0, width: 52, height: 30, borderRadius: 15, border: 'none', position: 'relative',
                    cursor: passBusy || pass === null ? 'default' : 'pointer',
                    background: pass?.active ? 'var(--accent)' : 'var(--bg-3)',
                    border: `1px solid ${pass?.active ? 'var(--accent)' : 'var(--line-1)'}`,
                    opacity: passBusy || pass === null ? 0.6 : 1, transition: 'all 0.15s',
                  }}>
                  <span style={{
                    position: 'absolute', top: 3, left: pass?.active ? 24 : 3, width: 22, height: 22,
                    borderRadius: '50%', background: '#fff', boxShadow: '0 1px 3px rgba(0,0,0,0.2)', transition: 'left 0.15s',
                  }}/>
                </button>
              </div>
            </div>

            {/* AI 챗봇 */}
            <div style={{ ...card, marginBottom: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--fg-2)' }}>
                  <i className="bi bi-robot" style={{ marginRight: 6 }}/>AI 챗봇
                </div>
                {chatEnabled && (
                  <span style={{ fontSize: '0.72rem', color: 'var(--fg-3)' }}>호출당 {chatCost.toLocaleString()} C 차감</span>
                )}
              </div>

              {!chatEnabled ? (
                <div style={{ textAlign: 'center', color: 'var(--fg-3)', fontSize: '0.82rem', padding: '20px 0' }}>
                  AI 챗봇이 설정되지 않았습니다 (API 키 없음).
                </div>
              ) : (
                <>
                  <div style={{
                    maxHeight: 260, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 8,
                    padding: '4px 2px', marginBottom: 12,
                  }}>
                    {chatLog.length === 0 ? (
                      <div style={{ textAlign: 'center', color: 'var(--fg-3)', fontSize: '0.8rem', padding: '16px 0' }}>
                        궁금한 점을 물어보세요. (예: "PER이 뭐야?")
                      </div>
                    ) : chatLog.map((m, i) => (
                      <div key={i} style={{ display: 'flex', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
                        <div style={{
                          maxWidth: '85%', padding: '8px 12px', borderRadius: 12, fontSize: '0.83rem', whiteSpace: 'pre-wrap', lineHeight: 1.5,
                          background: m.role === 'user' ? 'var(--accent)' : (m.error ? 'var(--down-soft, #fef2f2)' : 'var(--bg-3)'),
                          color: m.role === 'user' ? '#fff' : (m.error ? 'var(--down)' : 'var(--fg-1)'),
                          border: m.role === 'user' ? 'none' : `1px solid ${m.error ? 'var(--down, #f87171)' : 'var(--line-1)'}`,
                        }}>
                          {m.text}
                          {m.role === 'bot' && !m.error && m.cost != null && (
                            <div style={{ fontSize: '0.68rem', color: 'var(--fg-3)', marginTop: 4 }}>−{Number(m.cost).toLocaleString()} C</div>
                          )}
                        </div>
                      </div>
                    ))}
                    {chatSending && (
                      <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
                        <div style={{ padding: '8px 12px', borderRadius: 12, fontSize: '0.83rem', background: 'var(--bg-3)', border: '1px solid var(--line-1)', color: 'var(--fg-3)' }}>
                          답변 생성 중…
                        </div>
                      </div>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <input className="form-control" value={chatInput} placeholder="메시지를 입력하세요"
                      onChange={e => setChatInput(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) sendChat(); }}
                      disabled={chatSending}/>
                    <button className="btn btn-primary" type="button" onClick={sendChat}
                      disabled={chatSending || !chatInput.trim()} style={{ flexShrink: 0 }}>
                      보내기
                    </button>
                  </div>
                </>
              )}
            </div>

            {/* 내역 */}
            <div style={card}>
              <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--fg-2)', marginBottom: 12 }}>이용 내역</div>
              {creditLoading ? (
                <div style={{ textAlign: 'center', padding: '24px 0' }}><div className="spinner" style={{ margin: '0 auto' }}/></div>
              ) : txns.length === 0 ? (
                <div style={{ textAlign: 'center', color: 'var(--fg-3)', fontSize: '0.82rem', padding: '24px 0' }}>
                  아직 충전/사용 내역이 없습니다.
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {txns.map(tx => {
                    const isCharge = tx.kind === 'charge';
                    return (
                      <div key={tx.id} style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        padding: '10px 4px', borderBottom: '1px solid var(--line-1)',
                      }}>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontSize: '0.83rem', color: 'var(--fg-1)', fontWeight: 600 }}>
                            {tx.memo || (isCharge ? '크레딧 충전' : '크레딧 사용')}
                          </div>
                          <div style={{ fontSize: '0.7rem', color: 'var(--fg-3)' }}>{tx.created_at}</div>
                        </div>
                        <div style={{ textAlign: 'right', flexShrink: 0, marginLeft: 12 }}>
                          <div style={{ fontSize: '0.85rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: isCharge ? 'var(--up)' : 'var(--down)' }}>
                            {isCharge ? '+' : '−'}{Number(tx.amount).toLocaleString()}
                          </div>
                          <div style={{ fontSize: '0.7rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>
                            잔액 {Number(tx.balance_after).toLocaleString()}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* AI 추천받기 ON 경고 모달 */}
      {showPassModal && (
        <div onClick={() => setShowPassModal(false)}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000,
            display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20,
          }}>
          <div onClick={e => e.stopPropagation()}
            style={{
              background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)',
              padding: 24, maxWidth: 380, width: '100%', boxShadow: 'var(--menu-shadow, 0 8px 30px rgba(0,0,0,0.2))',
            }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
              <i className="bi bi-exclamation-triangle-fill" style={{ fontSize: '1.3rem', color: 'var(--accent)' }}/>
              <div style={{ fontSize: '1rem', fontWeight: 800, color: 'var(--fg-1)' }}>크레딧 차감 안내</div>
            </div>
            <div style={{ fontSize: '0.86rem', color: 'var(--fg-2)', lineHeight: 1.65, marginBottom: 8 }}>
              AI 추천받기를 켜면 <b style={{ color: 'var(--accent)' }}>{Number(pass?.cost ?? 1000).toLocaleString()} 크레딧</b>이 즉시 차감됩니다.
            </div>
            <ul style={{ fontSize: '0.78rem', color: 'var(--fg-3)', lineHeight: 1.7, paddingLeft: 18, margin: '0 0 18px' }}>
              <li>오늘(한국시간 07:00 기준) 하루 동안 AI 추천이 열립니다.</li>
              <li>같은 날 껐다 다시 켜도 재차감되지 않습니다.</li>
              <li>끄더라도 환불되지 않습니다.</li>
            </ul>
            <div style={{
              fontSize: '0.78rem', color: 'var(--fg-3)', marginBottom: 18,
              padding: '8px 12px', background: 'var(--bg-3)', borderRadius: 'var(--r-2)',
            }}>
              현재 잔액 <b style={{ color: 'var(--fg-1)', fontFamily: 'var(--font-mono)' }}>{balance === null ? '—' : balance.toLocaleString()} C</b>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="button" className="btn" onClick={() => setShowPassModal(false)}
                style={{ flex: 1, background: 'var(--bg-3)', border: '1px solid var(--line-1)', color: 'var(--fg-2)' }}>
                취소
              </button>
              <button type="button" className="btn btn-primary" onClick={enablePass}
                disabled={balance !== null && balance < (pass?.cost ?? 1000)}
                style={{ flex: 1 }}>
                {balance !== null && balance < (pass?.cost ?? 1000) ? '크레딧 부족' : '차감하고 켜기'}
              </button>
            </div>
          </div>
        </div>
      )}
    </StockLayout>
  );
}
