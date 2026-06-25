import React, { useState, useEffect, useRef } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

export default function AlertConfig() {
  const [form, setForm]           = useState({ kakao_access_token: '', kakao_refresh_token: '' });
  const [emailForm, setEmailForm] = useState({ email_enabled:'0', email_to:'', email_user:'', email_password:'', email_smtp_host:'smtp.gmail.com', email_smtp_port:'587' });
  const [loading,  setLoading]    = useState(true);
  const [saving,   setSaving]     = useState(false);
  const [saved,    setSaved]      = useState(false);
  const [saveError,setSaveError]  = useState('');
  const [emailSaving, setEmailSaving] = useState(false);
  const [emailSaved,  setEmailSaved]  = useState(false);
  const [emailTesting,setEmailTesting]= useState(false);
  const [emailTestMsg,setEmailTestMsg]= useState('');
  const savedTimerRef = useRef(null);

  useEffect(() => () => clearTimeout(savedTimerRef.current), []);

  useEffect(() => {
    Promise.all([
      api.get('/api/alert_config/kakao_status').catch(() => ({ data: {} })),
      api.get('/api/settings/email').catch(() => ({ data: {} })),
    ]).then(([r1, r2]) => {
      const tokens = r1.data?.tokens || [];
      const map = Object.fromEntries(tokens.map(t => [t.key, t.preview + '...']));
      setForm(f => ({
        ...f,
        kakao_access_token:  map['KAKAO_ACCESS_TOKEN']  || '',
        kakao_refresh_token: map['KAKAO_REFRESH_TOKEN'] || '',
      }));
      const cfg = r2.data?.config || {};
      setEmailForm(f => ({ ...f,
        email_enabled:   cfg.email_enabled   ?? '0',
        email_to:        cfg.email_to        ?? '',
        email_user:      cfg.email_user      ?? '',
        email_password:  cfg.email_password  ?? '',
        email_smtp_host: cfg.email_smtp_host ?? 'smtp.gmail.com',
        email_smtp_port: cfg.email_smtp_port ?? '587',
      }));
    }).finally(() => setLoading(false));
  }, []);

  const save = async () => {
    setSaving(true); setSaveError('');
    try {
      await api.post('/api/alert_config/kakao_token', {
        access_token:  form.kakao_access_token,
        refresh_token: form.kakao_refresh_token,
      });
      setSaved(true);
      clearTimeout(savedTimerRef.current);
      savedTimerRef.current = setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setSaveError(err.response?.data?.error || '저장 실패');
    }
    setSaving(false);
  };

  if (loading) return <StockLayout title="알림 설정"><div style={{ textAlign:'center', padding:'80px 0' }}><div className="spinner" style={{ margin:'0 auto' }}/></div></StockLayout>;

  return (
    <StockLayout title="알림 설정">
      <div style={{ maxWidth:560, margin:'0 auto', display:'grid', gap:16 }}>
        {/* 카카오 설정 */}
        <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'20px' }}>
          <div style={{ fontWeight:700, fontSize:'0.9rem', color:'var(--fg-1)', marginBottom:16, display:'flex', alignItems:'center', gap:8 }}>
            <i className="bi bi-chat-fill" style={{ color:'#FEE500' }}/>KakaoTalk 알림 설정
          </div>
          <div style={{ padding:'10px 14px', background:'var(--lime-soft)', border:'1px solid var(--lime-border)', borderRadius:'var(--r-2)', fontSize:'0.78rem', color:'var(--fg-2)', marginBottom:16 }}>
            <i className="bi bi-info-circle me-1"/>Kakao Developers에서 발급한 Access Token을 입력하세요. 저장된 토큰은 보안을 위해 앞 8자만 표시됩니다.
          </div>
          <div style={{ display:'grid', gap:12 }}>
            <div>
              <label className="form-label" style={{ fontSize:'0.78rem', fontWeight:600, color:'var(--fg-2)' }}>Access Token</label>
              <input className="form-control" type="text" value={form.kakao_access_token} placeholder="새 Access Token 입력"
                onChange={e => setForm(f=>({...f, kakao_access_token: e.target.value}))} />
            </div>
            <div>
              <label className="form-label" style={{ fontSize:'0.78rem', fontWeight:600, color:'var(--fg-2)' }}>Refresh Token</label>
              <input className="form-control" type="text" value={form.kakao_refresh_token} placeholder="새 Refresh Token 입력"
                onChange={e => setForm(f=>({...f, kakao_refresh_token: e.target.value}))} />
            </div>
          </div>
        </div>

        {/* 이메일 알림 설정 */}
        <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'20px' }}>
          <div style={{ fontWeight:700, fontSize:'0.9rem', color:'var(--fg-1)', marginBottom:16, display:'flex', alignItems:'center', gap:8 }}>
            <i className="bi bi-envelope-fill" style={{ color:'#3b82f6' }}/>이메일 알림 설정
          </div>
          <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:14 }}>
            <label style={{ fontSize:'0.83rem', color:'var(--fg-2)', cursor:'pointer', display:'flex', alignItems:'center', gap:8 }}>
              <input type="checkbox" checked={emailForm.email_enabled === '1'}
                onChange={e => setEmailForm(f => ({...f, email_enabled: e.target.checked ? '1' : '0'}))} />
              이메일 알림 활성화
            </label>
          </div>
          {emailForm.email_enabled === '1' && (
            <div style={{ display:'grid', gap:10 }}>
              {[['email_to','수신 이메일 (to)','text','you@gmail.com'],
                ['email_user','발신 계정 (SMTP 로그인)','text','sender@gmail.com'],
                ['email_password','앱 비밀번호','password','Google 앱 비밀번호'],
                ['email_smtp_host','SMTP 호스트','text','smtp.gmail.com'],
                ['email_smtp_port','SMTP 포트','text','587'],
              ].map(([k,l,t,ph]) => (
                <div key={k}>
                  <label style={{ fontSize:'0.72rem', color:'var(--fg-3)', fontWeight:600, display:'block', marginBottom:3 }}>{l}</label>
                  <input className="form-control" type={t} value={emailForm[k]} placeholder={ph}
                    onChange={e => setEmailForm(f => ({...f, [k]: e.target.value}))} />
                </div>
              ))}
              <div style={{ display:'flex', gap:8, marginTop:4 }}>
                <button onClick={async () => {
                  setEmailSaving(true);
                  try { await api.post('/api/settings/email', emailForm); setEmailSaved(true); setTimeout(() => setEmailSaved(false), 3000); }
                  catch (e) { alert(e.response?.data?.message || '저장 실패'); }
                  setEmailSaving(false);
                }} disabled={emailSaving}
                  style={{ background:'var(--accent)', color:'#fff', border:'none', borderRadius:'var(--r-2)', padding:'7px 16px', fontSize:'0.8rem', fontWeight:700, cursor:'pointer' }}>
                  {emailSaving ? '저장 중...' : '저장'}
                </button>
                <button onClick={async () => {
                  setEmailTesting(true); setEmailTestMsg('');
                  try { const r = await api.post('/api/settings/email/test'); setEmailTestMsg(r.data?.message || '완료'); }
                  catch (e) { setEmailTestMsg('실패: ' + (e.response?.data?.message || e.message)); }
                  setEmailTesting(false);
                }} disabled={emailTesting}
                  style={{ background:'var(--bg-3)', color:'var(--fg-2)', border:'1px solid var(--line-2)', borderRadius:'var(--r-2)', padding:'7px 14px', fontSize:'0.8rem', cursor:'pointer' }}>
                  {emailTesting ? '발송 중...' : '테스트 발송'}
                </button>
                {emailSaved && <span style={{ color:'var(--up)', fontSize:'0.8rem', alignSelf:'center' }}>✓ 저장됨</span>}
                {emailTestMsg && <span style={{ fontSize:'0.78rem', color:'var(--fg-2)', alignSelf:'center' }}>{emailTestMsg}</span>}
              </div>
            </div>
          )}
        </div>

        {/* 스케줄 안내 */}
        <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'20px' }}>
          <div style={{ fontWeight:700, fontSize:'0.9rem', color:'var(--fg-1)', marginBottom:14 }}>
            <i className="bi bi-clock me-2" style={{ color:'var(--accent)' }}/>자동 실행 스케줄
          </div>
          {[
            ['08:40',    '개장전 뉴스 크롤링 + 카카오 알림'],
            ['9:00~15:00 (30분마다)', 'DART 공시 체크'],
            ['9:00~15:00 (10분마다)', '가격 알림 체크'],
            ['20:00',    'AI 일일 추천 생성 + 카카오 발송'],
            ['매주 일 02:00', 'XGBoost 모델 재학습'],
          ].map(([t,d]) => (
            <div key={t} style={{ display:'flex', gap:12, padding:'8px 0', borderBottom:'1px solid var(--line-1)', fontSize:'0.83rem' }}>
              <span style={{ fontFamily:'var(--font-mono)', fontWeight:700, color:'var(--accent)', minWidth:180, flexShrink:0 }}>{t}</span>
              <span style={{ color:'var(--fg-2)' }}>{d}</span>
            </div>
          ))}
        </div>

        {saveError && <div className="alert alert-danger" style={{fontSize:'0.83rem',padding:'10px 14px',marginBottom:12}}>{saveError}</div>}
        {saved && <div className="alert" style={{ background:'var(--lime-soft)', border:'1px solid var(--lime-border)', borderRadius:'var(--r-2)', padding:'10px 14px', fontSize:'0.83rem', color:'var(--accent)', display:'flex', alignItems:'center', gap:8 }}>
          <i className="bi bi-check-circle-fill"/>저장되었습니다.
        </div>}
        <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? '저장 중...' : '토큰 저장'}</button>
      </div>
    </StockLayout>
  );
}
