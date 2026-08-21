# 주식 시장 대시보드

한국 주식 시장 분석·포트폴리오·AI 추천을 한곳에서 제공하는 웹 대시보드.
**FastAPI**(백엔드) + **React SPA**(프론트) + **MySQL**(데이터) 구성이며, 세션 인증과 크레딧 기반 유료 기능을 포함한다.

---

## 한눈에

| | |
|---|---|
| 무엇 | 한국 주식 시장 분석·포트폴리오·AI 추천 대시보드 |
| 스택 | FastAPI · React SPA · MySQL |
| 규모 | Python 32,170줄 · JS 13,198줄 · API 엔드포인트 251개 · 테이블 35개 |
| 테스트 | 테스트 함수 38개 |
| 포함 | 세션 인증, 크레딧 기반 유료 기능, 시세·수급·공시 수집 파이프라인 |

예측 모델을 붙이면서 얻은 것은 성능이 아니라 **검증 설계**였다. 초기에 검증 정확도가 비현실적으로 높게 나와 피처를 하나씩 되짚었고, 예측 시점 이후 데이터가 학습에 섞여 들어간 **미래 정보 누출**을 찾아 제거했다. 누출을 막고 재학습하자 성능은 크게 떨어졌지만 그 숫자는 재현되는 값이었다.

## 기술 스택

| 영역 | 사용 기술 |
|---|---|
| 백엔드 | FastAPI, Uvicorn, Starlette SessionMiddleware |
| 프론트 | React, Vite, react-router-dom (SPA → `static/spa/`로 빌드) |
| DB | MySQL (`pymysql` + `dbutils` 커넥션 풀) |
| 스케줄러 | APScheduler (인프로세스, KST) |
| 결제 | PortOne V2 (키 미설정 시 mock 모드) |
| AI | Anthropic Claude (챗봇·종목 분석), XGBoost/LightGBM 앙상블(추천 모델) |
| 시장 데이터 | 한국투자증권(KIS, 국내 시세·일봉·외국인), DART, KRX(pykrx), 네이버 금융, 한국은행(ECOS), FRED, yfinance 등 |

---

## 주요 기능

- **시장/종목** — 실시간 시세, 수출입 동향, 종목 상세·비교, 기업 실적 분석
- **포트폴리오** — 보유 현황, 최적화, 리스크 분석, 월별 성과, 배당 캘린더, 관심 종목, 가상매매
- **스크리닝** — 종목 필터, 네이버 테마 히트맵, 섹터 히트맵, 52주 신고가·신저가
- **AI·전략** — 매수/매도 분석, **AI 추천 종목**, 추천 기록, 백테스트, 퀀트 트레이딩, 학습 리포트, 자동화 워크플로
- **리서치·알림** — 시장 보고서, 실적 캘린더, 뉴스, 공시·가격 알림
- **크레딧/결제** — 크레딧 충전(PortOne), AI 챗봇·분석 호출당 차감, **AI 추천 데이 패스**(하루 1회 차감으로 추천 열람)

### AI 추천 데이 패스
하루 1회 크레딧을 차감하면 그날 AI 추천 종목 열람이 활성화된다. 하루 경계는 **KST 07:00**이며,
같은 날 껐다 켜도 재차감되지 않는다(OFF는 환불 없음). 추천 모델은 매일 **06:30(KST)** 자동 실행된다.

---

## 프로젝트 구조

```
.
├── app.py              # FastAPI 진입점 (라우터 등록, 스케줄러, SPA 서빙)
├── config.py           # 환경변수 기반 설정
├── routes/             # API 라우터 (auth, credits, recommend, recommend_pass, ...)
├── database/           # DB 커넥션 풀
├── XGBoost_v2/         # 추천/예측 모델 (학습·일일 추천 생성)
├── agent/ · notify/ · trading/         # 에이전트·알림·매매(주문은 영구 비활성)
├── client/             # React SPA 소스 (Vite) → build 시 static/spa/ 로 출력
├── static/             # 정적 자원 (빌드 산출물 static/spa/ 포함, gitignore)
├── DEPLOY.md           # 배포 가이드
└── .env.example        # 환경변수 템플릿
```

---

## 빠른 시작

```bash
# 1) 환경변수
cp .env.example .env          # 값 채우기 (DB, SECRET_KEY 등)

# 2) 백엔드
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt

# 3) 프론트 빌드
cd client && npm install && npm run build && cd ..

# 4) 실행 (.env의 PORT 사용, 기본 8030)
python app.py
```

DB 테이블은 앱 기동 시 자동 생성된다. 기동 후 `http://localhost:8030` 접속.
상세 배포 절차(스케줄러, HTTPS, 결제 모드 등)는 **[DEPLOY.md](DEPLOY.md)** 참고.

---

## 환경변수

`.env.example`의 모든 키에 대한 설명이 포함돼 있다. 핵심:

- **필수**: `SECRET_KEY`, `DB_*`, `PORT`, `APP_BASE_URL`, `RUN_SCHEDULER`
- **결제(mock)**: `PORTONE_*` 비우면 실결제 없이 충전 성공 처리
- **AI**: `ANTHROPIC_API_KEY`(챗봇·분석·추천 패스), `RECOMMEND_PASS_COST` / `RECOMMEND_PASS_RESET_HOUR`

> `.env`에는 실제 비밀값이 들어가며 `.gitignore`로 제외된다. **절대 커밋·공개 금지.**

---

## 라이선스

비공개 프로젝트 (Private). 무단 배포·재사용 금지.
