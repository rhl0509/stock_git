import axios from 'axios';

const api = axios.create({
  baseURL:         '/',
  withCredentials: true,
  headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
});

api.interceptors.response.use(
  res => res,
  err => {
    if (err.response?.status === 401 && !window.location.pathname.includes('/login'))
      window.location.href = '/login';
    return Promise.reject(err);
  }
);

export default api;
