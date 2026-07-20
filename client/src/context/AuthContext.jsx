import React, { createContext, useContext, useState, useEffect } from 'react';
import api from '../api/index.js';
import { setToken, clearToken } from '../api/token.js';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser]       = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/auth/me')
      .then(r => setUser(r.data))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const login = async (user_id, password) => {
    const res = await api.post('/auth/login', { user_id, password });
    if (res.data?.token) setToken(res.data.token);   // 모바일 앱용 Bearer 토큰 저장
    const me = await api.get('/auth/me');
    setUser(me.data);
    // return 없음 — 성공 시 undefined 반환
  };

  const logout = async () => {
    try { await api.post('/auth/logout', {}); } catch {}
    clearToken();
    setUser(null);
  };

  // 등급/ai_access 가 서버에서 바뀐 뒤(예: 충전 자동 승급) 최신 상태로 다시 불러온다.
  const refreshUser = async () => {
    try {
      const me = await api.get('/auth/me');
      setUser(me.data);
      return me.data;
    } catch {
      return null;
    }
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() { return useContext(AuthContext); }
