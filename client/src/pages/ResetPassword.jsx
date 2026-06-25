import React, { useState, useMemo } from 'react';
import { Link, useSearchParams, useNavigate } from 'react-router-dom';
import api from '../api/index.js';

export default function ResetPassword() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = useMemo(() => params.get('token') || '', [params]);

  const [pw, setPw]         = useState('');
  const [pw2, setPw2]       = useState('');
  const [error, setError]   = useState('');
  const [done, setDone]     = useState(false);
  const [loading, setLoading] = useState(false);

  const submit = async e => {
    e.preventDefault();
    setError('');
    if (pw.length < 8) { setError('비밀번호는 8자 이상이어야 합니다.'); return; }
    if (pw !== pw2)    { setError('비밀번호가 일치하지 않습니다.'); return; }
    setLoading(true);
    try {
      await api.post('/auth/reset-password', { token, password: pw });
      setDone(true);
    } catch (err) {
      setError(err.response?.data?.error || '비밀번호 변경에 실패했습니다.');
    }
    setLoading(false);
  };

  const cardStyle = {
    background: 'var(--bg-2)', border: '1px solid var(--line-1)',
    borderRadius: 'var(--r-3)', padding: '28px 24px',
  };
  const labelStyle = { fontSize: '0.8rem', fontWeight: 600, color: 'var(--fg-2)' };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-1)', padding: 16 }}>
      <div style={{ width: '100%', maxWidth: 420 }}>

        {/* 로고 */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{ width: 48, height: 48, borderRadius: 12, background: 'var(--accent)', color: '#fff', fontSize: '1.3rem', fontWeight: 800, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginBottom: 12 }}>주</div>
          <h1 style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--fg-1)', margin: '0 0 4px' }}>GAGYE</h1>
          <p style={{ fontSize: '0.83rem', color: 'var(--fg-3)', margin: 0 }}>비밀번호 재설정</p>
        </div>

        <div style={cardStyle}>
          {!token ? (
            <div style={{ textAlign: 'center', padding: '12px 0' }}>
              <i className="bi bi-exclamation-triangle" style={{ fontSize: '1.8rem', color: 'var(--down)' }}/>
              <p style={{ fontSize: '0.85rem', color: 'var(--fg-2)', marginTop: 12 }}>
                유효하지 않은 접근입니다. 비밀번호 재설정 메일의 링크로 다시 접속해주세요.
              </p>
              <Link to="/find-account" className="btn btn-outline-secondary btn-sm" style={{ marginTop: 8 }}>
                재설정 링크 다시 받기
              </Link>
            </div>
          ) : done ? (
            <div style={{ textAlign: 'center', padding: '12px 0' }}>
              <i className="bi bi-check-circle-fill" style={{ fontSize: '1.9rem', color: 'var(--up)' }}/>
              <p style={{ fontSize: '0.9rem', color: 'var(--fg-1)', marginTop: 12, fontWeight: 600 }}>
                비밀번호가 변경되었습니다.
              </p>
              <p style={{ fontSize: '0.8rem', color: 'var(--fg-3)', marginBottom: 16 }}>
                새 비밀번호로 로그인해주세요.
              </p>
              <button className="btn btn-primary w-100" onClick={() => navigate('/login')}>
                로그인하러 가기
              </button>
            </div>
          ) : (
            <>
              <p style={{ fontSize: '0.8rem', color: 'var(--fg-3)', marginBottom: 18 }}>
                새로 사용할 비밀번호를 입력하세요. (8자 이상)
              </p>
              {error && (
                <div className="alert alert-danger" style={{ fontSize: '0.83rem', padding: '10px 14px', marginBottom: 16 }}>
                  <i className="bi bi-exclamation-triangle me-1"/>{error}
                </div>
              )}
              <form onSubmit={submit}>
                <div className="mb-3">
                  <label className="form-label" style={labelStyle}>새 비밀번호</label>
                  <input className="form-control" type="password" value={pw} placeholder="8자 이상"
                    onChange={e => setPw(e.target.value)} required autoFocus />
                </div>
                <div className="mb-4">
                  <label className="form-label" style={labelStyle}>새 비밀번호 확인</label>
                  <input className="form-control" type="password" value={pw2} placeholder="다시 한 번 입력"
                    onChange={e => setPw2(e.target.value)} required />
                </div>
                <button className="btn btn-primary w-100" type="submit" disabled={loading}>
                  {loading ? '변경 중...' : '비밀번호 변경'}
                </button>
              </form>
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
