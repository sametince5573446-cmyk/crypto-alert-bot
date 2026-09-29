import os
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# =========================================================
# AYARLAR
# =========================================================

TOTAL_CAPITAL = 100.0

MIN_BUDGET = 10.0
MAX_BUDGET = 40.0

MAX_RISK_DOLLARS = 2.50
MAX_ALERTS = 3

NEWS_HOURS = 12

SPOT_URL = "https://data-api.binance.vision"
FUTURES_URL = "https://fapi.binance.com"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:
        requests.post(url, data=data, timeout=20)
    except Exception as e:
        print("Telegram hatası:", e)


# =========================================================
# BINANCE
# =========================================================

def get_json(url, params=None):

    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("API hatası:", url, e)
        return None


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

        if any(symbol.endswith(x) for x in [
            "USDCUSDT",
            "FDUSDUSDT",
            "TUSDUSDT",
            "USDPUSDT",
            "BUSDUSDT"
        ]):
            continue

        try:
            volume = float(x.get("quoteVolume", 0))
            price = float(x.get("lastPrice", 0))
            change = float(x.get("priceChangePercent", 0))

            if volume <= 0 or price <= 0:
                continue

            coins.append({
                "symbol": symbol,
                "price": price,
                "change24h": change,
                "volume": volume
            })

        except:
            continue

    coins.sort(
        key=lambda x: x["volume"],
        reverse=True
    )

    return coins


# =========================================================
# KLINE
# =========================================================

def get_klines(symbol, interval="1h", limit=100):

    data = get_json(
        f"{SPOT_URL}/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )

    if not data:
        return []

    result = []

    for x in data:

        try:
            result.append({
                "open": float(x[1]),
                "high": float(x[2]),
                "low": float(x[3]),
                "close": float(x[4]),
                "volume": float(x[5])
            })
        except:
            pass

    return result


# =========================================================
# FUTURES VERİLERİ
# =========================================================

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
        return float(data[0]["fundingRate"]) * 100
    except:
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
    except:
        return 0


def get_oi_change(symbol):

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
        old = float(data[-2]["sumOpenInterest"])
        new = float(data[-1]["sumOpenInterest"])

        if old == 0:
            return 0

        return ((new - old) / old) * 100

    except:
        return 0


def get_long_short_ratio():

    data = get_json(
        f"{FUTURES_URL}/futures/data/globalLongShortAccountRatio",
        {
            "symbol": "BTCUSDT",
            "period": "1h",
            "limit": 1
        }
    )

    if not data:
        return 1.0

    try:
        return float(data[0]["longShortRatio"])
    except:
        return 1.0


# =========================================================
# EMA
# =========================================================

def ema(values, period):

    if len(values) < period:
        return values[-1] if values else 0

    multiplier = 2 / (period + 1)

    ema_value = sum(values[:period]) / period

    for price in values[period:]:
        ema_value = (
            (price - ema_value) * multiplier
        ) + ema_value

    return ema_value


# =========================================================
# RSI
# =========================================================

def calculate_rsi(closes, period=14):

    if len(closes) <= period:
        return 50

    gains = []
    losses = []

    for i in range(1, len(closes)):

        diff = closes[i] - closes[i - 1]

        if diff >= 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):

        avg_gain = (
            (avg_gain * (period - 1)) + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1)) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


# =========================================================
# BTC ANALİZİ
# =========================================================

def analyze_btc():

    candles = get_klines(
        "BTCUSDT",
        "1h",
        100
    )

    if not candles:
        return {
            "trend": "NÖTR",
            "rsi": 50,
            "change6h": 0
        }

    closes = [x["close"] for x in candles]

    e9 = ema(closes, 9)
    e21 = ema(closes, 21)

    rsi = calculate_rsi(closes)

    current = closes[-1]

    if e9 > e21 and current > e9:
        trend = "YUKARI"

    elif e9 < e21 and current < e9:
        trend = "AŞAĞI"

    else:
        trend = "NÖTR"

    if len(closes) >= 7:

        old = closes[-7]

        if old != 0:
            change6h = (
                (current - old) / old
            ) * 100
        else:
            change6h = 0

    else:
        change6h = 0

    return {
        "trend": trend,
        "rsi": rsi,
        "change6h": change6h
    }


# =========================================================
# HABERLER
# =========================================================

NEWS_SOURCES = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss"
]


POSITIVE_WORDS = [
    "etf",
    "approved",
    "approval",
    "partnership",
    "partner",
    "adoption",
    "launch",
    "launched",
    "integration",
    "integrated",
    "listing",
    "listed",
    "investment",
    "fund",
    "funding",
    "upgrade",
    "growth",
    "bullish",
    "surge",
    "rally",
    "record",
    "institutional"
]


NEGATIVE_WORDS = [
    "hack",
    "hacked",
    "exploit",
    "exploited",
    "attack",
    "lawsuit",
    "fraud",
    "scam",
    "delist",
    "delisted",
    "unlock",
    "liquidation",
    "liquidated",
    "investigation",
    "ban",
    "banned",
    "stolen",
    "breach",
    "bankrupt",
    "bearish",
    "dump",
    "collapse"
]


def get_news():

    all_news = []

    cutoff = datetime.now(
        timezone.utc
    ) - timedelta(hours=NEWS_HOURS)

    for source in NEWS_SOURCES:

        try:

            response = requests.get(
                source,
                timeout=20
            )

            root = ET.fromstring(
                response.content
            )

            for item in root.findall(".//item"):

                title_element = item.find("title")

                if title_element is None:
                    continue

                title = title_element.text or ""

                pub_date = item.find("pubDate")

                date = None

                if pub_date is not None and pub_date.text:

                    try:
                        date = datetime.strptime(
                            pub_date.text,
                            "%a, %d %b %Y %H:%M:%S %z"
                        ).astimezone(timezone.utc)

                    except:
                        date = None

                if date is None or date >= cutoff:

                    all_news.append({
                        "title": title.strip(),
                        "date": date
                    })

        except Exception as e:

            print(
                "Haber kaynağı hatası:",
                source,
                e
            )

    return all_news


# =========================================================
# HABER ANALİZİ
# =========================================================

def analyze_news(symbol, news):

    coin = symbol.replace(
        "USDT",
        ""
    ).lower()

    relevant = []

    for item in news:

        title = item["title"]

        text_lower = title.lower()

        # Coin adı haber başlığında geçiyor mu?
        if coin in text_lower:

            relevant.append(item)

    if not relevant:

        return {
            "sentiment": "NÖTR",
            "headline": "",
            "reason": []
        }

    positive_count = 0
    negative_count = 0

    selected = []

    for item in relevant[:5]:

        title_lower = item["title"].lower()

        pos = sum(
            1 for word in POSITIVE_WORDS
            if word in title_lower
        )

        neg = sum(
            1 for word in NEGATIVE_WORDS
            if word in title_lower
        )

        positive_count += pos
        negative_count += neg

        selected.append(item)

    # Haber yorumu
    if negative_count > positive_count:

        sentiment = "OLUMSUZ"

        reason = []

        combined_text = " ".join(
            x["title"].lower()
            for x in selected
        )

        if any(
            x in combined_text
            for x in [
                "hack",
                "exploit",
                "attack",
                "breach",
                "stolen"
            ]
        ):
            reason.append(
                "Güvenle ilgili kötü bir gelişme var."
            )

        if any(
            x in combined_text
            for x in [
                "unlock",
                "delist",
                "liquidation",
                "dump"
            ]
        ):
            reason.append(
                "Satış baskısı oluşabilir."
            )

        if any(
            x in combined_text
            for x in [
                "lawsuit",
                "fraud",
                "scam",
                "ban"
            ]
        ):
            reason.append(
                "Coin için olumsuz bir gelişme var."
            )

        if not reason:

            reason.append(
                "Haber kısa vadede fiyatı baskılayabilir."
            )

    elif positive_count > negative_count:

        sentiment = "OLUMLU"

        reason = []

        combined_text = " ".join(
            x["title"].lower()
            for x in selected
        )

        if any(
            x in combined_text
            for x in [
                "etf",
                "approved",
                "approval"
            ]
        ):
            reason.append(
                "Coin için yatırım ilgisi artabilir."
            )

        if any(
            x in combined_text
            for x in [
                "partnership",
                "partner",
                "integration"
            ]
        ):
            reason.append(
                "Coinin kullanım alanı genişleyebilir."
            )

        if any(
            x in combined_text
            for x in [
                "listing",
                "listed"
            ]
        ):
            reason.append(
                "Daha fazla yatırımcı coin'e ulaşabilir."
            )

        if any(
            x in combined_text
            for x in [
                "investment",
                "fund",
                "institutional"
            ]
        ):
            reason.append(
                "Yatırım ilgisi artabilir."
            )

        if any(
            x in combined_text
            for x in [
                "upgrade",
                "launch",
                "growth",
                "adoption"
            ]
        ):
            reason.append(
                "Proje açısından olumlu bir gelişme var."
            )

        if not reason:

            reason.append(
                "Haber coin'e olan ilgiyi artırabilir."
            )

    else:

        sentiment = "NÖTR"

        reason = [
            "Haber var ancak fiyatı ciddi şekilde etkileyecek kadar güçlü görünmüyor."
        ]

    return {
        "sentiment": sentiment,
        "headline": selected[0]["title"],
        "reason": reason[:3]
    }


# =========================================================
# FIRSAT GÜCÜ
# =========================================================

def opportunity_label(score):

    if score >= 7:
        return "🚀 ÇOK GÜÇLÜ"

    elif score >= 6:
        return "🟢 GÜÇLÜ"

    elif score >= 5:
        return "🟡 ORTA GÜÇLÜ"

    return "⚪ ZAYIF"


# =========================================================
# BÜTÇE + KALDIRAÇ
# =========================================================

def choose_budget_and_leverage(
    score,
    news_sentiment,
    risk_percent
):

    if score >= 7:

        desired_budget = 40.0

    elif score >= 6:

        desired_budget = 30.0

    elif score >= 5:

        desired_budget = 20.0

    else:

        desired_budget = 10.0

    # Kötü haber varsa bütçeyi düşür
    if news_sentiment == "OLUMSUZ":

        desired_budget = min(
            desired_budget,
            10.0
        )

    # Hafif risk varsa orta bütçe
    elif news_sentiment == "HAFİF OLUMSUZ":

        desired_budget = min(
            desired_budget,
            20.0
        )

    # Kaldıraç
    if score >= 7 and risk_percent <= 0.80:

        leverage = 10

    elif score >= 6 and risk_percent <= 1.00:

        leverage = 8

    elif score >= 5 and risk_percent <= 1.30:

        leverage = 6

    elif risk_percent <= 1.80:

        leverage = 5

    else:

        leverage = 3

    # Maksimum zarar hesabı
    max_budget_by_risk = (
        MAX_RISK_DOLLARS /
        (leverage * risk_percent / 100)
    )

    actual_budget = min(
        desired_budget,
        max_budget_by_risk,
        MAX_BUDGET
    )

    if actual_budget < MIN_BUDGET:
        return None

    return {
        "budget": actual_budget,
        "leverage": leverage
    }


# =========================================================
# İŞLEM PLANI
# =========================================================

def create_trade_plan(
    symbol,
    price,
    signal,
    support,
    resistance,
    volatility,
    score,
    news_sentiment
):

    if signal == "LONG":

        stop = support * 0.995

        if stop >= price:

            stop = price * (
                1 - max(
                    volatility * 1.5,
                    0.01
                )
            )

        entry_low = price * 0.997
        entry_high = price * 1.003

        risk_distance = (
            price - stop
        )

        if risk_distance <= 0:
            return None

        tp1 = price + (
            risk_distance * 1.5
        )

        tp2 = price + (
            risk_distance * 2.5
        )

        direction_text = "LONG"

    else:

        stop = resistance * 1.005

        if stop <= price:

            stop = price * (
                1 + max(
                    volatility * 1.5,
                    0.01
                )
            )

        entry_low = price * 0.997
        entry_high = price * 1.003

        risk_distance = (
            stop - price
        )

        if risk_distance <= 0:
            return None

        tp1 = price - (
            risk_distance * 1.5
        )

        tp2 = price - (
            risk_distance * 2.5
        )

        direction_text = "SHORT"

    risk_percent = (
        risk_distance / price
    ) * 100

    if risk_percent <= 0:
        return None

    rr = (
        abs(tp1 - price) /
        risk_distance
    )

    if rr < 1.3:
        return None

    money = choose_budget_and_leverage(
        score,
        news_sentiment,
        risk_percent
    )

    if not money:
        return None

    budget = money["budget"]
    leverage = money["leverage"]

    notional = (
        budget * leverage
    )

    estimated_loss = (
        notional *
        risk_percent /
        100
    )

    tp1_profit = (
        notional *
        (abs(tp1 - price) / price)
    )

    tp2_profit = (
        notional *
        (abs(tp2 - price) / price)
    )

    return {
        "symbol": symbol,
        "signal": direction_text,
        "score": score,
        "budget": budget,
        "leverage": leverage,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "loss": estimated_loss,
        "tp1_profit": tp1_profit,
        "tp2_profit": tp2_profit,
        "rr": rr
    }


# =========================================================
# COIN ANALİZİ
# =========================================================

def analyze_coin(
    coin,
    btc,
    news
):

    symbol = coin["symbol"]

    candles = get_klines(
        symbol,
        "1h",
        100
    )

    if len(candles) < 30:
        return None

    closes = [
        x["close"]
        for x in candles
    ]

    highs = [
        x["high"]
        for x in candles
    ]

    lows = [
        x["low"]
        for x in candles
    ]

    volumes = [
        x["volume"]
        for x in candles
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

    # Son 20 mum destek/direnç
    support = min(
        lows[-20:]
    )

    resistance = max(
        highs[-20:]
    )

    # Volatilite
    returns = []

    for i in range(1, len(closes)):

        if closes[i - 1] != 0:

            returns.append(
                abs(
                    (closes[i] - closes[i - 1])
                    / closes[i - 1]
                )
            )

    if returns:

        volatility = sum(
            returns[-20:]
        ) / len(
            returns[-20:]
        )

    else:

        volatility = 0.01

    # Hacim
    avg_volume = sum(
        volumes[-20:]
    ) / 20

    current_volume = volumes[-1]

    volume_ratio = (
        current_volume /
        avg_volume
        if avg_volume > 0
        else 1
    )

    # Futures
    funding = get_funding(
        symbol
    )

    oi = get_open_interest(
        symbol
    )

    oi_change = get_oi_change(
        symbol
    )

    ls_ratio = get_long_short_ratio()

    # Haber
    news_info = analyze_news(
        symbol,
        news
    )

    sentiment = news_info["sentiment"]

    # =====================================================
    # PUANLAMA
    # =====================================================

    long_score = 0
    short_score = 0

    reasons_long = []
    reasons_short = []

    # Trend
    if ema9 > ema21:

        long_score += 2
        reasons_long.append(
            "Trend yukarı"
        )

    elif ema9 < ema21:

        short_score += 2
        reasons_short.append(
            "Trend aşağı"
        )

    # Fiyat
    if price > ema9:

        long_score += 1
        reasons_long.append(
            "Fiyat yukarı yönde"
        )

    elif price < ema9:

        short_score += 1
        reasons_short.append(
            "Fiyat aşağı yönde"
        )

    # RSI
    if 45 <= rsi <= 68:

        long_score += 1
        reasons_long.append(
            "RSI uygun"
        )

    elif 32 <= rsi <= 55:

        short_score += 1
        reasons_short.append(
            "RSI düşüş için uygun"
        )

    # Hacim
    if volume_ratio >= 1.20:

        if price > ema9:

            long_score += 1
            reasons_long.append(
                "Hareketi destekleyen hacim var"
            )

        elif price < ema9:

            short_score += 1
            reasons_short.append(
                "Düşüşü destekleyen hacim var"
            )

    # Funding
    if funding < -0.01:

        long_score += 1

    elif funding > 0.03:

        short_score += 1

    # OI
    if oi_change > 2:

        if price > ema9:

            long_score += 1

        elif price < ema9:

            short_score += 1

    # Long/Short oranı
    if ls_ratio < 0.85:

        long_score += 1

    elif ls_ratio > 1.20:

        short_score += 1

    # BTC filtresi
    if btc["trend"] == "YUKARI":

        long_score += 1

    elif btc["trend"] == "AŞAĞI":

        short_score += 1

    # Haber
    if sentiment == "OLUMLU":

        long_score += 2

        reasons_long.append(
            "Haber akışı olumlu"
        )

    elif sentiment == "HAFİF OLUMLU":

        long_score += 1

        reasons_long.append(
            "Haber akışı olumlu"
        )

    elif sentiment == "OLUMSUZ":

        long_score -= 2

        short_score += 1

        reasons_short.append(
            "Haber akışı olumsuz"
        )

    # =====================================================
    # SİNYAL
    # =====================================================

    if long_score >= 5 and long_score > short_score:

        signal = "LONG"
        score = long_score
        reasons = reasons_long

    elif short_score >= 5 and short_score > long_score:

        signal = "SHORT"
        score = short_score
        reasons = reasons_short

    else:

        return None

    # Çok kötü haber varsa LONG engelle
    if (
        signal == "LONG"
        and sentiment == "OLUMSUZ"
    ):

        return None

    # SHORT için kötü haber destekliyor
    if (
        signal == "SHORT"
        and sentiment == "OLUMSUZ"
        and score < 6
    ):

        return None

    trade = create_trade_plan(
        symbol,
        price,
        signal,
        support,
        resistance,
        volatility,
        score,
        sentiment
    )

    if not trade:
        return None

    trade["rsi"] = rsi
    trade["news"] = news_info
    trade["reasons"] = reasons[:4]
    trade["price"] = price

    return trade


# =========================================================
# MESAJ OLUŞTURMA
# =========================================================

def format_price(value):

    if value >= 100:
        return f"{value:.2f}"

    elif value >= 1:
        return f"{value:.5f}"

    else:
        return f"{value:.8f}"


def format_trade(trade):

    strength = opportunity_label(
        trade["score"]
    )

    signal_emoji = (
        "🟢"
        if trade["signal"] == "LONG"
        else "🔴"
    )

    news = trade["news"]

    if news["sentiment"] == "OLUMSUZ":

        news_emoji = "🔴"

    elif news["sentiment"] == "OLUMLU":

        news_emoji = "🟢"

    else:

        news_emoji = "⚪"

    message = ""

    message += "🚨 KRİPTO FIRSATLARI 🚨\n\n"

    message += f"💵 Sermaye: ${TOTAL_CAPITAL:.2f}\n\n"

    message += (
        f"{signal_emoji} İŞLEM: "
        f"{trade['signal']} — {strength}\n"
    )

    message += (
        f"🪙 Coin: {trade['symbol']}\n"
    )

    message += (
        f"💰 Bütçe: ${trade['budget']:.2f}\n"
    )

    message += (
        f"⚡ Kaldıraç: "
        f"{trade['leverage']}x\n\n"
    )

    message += "📥 GİRİŞ\n"

    message += (
        f"{format_price(trade['entry_low'])} - "
        f"{format_price(trade['entry_high'])}\n\n"
    )

    message += "🛑 STOP LOSS\n"

    message += (
        f"{format_price(trade['stop'])}\n\n"
    )

    message += "🎯 TP1\n"

    message += (
        f"{format_price(trade['tp1'])}\n\n"
    )

    message += "🎯 TP2\n"

    message += (
        f"{format_price(trade['tp2'])}\n\n"
    )

    message += (
        f"💵 Stop olursa: "
        f"~${trade['loss']:.2f}\n"
    )

    message += (
        f"📈 TP1 kârı: "
        f"~${trade['tp1_profit']:.2f}\n"
    )

    message += (
        f"📈 TP2 kârı: "
        f"~${trade['tp2_profit']:.2f}\n\n"
    )

    # =====================================================
    # HABER
    # =====================================================

    message += "📰 HABER\n"

    message += (
        f"{news_emoji} "
        f"{news['sentiment']}\n"
    )

    if news["headline"]:

        message += (
            f"• {news['headline']}\n\n"
        )

        message += "💡 Neden "

        if news["sentiment"] == "OLUMLU":
            message += "olumlu?\n"

        elif news["sentiment"] == "OLUMSUZ":
            message += "olumsuz?\n"

        else:
            message += "nötr?\n"

        for reason in news["reason"]:

            message += (
                f"• {reason}\n"
            )

    else:

        message += (
            "• Önemli bir haber bulunamadı.\n"
        )

    message += "\n"

    # =====================================================
    # NEDEN
    # =====================================================

    message += "📌 NEDEN?\n"

    for reason in trade["reasons"][:4]:

        message += (
            f"• {reason}\n"
        )

    message += "\n"

    message += (
        f"📊 Risk/Getiri: "
        f"1:{trade['rr']:.2f}\n\n"
    )

    message += (
        "⚠️ Manuel işlem.\n"
        "Otomatik emir açılmaz."
    )

    return message


# =========================================================
# ANA SİSTEM
# =========================================================

def main():

    print(
        "Bot başladı..."
    )

    tickers = get_spot_tickers()

    if not tickers:

        send_telegram(
            "❌ Binance verisi alınamadı."
        )

        return

    btc = analyze_btc()

    print(
        "BTC:",
        btc
    )

    news = get_news()

    print(
        f"{len(news)} haber bulundu."
    )

    # En yüksek hacimli 40 coin
    coins = tickers[:40]

    opportunities = []

    for coin in coins:

        try:

            result = analyze_coin(
                coin,
                btc,
                news
            )

            if result:

                opportunities.append(
                    result
                )

        except Exception as e:

            print(
                coin["symbol"],
                "analiz hatası:",
                e
            )

        time.sleep(0.10)

    # En güçlü fırsatlar
    opportunities.sort(
        key=lambda x: (
            x["score"],
            x["rr"]
        ),
        reverse=True
    )

    if not opportunities:

        message = ""

        message += (
            "🟢 PİYASA TARAMASI TAMAMLANDI\n\n"
        )

        message += (
            f"💵 Sermaye: "
            f"${TOTAL_CAPITAL:.2f}\n"
        )

        message += (
            "🌐 BTC DURUMU\n"
        )

        message += (
            f"Trend: {btc['trend']}\n"
        )

        message += (
            f"RSI: {btc['rsi']:.1f}\n"
        )

        message += (
            f"6s: {btc['change6h']:+.2f}%\n\n"
        )

        message += (
            f"🔎 {len(coins)} coin tarandı.\n"
        )

        message += (
            "⏸️ WAIT — Uygun işlem fırsatı bulunamadı.\n\n"
        )

        message += (
            "⚠️ Otomatik emir açılmaz.\n"
            "Manuel değerlendirme içindir."
        )

        send_telegram(
            message
        )

        return

    # Fırsatları gönder
    selected = opportunities[
        :MAX_ALERTS
    ]

    header = ""

    header += (
        "🚨 KRİPTO FIRSATLARI 🚨\n\n"
    )

    header += (
        f"💵 Sermaye: "
        f"${TOTAL_CAPITAL:.2f}\n\n"
    )

    header += (
        "🌐 BTC\n"
    )

    header += (
        f"Trend: {btc['trend']}\n"
    )

    header += (
        f"RSI: {btc['rsi']:.1f}\n"
    )

    header += (
        f"6s: {btc['change6h']:+.2f}%\n\n"
    )

    header += (
        f"🔎 {len(coins)} coin tarandı.\n"
    )

    header += (
        f"🔥 {len(selected)} fırsat bulundu.\n\n"
    )

    send_telegram(
        header
    )

    for trade in selected:

        send_telegram(
            format_trade(trade)
        )

        time.sleep(1)


if __name__ == "__main__":

    main()
