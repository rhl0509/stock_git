import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';

export default function Login() {
  const { login } = useAuth();
  const navigate  = useNavigate();
  const [form, setForm]   = useState({ user_id: '', password: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const submit = async e => {
    e.preventDefault();
    setError(''); setLoading(true);
    try {
      await login(form.user_id, form.password);
      navigate('/stock_live');
    } catch (err) {
      setError(err.response?.data?.error || '로그인에 실패했습니다.');
    }
    setLoading(false);
  };

  return (
    <div style={{ minHeight:'100vh', display:'flex', alignItems:'center', justifyContent:'center', background:'var(--bg-1)', padding:16 }}>
      <div style={{ width:'100%', maxWidth:400 }}>
        <div style={{ textAlign:'center', marginBottom:32 }}>
          <div style={{ width:48, height:48, borderRadius:12, background:'var(--accent)', color:'#fff', fontSize:'1.3rem', fontWeight:800, display:'inline-flex', alignItems:'center', justifyContent:'center', marginBottom:12 }}>주</div>
          <h1 style={{ fontSize:'1.4rem', fontWeight:700, color:'var(--fg-1)', margin:'0 0 4px' }}>GAGYE</h1>
          <p style={{ fontSize:'0.83rem', color:'var(--fg-3)', margin:0 }}>주식 현황 · 포트폴리오 · AI 분석</p>
        </div>

        <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'28px 24px' }}>
          <h2 style={{ fontSize:'1rem', fontWeight:700, color:'var(--fg-1)', marginBottom:20 }}>로그인</h2>
          {error && <div className="alert alert-danger" style={{ fontSize:'0.83rem', padding:'10px 14px', marginBottom:16 }}>{error}</div>}
          <form onSubmit={submit}>
            <div className="mb-3">
              <label className="form-label" style={{ fontSize:'0.8rem', fontWeight:600, color:'var(--fg-2)' }}>아이디</label>
              <input className="form-control" type="text" value={form.user_id}
                onChange={e => setForm(f => ({ ...f, user_id: e.target.value }))}
                placeholder="아이디를 입력하세요" required autoFocus />
            </div>
            <div className="mb-4">
              <label className="form-label" style={{ fontSize:'0.8rem', fontWeight:600, color:'var(--fg-2)' }}>비밀번호</label>
              <input className="form-control" type="password" value={form.password}
                onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                placeholder="비밀번호를 입력하세요" required />
            </div>
            <button className="btn btn-primary w-100" type="submit" disabled={loading}>
              {loading ? <span className="spinner" style={{ width:16, height:16, border:'2px solid rgba(255,255,255,0.3)', borderTopColor:'#fff', margin:'0 auto' }}/> : '로그인'}
            </button>
          </form>
        </div>

        <p style={{ textAlign:'center', marginTop:20, fontSize:'0.82rem', color:'var(--fg-3)' }}>
          계정이 없으신가요?&nbsp;
          <Link to="/register" style={{ color:'var(--accent)', fontWeight:600, textDecoration:'none' }}>회원가입</Link>
        </p>
        <p style={{ textAlign:'center', marginTop:8, fontSize:'0.82rem', color:'var(--fg-3)' }}>
          <Link to="/find-account" style={{ color:'var(--fg-2)', textDecoration:'none' }}>
            아이디 · 비밀번호 찾기
          </Link>
        </p>
      </div>
    </div>
  );
}
