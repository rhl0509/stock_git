import React, { useEffect, useState } from 'react';
import api from '../api/index.js';

export default function IndexBar() {
  const [indices, setIndices] = useState([]);
  const [error, setError] = useState(false);

  useEffect(() => {
    const fetch = () =>
      api.get('/api/market/indices')
        .then(r => { setIndices(r.data); setError(false); })
        .catch(() => setError(true));
    fetch();
    const t = setInterval(fetch, 300000);
    return () => clearInterval(t);
  }, []);

  const fmt = v => v == null ? '-' : v >= 1000 ? v.toLocaleString('ko', { maximumFractionDigits: 2 }) : v.toFixed(2);

  return (
    <div className="index-bar" id="indexBar">
      {error && <span style={{ color:'var(--down)', fontSize:'0.7rem' }}>지수 로드 실패</span>}
      {!error && !indices.length && <div style={{ fontSize:'0.7rem', color:'var(--fg-3)', fontFamily:'var(--font-mono)' }}>로딩 중...</div>}
      {indices.map((idx, i) => (
        <React.Fragment key={idx.name}>
          {i > 0 && <div style={{ width:1, height:14, background:'var(--line-1)', flexShrink:0 }}/>}
          <div className="index-item">
            <span className="index-name">{idx.name}</span>
            <span className="index-price">{fmt(idx.price)}</span>
            <span className={`index-chg ${idx.change_pct > 0 ? 'up' : idx.change_pct < 0 ? 'down' : 'flat'}`}>
              {idx.change_pct != null ? `${idx.change_pct > 0 ? '+' : ''}${idx.change_pct.toFixed(2)}%` : '-'}
            </span>
          </div>
        </React.Fragment>
      ))}
    </div>
  );
}
