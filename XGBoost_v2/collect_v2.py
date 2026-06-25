"""
collect_v2.py — KOSPI + KOSDAQ 통합 OHLCV 수집.
기존 collect.py 대체. data/ohlcv/*.parquet 저장.

실행:
  python collect_v2.py                        # KOSPI+KOSDAQ 전체
  python collect_v2.py --market KOSPI
  python collect_v2.py --market KOSDAQ --top 100
"""
import os, sys, time, json, logging, argparse, warnings
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).parent
DATA_DIR = ROOT_DIR / 'data' / 'ohlcv'
DATA_DIR.mkdir(parents=True, exist_ok=True)

OHLCV_COUNT = 1800
MIN_ROWS = 120
YFINANCE_DELAY = 0.25


# ═════════════════════════════════════════════════════════════════════════
# KOSPI 시총 상위 200 (기존 유지)
# ═════════════════════════════════════════════════════════════════════════
_KOSPI = [
    ("005930","삼성전자"),("000660","SK하이닉스"),("009150","삼성전기"),("066570","LG전자"),
    ("018260","삼성에스디에스"),("006400","삼성SDI"),("034730","SK"),("000990","DB하이텍"),
    ("402340","SK스퀘어"),
    ("042700","한미반도체"),("005380","현대차"),("000270","기아"),("012330","현대모비스"),
    ("204320","만도"),("051910","LG화학"),("003670","포스코퓨처엠"),("009830","한화솔루션"),
    ("010130","고려아연"),("011790","SKC"),("011170","롯데케미칼"),("002380","KCC"),
    ("006650","대한유화"),("004370","농심"),("068270","셀트리온"),("207940","삼성바이오로직스"),
    ("128940","한미약품"),("000100","유한양행"),("185750","종근당"),("069620","대웅제약"),
    ("001060","JW중외제약"),("170900","동아에스티"),("035420","NAVER"),("035720","카카오"),
    ("036570","엔씨소프트"),("251270","넷마블"),("259960","크래프톤"),("293490","카카오게임즈"),
    ("017670","SK텔레콤"),("030200","KT"),("032640","LG유플러스"),("105560","KB금융"),
    ("055550","신한지주"),("086790","하나금융지주"),("316140","우리금융지주"),("024110","기업은행"),
    ("071050","한국금융지주"),("138040","메리츠금융지주"),("000810","삼성화재"),("088350","한화생명"),
    ("032830","삼성생명"),("082640","동양생명"),("001450","현대해상"),("000060","메리츠화재"),
    ("096770","SK이노베이션"),("010950","S-Oil"),("015760","한국전력"),("036460","한국가스공사"),
    ("003490","대한항공"),("180640","한진칼"),("004020","현대제철"),("005490","POSCO홀딩스"),
    ("042660","한화오션"),("329180","현대중공업"),("009540","HD한국조선해양"),("010140","삼성중공업"),
    ("047050","포스코인터내셔널"),("028260","삼성물산"),("000720","현대건설"),("375500","DL이앤씨"),
    ("047040","대우건설"),("006200","한국전력기술"),("000080","하이트진로"),("069960","현대백화점"),
    ("004170","신세계"),("023530","롯데쇼핑"),("007070","GS리테일"),("139480","이마트"),
    ("097950","CJ제일제당"),("000120","CJ대한통운"),("003550","LG"),("001040","CJ"),
    ("047810","한국항공우주"),("064350","현대로템"),("012450","한화에어로스페이스"),("035900","JYP Ent."),
    ("041510","에스엠"),("352820","하이브"),("122870","YG엔터테인먼트"),("021240","코웨이"),
    ("010060","OCI홀딩스"),("004490","세방전지"),("014820","동원시스템즈"),("007310","오뚜기"),
    ("005850","에스엘"),("008770","호텔신라"),("272210","한화시스템"),("298040","효성중공업"),
    ("298000","효성티앤씨"),("170950","효성화학"),("094280","에이피티씨"),("011200","HMM"),
    ("035250","강원랜드"),("000880","한화"),("009240","한샘"),("008040","흥국화재"),
    ("010620","현대미포조선"),("267250","HD현대"),("000240","한국타이어앤테크놀로지"),("025860","남해화학"),
    ("003230","삼양식품"),("001740","SK네트웍스"),("016360","삼성증권"),("003460","유화증권"),
    ("030610","교보증권"),("039490","키움증권"),("006800","미래에셋증권"),("001500","현대차증권"),
    ("005940","NH투자증권"),("010820","한화투자증권"),("088980","맥쿼리인프라"),("247540","에코프로비엠"),
    ("086520","에코프로"),("373220","LG에너지솔루션"),("102780","COSMO신소재"),("285130","SK케미칼"),
    ("096530","씨젠"),("240810","원익IPS"),("036540","SFA반도체"),("050960","수산씨아이에스"),
    ("065150","MP한강"),("067310","하나마이크론"),("042090","코텍"),("088790","화인베스틸"),
    ("140610","엔에스엔"),("048410","현대바이오"),("005690","파미셀"),("214150","클래시스"),
    ("112160","CJ바이오사이언스"),("000210","대림"),("002790","아모레퍼시픽그룹"),("090430","아모레퍼시픽"),
    ("051600","한전KPS"),("030000","제일기획"),("004830","덕성"),("007860","서연"),
    ("005720","넥센타이어"),("014530","에쓰씨엔지니어링"),("000150","두산"),("042670","두산밥캣"),
    ("034220","LG디스플레이"),("010120","LS ELECTRIC"),("010600","웰닉스머티리얼즈"),
    # 필터 유니버스 추가 종목
    ("000670","DB손해보험"),("004000","롯데케미칼"),("005300","롯데칠성"),
    ("005830","DB손해보험우"),("005935","삼성전자우"),("006360","GS건설"),
    ("011070","LG이노텍"),("017800","현대엘리베이터"),("020560","아시아나항공"),
    ("034020","두산에너빌리티"),("060980","한라홀딩스"),("161390","한국타이어앤테크놀로지"),
    ("241560","두산밥캣"),("271560","오리온"),("280360","롯데웰푸드"),
    ("298050","효성화학"),("323410","카카오뱅크"),
]

# ═════════════════════════════════════════════════════════════════════════
# KOSDAQ 시총 상위 150 (2024~2025 기준)
# ═════════════════════════════════════════════════════════════════════════
_KOSDAQ = [
    ("196170","알테오젠"),("068760","셀트리온제약"),("247540","에코프로비엠"),("086520","에코프로"),
    ("091990","셀트리온헬스케어"),("066970","엘앤에프"),("263750","펄어비스"),("112040","위메이드"),
    ("058470","리노공업"),("403870","HPSP"),("039030","이오테크닉스"),("277810","레인보우로보틱스"),
    ("293490","카카오게임즈"),("357780","솔브레인"),("214450","파마리서치"),("065350","신성통상"),
    ("095340","ISC"),("078600","대주전자재료"),("085660","차바이오텍"),("214150","클래시스"),
    ("041510","에스엠"),("265520","AP시스템"),("299030","하이딥"),("348370","엔켐"),
    ("095660","네오위즈"),("067310","하나마이크론"),("195940","HK이노엔"),("448280","유일로보틱스"),
    ("950140","잉글우드랩"),("950210","프레스티지바이오파마"),("131970","두산테스나"),("141080","리가켐바이오"),
    ("145020","휴젤"),("226320","잇츠한불"),("240810","원익IPS"),("035900","JYP Ent."),
    ("137310","에스디바이오센서"),("178920","PI첨단소재"),("086900","메디톡스"),("099430","바이오플러스"),
    ("036930","주성엔지니어링"),("089790","제이티"),("260970","S&K폴리텍"),("178320","서진시스템"),
    ("066970","엘앤에프"),("241590","화승엔터프라이즈"),("108320","LX세미콘"),("090460","비에이치"),
    ("319660","피에스케이"),("039200","오스코텍"),("043370","평화정공"),("033290","코웰패션"),
    ("950130","엑세스바이오"),("357580","이구산업"),("196300","뷰노"),("400760","NAIZ"),
    ("277880","티엘비"),("126880","제이엔비"),("109820","진매트릭스"),("251970","펌텍코리아"),
    ("376300","디어유"),("064260","다날"),("122990","와이솔"),("189300","인텔리안테크"),
    ("236200","에스티팜"),("032500","케이엠더블유"),("217270","넵튠"),("376190","리썬콘텐츠"),
    ("228760","지노믹트리"),("218410","RFHIC"),("058610","에스피지"),("085370","루트로닉"),
    ("307280","미투온"),("217500","엘엠에스"),("067900","와이엔텍"),("403870","HPSP"),
    ("289080","넥스틴"),("290670","베스파"),("272210","한화시스템"),("317830","에이플러스에셋"),
    ("272290","이녹스첨단소재"),("402030","에이프로젠바이오로직스"),("099320","쎄트렉아이"),("136540","윈스"),
    ("078340","컴투스"),("225570","넥슨게임즈"),("084370","유진테크"),("263750","펄어비스"),
    ("108230","톱텍"),("290690","에스티아이"),("036830","솔브레인홀딩스"),("039840","디오"),
    ("192440","슈피겐코리아"),("228670","투비소프트"),("035760","CJ ENM"),("047920","HLB제약"),
    ("028300","HLB"),("298380","에이비엘바이오"),("183300","코미코"),("080720","유진기업"),
    ("393890","케이옥션"),("263810","심텍홀딩스"),("234340","자람테크놀로지"),("353200","대덕전자"),
    ("950170","JTC"),("950160","코오롱티슈진"),("114840","에프알텍"),("067160","아프리카TV"),
    ("230240","에치에프알"),("035600","KG이니시스"),("093320","케이아이엔엑스"),("950220","네오이뮨텍"),
    ("352820","하이브"),("018290","브이티"),("179900","유테크"),("215000","골프존"),
    ("065660","안트로젠"),("237690","에스티팜"),("347860","알체라"),("418550","제이엠멀티"),
    ("263860","드림텍"),("101670","코리아에스이"),("074600","원익큐엔씨"),("166090","하나머티리얼즈"),
    ("079190","EMW"),("052710","아모텍"),("251270","넷마블"),("033500","동성화인텍"),
    ("900140","엘브이엠씨홀딩스"),("102710","이엔에프테크놀로지"),("317330","덕산테코피아"),("900290","GRT"),
    ("094170","동운아나텍"),("950110","SBI핀테크솔루션즈"),("950210","프레스티지바이오파마"),("136510","쎄니트"),
    ("196170","알테오젠"),("064550","바이오니아"),("039440","에스티아이"),("900120","씨케이에이치"),
    ("067630","HLB생명과학"),("357120","코람코더원리츠"),("417500","한선엔지니어링"),("036010","아비코전자"),
    ("222080","씨아이에스"),("199800","툴젠"),("290720","오스테오닉"),("365900","엑세스바이오"),
    ("203450","유비쿼스"),("130580","나이스정보통신"),("900070","글로벌에스엠"),("900310","컬러레이"),
    # 필터 유니버스 추가 종목
    ("336370","솔루스첨단소재"),("229640","LS에코에너지"),("025540","SFC"),
]


def _dedup(items):
    seen = set(); out = []
    for c, n in items:
        if c not in seen:
            seen.add(c); out.append((c, n))
    return out


_KOSPI = _dedup(_KOSPI)
_KOSDAQ = _dedup(_KOSDAQ)


def get_tickers(market: str = "ALL", top: int = None) -> list[dict]:
    """market: KOSPI | KOSDAQ | ALL"""
    result = []
    if market in ("KOSPI", "ALL"):
        kospi = _KOSPI[:top] if top else _KOSPI
        result += [{"code": c, "name": n, "market": "KOSPI"} for c, n in kospi]
    if market in ("KOSDAQ", "ALL"):
        kosdaq = _KOSDAQ[:top] if top else _KOSDAQ
        result += [{"code": c, "name": n, "market": "KOSDAQ"} for c, n in kosdaq]
    return result


def get_db_tickers(market: str = "ALL", top: int = None) -> list[dict]:
    """kr_stocks 테이블 전체를 유니버스로 사용 (code, name, market)."""
    sys.path.insert(0, str(ROOT_DIR.parent))
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if market == "ALL":
                cur.execute("SELECT code, name, market FROM kr_stocks ORDER BY code")
            else:
                cur.execute("SELECT code, name, market FROM kr_stocks WHERE market=%s ORDER BY code", (market,))
            rows = cur.fetchall()
    finally:
        conn.close()
    out = [{"code": r["code"], "name": r["name"], "market": (r["market"] or "KOSPI")} for r in rows]
    return out[:top] if top else out


# ═════════════════════════════════════════════════════════════════════════
# OHLCV 수집 (yfinance)
# ═════════════════════════════════════════════════════════════════════════

def _yfcode(code: str, market: str = "KOSPI") -> str:
    """국내 종목코드 → yfinance 심볼 (KOSDAQ은 .KQ)"""
    if "." in code:
        return code
    suffix = ".KQ" if market == "KOSDAQ" else ".KS"
    return code + suffix


def fetch_yfinance(code: str, market: str = "KOSPI",
                    count: int = OHLCV_COUNT) -> pd.DataFrame | None:
    try:
        import yfinance as yf
        yfcode = _yfcode(code, market)
        end    = datetime.now()
        start  = end - timedelta(days=max(int(count * 1.5), 1800))
        raw    = yf.Ticker(yfcode).history(start=start, end=end, auto_adjust=False)
        if raw is None or raw.empty or len(raw) < MIN_ROWS:
            return None
        df = raw[["Open","High","Low","Close","Volume"]].copy()
        df.columns = ["open","high","low","close","volume"]
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df = df.sort_index()
        daily = df["close"].pct_change().abs()
        df = df[daily < 0.30]
        time.sleep(YFINANCE_DELAY)
        return df
    except Exception:
        return None


def save_ohlcv(code: str, df: pd.DataFrame):
    path = DATA_DIR / f"{code}.parquet"
    df.to_parquet(path, engine="pyarrow", compression="snappy")


def load_ohlcv(code: str) -> pd.DataFrame | None:
    path = DATA_DIR / f"{code}.parquet"
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path, engine="pyarrow")
    except Exception:
        return None


def is_fresh(code: str, hours: int = 20) -> bool:
    path = DATA_DIR / f"{code}.parquet"
    if not path.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    return age.total_seconds() < hours * 3600


def list_collected() -> list[str]:
    return sorted([p.stem for p in DATA_DIR.glob("*.parquet")])


# ═════════════════════════════════════════════════════════════════════════
# 메인 수집
# ═════════════════════════════════════════════════════════════════════════

def collect_all(market: str = "ALL", top: int = None,
                force: bool = False, count: int = OHLCV_COUNT,
                source: str = "hardcoded"):
    tickers = get_db_tickers(market, top) if source == "db" else get_tickers(market, top)
    total = len(tickers)
    success = skipped = 0
    failed = []

    logger.info(f"[collect] 대상: {total}개 ({market})")

    try:
        from tqdm import tqdm
        iterable = tqdm(tickers, desc="수집", ncols=80)
    except ImportError:
        iterable = tickers

    # 종목 → market 매핑 저장 (feature 빌드 시 참조용)
    market_map = {}

    for t in iterable:
        code, mk = t["code"], t["market"]
        market_map[code] = mk

        if not force and is_fresh(code):
            skipped += 1
            continue

        df = fetch_yfinance(code, market=mk, count=count)
        if df is not None and len(df) >= MIN_ROWS:
            save_ohlcv(code, df)
            success += 1
        else:
            failed.append(code)

    # 종목 메타 저장 (기존 메타와 병합 — 다른 소스 수집분을 덮어쓰지 않음)
    meta_path = DATA_DIR.parent / 'ticker_meta.json'
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
        except Exception:
            meta = {}
    meta.update({t["code"]: {"name": t["name"], "market": t["market"]} for t in tickers})
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    logger.info(f"[collect] 성공={success} 스킵={skipped} 실패={len(failed)}")
    if failed:
        logger.warning(f"[collect] 실패 {len(failed)}개: {failed[:10]}...")

    summary = {
        "collected_at": datetime.now().isoformat(),
        "market": market, "total": total,
        "success": success, "skipped": skipped, "failed": failed,
    }
    with open(DATA_DIR.parent / 'collect_summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return summary


def load_ticker_meta() -> dict:
    """종목 메타 정보 로드 (code → {name, market})"""
    path = DATA_DIR.parent / 'ticker_meta.json'
    if not path.exists():
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def parse_args():
    p = argparse.ArgumentParser(description="KOSPI+KOSDAQ OHLCV 수집")
    p.add_argument('--market', choices=['KOSPI','KOSDAQ','ALL'], default='ALL')
    p.add_argument('--top', type=int, default=None)
    p.add_argument('--count', type=int, default=OHLCV_COUNT)
    p.add_argument('--force', action='store_true')
    p.add_argument('--source', choices=['hardcoded','db'], default='hardcoded',
                   help="db: kr_stocks 테이블 전체를 유니버스로 사용")
    p.add_argument('--list', action='store_true')
    return p.parse_args()


if __name__ == '__main__':
    args = parse_args()
    if args.list:
        codes = list_collected()
        meta = load_ticker_meta()
        for c in codes:
            m = meta.get(c, {})
            print(f"  {c} [{m.get('market','?')}] {m.get('name','')}")
        logger.info(f"총 {len(codes)}개")
        sys.exit(0)

    logger.info("=" * 60)
    logger.info(f"■ OHLCV 수집 시작 ({args.market}, source={args.source})")
    logger.info("=" * 60)
    collect_all(market=args.market, top=args.top, force=args.force,
                count=args.count, source=args.source)
    logger.info("다음: python train_v2.py --source local")