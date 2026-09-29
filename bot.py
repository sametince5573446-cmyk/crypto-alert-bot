import os
import time
import json
import subprocess
import requests
import xml.etree.ElementTree as ET

from datetime import datetime, timezone, timedelta


# ============================================================
# AYARLAR
# ============================================================

TOTAL_CAPITAL = 100.0

MIN_BUDGET = 10.0
MAX_BUDGET = 40.0

MAX_RISK_DOLLARS = 2.50

BINANCE_SCAN_COUNT = 100
MAX_ALERTS = 3

NEWS_HOURS = 12

SPECIAL_COINS = [
    "XVGUSDT",
    "QNTUSDT"
]

SPOT_URL = "https://data-api.binance.vision"
FUTURES_URL = "https://fapi.binance.com"

DEX_URL = "https://api.dexscreener.com"

SOLANA_STATE_FILE = "solana_alerts.json"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ============================================================
# HTTP
# ============================================================

def get_json(url, params=None, timeout=15):

    try:

        r = requests.get(
            url,
            params=params,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
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

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    try:

        r = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=15
        )

        return r.status_code == 200

    except Exception:
        return False


# ============================================================
# BINANCE SPOT
# ============================================================

def get_spot_tickers():

    data = get_json(
        f"{SPOT_URL}/api/v3/ticker/24hr"
    )

    if not data:
        return []

    result = []

    for x in data:

        symbol = x.get("symbol", "")

        if not symbol.endswith("USDT"):
            continue

        if any(
            bad in symbol
            for bad in [
                "UPUSDT",
                "DOWNUSDT",
                "BULLUSDT",
                "BEARUSDT"
            ]
        ):
            continue

        try:

            volume = float(
                x.get("quoteVolume", 0)
            )

            change = float(
                x.get("priceChangePercent", 0)
            )

            price = float(
                x.get("lastPrice", 0)
            )

            if volume <= 0 or price <= 0:
                continue

            result.append({
                "symbol": symbol,
                "volume": volume,
                "change24": change,
                "price": price
            })

        except Exception:
            continue

    result.sort(
        key=lambda x: x["volume"],
        reverse=True
    )

    return result


def get_klines(
    symbol,
    interval="1h",
    limit=80
):

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

    result = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        result = (
            price - result
        ) * multiplier + result

    return result


def calculate_rsi(
    closes,
    period=14
):

    if len(closes) < period + 1:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(closes)):

        change = (
            closes[i] -
            closes[i - 1]
        )

        if change > 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(abs(change))

    avg_gain = (
        sum(gains[-period:]) /
        period
    )

    avg_loss = (
        sum(losses[-period:]) /
        period
    )

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


def analyze_technical(klines):

    if not klines or len(klines) < 30:
        return None

    try:

        highs = [
            float(x[2])
            for x in klines
        ]

        lows = [
            float(x[3])
            for x in klines
        ]

        closes = [
            float(x[4])
            for x in klines
        ]

        volumes = [
            float(x[5])
            for x in klines
        ]

        price = closes[-1]

        ema9 = ema(
            closes,
            9
        )

        ema21 = ema(
            closes,
            21
        )

        rsi = calculate_rsi(
            closes
        )

        support = min(
            lows[-24:]
        )

        resistance = max(
            highs[-24:]
        )

        avg_volume = (
            sum(volumes[-21:-1]) /
            max(len(volumes[-21:-1]), 1)
        )

        current_volume = volumes[-1]

        volume_ratio = (
            current_volume /
            avg_volume
            if avg_volume > 0
            else 1
        )

        change3 = (
            (
                price -
                closes[-4]
            ) /
            closes[-4]
        ) * 100

        change6 = (
            (
                price -
                closes[-7]
            ) /
            closes[-7]
        ) * 100

        if ema9 > ema21:

            trend = "YUKARI"

        elif ema9 < ema21:

            trend = "AŞAĞI"

        else:

            trend = "NÖTR"

        if (
            abs(ema9 - ema21) /
            price * 100
        ) < 0.15:

            trend = "NÖTR"

        return {
            "price": price,
            "ema9": ema9,
            "ema21": ema21,
            "rsi": rsi,
            "support": support,
            "resistance": resistance,
            "volume_ratio": volume_ratio,
            "change3": change3,
            "change6": change6,
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

    result = analyze_technical(
        klines
    )

    if not result:

        return {
            "trend": "NÖTR",
            "rsi": 50,
            "change6": 0
        }

    return result


# ============================================================
# FUTURES
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

        return (
            float(
                data[-1]["fundingRate"]
            ) * 100
        )

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

        return (
            (new - old) /
            old *
            100
        )

    except Exception:
        return 0


# ============================================================
# HABER
# ============================================================

RSS_FEEDS = [

    "https://www.coindesk.com/"
    "arc/outboundfeeds/rss/",

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

    cutoff = (
        datetime.now(timezone.utc)
        -
        timedelta(
            hours=NEWS_HOURS
        )
    )

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

            root = ET.fromstring(
                r.content
            )

            for item in root.findall(
                ".//item"
            ):

                title_el = item.find(
                    "title"
                )

                date_el = item.find(
                    "pubDate"
                )

                if title_el is None:
                    continue

                title = (
                    title_el.text or ""
                ).strip()

                pub_date = None

                if date_el is not None:

                    try:

                        from email.utils import (
                            parsedate_to_datetime
                        )

                        pub_date = (
                            parsedate_to_datetime(
                                date_el.text
                            )
                        )

                        if pub_date.tzinfo is None:

                            pub_date = (
                                pub_date.replace(
                                    tzinfo=timezone.utc
                                )
                            )

                    except Exception:
                        pass

                if (
                    pub_date and
                    pub_date < cutoff
                ):
                    continue

                news.append({
                    "title": title
                })

        except Exception:
            continue

    return news


def news_for_coin(
    symbol,
    news
):

    base = symbol.replace(
        "USDT",
        ""
    ).upper()

    result = []

    for item in news:

        title = item[
            "title"
        ]

        lower = title.lower()

        if base.lower() not in lower:
            continue

        positive = sum(
            word in lower
            for word in POSITIVE_WORDS
        )

        negative = sum(
            word in lower
            for word in NEGATIVE_WORDS
        )

        if negative > positive:

            sentiment = "OLUMSUZ"

        elif positive > negative:

            sentiment = "OLUMLU"

        else:

            sentiment = "NÖTR"

        result.append({
            "title": title,
            "sentiment": sentiment
        })

    return result[:2]


def news_reason(
    sentiment
):

    if sentiment == "OLUMLU":

        return (
            "Olumlu gelişme ilgi ve "
            "alım isteğini artırabilir."
        )

    if sentiment == "OLUMSUZ":

        return (
            "Olumsuz gelişme satış "
            "baskısı oluşturabilir."
        )

    return (
        "Haber tarafında belirgin "
        "bir yön yok."
    )


# ============================================================
# SİNYAL
# ============================================================

def calculate_signal(
    tech,
    funding,
    oi_change,
    news_items
):

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []

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

    if (
        50 <= tech["rsi"] <= 68
    ):

        long_score += 1

        long_reasons.append(
            "Momentum alıcı tarafında."
        )

    if (
        32 <= tech["rsi"] <= 50
    ):

        short_score += 1

        short_reasons.append(
            "Momentum satıcı tarafına dönüyor."
        )

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

        elif tech["change3"] < 0:

            short_score += 1

    if oi_change > 3:

        if tech["change3"] > 0:

            long_score += 1

        elif tech["change3"] < 0:

            short_score += 1

    if funding > 0.05:

        short_score += 1

        short_reasons.append(
            "Long tarafında yoğunluk oluşuyor."
        )

    elif funding < -0.05:

        long_score += 1

        long_reasons.append(
            "Short tarafında yoğunluk oluşuyor."
        )

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
        "reasons": reasons[:4]
    }


# ============================================================
# BÜTÇE
# ============================================================

def choose_budget(
    score,
    stop_percent
):

    if score >= 7:

        strength = "🚀 ÇOK GÜÇLÜ"
        desired = 40

    elif score >= 6:

        strength = "🟢 GÜÇLÜ"
        desired = 30

    elif score >= 5:

        strength = "🟡 ORTA GÜÇLÜ"
        desired = 20

    else:

        strength = "⚪ ZAYIF"
        desired = 10

    if (
        score >= 7 and
        stop_percent <= 0.80
    ):

        leverage = 10

    elif (
        score >= 6 and
        stop_percent <= 1.00
    ):

        leverage = 8

    elif (
        score >= 5 and
        stop_percent <= 1.30
    ):

        leverage = 6

    elif stop_percent <= 1.80:

        leverage = 5

    else:

        leverage = 3

    risk = (
        leverage *
        stop_percent /
        100
    )

    if risk <= 0:
        risk = 0.01

    max_budget = (
        MAX_RISK_DOLLARS /
        risk
    )

    budget = min(
        desired,
        max_budget,
        MAX_BUDGET,
        TOTAL_CAPITAL
    )

    budget = max(
        MIN_BUDGET,
        round(budget, 2)
    )

    while (
        budget *
        leverage *
        stop_percent /
        100
        > MAX_RISK_DOLLARS
        and leverage > 1
    ):

        leverage -= 1

    return (
        strength,
        budget,
        leverage
    )


# ============================================================
# İŞLEM PLANI
# ============================================================

def make_trade_plan(
    direction,
    tech,
    score
):

    entry = tech["price"]

    if direction == "LONG":

        stop = min(
            tech["support"],
            entry * 0.985
        )

        risk_percent = (
            entry - stop
        ) / entry * 100

        if risk_percent < 0.35:

            risk_percent = 0.35

            stop = (
                entry *
                (
                    1 -
                    risk_percent /
                    100
                )
            )

        tp1 = entry * (
            1 +
            risk_percent *
            1.5 /
            100
        )

        tp2 = entry * (
            1 +
            risk_percent *
            2.5 /
            100
        )

    else:

        stop = max(
            tech["resistance"],
            entry * 1.015
        )

        risk_percent = (
            stop - entry
        ) / entry * 100

        if risk_percent < 0.35:

            risk_percent = 0.35

            stop = (
                entry *
                (
                    1 +
                    risk_percent /
                    100
                )
            )

        tp1 = entry * (
            1 -
            risk_percent *
            1.5 /
            100
        )

        tp2 = entry * (
            1 -
            risk_percent *
            2.5 /
            100
        )

    strength, budget, leverage = (
        choose_budget(
            score,
            risk_percent
        )
    )

    loss = (
        budget *
        leverage *
        risk_percent /
        100
    )

    if direction == "LONG":

        profit1 = (
            budget *
            leverage *
            (
                tp1 - entry
            ) /
            entry
        )

        profit2 = (
            budget *
            leverage *
            (
                tp2 - entry
            ) /
            entry
        )

    else:

        profit1 = (
            budget *
            leverage *
            (
                entry - tp1
            ) /
            entry
        )

        profit2 = (
            budget *
            leverage *
            (
                entry - tp2
            ) /
            entry
        )

    return {
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "budget": budget,
        "leverage": leverage,
        "loss": loss,
        "profit1": profit1,
        "profit2": profit2,
        "strength": strength
    }


# ============================================================
# BTC FİLTRESİ
# ============================================================

def btc_allows_trade(
    direction,
    btc
):

    if not btc:
        return True

    if (
        direction == "LONG" and
        btc["trend"] == "AŞAĞI" and
        btc["rsi"] < 42
    ):

        return False

    if (
        direction == "SHORT" and
        btc["trend"] == "YUKARI" and
        btc["rsi"] > 58
    ):

        return False

    return True


# ============================================================
# BINANCE MESAJ
# ============================================================

def format_binance_alert(
    symbol,
    signal,
    plan,
    news_items
):

    sentiment = "NÖTR"

    if news_items:

        sentiments = [
            x["sentiment"]
            for x in news_items
        ]

        if "OLUMSUZ" in sentiments:

            sentiment = "OLUMSUZ"

        elif "OLUMLU" in sentiments:

            sentiment = "OLUMLU"

    message = (
        "🚨 FIRSAT\n\n"
        f"🪙 {symbol}\n"
        f"📊 {signal['direction']}\n"
        f"🔥 Sinyal: {plan['strength']}\n\n"
        f"💵 Bütçe: ${plan['budget']:.2f}\n"
        f"⚡ Kaldıraç: {plan['leverage']}x\n\n"
        f"📍 Giriş: {plan['entry']:.8f}\n"
        f"🛑 Stop: {plan['stop']:.8f}\n"
        f"🎯 TP1: {plan['tp1']:.8f}\n"
        f"🎯 TP2: {plan['tp2']:.8f}\n\n"
        f"🔻 Tahmini zarar: ${plan['loss']:.2f}\n"
        f"🟢 TP1 kâr: ${plan['profit1']:.2f}\n"
        f"🟢 TP2 kâr: ${plan['profit2']:.2f}\n\n"
        f"📰 Haber: {sentiment}\n"
    )

    if signal["reasons"]:

        message += "\n💡 Neden?\n"

        for reason in signal["reasons"]:

            message += (
                f"• {reason}\n"
            )

    if news_items:

        message += "\n📰 Haber:\n"

        for item in news_items:

            message += (
                f"• {item['title'][:140]}\n"
                f"  → "
                f"{news_reason(item['sentiment'])}\n"
            )

    message += (
        "\n⚠️ Manuel değerlendirme içindir.\n"
        "Otomatik emir açılmaz."
    )

    return message


# ============================================================
# SOLANA API
# ============================================================

def dex_get(path):

    return get_json(
        f"{DEX_URL}{path}"
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


def get_solana_pairs(
    address
):

    data = dex_get(
        f"/token-pairs/v1/solana/{address}"
    )

    if not isinstance(data, list):
        return []

    return data


# ============================================================
# SOLANA STATE
# ============================================================

def load_solana_state():

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

    except Exception:

        return {}


def save_solana_state(state):

    with open(
        SOLANA_STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2
        )


def clean_old_state(state):

    now = datetime.now(
        timezone.utc
    )

    cleaned = {}

    for address, timestamp in state.items():

        try:

            old = datetime.fromisoformat(
                timestamp
            )

            if (
                now - old
            ).total_seconds() < 86400:

                cleaned[address] = timestamp

        except Exception:
            continue

    return cleaned


# ============================================================
# SOLANA PAIR SEÇİMİ
# ============================================================

def choose_best_pair(
    pairs
):

    candidates = []

    for pair in pairs:

        try:

            liquidity = float(
                (
                    pair.get(
                        "liquidity"
                    ) or {}
                ).get(
                    "usd",
                    0
                ) or 0
            )

            volume24 = float(
                (
                    pair.get(
                        "volume"
                    ) or {}
                ).get(
                    "h24",
                    0
                ) or 0
            )

            if liquidity < 10000:
                continue

            candidates.append(
                (
                    volume24,
                    liquidity,
                    pair
                )
            )

        except Exception:
            continue

    if not candidates:
        return None

    candidates.sort(
        key=lambda x: (
            x[0],
            x[1]
        ),
        reverse=True
    )

    return candidates[0][2]


# ============================================================
# SOLANA ERKEN ANALİZ
# ============================================================

def analyze_solana_token(
    pair,
    is_profile,
    is_takeover,
    is_boost
):

    try:

        price_change = (
            pair.get(
                "priceChange"
            ) or {}
        )

        volume = (
            pair.get(
                "volume"
            ) or {}
        )

        txns = (
            pair.get(
                "txns"
            ) or {}
        )

        liquidity = (
            pair.get(
                "liquidity"
            ) or {}
        )

        change1h = float(
            price_change.get(
                "h1",
                0
            ) or 0
        )

        change6h = float(
            price_change.get(
                "h6",
                0
            ) or 0
        )

        change24h = float(
            price_change.get(
                "h24",
                0
            ) or 0
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

        liquidity_usd = float(
            liquidity.get(
                "usd",
                0
            ) or 0
        )

        tx1h = (
            txns.get(
                "h1"
            ) or {}
        )

        buys = int(
            tx1h.get(
                "buys",
                0
            ) or 0
        )

        sells = int(
            tx1h.get(
                "sells",
                0
            ) or 0
        )

        total_tx = buys + sells

        # ----------------------------------------------------
        # ÇOK YÜKSELMİŞ COINLERİ ELE
        # ----------------------------------------------------

        if change1h >= 25:
            return None

        if change6h >= 40:
            return None

        if change24h >= 100:
            return None

        # Negatif hareketleri erken fırsat olarak alma
        if change1h <= 0:
            return None

        # ----------------------------------------------------
        # HACİM HESABI
        # ----------------------------------------------------

        if volume24h <= 0:
            return None

        average_hourly_volume = (
            volume24h / 24
        )

        if average_hourly_volume <= 0:
            return None

        volume_ratio = (
            volume1h /
            average_hourly_volume
        )

        # Artık hacim kesinlikle şart
        if volume_ratio < 1.8:
            return None

        # ----------------------------------------------------
        # LİKİDİTE
        # ----------------------------------------------------

        if liquidity_usd < 10000:
            return None

        # ----------------------------------------------------
        # ALIM/SATIŞ
        # ----------------------------------------------------

        if total_tx < 40:
            return None

        buyer_ratio = (
            buys /
            max(sells, 1)
        )

        if buyer_ratio < 1.15:
            return None

        score = 0

        reasons = []

        # ----------------------------------------------------
        # FİYAT
        # ----------------------------------------------------

        if 3 <= change1h <= 10:

            score += 3

            reasons.append(
                "Fiyat henüz fazla yükselmedi."
            )

        elif 10 < change1h < 15:

            score += 2

            reasons.append(
                "Fiyat hareketi hızlandı."
            )

        elif 15 <= change1h < 25:

            score += 1

            reasons.append(
                "Hareket güçlü ancak erken aşama azalıyor."
            )

        # ----------------------------------------------------
        # HACİM
        # ----------------------------------------------------

        if volume_ratio >= 5:

            score += 4

            reasons.append(
                f"Hacim normalin yaklaşık "
                f"{volume_ratio:.1f} katına çıktı."
            )

        elif volume_ratio >= 3:

            score += 3

            reasons.append(
                f"Hacim yaklaşık "
                f"{volume_ratio:.1f} katına çıktı."
            )

        elif volume_ratio >= 1.8:

            score += 2

            reasons.append(
                "Hacim belirgin şekilde artıyor."
            )

        # ----------------------------------------------------
        # ALICILAR
        # ----------------------------------------------------

        if buyer_ratio >= 2:

            score += 3

            reasons.append(
                "Alıcı işlemleri satıcılardan belirgin fazla."
            )

        elif buyer_ratio >= 1.5:

            score += 2

            reasons.append(
                "Alıcı tarafı güçlü."
            )

        else:

            score += 1

            reasons.append(
                "Alıcı tarafı biraz daha güçlü."
            )

        # ----------------------------------------------------
        # İŞLEM SAYISI
        # ----------------------------------------------------

        if total_tx >= 500:

            score += 2

            reasons.append(
                "İşlem sayısı ciddi şekilde hareketlenmiş."
            )

        elif total_tx >= 100:

            score += 1

            reasons.append(
                "İşlem sayısı hareketlenmiş."
            )

        # ----------------------------------------------------
        # LİKİDİTE
        # ----------------------------------------------------

        if liquidity_usd >= 50000:

            score += 2

            reasons.append(
                "Likidite güçlü."
            )

        else:

            score += 1

            reasons.append(
                "Likidite yeterli seviyede."
            )

        # ----------------------------------------------------
        # SOSYAL / TOPLULUK
        # ----------------------------------------------------

        if is_profile:

            score += 1

            reasons.append(
                "Token hakkında yeni sosyal hareketlilik var."
            )

        if is_takeover:

            score += 2

            reasons.append(
                "Topluluk tarafında yeni hareketlilik var."
            )

        # Boost sadece EK sinyal
        if is_boost:

            score += 1

        # ----------------------------------------------------
        # FİNAL EŞİK
        # ----------------------------------------------------

        # En az 9 puan
        if score < 9:
            return None

        symbol = (
            pair.get(
                "baseToken",
                {}
            ).get(
                "symbol",
                "UNKNOWN"
            )
        )

        return {
            "address": (
                pair.get(
                    "baseToken",
                    {}
                ).get(
                    "address",
                    ""
                )
            ),
            "symbol": symbol,
            "change1h": change1h,
            "change6h": change6h,
            "change24h": change24h,
            "volume_ratio": volume_ratio,
            "buys": buys,
            "sells": sells,
            "buyer_ratio": buyer_ratio,
            "total_tx": total_tx,
            "liquidity": liquidity_usd,
            "score": score,
            "reasons": reasons[:6],
            "url": pair.get(
                "url",
                ""
            )
        }

    except Exception:
        return None


# ============================================================
# SOLANA TARAMA
# ============================================================

def scan_solana():

    profiles = (
        get_solana_profiles()
    )

    takeovers = (
        get_solana_takeovers()
    )

    boosts = (
        get_solana_boosts()
    )

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

    # API yükünü sınırlıyoruz
    addresses = addresses[:25]

    opportunities = []

    for address in addresses:

        pairs = get_solana_pairs(
            address
        )

        pair = choose_best_pair(
            pairs
        )

        if not pair:
            continue

        result = analyze_solana_token(
            pair,
            address in profile_addresses,
            address in takeover_addresses,
            address in boost_addresses
        )

        if result:

            opportunities.append(
                result
            )

        time.sleep(0.15)

    opportunities.sort(
        key=lambda x: (
            x["score"],
            x["volume_ratio"],
            x["liquidity"]
        ),
        reverse=True
    )

    return opportunities[:3]


# ============================================================
# SOLANA MESAJ
# ============================================================

def format_solana_alert(
    item
):

    message = (
        "🚨 ERKEN UYARI — SOLANA\n\n"
        f"🪙 {item['symbol']}\n"
        f"📈 Son hareket: "
        f"{item['change1h']:.1f}%\n"
        f"🔥 Hacim: "
        f"{item['volume_ratio']:.1f}x\n"
        f"👥 Alıcılar: "
        f"{item['buys']}\n"
        f"💧 Likidite: "
        f"${item['liquidity']:,.0f}\n\n"
        "💡 Neden dikkat çekti?\n"
    )

    for reason in item["reasons"]:

        message += (
            f"• {reason}\n"
        )

    if item["change1h"] <= 10:

        stage = "🟢 ERKEN HAREKET"

    else:

        stage = "🟡 ERKEN AŞAMA"

    message += (
        f"\n{stage}\n"
        "⚠️ Meme coin — çok yüksek risk\n"
        "📍 Solana\n"
        "🔎 Phantom'dan kontrol et.\n"
    )

    if item["url"]:

        message += (
            "\n🔗 DEX Screener:\n"
            f"{item['url']}"
        )

    return message


# ============================================================
# SOLANA TEKRAR KONTROLÜ
# ============================================================

def should_send_solana(
    item,
    state
):

    address = item.get(
        "address",
        ""
    )

    if not address:
        return True

    if address not in state:
        return True

    try:

        old_time = datetime.fromisoformat(
            state[address]
        )

        now = datetime.now(
            timezone.utc
        )

        hours = (
            now - old_time
        ).total_seconds() / 3600

        # 24 saat dolmadan aynı coin tekrar gelmesin
        if hours < 24:

            return False

    except Exception:
        pass

    return True


# ============================================================
# GITHUB STATE KAYDET
# ============================================================

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

        result = subprocess.run(
            [
                "git",
                "diff",
                "--cached",
                "--quiet"
            ],
            check=False
        )

        if result.returncode == 0:
            return

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

        print(
            "State commit hatası:",
            e
        )


# ============================================================
# ANA
# ============================================================

def main():

    print(
        "Crypto Alert Bot başlıyor..."
    )

    # --------------------------------------------------------
    # Haber
    # --------------------------------------------------------

    news = get_news()

    # --------------------------------------------------------
    # BTC
    # --------------------------------------------------------

    btc = get_btc_analysis()

    print(
        "BTC:",
        btc["trend"],
        "RSI:",
        round(
            btc["rsi"],
            1
        )
    )

    # --------------------------------------------------------
    # Binance
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

    symbols = {
        x["symbol"]
        for x in selected
    }

    # XVG ve QNT zorunlu takip
    for special in SPECIAL_COINS:

        if special not in symbols:

            extra = next(
                (
                    x
                    for x in tickers
                    if x["symbol"] == special
                ),
                None
            )

            if extra:
                selected.append(
                    extra
                )

    opportunities = []

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

        # Çok sert hareketleri ele
        if abs(
            tech["change6"]
        ) > 25:

            continue

        # Aşırı RSI
        if (
            tech["rsi"] > 78 or
            tech["rsi"] < 22
        ):

            continue

        news_items = news_for_coin(
            symbol,
            news
        )

        preliminary = calculate_signal(
            tech,
            0,
            0,
            news_items
        )

        # Zayıf adaylarda Futures sorgulama
        if preliminary["score"] < 4:
            continue

        funding = get_funding(
            symbol
        )

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

        telegram_send(
            format_binance_alert(
                opportunity["symbol"],
                opportunity["signal"],
                opportunity["plan"],
                opportunity["news"]
            )
        )

        sent += 1

    # --------------------------------------------------------
    # SOLANA
    # --------------------------------------------------------

    state = load_solana_state()

    state = clean_old_state(
        state
    )

    try:

        solana = scan_solana()

        for item in solana:

            if not should_send_solana(
                item,
                state
            ):

                print(
                    "Tekrar engellendi:",
                    item["symbol"]
                )

                continue

            telegram_send(
                format_solana_alert(
                    item
                )
            )

            address = item.get(
                "address",
                ""
            )

            if address:

                state[address] = (
                    datetime.now(
                        timezone.utc
                    ).isoformat()
                )

    except Exception as e:

        print(
            "Solana radar hatası:",
            e
        )

    # State'i kaydet
    save_solana_state(
        state
    )

    commit_state()

    # --------------------------------------------------------
    # ÖZET
    # --------------------------------------------------------

    summary = (
        "🟢 PİYASA TARAMASI TAMAMLANDI\n\n"
        f"💵 Sermaye: ${TOTAL_CAPITAL:.2f}\n"
        f"🔎 Binance: {len(selected)} coin\n"
        "⭐ Özel takip: XVG / QNT\n"
        "🚀 Solana erken radar: AKTİF\n"
        "📰 Haber taraması: AKTİF\n\n"
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

    telegram_send(
        summary
    )

    print(
        "Tarama tamamlandı."
    )


if __name__ == "__main__":
    main()
