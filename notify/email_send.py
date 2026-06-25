"""notify/email_send.py — 이메일 알림 발송 (SMTP)."""
from __future__ import annotations
import base64, hashlib, os, smtplib, logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def _fernet():
    from cryptography.fernet import Fernet
    from config import Config
    key = base64.urlsafe_b64encode(hashlib.sha256(Config.SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt_password(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_password(ciphertext: str) -> str:
    """복호화 실패 시 원문 반환 (평문 저장된 기존 값 호환)."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except Exception:
        return ciphertext


def _get_email_config() -> dict:
    """DB 또는 환경변수에서 이메일 설정 로드."""
    try:
        from database.db_connection import get_db_connection
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT `key`, `value` FROM app_settings WHERE `key` LIKE 'email_%'")
            rows = cur.fetchall()
        conn.close()
        cfg = {r['key'].replace('email_', ''): r['value'] for r in rows}
        if cfg.get('password'):
            cfg['password'] = decrypt_password(cfg['password'])
        if cfg.get('to'):
            return cfg
    except Exception:
        pass
    return {
        'smtp_host': os.getenv('EMAIL_SMTP_HOST', 'smtp.gmail.com'),
        'smtp_port': os.getenv('EMAIL_SMTP_PORT', '587'),
        'user':      os.getenv('EMAIL_USER', ''),
        'password':  os.getenv('EMAIL_PASSWORD', ''),
        'to':        os.getenv('EMAIL_TO', ''),
    }


def send_email(subject: str, body: str, html: bool = False) -> bool:
    """이메일 발송. 성공 시 True 반환."""
    cfg = _get_email_config()
    if not cfg.get('to') or not cfg.get('user'):
        logger.debug('[email] 이메일 설정 없음 — 발송 스킵')
        return False
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = cfg['user']
        msg['To']      = cfg['to']
        part = MIMEText(body, 'html' if html else 'plain', 'utf-8')
        msg.attach(part)

        port = int(cfg.get('smtp_port', 587))
        with smtplib.SMTP(cfg['smtp_host'], port, timeout=15) as s:
            s.ehlo()
            s.starttls()
            s.login(cfg['user'], cfg['password'])
            s.sendmail(cfg['user'], cfg['to'], msg.as_string())
        logger.info(f'[email] 발송 성공 → {cfg["to"]}')
        return True
    except Exception as e:
        logger.warning(f'[email] 발송 실패: {e}')
        return False


def send_email_to(recipient: str, subject: str, body: str, html: bool = False) -> bool:
    """임의 수신자에게 발송. SMTP 자격증명은 소유자 설정을 재사용하되 To만 교체.

    계정 복구(비밀번호 재설정)처럼 가입자 본인 이메일로 보내야 하는 경우 사용한다.
    SMTP 미설정(user/password 없음) 시 False를 반환하고 발송하지 않는다.
    """
    cfg = _get_email_config()
    if not cfg.get('user') or not cfg.get('password'):
        logger.warning('[email] SMTP 자격증명 없음 — 메일 발송 불가')
        return False
    if not recipient:
        return False
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = cfg['user']
        msg['To']      = recipient
        msg.attach(MIMEText(body, 'html' if html else 'plain', 'utf-8'))

        port = int(cfg.get('smtp_port', 587))
        with smtplib.SMTP(cfg['smtp_host'], port, timeout=15) as s:
            s.ehlo()
            s.starttls()
            s.login(cfg['user'], cfg['password'])
            s.sendmail(cfg['user'], recipient, msg.as_string())
        logger.info(f'[email] 발송 성공 → {recipient}')
        return True
    except Exception as e:
        logger.warning(f'[email] 발송 실패 ({recipient}): {e}')
        return False


def smtp_configured() -> bool:
    """SMTP 발송 자격증명(user/password)이 갖춰졌는지."""
    cfg = _get_email_config()
    return bool(cfg.get('user') and cfg.get('password'))


def send_password_reset(recipient: str, reset_url: str, valid_minutes: int = 30) -> bool:
    """비밀번호 재설정 링크 메일 발송."""
    subject = "[GAGYE] 비밀번호 재설정 안내"
    html = f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:480px;margin:0 auto;color:#1f2937">
  <h2 style="font-size:18px">비밀번호 재설정</h2>
  <p style="font-size:14px;line-height:1.6">
    아래 버튼을 눌러 새 비밀번호를 설정하세요. 이 링크는 <b>{valid_minutes}분간</b>만 유효합니다.
  </p>
  <p style="margin:24px 0">
    <a href="{reset_url}"
       style="display:inline-block;background:#4f46e5;color:#fff;text-decoration:none;
              padding:12px 22px;border-radius:8px;font-size:14px;font-weight:600">
      비밀번호 재설정하기
    </a>
  </p>
  <p style="font-size:12px;color:#6b7280;line-height:1.6">
    버튼이 동작하지 않으면 아래 주소를 복사해 브라우저에 붙여넣으세요.<br>
    <span style="word-break:break-all">{reset_url}</span>
  </p>
  <hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0">
  <p style="font-size:12px;color:#9ca3af;line-height:1.6">
    본인이 요청하지 않았다면 이 메일을 무시하세요. 비밀번호는 변경되지 않습니다.
  </p>
</div>
"""
    return send_email_to(recipient, subject, html, html=True)


def send_email_if_enabled(subject: str, body: str) -> bool:
    """알림 설정에서 이메일 활성화된 경우만 발송."""
    try:
        from database.db_connection import get_db_connection
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT `value` FROM app_settings WHERE `key`='email_enabled'")
            row = cur.fetchone()
        conn.close()
        if not row or row['value'] != '1':
            return False
    except Exception:
        pass
    return send_email(subject, body)
