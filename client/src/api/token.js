// Bearer 토큰 저장소.
// 웹은 쿠키 세션으로도 인증되지만, Capacitor 앱(서드파티 쿠키 차단)은 토큰이 필수다.
// 현재는 localStorage 사용. P2에서 네이티브는 @capacitor/preferences 로 교체 예정.
const KEY = 'auth_token';

export function getToken() {
  try { return localStorage.getItem(KEY) || ''; } catch { return ''; }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(KEY, token);
    else localStorage.removeItem(KEY);
  } catch { /* 저장 불가 환경 무시 */ }
}

export function clearToken() {
  try { localStorage.removeItem(KEY); } catch { /* noop */ }
}
