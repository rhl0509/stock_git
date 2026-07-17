# DB 연결 및 비밀키 등 설정 파일
import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

_secret_key = os.getenv('SECRET_KEY')
if not _secret_key:
    raise RuntimeError("SECRET_KEY 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요.")


class Config:
    """FastAPI 기본 설정 클래스"""

    SECRET_KEY = _secret_key

    # MySQL 연결 설정
    MYSQL_HOST     = os.getenv('DB_HOST', 'localhost')
    MYSQL_USER     = os.getenv('DB_USER', 'root')
    MYSQL_PASSWORD = os.getenv('DB_PASSWORD', '')
    MYSQL_DB       = os.getenv('DB_NAME', 'stock_stack')

    MYSQL_CURSORCLASS = 'DictCursor'

    # 포트원(PortOne) 결제 — 테스트 모드. 키가 없으면 라우트가 mock 모드로 동작한다.
    #   PORTONE_STORE_ID    : 상점 식별자 (프론트 SDK / 결제창에 사용)
    #   PORTONE_CHANNEL_KEY : 결제 채널 키 (프론트 결제창 requestPayment 에 사용)
    #   PORTONE_API_SECRET  : V2 REST API 시크릿 (서버 결제검증에 사용)
    #   PORTONE_WEBHOOK_SECRET : V2 웹훅 서명 검증 시크릿(whsec_...). 결제완료 통지 위·변조 차단.
    #                            비어 있으면 웹훅을 모두 거부(서명 검증 불가)하므로 실결제 전 반드시 설정.
    PORTONE_STORE_ID      = os.getenv('PORTONE_STORE_ID', '')
    PORTONE_CHANNEL_KEY   = os.getenv('PORTONE_CHANNEL_KEY', '')
    PORTONE_API_SECRET    = os.getenv('PORTONE_API_SECRET', '')
    PORTONE_WEBHOOK_SECRET = os.getenv('PORTONE_WEBHOOK_SECRET', '')

    # Claude(유료) AI 챗봇 — 키가 없으면 챗봇 비활성화.
    #   ANTHROPIC_API_KEY  : Anthropic API 키 (없으면 챗봇 OFF)
    #   CHAT_MODEL         : 사용할 모델 (기본 haiku — 저렴)
    #   CHAT_CREDIT_COST   : 챗봇 호출 1회당 고정 차감 크레딧
    ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
    CHAT_MODEL        = os.getenv('CHAT_MODEL', 'claude-haiku-4-5')
    CHAT_CREDIT_COST  = int(os.getenv('CHAT_CREDIT_COST', '100'))

    # 종목 AI 분석 1회당 고정 차감 크레딧 (Claude opus 호출, 챗봇보다 비쌈)
    ADVISOR_CREDIT_COST = int(os.getenv('ADVISOR_CREDIT_COST', '500'))

    # AI 추천 데이 패스: 하루(KST 07:00~다음날 07:00) 1회 차감 크레딧 + 하루 경계 시각.
    RECOMMEND_PASS_COST       = int(os.getenv('RECOMMEND_PASS_COST', '1000'))
    RECOMMEND_PASS_RESET_HOUR = int(os.getenv('RECOMMEND_PASS_RESET_HOUR', '7'))

    JSON_AS_ASCII = False

    DEBUG = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'

    # 비밀번호 재설정 링크가 가리킬 서비스 베이스 URL (운영 시 공인 도메인으로 변경).
    # SMTP 발송 자격증명은 notify/email_send.py(EMAIL_* / app_settings)를 재사용한다.
    APP_BASE_URL  = os.getenv('APP_BASE_URL', 'http://localhost:5000').rstrip('/')
