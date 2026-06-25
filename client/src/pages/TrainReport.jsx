import React, { useState, useEffect } from 'react';
import StockLayout from '../layouts/StockLayout.jsx';
import api from '../api/index.js';

const FEAT_KR = {
  ret_1d: '1일 수익률', ret_3d: '3일 수익률', ret_5d: '5일 수익률',
  ret_10d: '10일 수익률', ret_20d: '20일 수익률', ret_60d: '60일 수익률',
  gap_open: '갭 오픈율', volume_ratio: '거래량비 (5일)', vol_ratio_5: '5일 거래량비',
  vol_ratio_20: '20일 거래량비', turnover: '회전율',
  cci_20: 'CCI (20일)', cci_10: 'CCI (10일)', cci_5: 'CCI (5일)',
  atr_ratio: 'ATR 변동성비', atr_14: 'ATR (14일)',
  bb_pct: '볼린저밴드 위치', bb_width: '볼린저밴드 폭',
  rsi_14: 'RSI (14일)', rsi_vs_market: 'RSI vs 시장 상대강도',
  low52w_pct: '52주 저점 대비 %', high52w_pct: '52주 고점 대비 %',
  macd_hist: 'MACD 히스토그램', macd_signal: 'MACD 시그널',
  ma5_ratio: '5일선 괴리율', ma20_ratio: '20일선 괴리율',
  ma60_ratio: '60일선 괴리율', ma120_ratio: '120일선 괴리율',
  per: 'PER', pbr: 'PBR', roe: 'ROE', eps_growth: 'EPS 성장률',
  market_ret_1d: '시장 1일 수익률', sector_ret_1d: '섹터 1일 수익률',
  beta: '베타 (시장민감도)', momentum_20: '20일 모멘텀',
  stoch_k: '스토캐스틱 %K', stoch_d: '스토캐스틱 %D',
  obv_ratio: 'OBV 비율', mfi_14: 'MFI (14일)',
  disparity_5: '5일 이격도', disparity_20: '20일 이격도',
  close_rank: '가격 분위수', pct_rank: '수익률 분위수',
};

const PARAM_KR = {
  max_depth: '트리 최대 깊이',
  eta: '학습률 (learning rate)',
  subsample: '샘플 추출 비율',
  colsample_bytree: '특성 추출 비율',
  min_child_weight: '최소 자식 노드 가중치',
  gamma: '분기 최소 손실 감소 (γ)',
  lambda: 'L2 정규화 (λ)',
  alpha: 'L1 정규화 (α)',
  device: '학습 장치',
  seed: '랜덤 시드',
};

const LABEL_META = {
  daily:  { kr: '일봉', icon: 'bi-calendar-day',   desc: '다음 영업일 기준 +3% 이상 상승 예측', color: '#3b82f6' },
  short:  { kr: '단기', icon: 'bi-calendar-week',  desc: '3~5일 내 +5% 이상 상승 예측',         color: '#8b5cf6' },
  swing:  { kr: '스윙', icon: 'bi-calendar-month', desc: '10~20일 내 +8% 이상 상승 예측',        color: '#f59e0b' },
};

function aucGrade(auc) {
  if (auc >= 0.72) return { label: '우수', desc: '예측력 높음',    color: 'var(--up)',     bg: 'rgba(34,197,94,0.1)'  };
  if (auc >= 0.65) return { label: '양호', desc: '예측력 적정',    color: '#f59e0b',       bg: 'rgba(245,158,11,0.1)' };
  return              { label: '미흡', desc: '예측력 낮음',    color: 'var(--down)',   bg: 'rgba(239,68,68,0.1)'  };
}

function MetricCard({ label, value, display, subtext, grade }) {
  return (
    <div style={{ background: grade ? grade.bg : 'var(--bg-2)', border: `1px solid ${grade ? grade.color + '44' : 'var(--line-1)'}`, borderRadius: 'var(--r-3)', padding: '16px 18px', flex: 1, minWidth: 140 }}>
      <div style={{ fontSize: '0.72rem', color: 'var(--fg-3)', textTransform: 'uppercase', letterSpacing: '0.05em', fontFamily: 'var(--font-mono)', marginBottom: 6 }}>{label}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span style={{ fontSize: '1.6rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: grade ? grade.color : 'var(--fg-1)' }}>{display}</span>
        {grade && <span style={{ fontSize: '0.72rem', fontWeight: 700, color: grade.color, background: grade.bg, border: `1px solid ${grade.color}44`, borderRadius: 4, padding: '1px 6px' }}>{grade.label}</span>}
      </div>
      {subtext && <div style={{ fontSize: '0.72rem', color: 'var(--fg-3)', marginTop: 4 }}>{subtext}</div>}
    </div>
  );
}

function FeatureBar({ feature, importance, max, rank }) {
  const kr = FEAT_KR[feature] || feature;
  const pct = max > 0 ? (importance / max) * 100 : 0;
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '18px 1fr auto', gap: 8, alignItems: 'center' }}>
      <span style={{ fontSize: '0.65rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)', textAlign: 'right' }}>{rank}</span>
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
          <span style={{ fontSize: '0.78rem', color: 'var(--fg-1)', fontWeight: rank <= 3 ? 700 : 400 }}>{kr}</span>
          <span style={{ fontSize: '0.65rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>{feature}</span>
        </div>
        <div style={{ height: 8, background: 'var(--line-1)', borderRadius: 4, overflow: 'hidden' }}>
          <div style={{ width: `${pct}%`, height: '100%', background: rank === 1 ? 'var(--up)' : rank <= 3 ? 'var(--accent)' : 'var(--line-2)', borderRadius: 4, transition: 'width 0.4s ease' }} />
        </div>
      </div>
      <span style={{ fontSize: '0.72rem', fontFamily: 'var(--font-mono)', color: 'var(--fg-2)', minWidth: 44, textAlign: 'right' }}>{(importance * 100).toFixed(1)}%</span>
    </div>
  );
}

function ParamRow({ name, value }) {
  const kr = PARAM_KR[name];
  if (!kr) return null;
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 0', borderBottom: '1px solid var(--line-1)' }}>
      <div>
        <span style={{ fontSize: '0.8rem', color: 'var(--fg-1)' }}>{kr}</span>
        <span style={{ fontSize: '0.68rem', color: 'var(--fg-3)', fontFamily: 'var(--font-mono)', marginLeft: 6 }}>{name}</span>
      </div>
      <span style={{ fontSize: '0.82rem', fontFamily: 'var(--font-mono)', color: 'var(--accent)', fontWeight: 600 }}>{String(value)}</span>
    </div>
  );
}

export default function TrainReport() {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState('daily');
  const [showTickers, setShowTickers] = useState(false);

  const [shap, setShap] = useState({});

  const fetchReport = () => {
    setLoading(true);
    setError('');
    api.get('/api/train_report')
      .then(r => {
        setReport(r.data?.report || r.data || null);
        setShap(r.data?.shap || {});
      })
      .catch(e => setError(e.response?.data?.error || '리포트 없음'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchReport(); }, []);

  if (loading) return (
    <StockLayout title="ML 학습 리포트">
      <div style={{ textAlign: 'center', padding: '80px 0' }}><div className="spinner" style={{ margin: '0 auto' }} /></div>
    </StockLayout>
  );

  if (error || !report) return (
    <StockLayout title="ML 학습 리포트">
      <div style={{ textAlign: 'center', padding: '80px 0', color: 'var(--fg-3)' }}>
        <i className="bi bi-file-bar-graph" style={{ fontSize: '2.5rem', display: 'block', marginBottom: 12, opacity: 0.3 }} />
        <p style={{ margin: 0, fontSize: '0.85rem' }}>{error || '데이터 없음'}</p>
        <p style={{ margin: '8px 0 0', fontSize: '0.78rem' }}>파이프라인에서 XGBoost 모델을 먼저 학습시켜 주세요.</p>
      </div>
    </StockLayout>
  );

  const labels = report.labels || {};
  const cur = labels[activeTab] || {};
  const meta = LABEL_META[activeTab] || {};
  const grade = cur.cv_auc != null ? aucGrade(cur.cv_auc) : null;
  const features = (cur.top_features_fscore || []).filter(f => f.importance > 0);
  const featMax = features.length ? features[0].importance : 1;
  const params = cur.best_params || {};
  const trainedAt = report.trained_at ? report.trained_at.slice(0, 19).replace('T', ' ') : '-';

  return (
    <StockLayout title="ML 학습 리포트">

      {/* 학습 메타 요약 */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 20, alignItems: 'center' }}>
        {[
          { icon: 'bi-clock',        label: '학습 일시',   value: trainedAt },
          { icon: 'bi-bar-chart',    label: '학습 종목',   value: `${report.n_tickers?.toLocaleString('ko') || '-'}개` },
          { icon: 'bi-database',     label: '학습 샘플',   value: `${report.n_samples?.toLocaleString('ko') || '-'}행` },
          { icon: 'bi-list-columns', label: '입력 피처',   value: `${report.n_features || '-'}개` },
          { icon: 'bi-gpu-card',     label: '학습 장치',   value: params.device || 'cpu' },
        ].map(({ icon, label, value }) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 7, background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-2)', padding: '7px 13px', fontSize: '0.8rem', whiteSpace: 'nowrap' }}>
            <i className={`bi ${icon}`} style={{ color: 'var(--accent)', fontSize: '0.85rem' }} />
            <span style={{ color: 'var(--fg-3)' }}>{label}</span>
            <strong style={{ color: 'var(--fg-1)' }}>{value}</strong>
          </div>
        ))}
        <button onClick={fetchReport} disabled={loading} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 13px', background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-2)', cursor: loading ? 'not-allowed' : 'pointer', fontSize: '0.8rem', color: 'var(--fg-2)', opacity: loading ? 0.5 : 1, transition: 'all 0.15s', whiteSpace: 'nowrap' }}>
          <i className={`bi bi-arrow-clockwise${loading ? ' spin' : ''}`} style={{ fontSize: '0.9rem' }} />
          {loading ? '불러오는 중...' : '새로고침'}
        </button>
      </div>

      {/* 탭 */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
        {Object.entries(LABEL_META).map(([key, m]) => {
          const lb = labels[key] || {};
          const g = lb.cv_auc != null ? aucGrade(lb.cv_auc) : null;
          const isActive = activeTab === key;
          return (
            <button key={key} onClick={() => setActiveTab(key)} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '9px 18px', borderRadius: 'var(--r-3)', border: isActive ? `2px solid ${m.color}` : '2px solid var(--line-1)', background: isActive ? `${m.color}18` : 'var(--bg-2)', cursor: 'pointer', transition: 'all 0.15s' }}>
              <i className={`bi ${m.icon}`} style={{ color: isActive ? m.color : 'var(--fg-3)', fontSize: '1rem' }} />
              <div style={{ textAlign: 'left' }}>
                <div style={{ fontSize: '0.85rem', fontWeight: isActive ? 700 : 500, color: isActive ? 'var(--fg-1)' : 'var(--fg-2)' }}>{m.kr} 모델</div>
                {lb.cv_auc != null && (
                  <div style={{ fontSize: '0.68rem', color: g?.color, fontFamily: 'var(--font-mono)' }}>AUC {lb.cv_auc.toFixed(4)} · {g?.label}</div>
                )}
              </div>
            </button>
          );
        })}
      </div>

      {/* 모델 설명 배너 */}
      <div style={{ background: `${meta.color}12`, border: `1px solid ${meta.color}44`, borderRadius: 'var(--r-3)', padding: '10px 16px', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 10 }}>
        <i className={`bi ${meta.icon}`} style={{ color: meta.color, fontSize: '1.1rem' }} />
        <div>
          <span style={{ fontSize: '0.85rem', fontWeight: 700, color: meta.color }}>{meta.kr} 모델 </span>
          <span style={{ fontSize: '0.82rem', color: 'var(--fg-2)' }}>{meta.desc}</span>
          {cur.n_rounds && <span style={{ fontSize: '0.75rem', color: 'var(--fg-3)', marginLeft: 12 }}>부스팅 라운드 {cur.n_rounds}회</span>}
        </div>
        {grade && (
          <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
            <div style={{ fontSize: '0.72rem', color: 'var(--fg-3)' }}>예측력 등급</div>
            <div style={{ fontSize: '0.9rem', fontWeight: 700, color: grade.color }}>{grade.label} — {grade.desc}</div>
          </div>
        )}
      </div>

      {/* 성능 지표 카드 */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 20 }}>
        {cur.cv_auc != null && (
          <MetricCard
            label="AUC (교차검증)"
            value={cur.cv_auc}
            display={cur.cv_auc.toFixed(4)}
            subtext="0.7 이상이면 예측력 양호, 0.5는 랜덤 수준"
            grade={aucGrade(cur.cv_auc)}
          />
        )}
        {cur.cv_acc != null && (
          <MetricCard
            label="Accuracy (정확도)"
            value={cur.cv_acc}
            display={`${(cur.cv_acc * 100).toFixed(2)}%`}
            subtext="전체 예측 중 맞춘 비율 (클래스 불균형 영향 있음)"
            grade={cur.cv_acc >= 0.57 ? { label: '양호', color: '#f59e0b', bg: 'rgba(245,158,11,0.08)' } : null}
          />
        )}
        {cur.buy_ratio != null && (
          <MetricCard
            label="매수 신호 비율"
            value={cur.buy_ratio}
            display={`${(cur.buy_ratio * 100).toFixed(2)}%`}
            subtext={`전체 ${report.n_samples?.toLocaleString('ko')}행 중 상승 라벨 비율`}
          />
        )}
      </div>

      {/* 피처 중요도 + 하이퍼파라미터 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.6fr) minmax(0,1fr)', gap: 14, marginBottom: 20 }}>

        {/* 피처 중요도 */}
        <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '18px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
            <i className="bi bi-bar-chart-horizontal" style={{ color: 'var(--accent)', fontSize: '1rem' }} />
            <span style={{ fontWeight: 700, fontSize: '0.88rem', color: 'var(--fg-1)' }}>주요 예측 피처 (F-Score 기준)</span>
            <span style={{ fontSize: '0.72rem', color: 'var(--fg-3)', marginLeft: 4 }}>— 이 항목들이 예측에 가장 큰 영향을 미침</span>
          </div>
          {features.length === 0 ? (
            <div style={{ color: 'var(--fg-3)', fontSize: '0.82rem', textAlign: 'center', padding: '24px 0' }}>피처 중요도 데이터 없음</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {features.map((f, i) => (
                <FeatureBar key={f.feature} feature={f.feature} importance={f.importance} max={featMax} rank={i + 1} />
              ))}
            </div>
          )}
          {/* SHAP 중요도 (주간 재학습 시 생성) */}
          {(shap[activeTab] || []).length > 0 && (() => {
            const sf = shap[activeTab].slice(0, 10);
            const sMax = sf[0]?.shap_importance || 1;
            return (
              <div style={{ marginTop: 18 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                  <i className="bi bi-diagram-3" style={{ color: 'var(--up)', fontSize: '1rem' }} />
                  <span style={{ fontWeight: 700, fontSize: '0.88rem', color: 'var(--fg-1)' }}>SHAP 기여도 (예측 영향력)</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {sf.map((f, i) => (
                    <div key={f.feature} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.78rem' }}>
                      <span style={{ width: 18, color: 'var(--fg-3)', fontFamily: 'var(--font-mono)', fontSize: '0.7rem' }}>{i + 1}</span>
                      <span style={{ width: 130, fontFamily: 'var(--font-mono)', color: 'var(--fg-2)', overflow: 'hidden', textOverflow: 'ellipsis' }}>{f.feature}</span>
                      <div style={{ flex: 1, height: 10, background: 'var(--bg-3)', borderRadius: 5, overflow: 'hidden' }}>
                        <div style={{ width: `${Math.round(f.shap_importance / sMax * 100)}%`, height: '100%', background: 'var(--up)', opacity: 0.8 }} />
                      </div>
                      <span style={{ width: 60, textAlign: 'right', fontFamily: 'var(--font-mono)', color: 'var(--fg-3)', fontSize: '0.7rem' }}>{f.shap_importance.toFixed(4)}</span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })()}
          <div style={{ marginTop: 14, padding: '10px 12px', background: 'var(--bg-3)', borderRadius: 'var(--r-2)', fontSize: '0.72rem', color: 'var(--fg-3)' }}>
            <i className="bi bi-info-circle me-1" />
            F-Score는 트리 분기 빈도 기반, SHAP은 실제 예측값 기여도 기반입니다. SHAP은 주간 재학습(일 02:00) 시 자동 생성됩니다.
          </div>
        </div>

        {/* 하이퍼파라미터 */}
        <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '18px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <i className="bi bi-sliders" style={{ color: 'var(--accent)', fontSize: '1rem' }} />
            <span style={{ fontWeight: 700, fontSize: '0.88rem', color: 'var(--fg-1)' }}>학습 하이퍼파라미터</span>
          </div>
          <div>
            {Object.entries(params).map(([k, v]) => <ParamRow key={k} name={k} value={v} />)}
          </div>
          <div style={{ marginTop: 14, padding: '10px 12px', background: 'var(--bg-3)', borderRadius: 'var(--r-2)', fontSize: '0.72rem', color: 'var(--fg-3)' }}>
            <i className="bi bi-info-circle me-1" />
            Optuna/Grid Search로 최적화된 파라미터입니다. 재학습 시 변경될 수 있습니다.
          </div>
        </div>
      </div>

      {/* 전체 모델 AUC 비교 */}
      <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: '16px 20px', marginBottom: 16 }}>
        <div style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--fg-1)', marginBottom: 14 }}>
          <i className="bi bi-diagram-2 me-2" style={{ color: 'var(--accent)' }} />
          3개 모델 성능 비교
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 10 }}>
          {Object.entries(LABEL_META).map(([key, m]) => {
            const lb = labels[key] || {};
            const g = lb.cv_auc != null ? aucGrade(lb.cv_auc) : null;
            return (
              <div key={key} onClick={() => setActiveTab(key)} style={{ cursor: 'pointer', padding: '14px', border: `1px solid ${activeTab === key ? m.color : 'var(--line-1)'}`, borderRadius: 'var(--r-2)', background: activeTab === key ? `${m.color}10` : 'var(--bg-3)', transition: 'all 0.15s' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                  <i className={`bi ${m.icon}`} style={{ color: m.color, fontSize: '0.9rem' }} />
                  <span style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--fg-1)' }}>{m.kr}</span>
                  {g && <span style={{ marginLeft: 'auto', fontSize: '0.68rem', color: g.color, fontWeight: 700 }}>{g.label}</span>}
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                  {lb.cv_auc != null && (
                    <div>
                      <div style={{ fontSize: '0.65rem', color: 'var(--fg-3)' }}>AUC</div>
                      <div style={{ fontSize: '1rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: g?.color }}>{lb.cv_auc.toFixed(4)}</div>
                    </div>
                  )}
                  {lb.cv_acc != null && (
                    <div>
                      <div style={{ fontSize: '0.65rem', color: 'var(--fg-3)' }}>정확도</div>
                      <div style={{ fontSize: '1rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: 'var(--fg-2)' }}>{(lb.cv_acc * 100).toFixed(1)}%</div>
                    </div>
                  )}
                </div>
                {lb.buy_ratio != null && (
                  <div style={{ marginTop: 8, fontSize: '0.68rem', color: 'var(--fg-3)' }}>
                    매수 라벨 비율: <span style={{ color: 'var(--fg-2)' }}>{(lb.buy_ratio * 100).toFixed(1)}%</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* 학습 종목 목록 */}
      {report.tickers?.length > 0 && (
        <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'hidden' }}>
          <button onClick={() => setShowTickers(v => !v)} style={{ width: '100%', padding: '13px 18px', display: 'flex', alignItems: 'center', gap: 8, background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left' }}>
            <i className="bi bi-list-ul" style={{ color: 'var(--accent)' }} />
            <span style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--fg-1)' }}>학습 종목 목록</span>
            <span style={{ fontSize: '0.75rem', color: 'var(--fg-3)', marginLeft: 4 }}>{report.tickers.length}개 종목</span>
            <i className={`bi bi-chevron-${showTickers ? 'up' : 'down'}`} style={{ color: 'var(--fg-3)', marginLeft: 'auto', fontSize: '0.75rem' }} />
          </button>
          {showTickers && (
            <div style={{ padding: '0 18px 16px', borderTop: '1px solid var(--line-1)' }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 12 }}>
                {report.tickers.map(t => (
                  <span key={t} style={{ fontSize: '0.72rem', fontFamily: 'var(--font-mono)', color: 'var(--fg-2)', background: 'var(--bg-3)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-1)', padding: '2px 7px' }}>{t}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

    </StockLayout>
  );
}
