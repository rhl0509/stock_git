# 배포 가이드 (5099 / D:\stock_git)

주식 시장 대시보드(FastAPI + React SPA + MySQL) 배포 절차. 포트 **5099**, 단일 프로세스 운영 기준.

---

## 1. 사전 요구사항

| 항목 | 버전/비고 |
|---|---|
| Python | 3.10+ (코드에서 `X | None` 유니온 문법 사용) |
| Node.js | 18+ (프론트 빌드용) |
| MySQL | 8.x, DB명 `expense_tracker` (UTF-8 `utf8mb4`) |
| OS | Windows / Linux 무관 (현재 Windows에서 운영) |

> 키움 API 연동(`/api/kiwoom/*`)은 32bit 콜렉터·네이티브 환경 전제라 Windows에서만 동작. 그 외 기능은 OS 무관.

---

## 2. 코드 배치

`D:\stock_git`은 git 저장소가 아니므로 **파일 복사 방식**으로 배포한다.
빌드 산출물 `static/spa/`는 `.gitignore` 대상이므로 **배포 서버에서 직접 빌드**하거나 산출물을 함께 복사해야 한다.

---

## 3. 환경변수 (.env)

`.env.example`을 복사해 `.env`를 만들고 값을 채운다.

```bash
cp .env.example .env
```

### 필수
| 키 | 설명 |
|---|---|
| `SECRET_KEY` | 세션 서명 키. 없으면 기동 시 예외. `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DB_HOST` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | MySQL 접속 정보 |
| `PORT` | `5099` |
| `APP_BASE_URL` | 비밀번호 재설정 메일 링크 베이스. **운영 공인 도메인으로 변경** |
| `RUN_SCHEDULER` | 단일 프로세스 배포는 `true` (멀티 워커면 `false` + 별도 스케줄러 프로세스) |

### 결제 (mock 모드 — 의도된 운영 방식)
`PORTONE_STORE_ID` / `PORTONE_CHANNEL_KEY` / `PORTONE_API_SECRET`를 **비워두면 mock 결제**로 동작한다(실결제 없이 크레딧 충전 즉시 성공). 현재 배포는 mock 유지. 실유료 전환 시에만 PortOne 콘솔에서 키 발급 후 입력.

### AI 기능 (선택)
| 키 | 효과 |
|---|---|
| `ANTHROPIC_API_KEY` | 설정 시 AI 챗봇·종목 분석·AI 추천 패스 동작(실 크레딧 차감) |
| `RECOMMEND_PASS_COST` | AI 추천 데이 패스 1일 차감 크레딧 (기본 1000) |
| `RECOMMEND_PASS_RESET_HOUR` | 패스 하루 경계 시각 KST (기본 7 → 07:00) |

> `.env`에는 실 비밀값이 들어가므로 **절대 커밋·외부 유출 금지** (`.gitignore`에 이미 제외됨).

---

## 4. 백엔드 설치

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux
pip install -r requirements.txt
```

DB 테이블(`user_credits`, `credit_transactions`, `payments`, `recommend_pass` 등)은
**앱 기동 시 자동 생성**되므로 별도 마이그레이션 불필요.

---

## 5. 프론트엔드 빌드

```bash
cd client
npm install
npm run build      # → ../static/spa/ 로 출력
```

빌드 산출물은 백엔드가 정적 서빙한다. **프론트만 바뀌면 재빌드 후 새로고침으로 반영**되며 백엔드 재시작은 불필요.

---

## 6. 실행

`.env`의 `PORT`를 사용해 기동:

```bash
python app.py
```

또는 직접 uvicorn:

```bash
uvicorn app:app --host 127.0.0.1 --port 5099
```

- `reload=False` 고정 → **Python 코드 변경은 재시작해야 반영**된다.
- `RUN_SCHEDULER=true`면 기동 시 인프로세스 스케줄러(APScheduler, KST)가 등록된다:
  | 잡 | 시각(KST) |
  |---|---|
  | 아침 뉴스 크롤 | 평일/매일 08:40 |
  | AI 추천 모델(정규화+절대값) | **매일 06:30** |
  | 공시 알림 | 평일 09–15시 매 30분 |
  | 가격 알림 | 평일 09–15시 매 10분 |
  | 주간 학습 | 일요일 02:00 |

---

## 7. 헬스 체크

```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5099/                       # 302 (로그인 리다이렉트)
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5099/api/recommend-pass/status   # 401 (미인증)
```

302/401이 나오면 정상 기동. 스케줄러 상태는 로그에서 `[SCHEDULER]` 라인으로 확인.

---

## 8. 공개(HTTPS) 노출 시 조정

리버스 프록시(Nginx 등) + HTTPS로 외부 공개할 경우:

| 위치 | 현재값 | 변경 |
|---|---|---|
| `app.py` SessionMiddleware | `https_only=False`, `same_site="lax"` | `https_only=True` |
| `app.py:375` host | `127.0.0.1` | 같은 호스트 프록시면 유지, 직접 노출 시 `0.0.0.0` |
| `.env` `APP_BASE_URL` | `http://localhost:5099` | 공인 도메인(`https://...`) |

> 같은 호스트에서 리버스 프록시가 5099로 프록시하는 구성이면 `127.0.0.1` 유지가 더 안전하다.

---

## 9. 운영 메모

- **재시작이 필요한 변경**: Python 코드, `.env`. (프론트 빌드는 새로고침으로 반영)
- **멀티 워커 운영**: `RUN_SCHEDULER=false`로 끄고 스케줄러는 단일 별도 프로세스로 분리할 것(중복 실행 방지).
- **크레딧/결제 데이터**: `user_credits`(잔액), `credit_transactions`(내역), `payments`(결제), `recommend_pass`(AI 추천 패스). mock 모드에서도 동일 테이블에 기록된다.
