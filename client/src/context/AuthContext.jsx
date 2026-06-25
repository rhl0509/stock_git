import React, { createContext, useContext, useState, useEffect } from 'react';
import api from '../api/index.js';

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
    await api.post('/auth/login', { user_id, password });
    const me = await api.get('/auth/me');
    setUser(me.data);
    // return 없음 — 성공 시 undefined 반환
  };

  const logout = async () => {
    try { await api.post('/auth/logout', {}); } catch {}
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() { return useContext(AuthContext); }
