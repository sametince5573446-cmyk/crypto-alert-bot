import os
import time
import math
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta


# ============================================================
# AYARLAR
# ============================================================

TOTAL_CAPITAL = 100.0

MIN_BUDGET = 10.0
MAX_BUDGET = 40.0

# Bir işlemde planlanan maksimum zarar
MAX_RISK_DOLLARS = 2.50

# Binance'te taranacak coin sayısı
BINANCE_SCAN_COUNT = 100

# Aynı çalıştırmada gönderilecek maksimum Binance fırsatı
MAX_ALERTS = 3

# Haberlerin son kaç saatine bakılacak
NEWS_HOURS = 12

# Özel takip
SPECIAL_COINS = ["XVGUSDT", "QNTUSDT"]

# API
SPOT_URL = "https://data-api.binance.vision"
FUTURES_URL = "https://fapi.binance.com"

DEX_URL = "https://api.dexscreener.com"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ============================================================
# GENEL HTTP
# ============================================================

def get_json(url, params=None, timeout=15):
    try:
        r = requests.get(
            url,
            params=params,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"}
        )

        if r.status_code != 200:
            return None

        return r.json()

    except Exception:
        return None


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        r = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=15
        )

        return r.status_code == 200

    except Exception:
        return False


# ============================================================
# BINANCE
# ============================================================

def get_spot_tickers():
    data = get_json(
        f"{SPOT_URL}/api/v3/ticker/24hr"
    )

    if not data:
        return []

    coins = []

    for x in data:
        symbol = x.get("symbol", "")

        if not symbol.endswith("USDT"):
            continue

        if any(bad in symbol for bad in [
            "UPUSDT",
            "DOWNUSDT",
            "BULLUSDT",
            "BEARUSDT"
        ]):
            continue

        try:
            volume = float(x.get("quoteVolume", 0))
            price_change = float(x.get("priceChangePercent", 0))
            last_price = float(x.get("lastPrice", 0))

            if volume <= 0 or last_price <= 0:
                continue

            coins.append({
                "symbol": symbol,
                "volume": volume,
                "change24": price_change,
                "price": last_price
            })

        except Exception:
            continue

    coins.sort(
        key=lambda x: x["volume"],
        reverse=True
    )

    return coins


def get_klines(symbol, interval="1h", limit=80):
    return get_json(
        f"{SPOT_URL}/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )


# ============================================================
# TEKNİK ANALİZ
# ============================================================

def ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    result = sum(values[:period]) / period

    for price in values[period:]:
        result = (
            price - result
        ) * multiplier + result

    return result


def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]

        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def analyze_technical(klines):
    if not klines or len(klines) < 30:
        return None

    try:
        opens = [float(x[1]) for x in klines]
        highs = [float(x[2]) for x in klines]
        lows = [float(x[3]) for x in klines]
        closes = [float(x[4]) for x in klines]
        volumes = [float(x[5]) for x in klines]

        price = closes[-1]

        ema9 = ema(closes, 9)
        ema21 = ema(closes, 21)

        rsi = calculate_rsi(closes)

        support = min(lows[-24:])
        resistance = max(highs[-24:])

        avg_volume = sum(volumes[-21:-1]) / max(
            len(volumes[-21:-1]), 1
        )

        current_volume = volumes[-1]

        volume_ratio = (
            current_volume / avg_volume
            if avg_volume > 0 else 1
        )

        change_6h = (
            (price - closes[-7]) /
            closes[-7] * 100
            if len(closes) >= 7 else 0
        )

        change_3h = (
            (price - closes[-4]) /
            closes[-4] * 100
            if len(closes) >= 4 else 0
        )

        volatility = (
            (max(highs[-12:]) -
             min(lows[-12:])) /
            price * 100
        )

        trend = "YUKARI"

        if ema9 < ema21:
            trend = "AŞAĞI"

        if (
            abs(ema9 - ema21) /
            price * 100 < 0.15
        ):
            trend = "NÖTR"

        return {
            "price": price,
            "ema9": ema9,
            "ema21": ema21,
            "rsi": rsi,
            "support": support,
            "resistance": resistance,
            "volume_ratio": volume_ratio,
            "change6": change_6h,
            "change3": change_3h,
            "volatility": volatility,
            "trend": trend
        }

    except Exception:
        return None


# ============================================================
# BTC
# ============================================================

def get_btc_analysis():
    klines = get_klines(
        "BTCUSDT",
        "1h",
        50
    )

    data = analyze_technical(klines)

    if not data:
        return {
            "trend": "NÖTR",
            "rsi": 50,
            "change6": 0
        }

    return data


# ============================================================
# FUTURES VERİLERİ
# ============================================================

def get_funding(symbol):
    data = get_json(
        f"{FUTURES_URL}/fapi/v1/fundingRate",
        {
            "symbol": symbol,
            "limit": 1
        }
    )

    if not data:
        return 0

    try:
        return float(data[-1]["fundingRate"]) * 100
    except Exception:
        return 0


def get_open_interest(symbol):
    data = get_json(
        f"{FUTURES_URL}/fapi/v1/openInterest",
        {
            "symbol": symbol
        }
    )

    if not data:
        return 0

    try:
        return float(data["openInterest"])
    except Exception:
        return 0


def get_oi_history(symbol):
    data = get_json(
        f"{FUTURES_URL}/futures/data/openInterestHist",
        {
            "symbol": symbol,
            "period": "1h",
            "limit": 3
        }
    )

    if not data or len(data) < 2:
        return 0

    try:
        old = float(
            data[0].get(
                "sumOpenInterest",
                0
            )
        )

        new = float(
            data[-1].get(
                "sumOpenInterest",
                0
            )
        )

        if old == 0:
            return 0

        return (new - old) / old * 100

    except Exception:
        return 0


# ============================================================
# HABER
# ============================================================

RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss"
]

POSITIVE_WORDS = [
    "approval",
    "approved",
    "launch",
    "launched",
    "partnership",
    "partner",
    "listing",
    "adoption",
    "integration",
    "etf",
    "upgrade",
    "mainnet",
    "investment",
    "funding",
    "bullish",
    "buy",
    "growth",
    "record"
]

NEGATIVE_WORDS = [
    "hack",
    "hacked",
    "exploit",
    "lawsuit",
    "ban",
    "delist",
    "delisted",
    "scam",
    "fraud",
    "attack",
    "stolen",
    "liquidation",
    "dump",
    "unlock",
    "sell",
    "bearish"
]


def get_news():
    news = []

    cutoff = datetime.now(
        timezone.utc
    ) - timedelta(hours=NEWS_HOURS)

    for feed_url in RSS_FEEDS:

        try:
            r = requests.get(
                feed_url,
                timeout=15,
                headers={
                    "User-Agent": "Mozilla/5.0"
                }
            )

            if r.status_code != 200:
                continue

            root = ET.fromstring(r.content)

            for item in root.findall(".//item"):

                title_el = item.find("title")
                link_el = item.find("link")
                date_el = item.find("pubDate")

                if title_el is None:
                    continue

                title = (
                    title_el.text or ""
                ).strip()

                link = (
                    link_el.text
                    if link_el is not None
                    else ""
                )

                pub_date = None

                if date_el is not None:
                    try:
                        from email.utils import parsedate_to_datetime

                        pub_date = parsedate_to_datetime(
                            date_el.text
                        )

                        if pub_date.tzinfo is None:
                            pub_date = pub_date.replace(
                                tzinfo=timezone.utc
                            )

                    except Exception:
                        pass

                if pub_date and pub_date < cutoff:
                    continue

                news.append({
                    "title": title,
                    "link": link
                })

        except Exception:
            continue

    return news


def news_for_coin(symbol, news):
    base = symbol.replace(
        "USDT",
        ""
    ).upper()

    matches = []

    for item in news:

        title = item["title"].lower()

        if base.lower() not in title:
            continue

        positive = sum(
            1
            for word in POSITIVE_WORDS
            if word in title
        )

        negative = sum(
            1
            for word in NEGATIVE_WORDS
            if word in title
        )

        if negative > positive:
            sentiment = "OLUMSUZ"

        elif positive > negative:
            sentiment = "OLUMLU"

        else:
            sentiment = "NÖTR"

        matches.append({
            "title": item["title"],
            "sentiment": sentiment
        })

    return matches[:2]


def news_reason(sentiment):
    if sentiment == "OLUMLU":
        return (
            "Coin hakkında olumlu bir gelişme var; "
            "ilgi ve alım isteğini artırabilir."
        )

    if sentiment == "OLUMSUZ":
        return (
            "Coin hakkında olumsuz bir gelişme var; "
            "satış baskısı oluşturabilir."
        )

    return (
        "Haber tarafında belirgin bir yön yok."
    )


# ============================================================
# BTC FİLTRESİ
# ============================================================

def btc_allows_trade(direction, btc):

    if not btc:
        return True

    trend = btc["trend"]
    rsi = btc["rsi"]

    if direction == "LONG":

        if trend == "AŞAĞI" and rsi < 42:
            return False

    if direction == "SHORT":

        if trend == "YUKARI" and rsi > 58:
            return False

    return True


# ============================================================
# SİNYAL SKORU
# ============================================================

def calculate_signal(tech, funding, oi_change, news_items):

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []

    # Trend
    if tech["ema9"] > tech["ema21"]:
        long_score += 2
        long_reasons.append(
            "Kısa vadeli trend yukarı."
        )

    elif tech["ema9"] < tech["ema21"]:
        short_score += 2
        short_reasons.append(
            "Kısa vadeli trend aşağı."
        )

    # RSI
    if 50 <= tech["rsi"] <= 68:
        long_score += 1
        long_reasons.append(
            "Momentum alıcı tarafında."
        )

    if 32 <= tech["rsi"] <= 50:
        short_score += 1
        short_reasons.append(
            "Momentum satıcı tarafına dönüyor."
        )

    # Volume
    if tech["volume_ratio"] >= 1.5:

        if tech["change3"] > 0:
            long_score += 2
            long_reasons.append(
                "Hacim artışıyla birlikte yükseliş var."
            )

        elif tech["change3"] < 0:
            short_score += 2
            short_reasons.append(
                "Hacim artışıyla birlikte düşüş var."
            )

    elif tech["volume_ratio"] >= 1.15:

        if tech["change3"] > 0:
            long_score += 1
            long_reasons.append(
                "İşlem hacmi normalin üzerinde."
            )

        elif tech["change3"] < 0:
            short_score += 1
            short_reasons.append(
                "Satış hacmi normalin üzerinde."
            )

    # OI
    if oi_change > 3:

        if tech["change3"] > 0:
            long_score += 1
            long_reasons.append(
                "Vadeli işlemlerde pozisyon ilgisi artıyor."
            )

        elif tech["change3"] < 0:
            short_score += 1
            short_reasons.append(
                "Vadeli işlemlerde pozisyon ilgisi artıyor."
            )

    # Funding
    if funding > 0.05:
        short_score += 1
        short_reasons.append(
            "Long tarafında aşırı yoğunluk oluşuyor."
        )

    elif funding < -0.05:
        long_score += 1
        long_reasons.append(
            "Short tarafında yoğunluk oluşuyor."
        )

    # Haber
    for item in news_items:

        if item["sentiment"] == "OLUMLU":
            long_score += 1
            long_reasons.append(
                "Haber tarafında olumlu gelişme var."
            )

        elif item["sentiment"] == "OLUMSUZ":
            short_score += 1
            short_reasons.append(
                "Haber tarafında olumsuz gelişme var."
            )

    if long_score >= short_score:
        direction = "LONG"
        score = long_score
        reasons = long_reasons
    else:
        direction = "SHORT"
        score = short_score
        reasons = short_reasons

    return {
        "direction": direction,
        "score": score,
        "long_score": long_score,
        "short_score": short_score,
        "reasons": reasons[:4]
    }


# ============================================================
# BÜTÇE + KALDIRAÇ
# ============================================================

def choose_budget_and_leverage(score, stop_percent):

    if score >= 7:
        strength = "🚀 ÇOK GÜÇLÜ"
        desired_budget = 40

    elif score >= 6:
        strength = "🟢 GÜÇLÜ"
        desired_budget = 30

    elif score >= 5:
        strength = "🟡 ORTA GÜÇLÜ"
        desired_budget = 20

    else:
        strength = "⚪ ZAYIF"
        desired_budget = 10

    if score >= 7 and stop_percent <= 0.80:
        leverage = 10

    elif score >= 6 and stop_percent <= 1.00:
        leverage = 8

    elif score >= 5 and stop_percent <= 1.30:
        leverage = 6

    elif stop_percent <= 1.80:
        leverage = 5

    else:
        leverage = 3

    if stop_percent <= 0:
        stop_percent = 1

    max_budget_by_risk = (
        MAX_RISK_DOLLARS /
        (leverage * stop_percent / 100)
    )

    budget = min(
        desired_budget,
        max_budget_by_risk,
        MAX_BUDGET,
        TOTAL_CAPITAL
    )

    budget = max(
        MIN_BUDGET,
        round(budget, 2)
    )

    # Eğer risk hesabı minimum bütçeyi bile aşıyorsa
    # kaldıraç düşürülür.
    estimated_loss = (
        budget *
        leverage *
        stop_percent / 100
    )

    while estimated_loss > MAX_RISK_DOLLARS and leverage > 1:

        leverage -= 1

        estimated_loss = (
            budget *
            leverage *
            stop_percent / 100
        )

    return strength, budget, leverage


# ============================================================
# İŞLEM PLANI
# ============================================================

def make_trade_plan(direction, tech, score):

    entry = tech["price"]

    support = tech["support"]
    resistance = tech["resistance"]

    if direction == "LONG":

        stop = min(
            support,
            entry * 0.985
        )

        risk_percent = (
            (entry - stop) /
            entry * 100
        )

        if risk_percent < 0.35:
            risk_percent = 0.35
            stop = entry * (
                1 - risk_percent / 100
            )

        tp1 = entry * (
            1 + (risk_percent * 1.5) / 100
        )

        tp2 = entry * (
            1 + (risk_percent * 2.5) / 100
        )

    else:

        stop = max(
            resistance,
            entry * 1.015
        )

        risk_percent = (
            (stop - entry) /
            entry * 100
        )

        if risk_percent < 0.35:
            risk_percent = 0.35
            stop = entry * (
                1 + risk_percent / 100
            )

        tp1 = entry * (
            1 - (risk_percent * 1.5) / 100
        )

        tp2 = entry * (
            1 - (risk_percent * 2.5) / 100
        )

    strength, budget, leverage = (
        choose_budget_and_leverage(
            score,
            risk_percent
        )
    )

    loss = (
        budget *
        leverage *
        risk_percent / 100
    )

    if direction == "LONG":

        profit1 = (
            budget *
            leverage *
            (tp1 - entry) /
            entry
        )

        profit2 = (
            budget *
            leverage *
            (tp2 - entry) /
            entry
        )

    else:

        profit1 = (
            budget *
            leverage *
            (entry - tp1) /
            entry
        )

        profit2 = (
            budget *
            leverage *
            (entry - tp2) /
            entry
        )

    return {
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "risk_percent": risk_percent,
        "budget": budget,
        "leverage": leverage,
        "loss": loss,
        "profit1": profit1,
        "profit2": profit2,
        "strength": strength
    }


# ============================================================
# BINANCE MESAJI
# ============================================================

def format_binance_alert(
    symbol,
    signal,
    plan,
    news_items
):

    direction = signal["direction"]

    news_sentiment = "NÖTR"

    if news_items:
        sentiments = [
            x["sentiment"]
            for x in news_items
        ]

        if "OLUMSUZ" in sentiments:
            news_sentiment = "OLUMSUZ"

        elif "OLUMLU" in sentiments:
            news_sentiment = "OLUMLU"

    message = (
        f"🚨 FIRSAT\n\n"
        f"🪙 {symbol}\n"
        f"📊 {direction}\n"
        f"🔥 Sinyal: {plan['strength']}\n\n"
        f"💵 Bütçe: ${plan['budget']:.2f}\n"
        f"⚡ Kaldıraç: {plan['leverage']}x\n\n"
        f"📍 Giriş: {plan['entry']:.8f}\n"
        f"🛑 Stop: {plan['stop']:.8f}\n"
        f"🎯 TP1: {plan['tp1']:.8f}\n"
        f"🎯 TP2: {plan['tp2']:.8f}\n\n"
        f"🔻 Tahmini zarar: "
        f"${plan['loss']:.2f}\n"
        f"🟢 TP1 kâr: "
        f"${plan['profit1']:.2f}\n"
        f"🟢 TP2 kâr: "
        f"${plan['profit2']:.2f}\n\n"
        f"📰 Haber: {news_sentiment}\n"
    )

    if signal["reasons"]:

        message += "\n💡 Neden?\n"

        for reason in signal["reasons"]:
            message += f"• {reason}\n"

    if news_items:

        message += "\n📰 Son haberler:\n"

        for item in news_items:
            message += (
                f"• {item['title'][:150]}\n"
                f"  → {news_reason(item['sentiment'])}\n"
            )

    message += (
        "\n⚠️ Manuel değerlendirme içindir.\n"
        "Otomatik emir açılmaz."
    )

    return message


# ============================================================
# SOLANA ERKEN RADAR
# ============================================================

def dex_get(path):
    return get_json(
        f"{DEX_URL}{path}",
        timeout=15
    )


def get_solana_profiles():
    data = dex_get(
        "/token-profiles/latest/v1"
    )

    if not isinstance(data, list):
        return []

    return [
        x for x in data
        if x.get("chainId") == "solana"
    ]


def get_solana_takeovers():
    data = dex_get(
        "/community-takeovers/latest/v1"
    )

    if not isinstance(data, list):
        return []

    return [
        x for x in data
        if x.get("chainId") == "solana"
    ]


def get_solana_boosts():
    data = dex_get(
        "/token-boosts/latest/v1"
    )

    if not isinstance(data, list):
        return []

    return [
        x for x in data
        if x.get("chainId") == "solana"
    ]


def get_solana_pairs(token_address):

    data = dex_get(
        f"/token-pairs/v1/solana/{token_address}"
    )

    if not isinstance(data, list):
        return []

    return data


def choose_best_pair(pairs):

    valid = []

    for pair in pairs:

        try:
            liquidity = float(
                (pair.get("liquidity") or {}).get(
                    "usd", 0
                ) or 0
            )

            volume = float(
                (pair.get("volume") or {}).get(
                    "h24", 0
                ) or 0
            )

            if liquidity < 5000:
                continue

            valid.append(
                (
                    liquidity,
                    volume,
                    pair
                )
            )

        except Exception:
            continue

    if not valid:
        return None

    valid.sort(
        key=lambda x: (
            x[1],
            x[0]
        ),
        reverse=True
    )

    return valid[0][2]


def analyze_solana_token(pair, is_profile, is_takeover, is_boost):

    try:
        price_change = pair.get(
            "priceChange"
        ) or {}

        txns = pair.get(
            "txns"
        ) or {}

        volume = pair.get(
            "volume"
        ) or {}

        liquidity = pair.get(
            "liquidity"
        ) or {}

        change_1h = float(
            price_change.get("h1", 0) or 0
        )

        change_6h = float(
            price_change.get("h6", 0) or 0
        )

        change_24h = float(
            price_change.get("h24", 0) or 0
        )

        volume_1h = float(
            volume.get("h1", 0) or 0
        )

        volume_24h = float(
            volume.get("h24", 0) or 0
        )

        liquidity_usd = float(
            liquidity.get("usd", 0) or 0
        )

        tx_1h = txns.get("h1") or {}

        buys = int(
            tx_1h.get("buys", 0) or 0
        )

        sells = int(
            tx_1h.get("sells", 0) or 0
        )

        total_tx = buys + sells

        score = 0
        reasons = []

        # Henüz aşırı yükselmemiş olmalı
        if 2 <= change_1h <= 15:
            score += 2
            reasons.append(
                "Fiyat hareketi henüz erken aşamada."
            )

        elif change_1h > 35:
            # Fazla yükselmişse erken fırsat kabul etmiyoruz
            return None

        elif change_1h < 0:
            return None

        # 6 saatlik hareket
        if change_6h <= 25:
            score += 1

        # Hacim
        if volume_24h > 0:

            volume_ratio = (
                volume_1h /
                (volume_24h / 24)
            )

            if volume_ratio >= 3:
                score += 2
                reasons.append(
                    "Hacim belirgin şekilde hızlandı."
                )

            elif volume_ratio >= 1.8:
                score += 1
                reasons.append(
                    "Hacim normal seviyenin üzerine çıktı."
                )

        # Alıcılar
        if buys > sells * 1.4:
            score += 2
            reasons.append(
                "Alıcı işlemleri satıcılardan belirgin fazla."
            )

        elif buys > sells:
            score += 1
            reasons.append(
                "Alıcı tarafı biraz daha güçlü."
            )

        # İşlem sayısı
        if total_tx >= 100:
            score += 1
            reasons.append(
                "İşlem sayısı hareketlendi."
            )

        # Likidite
        if liquidity_usd >= 25000:
            score += 2
            reasons.append(
                "Likidite yeterli seviyede."
            )

        elif liquidity_usd >= 10000:
            score += 1
            reasons.append(
                "Likidite kabul edilebilir seviyede."
            )

        else:
            return None

        # Sosyal / profil hareketi
        if is_profile:
            score += 1
            reasons.append(
                "Token hakkında yeni sosyal/profil hareketi var."
            )

        # Community takeover
        if is_takeover:
            score += 2
            reasons.append(
                "Topluluk tarafında yeni hareketlilik var."
            )

        # Boost
        if is_boost:
            score += 1
            reasons.append(
                "DEX Screener üzerinde görünürlük artışı var."
            )

        if score < 6:
            return None

        symbol = (
            pair.get("baseToken", {})
            .get("symbol", "UNKNOWN")
        )

        return {
            "symbol": symbol,
            "price_change": change_1h,
            "volume_ratio": volume_1h / (
                volume_24h / 24
            ) if volume_24h > 0 else 0,
            "buys": buys,
            "sells": sells,
            "liquidity": liquidity_usd,
            "score": score,
            "reasons": reasons[:5],
            "url": pair.get("url", "")
        }

    except Exception:
        return None


def scan_solana():

    profiles = get_solana_profiles()
    takeovers = get_solana_takeovers()
    boosts = get_solana_boosts()

    # Adresleri topluyoruz
    profile_addresses = {
        x.get("tokenAddress")
        for x in profiles
        if x.get("tokenAddress")
    }

    takeover_addresses = {
        x.get("tokenAddress")
        for x in takeovers
        if x.get("tokenAddress")
    }

    boost_addresses = {
        x.get("tokenAddress")
        for x in boosts
        if x.get("tokenAddress")
    }

    addresses = list(
        profile_addresses |
        takeover_addresses |
        boost_addresses
    )

    # Çok fazla istek atmamak için ilk 20
    addresses = addresses[:20]

    opportunities = []

    for address in addresses:

        pairs = get_solana_pairs(address)

        pair = choose_best_pair(pairs)

        if not pair:
            continue

        result = analyze_solana_token(
            pair,
            address in profile_addresses,
            address in takeover_addresses,
            address in boost_addresses
        )

        if result:
            opportunities.append(result)

        # API'yi gereksiz zorlamayalım
        time.sleep(0.15)

    opportunities.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return opportunities[:3]


# ============================================================
# SOLANA TELEGRAM
# ============================================================

def format_solana_alert(item):

    message = (
        "🚨 ERKEN UYARI — SOLANA\n\n"
        f"🪙 {item['symbol']}\n"
        f"📈 Son hareket: "
        f"{item['price_change']:.1f}%\n"
        f"🔥 Hacim: "
        f"{item['volume_ratio']:.1f}x\n"
        f"👥 Alıcı işlemleri: "
        f"{item['buys']}\n"
        f"💧 Likidite: "
        f"${item['liquidity']:,.0f}\n\n"
        "💡 Neden dikkat çekti?\n"
    )

    for reason in item["reasons"]:
        message += f"• {reason}\n"

    message += (
        "\n🟡 ERKEN AŞAMA\n"
        "⚠️ Meme coin — çok yüksek risk\n"
        "📍 Solana\n"
        "🔎 Phantom'dan kontrol et.\n"
    )

    if item.get("url"):
        message += (
            f"\n🔗 DEX Screener:\n"
            f"{item['url']}"
        )

    return message


# ============================================================
# ANA SİSTEM
# ============================================================

def main():

    print("Bot başlıyor...")

    # --------------------------------------------------------
    # Haberleri tek sefer al
    # --------------------------------------------------------

    news = get_news()

    # --------------------------------------------------------
    # BTC
    # --------------------------------------------------------

    btc = get_btc_analysis()

    print(
        f"BTC: {btc['trend']} "
        f"RSI={btc['rsi']:.1f}"
    )

    # --------------------------------------------------------
    # Binance coinleri
    # --------------------------------------------------------

    tickers = get_spot_tickers()

    if not tickers:

        telegram_send(
            "❌ Binance verisi alınamadı."
        )

        return

    selected = tickers[
        :BINANCE_SCAN_COUNT
    ]

    # XVG + QNT zorunlu takip
    selected_symbols = {
        x["symbol"]
        for x in selected
    }

    for special in SPECIAL_COINS:

        if special not in selected_symbols:

            extra = next(
                (
                    x for x in tickers
                    if x["symbol"] == special
                ),
                None
            )

            if extra:
                selected.append(extra)

    opportunities = []

    print(
        f"{len(selected)} Binance coin taranıyor..."
    )

    # --------------------------------------------------------
    # Önce sadece teknik analiz
    # --------------------------------------------------------

    for coin in selected:

        symbol = coin["symbol"]

        klines = get_klines(
            symbol,
            "1h",
            80
        )

        tech = analyze_technical(
            klines
        )

        if not tech:
            continue

        # Aşırı hareket etmiş coinleri filtrele
        if abs(tech["change6"]) > 25:
            continue

        # RSI aşırılık filtresi
        if tech["rsi"] > 78 or tech["rsi"] < 22:
            continue

        news_items = news_for_coin(
            symbol,
            news
        )

        # Ön skor
        preliminary = calculate_signal(
            tech,
            0,
            0,
            news_items
        )

        # Zayıf coinlerde Futures isteği yapma
        if preliminary["score"] < 4:
            continue

        # ----------------------------------------------------
        # Futures sadece adaylarda
        # ----------------------------------------------------

        funding = get_funding(symbol)

        oi_change = get_oi_history(
            symbol
        )

        signal = calculate_signal(
            tech,
            funding,
            oi_change,
            news_items
        )

        if signal["score"] < 5:
            continue

        if not btc_allows_trade(
            signal["direction"],
            btc
        ):
            continue

        plan = make_trade_plan(
            signal["direction"],
            tech,
            signal["score"]
        )

        opportunities.append({
            "symbol": symbol,
            "signal": signal,
            "plan": plan,
            "news": news_items,
            "volume": coin["volume"]
        })

    # --------------------------------------------------------
    # En güçlü Binance fırsatları
    # --------------------------------------------------------

    opportunities.sort(
        key=lambda x: (
            x["signal"]["score"],
            x["volume"]
        ),
        reverse=True
    )

    sent = 0

    for opportunity in opportunities:

        if sent >= MAX_ALERTS:
            break

        message = format_binance_alert(
            opportunity["symbol"],
            opportunity["signal"],
            opportunity["plan"],
            opportunity["news"]
        )

        telegram_send(message)

        sent += 1

    # --------------------------------------------------------
    # Solana radar
    # --------------------------------------------------------

    try:

        solana_opportunities = (
            scan_solana()
        )

        for item in solana_opportunities:

            telegram_send(
                format_solana_alert(item)
            )

    except Exception as e:

        print(
            "Solana radar hatası:",
            str(e)
        )

    # --------------------------------------------------------
    # Özet
    # --------------------------------------------------------

    summary = (
        "🟢 PİYASA TARAMASI TAMAMLANDI\n\n"
        f"💵 Sermaye: ${TOTAL_CAPITAL:.2f}\n"
        f"🔎 Binance: {len(selected)} coin\n"
        f"⭐ Özel takip: XVG / QNT\n"
        f"🚀 Solana erken radar: AKTİF\n"
        f"📰 Haber taraması: AKTİF\n\n"
    )

    if sent == 0:

        summary += (
            "⏸️ WAIT\n"
            "Uygun Binance işlemi bulunamadı.\n"
        )

    else:

        summary += (
            f"🚨 {sent} Binance fırsatı gönderildi.\n"
        )

    summary += (
        "\n⚠️ Otomatik emir açılmaz.\n"
        "Manuel değerlendirme içindir."
    )

    telegram_send(summary)

    print("Tarama tamamlandı.")


if __name__ == "__main__":
    main()
