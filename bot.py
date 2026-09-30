import os
import json
import subprocess
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

# ============================================================
# AYARLAR
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SPOT_URL = "https://data-api.binance.vision"
FUTURES_URL = "https://fapi.binance.com"

CAPITAL = 100.0
MAX_RISK = 2.50

MAX_COINS = 100

SPECIAL_COINS = [
    "XVGUSDT",
    "QNTUSDT"
]

MAX_STOP_PERCENT = 5.0
MIN_LEVERAGE = 3

NEWS_HOURS = 12

SOLANA_STATE_FILE = "solana_alerts.json"


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=15
        )
    except Exception as e:
        print("Telegram:", e)


# ============================================================
# HTTP
# ============================================================

def get(url, params=None, timeout=15):

    try:

        r = requests.get(
            url,
            params=params,
            timeout=timeout
        )

        if r.status_code != 200:
            return None

        return r.json()

    except Exception as e:

        print("HTTP:", e)
        return None


# ============================================================
# BINANCE SPOT
# ============================================================

def ticker_24h():

    return get(
        SPOT_URL + "/api/v3/ticker/24hr",
        timeout=20
    ) or []


def klines(symbol, interval="1h", limit=100):

    return get(
        SPOT_URL + "/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    ) or []


# ============================================================
# BINANCE FUTURES
# ============================================================

def funding(symbol):

    data = get(
        FUTURES_URL + "/fapi/v1/fundingRate",
        {
            "symbol": symbol,
            "limit": 1
        }
    )

    if data:

        try:
            return float(data[-1]["fundingRate"])
        except:
            pass

    return 0.0


def open_interest_history(symbol):

    data = get(
        FUTURES_URL + "/futures/data/openInterestHist",
        {
            "symbol": symbol,
            "period": "1h",
            "limit": 3
        }
    )

    if not data or len(data) < 2:
        return 0.0

    try:

        old = float(data[-2]["sumOpenInterest"])
        new = float(data[-1]["sumOpenInterest"])

        if old <= 0:
            return 0.0

        return ((new - old) / old) * 100

    except:

        return 0.0


def mark_price(symbol):

    data = get(
        FUTURES_URL + "/fapi/v1/premiumIndex",
        {
            "symbol": symbol
        }
    )

    if data:

        try:
            return float(data["markPrice"])
        except:
            pass

    return 0.0


# ============================================================
# EMA
# ============================================================

def ema(values, period):

    if not values:
        return 0.0

    multiplier = 2 / (period + 1)

    result = values[0]

    for value in values[1:]:

        result = (
            (value - result) * multiplier
            + result
        )

    return result


# ============================================================
# RSI
# ============================================================

def rsi(values, period=14):

    if len(values) <= period:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = values[i] - values[i - 1]

        if change >= 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):

        avg_gain = (
            (avg_gain * (period - 1))
            + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1))
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


# ============================================================
# TIMEFRAME ANALYSIS
# ============================================================

def timeframe_analysis(symbol, interval):

    data = klines(symbol, interval, 100)

    if len(data) < 50:
        return None

    closes = [
        float(x[4])
        for x in data
    ]

    volumes = [
        float(x[5])
        for x in data
    ]

    e9 = ema(closes[-60:], 9)
    e21 = ema(closes[-60:], 21)

    current = closes[-1]

    old = closes[-2]

    change = (
        (current - old)
        / old
    ) * 100

    return {
        "price": current,
        "ema9": e9,
        "ema21": e21,
        "rsi": rsi(closes),
        "change": change,
        "volumes": volumes,
        "closes": closes
    }


# ============================================================
# BTC
# ============================================================

def btc_direction():

    h1 = timeframe_analysis(
        "BTCUSDT",
        "1h"
    )

    h4 = timeframe_analysis(
        "BTCUSDT",
        "4h"
    )

    if not h1 or not h4:

        return {
            "direction": "NÖTR",
            "rsi": 50,
            "change6h": 0
        }

    bullish = (
        h1["ema9"] > h1["ema21"]
        and
        h4["ema9"] > h4["ema21"]
    )

    bearish = (
        h1["ema9"] < h1["ema21"]
        and
        h4["ema9"] < h4["ema21"]
    )

    if bullish:

        direction = "YUKARI"

    elif bearish:

        direction = "AŞAĞI"

    else:

        direction = "NÖTR"

    return {
        "direction": direction,
        "rsi": h1["rsi"],
        "change6h": h1["change"]
    }


# ============================================================
# HABERLER
# ============================================================

POSITIVE = [
    "etf",
    "approved",
    "approval",
    "partnership",
    "adoption",
    "integration",
    "listing",
    "launch",
    "upgrade",
    "mainnet",
    "investment",
    "institutional"
]

NEGATIVE = [
    "hack",
    "exploit",
    "scam",
    "lawsuit",
    "ban",
    "delist",
    "delisting",
    "attack",
    "stolen",
    "fraud"
]


def get_news():

    feeds = [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss"
    ]

    result = []

    for feed in feeds:

        try:

            response = requests.get(
                feed,
                timeout=15
            )

            root = ET.fromstring(
                response.content
            )

            for item in root.iter("item"):

                title = item.findtext(
                    "title",
                    ""
                )

                pub = item.findtext(
                    "pubDate",
                    ""
                )

                result.append({
                    "title": title,
                    "pub": pub
                })

        except Exception as e:

            print("News:", e)

    return result


def news_for_coin(symbol, news):

    coin = symbol.replace(
        "USDT",
        ""
    ).lower()

    positive = 0
    negative = 0

    related = []

    for item in news:

        title = item["title"]

        low = title.lower()

        # Coin sembolü gerçekten başlıkta yoksa
        # bu haberi coin haberi kabul etme.
        if coin not in low:
            continue

        related.append(title)

        for word in POSITIVE:

            if word in low:
                positive += 1

        for word in NEGATIVE:

            if word in low:
                negative += 1

    if negative > positive:

        return "NEGATİF", related[:1]

    if positive > negative:

        return "POZİTİF", related[:1]

    return "NÖTR", []


# ============================================================
# COIN ANALİZİ
# ============================================================

def analyze_coin(symbol):

    h1 = timeframe_analysis(
        symbol,
        "1h"
    )

    h4 = timeframe_analysis(
        symbol,
        "4h"
    )

    if not h1 or not h4:
        return None

    price = h1["price"]

    # --------------------------------------------------------
    # 24 saatlik hareket
    # --------------------------------------------------------

    closes = h1["closes"]

    if len(closes) >= 25:

        change24h = (
            (closes[-1] - closes[-25])
            / closes[-25]
        ) * 100

    else:

        change24h = 0

    # Aşırı pump olmuş coinleri ele
    if abs(change24h) > 30:
        return None

    # --------------------------------------------------------
    # Hacim
    # --------------------------------------------------------

    volumes = h1["volumes"]

    recent_volume = volumes[-1]

    avg_volume = (
        sum(volumes[-25:-1])
        / 24
    )

    if avg_volume <= 0:
        return None

    volume_ratio = (
        recent_volume
        / avg_volume
    )

    # --------------------------------------------------------
    # Trend
    # --------------------------------------------------------

    h1_bull = (
        h1["ema9"]
        >
        h1["ema21"]
    )

    h1_bear = (
        h1["ema9"]
        <
        h1["ema21"]
    )

    h4_bull = (
        h4["ema9"]
        >
        h4["ema21"]
    )

    h4_bear = (
        h4["ema9"]
        <
        h4["ema21"]
    )

    if h1_bull and h4_bull:

        trend = "YUKARI"

    elif h1_bear and h4_bear:

        trend = "AŞAĞI"

    else:

        trend = "NÖTR"

    # --------------------------------------------------------
    # Destek / direnç
    # --------------------------------------------------------

    support = min(
        closes[-25:]
    )

    resistance = max(
        closes[-25:]
    )

    return {
        "symbol": symbol,
        "price": price,
        "h1": h1,
        "h4": h4,
        "trend": trend,
        "volume_ratio": volume_ratio,
        "change24h": change24h,
        "support": support,
        "resistance": resistance
    }


# ============================================================
# YÖN DOĞRULAMA
# ============================================================

def determine_direction(data, btc):

    trend = data["trend"]

    btc_dir = btc["direction"]

    # LONG
    if trend == "YUKARI":

        if btc_dir in [
            "YUKARI",
            "NÖTR"
        ]:

            return "LONG"

    # SHORT
    if trend == "AŞAĞI":

        if btc_dir in [
            "AŞAĞI",
            "NÖTR"
        ]:

            return "SHORT"

    return None


# ============================================================
# FUTURES DOĞRULAMASI
# ============================================================

def derivatives_confirmation(
    symbol,
    direction
):

    fr = funding(symbol)

    oi_change = open_interest_history(
        symbol
    )

    mark = mark_price(symbol)

    # Funding:
    # LONG için aşırı negatif funding destekleyici olabilir.
    # SHORT için aşırı pozitif funding destekleyici olabilir.

    funding_score = 0

    if direction == "LONG":

        if fr <= -0.0003:
            funding_score += 1

        elif fr > 0.0010:
            funding_score -= 1

    elif direction == "SHORT":

        if fr >= 0.0003:
            funding_score += 1

        elif fr < -0.0010:
            funding_score -= 1

    # OI
    oi_score = 0

    if direction == "LONG":

        if oi_change > 0.5:
            oi_score += 1

    elif direction == "SHORT":

        if oi_change > 0.5:
            oi_score += 1

    return {
        "funding": fr,
        "oi_change": oi_change,
        "mark": mark,
        "funding_score": funding_score,
        "oi_score": oi_score
    }


# ============================================================
# MOMENTUM
# ============================================================

def momentum_confirmation(data, direction):

    h1 = data["h1"]

    current = h1["price"]

    previous = h1["closes"][-2]

    move = (
        (current - previous)
        / previous
    ) * 100

    r = h1["rsi"]

    if direction == "LONG":

        # LONG için fiyatın aşağı değil yukarı
        # momentum göstermesini istiyoruz.
        if move <= 0:
            return False

        if r < 48 or r > 72:
            return False

    elif direction == "SHORT":

        # SHORT için fiyatın aşağı momentum
        # göstermesini istiyoruz.
        if move >= 0:
            return False

        if r < 28 or r > 55:
            return False

    return True


# ============================================================
# TRADE PLAN
# ============================================================

def create_plan(
    data,
    direction,
    score
):

    price = data["price"]

    support = data["support"]

    resistance = data["resistance"]

    if direction == "LONG":

        stop = support

        distance = price - stop

        if distance <= 0:
            return None

    else:

        stop = resistance

        distance = stop - price

        if distance <= 0:
            return None

    stop_percent = (
        distance
        / price
    ) * 100

    # %5 üstü kesinlikle yok
    if stop_percent > MAX_STOP_PERCENT:
        return None

    # Çok küçük stop da tehlikeli olabilir.
    if stop_percent < 0.15:
        return None

    # --------------------------------------------------------
    # TP
    # --------------------------------------------------------

    if direction == "LONG":

        tp1 = price + distance * 1.5
        tp2 = price + distance * 2.5

    else:

        tp1 = price - distance * 1.5
        tp2 = price - distance * 2.5

    # --------------------------------------------------------
    # Kaldıraç
    # --------------------------------------------------------

    if score >= 9:

        leverage = 10
        budget_target = 40

    elif score >= 8:

        leverage = 8
        budget_target = 35

    elif score >= 7:

        leverage = 6
        budget_target = 30

    elif score >= 6:

        leverage = 5
        budget_target = 20

    else:

        leverage = 3
        budget_target = 10

    leverage = max(
        leverage,
        MIN_LEVERAGE
    )

    # Stop genişse kaldıraç düşür
    if stop_percent > 4:

        leverage = min(
            leverage,
            3
        )

    elif stop_percent > 3:

        leverage = min(
            leverage,
            5
        )

    elif stop_percent > 2:

        leverage = min(
            leverage,
            6
        )

    # --------------------------------------------------------
    # Risk hesabı
    # --------------------------------------------------------

    risk_per_dollar = (
        stop_percent / 100
    ) * leverage

    if risk_per_dollar <= 0:
        return None

    max_budget = (
        MAX_RISK
        / risk_per_dollar
    )

    budget = min(
        budget_target,
        max_budget,
        CAPITAL
    )

    # Çok küçük pozisyon gönderme
    if budget < 5:
        return None

    estimated_loss = (
        budget
        * leverage
        * stop_percent
        / 100
    )

    if estimated_loss > MAX_RISK + 0.01:
        return None

    # --------------------------------------------------------
    # Kâr
    # --------------------------------------------------------

    tp1_percent = (
        abs(tp1 - price)
        / price
    ) * 100

    tp2_percent = (
        abs(tp2 - price)
        / price
    ) * 100

    profit1 = (
        budget
        * leverage
        * tp1_percent
        / 100
    )

    profit2 = (
        budget
        * leverage
        * tp2_percent
        / 100
    )

    return {
        "entry": price,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "stop_percent": stop_percent,
        "budget": budget,
        "leverage": leverage,
        "loss": estimated_loss,
        "profit1": profit1,
        "profit2": profit2
    }


# ============================================================
# ANA SİNYAL
# ============================================================

def evaluate_coin(
    data,
    btc,
    news
):

    symbol = data["symbol"]

    direction = determine_direction(
        data,
        btc
    )

    if not direction:
        return None

    # --------------------------------------------------------
    # Momentum
    # --------------------------------------------------------

    if not momentum_confirmation(
        data,
        direction
    ):
        return None

    # --------------------------------------------------------
    # Futures
    # --------------------------------------------------------

    derivatives = derivatives_confirmation(
        symbol,
        direction
    )

    # Negatif futures doğrulaması
    if derivatives["funding_score"] < 0:
        return None

    # OI'nin tersine hareket etmesini istemiyoruz
    if derivatives["oi_change"] < -1.0:
        return None

    # --------------------------------------------------------
    # Haber
    # --------------------------------------------------------

    sentiment, titles = news_for_coin(
        symbol,
        news
    )

    # --------------------------------------------------------
    # Skor
    # --------------------------------------------------------

    score = 0

    # 1H + 4H trend
    score += 2

    # BTC uyumu
    if btc["direction"] == data["trend"]:

        score += 2

    elif btc["direction"] == "NÖTR":

        score += 1

    # Hacim
    if data["volume_ratio"] >= 2:

        score += 2

    elif data["volume_ratio"] >= 1.4:

        score += 1

    else:

        return None

    # Momentum
    score += 2

    # OI
    if derivatives["oi_change"] >= 1:

        score += 1

    # Funding
    if derivatives["funding_score"] > 0:

        score += 1

    # Haber
    if sentiment != "NÖTR":

        score += 1

    # --------------------------------------------------------
    # Çok güçlü için daha yüksek eşik
    # --------------------------------------------------------

    if score < 7:
        return None

    # --------------------------------------------------------
    # Trade plan
    # --------------------------------------------------------

    plan = create_plan(
        data,
        direction,
        score
    )

    if not plan:
        return None

    # --------------------------------------------------------
    # GİRİŞ GÜNCELLİK KONTROLÜ
    # --------------------------------------------------------

    live = mark_price(symbol)

    if live <= 0:
        live = data["price"]

    entry = plan["entry"]

    difference = (
        abs(live - entry)
        / entry
    ) * 100

    # Sinyal fiyatından %0.5 fazla uzaklaşmışsa
    # eski sinyal gönderme.
    if difference > 0.50:

        return None

    plan["entry"] = live

    # --------------------------------------------------------
    # Son güvenlik hesabı
    # --------------------------------------------------------

    new_stop_percent = (
        abs(plan["stop"] - live)
        / live
    ) * 100

    if new_stop_percent > MAX_STOP_PERCENT:

        return None

    # --------------------------------------------------------
    # Güven etiketi
    # --------------------------------------------------------

    if score >= 10:

        label = "🚀 ÇOK GÜÇLÜ"

    elif score >= 8:

        label = "🟢 GÜÇLÜ"

    else:

        label = "🟡 ORTA GÜÇLÜ"

    # --------------------------------------------------------
    # NEDEN
    # --------------------------------------------------------

    reasons = []

    if direction == "LONG":

        reasons.append(
            "1H ve 4H trend yukarı."
        )

        reasons.append(
            "Momentum alıcı tarafında."
        )

    else:

        reasons.append(
            "1H ve 4H trend aşağı."
        )

        reasons.append(
            "Momentum satıcı tarafında."
        )

    if data["volume_ratio"] >= 1.4:

        reasons.append(
            "Hacim hareketi destekliyor."
        )

    if derivatives["oi_change"] > 0:

        reasons.append(
            "Open Interest yükseliyor."
        )

    if derivatives["funding_score"] > 0:

        reasons.append(
            "Funding yönü pozisyonu destekliyor."
        )

    if sentiment == "POZİTİF":

        reasons.append(
            "Coinle doğrudan ilişkili olumlu haber bulundu."
        )

    elif sentiment == "NEGATİF":

        reasons.append(
            "Coinle doğrudan ilişkili negatif haber bulundu."
        )

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "label": label,
        "plan": plan,
        "sentiment": sentiment,
        "titles": titles,
        "reasons": reasons,
        "funding": derivatives["funding"],
        "oi": derivatives["oi_change"]
    }


# ============================================================
# SOLANA RADAR
# ============================================================

def load_state():

    if not os.path.exists(
        SOLANA_STATE_FILE
    ):

        return {}

    try:

        with open(
            SOLANA_STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except:

        return {}


def save_state(state):

    with open(
        SOLANA_STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            state,
            f,
            indent=2
        )


def commit_state():

    try:

        subprocess.run(
            [
                "git",
                "config",
                "user.name",
                "crypto-alert-bot"
            ],
            check=False
        )

        subprocess.run(
            [
                "git",
                "config",
                "user.email",
                "crypto-alert-bot@users.noreply.github.com"
            ],
            check=False
        )

        subprocess.run(
            [
                "git",
                "add",
                SOLANA_STATE_FILE
            ],
            check=False
        )

        subprocess.run(
            [
                "git",
                "commit",
                "-m",
                "Update Solana alert state"
            ],
            check=False
        )

        subprocess.run(
            [
                "git",
                "push"
            ],
            check=False
        )

    except Exception as e:

        print("Git:", e)


def solana_profiles():

    urls = [
        "https://api.dexscreener.com/token-profiles/latest/v1",
        "https://api.dexscreener.com/token-boosts/latest/v1"
    ]

    addresses = []

    for url in urls:

        data = get(
            url,
            timeout=15
        )

        if not data:
            continue

        for item in data:

            if item.get(
                "chainId"
            ) != "solana":

                continue

            address = item.get(
                "tokenAddress"
            )

            if (
                address
                and
                address not in addresses
            ):

                addresses.append(
                    address
                )

    return addresses[:25]


def solana_pair(address):

    data = get(
        f"https://api.dexscreener.com/latest/dex/tokens/{address}",
        timeout=15
    )

    if not data:
        return None

    pairs = data.get(
        "pairs",
        []
    )

    pairs = [
        p for p in pairs
        if p.get("chainId") == "solana"
    ]

    if not pairs:
        return None

    pairs.sort(
        key=lambda x: float(
            x.get(
                "liquidity",
                {}
            ).get(
                "usd",
                0
            ) or 0
        ),
        reverse=True
    )

    return pairs[0]


def solana_radar():

    state = load_state()

    now = datetime.now(
        timezone.utc
    )

    cleaned = {}

    for address, stamp in state.items():

        try:

            old = datetime.fromisoformat(
                stamp
            )

            if (
                now - old
                <
                timedelta(hours=24)
            ):

                cleaned[address] = stamp

        except:

            pass

    state = cleaned

    addresses = solana_profiles()

    for address in addresses:

        if address in state:
            continue

        pair = solana_pair(
            address
        )

        if not pair:
            continue

        try:

            changes = pair.get(
                "priceChange",
                {}
            )

            change1h = float(
                changes.get(
                    "h1",
                    0
                ) or 0
            )

            change6h = float(
                changes.get(
                    "h6",
                    0
                ) or 0
            )

            change24h = float(
                changes.get(
                    "h24",
                    0
                ) or 0
            )

            volume = pair.get(
                "volume",
                {}
            )

            volume1h = float(
                volume.get(
                    "h1",
                    0
                ) or 0
            )

            volume24h = float(
                volume.get(
                    "h24",
                    0
                ) or 0
            )

            if volume24h <= 0:
                continue

            volume_ratio = (
                volume1h
                /
                (volume24h / 24)
            )

            liquidity = float(
                pair.get(
                    "liquidity",
                    {}
                ).get(
                    "usd",
                    0
                ) or 0
            )

            txns = pair.get(
                "txns",
                {}
            ).get(
                "h1",
                {}
            )

            buys = int(
                txns.get(
                    "buys",
                    0
                ) or 0
            )

            sells = int(
                txns.get(
                    "sells",
                    0
                ) or 0
            )

            total = buys + sells

            buyer_ratio = (
                buys
                /
                max(sells, 1)
            )

            # Çok yükselmiş coinleri ele
            if change1h >= 25:
                continue

            if change6h >= 40:
                continue

            if change24h >= 100:
                continue

            if change1h <= 0:
                continue

            if volume_ratio < 1.8:
                continue

            if liquidity < 10000:
                continue

            if total < 40:
                continue

            if buyer_ratio < 1.15:
                continue

            score = 0

            if 3 <= change1h < 10:
                score += 3

            elif 10 <= change1h < 15:
                score += 2

            elif 15 <= change1h < 25:
                score += 1

            else:
                continue

            if volume_ratio >= 5:
                score += 4

            elif volume_ratio >= 3:
                score += 3

            else:
                score += 2

            if buyer_ratio >= 2:
                score += 3

            elif buyer_ratio >= 1.5:
                score += 2

            else:
                score += 1

            if total >= 500:
                score += 2

            elif total >= 100:
                score += 1

            if liquidity >= 50000:
                score += 2

            else:
                score += 1

            if pair.get("boosts"):
                score += 1

            if score < 9:
                continue

            token = pair.get(
                "baseToken",
                {}
            )

            name = token.get(
                "symbol",
                "UNKNOWN"
            )

            if change1h <= 10:
                stage = "🟢 ERKEN HAREKET"
            else:
                stage = "🟡 ERKEN AŞAMA"

            message = f"""
🚨 ERKEN UYARI — SOLANA

🪙 {name}
📈 Son hareket: {change1h:.1f}%
🔥 Hacim: Normalden {volume_ratio:.1f}x
👥 Alıcı işlemleri: {buys}
💧 Likidite: ${liquidity:,.0f}

💡 Neden dikkat çekti?
• Fiyat henüz aşırı yükselmedi.
• Hacim normalin üzerine çıktı.
• Alıcı hareketi güçlendi.
• İşlem sayısı arttı.

{stage}

⚠️ Meme coin — çok yüksek risk
📍 Solana
🔎 Phantom'dan kontrol et.

🔗 DEX Screener:
{pair.get("url", "")}
"""

            telegram(message)

            state[address] = now.isoformat()

        except Exception as e:

            print(
                "Solana analiz:",
                e
            )

    save_state(state)

    commit_state()


# ============================================================
# ANA
# ============================================================

def main():

    print(
        "================================"
    )

    print(
        "CRYPTO ALERT BOT BAŞLADI"
    )

    print(
        "================================"
    )

    news = get_news()

    btc = btc_direction()

    print(
        "BTC:",
        btc["direction"],
        "RSI:",
        round(
            btc["rsi"],
            1
        )
    )

    tickers = ticker_24h()

    coins = []

    for item in tickers:

        symbol = item.get(
            "symbol",
            ""
        )

        if not symbol.endswith(
            "USDT"
        ):
            continue

        if (
            symbol.endswith("UPUSDT")
            or
            symbol.endswith("DOWNUSDT")
        ):
            continue

        try:

            volume = float(
                item.get(
                    "quoteVolume",
                    0
                )
            )

            coins.append(
                (
                    symbol,
                    volume
                )
            )

        except:

            pass

    coins.sort(
        key=lambda x: x[1],
        reverse=True
    )

    selected = [
        x[0]
        for x in coins[:MAX_COINS]
    ]

    for special in SPECIAL_COINS:

        if special not in selected:

            selected.append(
                special
            )

    opportunities = []

    for i, symbol in enumerate(
        selected,
        1
    ):

        print(
            f"[{i}/{len(selected)}]",
            symbol
        )

        data = analyze_coin(
            symbol
        )

        if not data:
            continue

        result = evaluate_coin(
            data,
            btc,
            news
        )

        if result:

            opportunities.append(
                result
            )

    # ========================================================
    # EN GÜÇLÜ SİNYAL
    # ========================================================

    if opportunities:

        opportunities.sort(
            key=lambda x: x["score"],
            reverse=True
        )

        best = opportunities[0]

        plan = best["plan"]

        message = f"""
🚨 FIRSAT

🪙 {best["symbol"]}
📊 {best["direction"]}
🔥 Sinyal: {best["label"]}

💵 Bütçe: ${plan["budget"]:.2f}
⚡ Kaldıraç: {plan["leverage"]}x

📍 Giriş: {plan["entry"]:.8f}
🛑 Stop: {plan["stop"]:.8f}
🎯 TP1: {plan["tp1"]:.8f}
🎯 TP2: {plan["tp2"]:.8f}

📏 Stop mesafesi: %{plan["stop_percent"]:.2f}

🔻 Tahmini zarar: ${plan["loss"]:.2f}
🟢 TP1 kâr: ${plan["profit1"]:.2f}
🟢 TP2 kâr: ${plan["profit2"]:.2f}

📰 Haber: {best["sentiment"]}
"""

        if best["titles"]:

            message += (
                "\n📰 "
                + best["titles"][0]
                + "\n"
            )

        message += "\n💡 Neden?\n"

        for reason in best["reasons"]:

            message += (
                "• "
                + reason
                + "\n"
            )

        message += f"""
📊 Funding: {best["funding"]:.5f}
📈 OI değişimi: {best["oi"]:+.2f}%

⚠️ Manuel değerlendirme içindir.
Otomatik emir açılmaz.
"""

        telegram(message)

    else:

        message = f"""
🟢 PİYASA TARAMASI TAMAMLANDI

💵 Sermaye: ${CAPITAL:.2f}

🌐 BTC DURUMU
Trend: {btc["direction"]}
RSI: {btc["rsi"]:.1f}
6s değişim: {btc["change6h"]:+.2f}%

🔎 {len(selected)} coin tarandı.

⏸️ WAIT — Doğrulaması yeterli işlem bulunamadı.

📌 Sıkı filtreler:
• 1H + 4H trend uyumu
• BTC yön kontrolü
• Momentum doğrulaması
• Hacim doğrulaması
• Funding kontrolü
• Open Interest kontrolü
• Maksimum %5 stop
• Minimum 3x kaldıraç
• Maksimum $2.50 planlanan zarar
• Güncel giriş fiyatı kontrolü
• İlgili haber kontrolü

⚠️ Otomatik emir açılmaz.
Manuel değerlendirme içindir.
"""

        telegram(message)

    # ========================================================
    # SOLANA
    # ========================================================

    try:

        solana_radar()

    except Exception as e:

        print(
            "Solana radar:",
            e
        )

    print(
        "BOT TAMAMLANDI"
    )


if __name__ == "__main__":

    main()
