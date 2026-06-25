import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import api from '../api/index.js';

export default function Register() {
  const navigate = useNavigate();
  const [form, setForm]   = useState({ user_id: '', name: '', email: '', password: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const submit = async e => {
    e.preventDefault();
    // 클라이언트 검증
    if (form.user_id.length < 3) return setError('아이디는 3자 이상이어야 합니다.');
    if (form.password.length < 6) return setError('비밀번호는 6자 이상이어야 합니다.');
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) return setError('올바른 이메일 형식이 아닙니다.');
    setError(''); setLoading(true);
    try {
      await api.post('/auth/register', form);
      navigate('/login');
    } catch (err) {
      setError(err.response?.data?.error || '회원가입에 실패했습니다.');
      setLoading(false); // 성공 시 언마운트되므로 에러 시에만 처리
    }
  };

  const field = (key, label, type = 'text', placeholder = '') => (
    <div className="mb-3">
      <label className="form-label" style={{ fontSize:'0.8rem', fontWeight:600, color:'var(--fg-2)' }}>{label}</label>
      <input className="form-control" type={type} value={form[key]}
        onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
        placeholder={placeholder} required />
    </div>
  );

  return (
    <div style={{ minHeight:'100vh', display:'flex', alignItems:'center', justifyContent:'center', background:'var(--bg-1)', padding:16 }}>
      <div style={{ width:'100%', maxWidth:400 }}>
        <div style={{ textAlign:'center', marginBottom:32 }}>
          <div style={{ width:48, height:48, borderRadius:12, background:'var(--accent)', color:'#fff', fontSize:'1.3rem', fontWeight:800, display:'inline-flex', alignItems:'center', justifyContent:'center', marginBottom:12 }}>주</div>
          <h1 style={{ fontSize:'1.4rem', fontWeight:700, color:'var(--fg-1)', margin:'0 0 4px' }}>GAGYE</h1>
          <p style={{ fontSize:'0.83rem', color:'var(--fg-3)', margin:0 }}>주식 현황 · 포트폴리오 · AI 분석</p>
        </div>

        <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'28px 24px' }}>
          <h2 style={{ fontSize:'1rem', fontWeight:700, color:'var(--fg-1)', marginBottom:20 }}>회원가입</h2>
          {error && <div className="alert alert-danger" style={{ fontSize:'0.83rem', padding:'10px 14px', marginBottom:16 }}>{error}</div>}
          <form onSubmit={submit}>
            {field('user_id',  '아이디',   'text',     '영문/숫자 조합')}
            {field('name',     '이름',     'text',     '이름을 입력하세요')}
            {field('email',    '이메일',   'email',    'example@email.com')}
            {field('password', '비밀번호', 'password', '6자 이상 입력하세요')}
            <button className="btn btn-primary w-100 mt-1" type="submit" disabled={loading}>
              {loading ? '처리 중...' : '회원가입'}
            </button>
          </form>
        </div>

        <p style={{ textAlign:'center', marginTop:20, fontSize:'0.82rem', color:'var(--fg-3)' }}>
          이미 계정이 있으신가요?&nbsp;
          <Link to="/login" style={{ color:'var(--accent)', fontWeight:600, textDecoration:'none' }}>로그인</Link>
        </p>
      </div>
    </div>
  );
}
