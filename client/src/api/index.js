import axios from 'axios';
import { Capacitor } from '@capacitor/core';
import { getToken, clearToken } from './token';

// 웹: 같은 오리진에서 서빙되므로 상대경로 '/'.
// 네이티브(Capacitor): 앱은 capacitor://localhost / http://localhost 에서 돌아 API가 없으므로
// 배포 서버 절대 URL(VITE_API_BASE)로 보내고 Bearer 토큰으로 인증한다(쿠키 미동작).
const API_BASE = Capacitor.isNativePlatform()
  ? (import.meta.env.VITE_API_BASE || '')
  : '/';

const api = axios.create({
  baseURL:         API_BASE,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
});

// 모바일 앱용: 저장된 Bearer 토큰을 모든 요청에 첨부(웹은 쿠키 세션이 우선이라 무해).
api.interceptors.request.use(config => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  res => res,
  err => {
    if (err.response?.status === 401 && !window.location.pathname.includes('/login')) {
      clearToken();
      window.location.href = '/login';
    }
    return Promise.reject(err);
  }
);

export default api;
