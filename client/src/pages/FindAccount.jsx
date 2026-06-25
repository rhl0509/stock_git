import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../api/index.js';

const TAB = { id: 'id', pw: 'pw' };

export default function FindAccount() {
  const [tab, setTab] = useState(TAB.id);

  // 아이디 찾기
  const [idForm, setIdForm]     = useState({ name: '', email: '' });
  const [idResult, setIdResult] = useState(null);
  const [idError, setIdError]   = useState('');
  const [idLoading, setIdLoading] = useState(false);

  // 비밀번호 찾기
  const [pwForm, setPwForm]     = useState({ user_id: '', email: '' });
  const [pwResult, setPwResult] = useState(null);
  const [pwError, setPwError]   = useState('');
  const [pwLoading, setPwLoading] = useState(false);

  const findId = async e => {
    e.preventDefault();
    setIdError(''); setIdResult(null); setIdLoading(true);
    try {
      const r = await api.post('/auth/find-id', idForm);
      setIdResult(r.data);
    } catch (err) {
      setIdError(err.response?.data?.error || '아이디 찾기에 실패했습니다.');
    }
    setIdLoading(false);
  };

  const findPw = async e => {
    e.preventDefault();
    setPwError(''); setPwResult(null); setPwLoading(true);
    try {
      const r = await api.post('/auth/find-password', pwForm);
      setPwResult(r.data);
    } catch (err) {
      setPwError(err.response?.data?.error || '비밀번호 찾기에 실패했습니다.');
    }
    setPwLoading(false);
  };

  const cardStyle = {
    background: 'var(--bg-2)', border: '1px solid var(--line-1)',
    borderRadius: 'var(--r-3)', padding: '28px 24px',
  };
  const labelStyle = { fontSize: '0.8rem', fontWeight: 600, color: 'var(--fg-2)' };
  const resultBox = (color, icon, children) => (
    <div style={{
      marginTop: 20, padding: '16px 18px',
      background: color === 'success' ? 'var(--lime-soft, #f0fdf4)' : 'var(--down-soft, #fef2f2)',
      border: `1px solid ${color === 'success' ? 'var(--lime-border, #86efac)' : 'var(--down, #f87171)'}`,
      borderRadius: 'var(--r-2)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <i className={`bi bi-${icon}`} style={{ color: color === 'success' ? 'var(--up)' : 'var(--down)', fontSize: '1.1rem' }}/>
        {children}
      </div>
    </div>
  );

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-1)', padding: 16 }}>
      <div style={{ width: '100%', maxWidth: 420 }}>

        {/* 로고 */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{ width: 48, height: 48, borderRadius: 12, background: 'var(--accent)', color: '#fff', fontSize: '1.3rem', fontWeight: 800, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginBottom: 12 }}>주</div>
          <h1 style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--fg-1)', margin: '0 0 4px' }}>GAGYE</h1>
          <p style={{ fontSize: '0.83rem', color: 'var(--fg-3)', margin: 0 }}>계정 찾기</p>
        </div>

        <div style={cardStyle}>
          {/* 탭 */}
          <div style={{ display: 'flex', gap: 0, marginBottom: 24, background: 'var(--bg-3)', borderRadius: 'var(--r-2)', padding: 3 }}>
            {[{ key: TAB.id, label: '아이디 찾기' }, { key: TAB.pw, label: '비밀번호 찾기' }].map(t => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                style={{
                  flex: 1, padding: '8px 0', border: 'none', borderRadius: 'var(--r-2)',
                  fontSize: '0.85rem', fontWeight: 600, cursor: 'pointer', transition: 'all 0.15s',
                  background: tab === t.key ? 'var(--bg-2)' : 'transparent',
                  color: tab === t.key ? 'var(--accent)' : 'var(--fg-3)',
                  boxShadow: tab === t.key ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
                }}
              >{t.label}</button>
            ))}
          </div>

          {/* ── 아이디 찾기 ── */}
          {tab === TAB.id && (
            <>
              <p style={{ fontSize: '0.8rem', color: 'var(--fg-3)', marginBottom: 18 }}>
                가입 시 등록한 <b>이름</b>과 <b>이메일</b>로 아이디를 확인할 수 있습니다.
              </p>
              {idError && (
                <div className="alert alert-danger" style={{ fontSize: '0.83rem', padding: '10px 14px', marginBottom: 16 }}>
                  <i className="bi bi-exclamation-triangle me-1"/>{idError}
                </div>
              )}
              <form onSubmit={findId}>
                <div className="mb-3">
                  <label className="form-label" style={labelStyle}>이름</label>
                  <input className="form-control" type="text" value={idForm.name} placeholder="가입 시 입력한 이름"
                    onChange={e => setIdForm(f => ({ ...f, name: e.target.value }))} required autoFocus />
                </div>
                <div className="mb-4">
                  <label className="form-label" style={labelStyle}>이메일</label>
                  <input className="form-control" type="email" value={idForm.email} placeholder="가입 시 입력한 이메일"
                    onChange={e => setIdForm(f => ({ ...f, email: e.target.value }))} required />
                </div>
                <button className="btn btn-primary w-100" type="submit" disabled={idLoading}>
                  {idLoading ? '조회 중...' : '아이디 찾기'}
                </button>
              </form>

              {idResult && resultBox('success', 'person-check-fill',
                <div>
                  <div style={{ fontSize: '0.82rem', color: 'var(--fg-3)', marginBottom: 4 }}>아이디 힌트</div>
                  <div style={{ fontSize: '1.3rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: 'var(--fg-1)', letterSpacing: 2 }}>
                    {idResult.hint}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--fg-3)', marginTop: 6 }}>
                    {idResult.message || '전체 아이디는 가입 이메일로 확인하세요.'}
                  </div>
                  {idResult.created_at && (
                    <div style={{ fontSize: '0.75rem', color: 'var(--fg-3)', marginTop: 4 }}>
                      가입일: {idResult.created_at}
                    </div>
                  )}
                </div>
              )}
            </>
          )}

          {/* ── 비밀번호 찾기 ── */}
          {tab === TAB.pw && (
            <>
              <p style={{ fontSize: '0.8rem', color: 'var(--fg-3)', marginBottom: 18 }}>
                아이디와 이메일이 일치하면 <b>비밀번호 재설정 링크</b>를 가입 이메일로 보내 드립니다.<br/>
                메일의 링크에서 새 비밀번호를 직접 설정하세요. (링크 30분 유효)
              </p>
              {pwError && (
                <div className="alert alert-danger" style={{ fontSize: '0.83rem', padding: '10px 14px', marginBottom: 16 }}>
                  <i className="bi bi-exclamation-triangle me-1"/>{pwError}
                </div>
              )}
              {!pwResult ? (
                <form onSubmit={findPw}>
                  <div className="mb-3">
                    <label className="form-label" style={labelStyle}>아이디</label>
                    <input className="form-control" type="text" value={pwForm.user_id} placeholder="가입 시 사용한 아이디"
                      onChange={e => setPwForm(f => ({ ...f, user_id: e.target.value }))} required autoFocus />
                  </div>
                  <div className="mb-4">
                    <label className="form-label" style={labelStyle}>이메일</label>
                    <input className="form-control" type="email" value={pwForm.email} placeholder="가입 시 입력한 이메일"
                      onChange={e => setPwForm(f => ({ ...f, email: e.target.value }))} required />
                  </div>
                  <button className="btn btn-primary w-100" type="submit" disabled={pwLoading}>
                    {pwLoading ? '처리 중...' : '재설정 링크 보내기'}
                  </button>
                </form>
              ) : (
                <div style={{ textAlign: 'center' }}>
                  <div style={{
                    background: 'var(--bg-3)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-2)',
                    padding: '20px', marginBottom: 16,
                  }}>
                    <i className="bi bi-envelope-check-fill" style={{ fontSize: '1.8rem', color: 'var(--up)' }}/>
                    <div style={{ fontSize: '0.85rem', color: 'var(--fg-2)', marginTop: 10, lineHeight: 1.6 }}>
                      {pwResult.message || '입력하신 정보와 일치하는 계정이 있다면 재설정 링크를 이메일로 보냈습니다.'}
                    </div>
                  </div>
                  <div style={{ fontSize: '0.78rem', color: 'var(--fg-3)', marginBottom: 16 }}>
                    <i className="bi bi-info-circle me-1"/>
                    메일이 보이지 않으면 스팸함도 확인해 주세요. (링크 30분 유효)
                  </div>
                  <button className="btn btn-outline-secondary btn-sm" onClick={() => { setPwResult(null); setPwForm({ user_id: '', email: '' }); }}>
                    다시 보내기
                  </button>
                </div>
              )}
            </>
          )}
        </div>

        {/* 하단 링크 */}
        <p style={{ textAlign: 'center', marginTop: 20, fontSize: '0.82rem', color: 'var(--fg-3)' }}>
          <Link to="/login" style={{ color: 'var(--accent)', fontWeight: 600, textDecoration: 'none' }}>
            <i className="bi bi-arrow-left me-1"/>로그인으로 돌아가기
          </Link>
        </p>
      </div>
    </div>
  );
}
