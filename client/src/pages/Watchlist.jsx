import React, { useState, useEffect } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import { Link } from 'react-router-dom';
import api from '../api/index.js';

function ItemRow({ item, onDelete }) {
  const chg = item.change_pct;
  return (
    <div style={{ display:'flex', alignItems:'center', gap:12, padding:'10px 12px', borderBottom:'1px solid var(--line-1)' }}>
      <div style={{ flex:1 }}>
        <div style={{ fontWeight:700, color:'var(--fg-1)', fontSize:'0.87rem' }}>{item.stock_name}</div>
        <div style={{ fontSize:'0.7rem', color:'var(--fg-3)', fontFamily:'var(--font-mono)' }}>{item.stock_code}</div>
        {item.memo && <div style={{ fontSize:'0.68rem', color:'var(--fg-3)', marginTop:2 }}>{item.memo}</div>}
      </div>
      {item.current_price != null && (
        <div style={{ textAlign:'right' }}>
          <div style={{ fontFamily:'var(--font-mono)', fontWeight:700, fontSize:'0.9rem' }}>{item.current_price.toLocaleString('ko')}</div>
          {chg != null && (
            <div style={{ fontSize:'0.75rem', fontFamily:'var(--font-mono)', color: chg > 0 ? 'var(--up)' : chg < 0 ? 'var(--down)' : 'var(--fg-3)' }}>
              {chg > 0 ? '+' : ''}{chg.toFixed(2)}%
            </div>
          )}
        </div>
      )}
      <Link to={`/stock_detail?code=${item.stock_code}&name=${encodeURIComponent(item.stock_name)}`}
        style={{ color:'var(--accent)', textDecoration:'none', fontSize:'0.75rem' }}>
        <i className="bi bi-zoom-in"/>
      </Link>
      <button onClick={() => onDelete(item.id)} style={{ background:'transparent', border:'none', color:'var(--down)', cursor:'pointer' }}>
        <i className="bi bi-trash"/>
      </button>
    </div>
  );
}

export default function Watchlist() {
  const [groups,       setGroups]       = useState([]);
  const [activeGroup,  setActiveGroup]  = useState(null);
  const [items,        setItems]        = useState([]);
  const [itemsLoading, setItemsLoading] = useState(false);
  const [showNewGroup, setShowNewGroup] = useState(false);
  const [newGroupName, setNewGroupName] = useState('');
  const [showAddItem,  setShowAddItem]  = useState(false);
  const [newItem,      setNewItem]      = useState({ stock_code:'', stock_name:'', memo:'' });
  const [searchQ,      setSearchQ]      = useState('');
  const [searchRes,    setSearchRes]    = useState([]);
  const [groupsError,  setGroupsError]  = useState(null);
  const [itemsError,   setItemsError]   = useState(null);

  const loadGroups = () => {
    setGroupsError(null);
    api.get('/api/watchlist/groups').then(r => {
      const gs = r.data?.groups || [];
      setGroups(gs);
      if (!activeGroup && gs.length) setActiveGroup(gs[0].id);
    }).catch(() => setGroupsError('그룹 목록을 불러오지 못했습니다.'));
  };

  const loadItems = (gid) => {
    if (!gid) return;
    setItemsLoading(true);
    setItemsError(null);
    api.get(`/api/watchlist/${gid}/items`)
      .then(r => setItems(r.data?.items || []))
      .catch(() => { setItems([]); setItemsError('종목 목록을 불러오지 못했습니다.'); })
      .finally(() => setItemsLoading(false));
  };

  useEffect(() => { loadGroups(); }, []);
  useEffect(() => { loadItems(activeGroup); }, [activeGroup]);

  // 종목 자동완성
  useEffect(() => {
    if (!searchQ.trim()) { setSearchRes([]); return; }
    const t = setTimeout(() => {
      api.get('/search-stock-kr', { params: { q: searchQ } })
        .then(r => setSearchRes(r.data || []))
        .catch(() => {});
    }, 250);
    return () => clearTimeout(t);
  }, [searchQ]);

  const createGroup = async e => {
    e.preventDefault();
    if (!newGroupName.trim()) return;
    await api.post('/api/watchlist/groups', { name: newGroupName.trim() });
    setNewGroupName(''); setShowNewGroup(false);
    loadGroups();
  };

  const deleteGroup = async gid => {
    if (!confirm('그룹을 삭제할까요? (종목 포함 모두 삭제)')) return;
    await api.delete(`/api/watchlist/groups/${gid}`);
    setActiveGroup(null);
    loadGroups();
  };

  const addItem = async e => {
    e.preventDefault();
    if (!newItem.stock_code) return;
    await api.post(`/api/watchlist/${activeGroup}/items`, newItem);
    setNewItem({ stock_code:'', stock_name:'', memo:'' });
    setSearchQ(''); setSearchRes([]);
    setShowAddItem(false);
    loadItems(activeGroup);
  };

  const deleteItem = async id => {
    await api.delete(`/api/watchlist/items/${id}`);
    loadItems(activeGroup);
  };

  return (
    <StockLayout title="관심종목">
      <div style={{ display:'grid', gridTemplateColumns:'220px 1fr', gap:16, alignItems:'start' }}>

        {/* 그룹 목록 */}
        <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'16px' }}>
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:12 }}>
            <span style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)' }}>그룹</span>
            <button onClick={() => setShowNewGroup(v => !v)}
              style={{ background:'none', border:'none', color:'var(--accent)', cursor:'pointer', fontSize:'1rem' }}>
              <i className="bi bi-plus-lg"/>
            </button>
          </div>
          {showNewGroup && (
            <form onSubmit={createGroup} style={{ marginBottom:10, display:'flex', gap:6 }}>
              <input className="form-control" style={{ fontSize:'0.8rem' }} placeholder="그룹명" value={newGroupName}
                onChange={e => setNewGroupName(e.target.value)} autoFocus />
              <button type="submit" style={{ background:'var(--accent)', color:'#fff', border:'none', borderRadius:'var(--r-1)', padding:'0 10px', cursor:'pointer', flexShrink:0 }}>
                <i className="bi bi-check"/>
              </button>
            </form>
          )}
          {groupsError && (
            <div style={{ fontSize:'0.75rem', color:'var(--down)', padding:'8px 4px', display:'flex', alignItems:'center', gap:6 }}>
              <i className="bi bi-exclamation-triangle-fill"/>{groupsError}
            </div>
          )}
          {groups.length === 0 && !groupsError ? (
            <div style={{ fontSize:'0.78rem', color:'var(--fg-3)', textAlign:'center', padding:'20px 0' }}>그룹 없음</div>
          ) : (
            <div style={{ display:'flex', flexDirection:'column', gap:4 }}>
              {groups.map(g => (
                <div key={g.id} style={{ display:'flex', alignItems:'center', gap:6, borderRadius:'var(--r-2)', padding:'8px 10px',
                  background: activeGroup === g.id ? 'var(--accent-muted, rgba(99,102,241,0.12))' : 'transparent', cursor:'pointer' }}
                  onClick={() => setActiveGroup(g.id)}>
                  <i className="bi bi-bookmark" style={{ color: activeGroup === g.id ? 'var(--accent)' : 'var(--fg-3)', fontSize:'0.8rem' }} />
                  <span style={{ flex:1, fontSize:'0.83rem', fontWeight: activeGroup === g.id ? 700 : 500, color: activeGroup === g.id ? 'var(--accent)' : 'var(--fg-1)' }}>{g.name}</span>
                  <span style={{ fontSize:'0.68rem', color:'var(--fg-3)', background:'var(--bg-3)', borderRadius:10, padding:'1px 6px' }}>{g.count}</span>
                  <button onClick={e => { e.stopPropagation(); deleteGroup(g.id); }}
                    style={{ background:'none', border:'none', color:'var(--fg-3)', cursor:'pointer', padding:0, fontSize:'0.75rem' }}>
                    <i className="bi bi-x"/>
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 종목 목록 */}
        <div style={{ background:'var(--bg-2)', border:'1px solid var(--line-1)', borderRadius:'var(--r-3)', padding:'16px' }}>
          {!activeGroup ? (
            <div style={{ textAlign:'center', padding:'60px', color:'var(--fg-3)', fontSize:'0.83rem' }}>
              <i className="bi bi-bookmark" style={{ fontSize:'2rem', opacity:0.2, display:'block', marginBottom:12 }} />
              왼쪽에서 그룹을 선택하거나 만드세요
            </div>
          ) : (
            <>
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:12 }}>
                <span style={{ fontWeight:700, fontSize:'0.87rem', color:'var(--fg-1)' }}>
                  {groups.find(g => g.id === activeGroup)?.name}
                </span>
                <button onClick={() => setShowAddItem(v => !v)}
                  style={{ background:'var(--accent)', color:'#fff', border:'none', borderRadius:'var(--r-2)', padding:'5px 12px', fontSize:'0.78rem', fontWeight:700, cursor:'pointer', display:'flex', alignItems:'center', gap:5 }}>
                  <i className="bi bi-plus-lg"/>종목 추가
                </button>
              </div>

              {showAddItem && (
                <form onSubmit={addItem} style={{ background:'var(--bg-3)', borderRadius:'var(--r-2)', padding:'12px', marginBottom:12 }}>
                  <div style={{ position:'relative', marginBottom:8 }}>
                    <input className="form-control" placeholder="종목명 검색" value={searchQ}
                      onChange={e => { setSearchQ(e.target.value); setNewItem(p => ({...p, stock_code:'', stock_name:''})); }} />
                    {searchRes.length > 0 && (
                      <div style={{ position:'absolute', top:'100%', left:0, right:0, zIndex:20, background:'var(--bg-1)', border:'1px solid var(--line-2)', borderRadius:'var(--r-2)', maxHeight:180, overflowY:'auto' }}>
                        {searchRes.slice(0,6).map(s => (
                          <button key={s.code} type="button" onClick={() => { setNewItem(p => ({...p, stock_code:s.code, stock_name:s.name})); setSearchQ(s.name); setSearchRes([]); }}
                            style={{ display:'block', width:'100%', padding:'8px 12px', border:'none', background:'none', textAlign:'left', cursor:'pointer', fontSize:'0.82rem' }}>
                            <span style={{ fontFamily:'var(--font-mono)', fontSize:'0.72rem', color:'var(--fg-3)', marginRight:8 }}>{s.code}</span>{s.name}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <input className="form-control" placeholder="메모 (선택)" value={newItem.memo}
                    onChange={e => setNewItem(p => ({...p, memo:e.target.value}))} style={{ marginBottom:8 }} />
                  <div style={{ display:'flex', gap:8 }}>
                    <button type="submit" disabled={!newItem.stock_code}
                      style={{ background:'var(--accent)', color:'#fff', border:'none', borderRadius:'var(--r-2)', padding:'6px 16px', fontSize:'0.78rem', fontWeight:700, cursor:'pointer', opacity: newItem.stock_code ? 1 : 0.5 }}>
                      추가
                    </button>
                    <button type="button" onClick={() => { setShowAddItem(false); setSearchQ(''); setSearchRes([]); }}
                      style={{ background:'var(--bg-2)', color:'var(--fg-2)', border:'1px solid var(--line-2)', borderRadius:'var(--r-2)', padding:'6px 12px', fontSize:'0.78rem', cursor:'pointer' }}>
                      취소
                    </button>
                  </div>
                </form>
              )}

              {itemsError && (
                <div style={{ background:'rgba(244,63,94,0.1)', border:'1px solid var(--down)', borderRadius:'var(--r-2)', padding:'10px 14px', marginBottom:10, color:'var(--down)', fontSize:'0.82rem', display:'flex', alignItems:'center', gap:8 }}>
                  <i className="bi bi-exclamation-triangle-fill"/>{itemsError}
                </div>
              )}
              {itemsLoading ? (
                <div style={{ textAlign:'center', padding:'40px', color:'var(--fg-3)' }}><div className="spinner" style={{ margin:'0 auto 8px' }}/> 로딩 중...</div>
              ) : items.length === 0 && !itemsError ? (
                <div style={{ textAlign:'center', padding:'40px', color:'var(--fg-3)', fontSize:'0.83rem' }}>종목을 추가하세요</div>
              ) : (
                items.map(item => <ItemRow key={item.id} item={item} onDelete={deleteItem} />)
              )}
            </>
          )}
        </div>
      </div>
    </StockLayout>
  );
}
