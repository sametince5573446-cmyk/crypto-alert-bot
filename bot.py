import os
import requests
import statistics
import xml.etree.ElementTree as ET
import re
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta


# =========================================================
# AYARLAR
# =========================================================

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

SPOT_URL = "https://data-api.binance.vision"
FUTURES_URL = "https://fapi.binance.com"

session = requests.Session()

TOTAL_CAPITAL = 100.0

# Fırsata göre bot bunu 10-40$ arasında belirleyecek
MIN_BUDGET = 10.0
MAX_BUDGET = 40.0

# Tek işlemde yaklaşık maksimum zarar
MAX_RISK_DOLLARS = 2.50

MAX_ALERTS = 3

# Haberler son kaç saat dikkate alınacak
NEWS_HOURS = 12


# =========================================================
# GENEL İSTEK
# =========================================================

def get_json(url, params=None):

    try:

        r = session.get(
            url,
            params=params,
            timeout=20
        )

        r.raise_for_status()

        return r.json()

    except Exception as e:

        print(f"İstek hatası: {url} -> {e}")

        return None


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):

    try:

        response = session.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=20
        )

        response.raise_for_status()

        print("Telegram mesajı başarıyla gönderildi.")

    except Exception as e:

        print(
            "Telegram gönderim hatası:",
            e
        )


# =========================================================
# SPOT VERİLERİ
# =========================================================

def get_24h_tickers():

    return get_json(
        f"{SPOT_URL}/api/v3/ticker/24hr"
    )


def get_spot_klines(symbol):

    return get_json(
        f"{SPOT_URL}/api/v3/klines",
        {
            "symbol": symbol,
            "interval": "1h",
            "limit": 100
        }
    )


# =========================================================
# FUTURES - FUNDING
# =========================================================

def get_funding(symbol):

    try:

        data = get_json(
            f"{FUTURES_URL}/fapi/v1/fundingRate",
            {
                "symbol": symbol,
                "limit": 1
            }
        )

        if not data:

            return None

        return float(
            data[-1]["fundingRate"]
        )

    except Exception as e:

        print(
            f"{symbol} Funding alınamadı: {e}"
        )

        return None


# =========================================================
# FUTURES - OPEN INTEREST
# =========================================================

def get_open_interest(symbol):

    try:

        data = get_json(
            f"{FUTURES_URL}/fapi/v1/openInterest",
            {
                "symbol": symbol
            }
        )

        if not data:

            return None

        return float(
            data["openInterest"]
        )

    except Exception as e:

        print(
            f"{symbol} Open Interest alınamadı: {e}"
        )

        return None


# =========================================================
# OPEN INTEREST DEĞİŞİMİ
# =========================================================

def get_open_interest_history(symbol):

    try:

        data = get_json(
            f"{FUTURES_URL}/futures/data/openInterestHist",
            {
                "symbol": symbol,
                "period": "1h",
                "limit": 3
            }
        )

        if not data or len(data) < 2:

            return None

        previous = float(
            data[-2]["sumOpenInterest"]
        )

        current = float(
            data[-1]["sumOpenInterest"]
        )

        if previous == 0:

            return None

        return (
            (current - previous)
            / previous
        ) * 100

    except Exception as e:

        print(
            f"{symbol} OI geçmişi alınamadı: {e}"
        )

        return None


# =========================================================
# LONG / SHORT ORANI
# =========================================================

def get_long_short_ratio(symbol):

    try:

        data = get_json(
            f"{FUTURES_URL}/futures/data/globalLongShortAccountRatio",
            {
                "symbol": symbol,
                "period": "1h",
                "limit": 1
            }
        )

        if not data:

            return None

        return float(
            data[-1]["longShortRatio"]
        )

    except Exception as e:

        print(
            f"{symbol} Long/Short alınamadı: {e}"
        )

        return None


# =========================================================
# EMA
# =========================================================

def calculate_ema(values, period):

    if len(values) < period:

        return None

    ema = statistics.mean(
        values[:period]
    )

    multiplier = 2 / (period + 1)

    for price in values[period:]:

        ema = (
            (price - ema)
            * multiplier
        ) + ema

    return ema


# =========================================================
# RSI
# =========================================================

def calculate_rsi(values, period=14):

    if len(values) < period + 1:

        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = (
            values[i]
            - values[i - 1]
        )

        if change > 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(
                abs(change)
            )

    avg_gain = statistics.mean(
        gains[:period]
    )

    avg_loss = statistics.mean(
        losses[:period]
    )

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            avg_gain * (period - 1)
            + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1)
            + losses[i]
        ) / period

    if avg_loss == 0:

        return 100

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


# =========================================================
# HABER SİSTEMİ
# =========================================================

NEWS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss"
]


POSITIVE_WORDS = [
    "approval",
    "approved",
    "partnership",
    "partner",
    "integration",
    "launch",
    "launched",
    "listing",
    "listed",
    "adoption",
    "upgrade",
    "bullish",
    "surge",
    "rally",
    "growth",
    "record",
    "investment",
    "funding",
    "etf",
    "inflows",
    "buy",
    "bought",
    "expands",
    "expansion"
]


NEGATIVE_WORDS = [
    "hack",
    "hacked",
    "exploit",
    "exploited",
    "attack",
    "stolen",
    "scam",
    "fraud",
    "lawsuit",
    "ban",
    "banned",
    "delist",
    "delisted",
    "liquidation",
    "liquidations",
    "bankrupt",
    "bankruptcy",
    "vulnerability",
    "breach",
    "rug",
    "rug pull",
    "unlock",
    "selloff",
    "sell-off",
    "outflow",
    "investigation",
    "warning"
]


def clean_text(text):

    if not text:

        return ""

    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    return " ".join(
        text.split()
    )


def get_news():

    all_news = []

    now = datetime.now(
        timezone.utc
    )

    cutoff = (
        now
        - timedelta(hours=NEWS_HOURS)
    )

    for feed_url in NEWS_FEEDS:

        try:

            response = session.get(
                feed_url,
                timeout=20,
                headers={
                    "User-Agent":
                    "Mozilla/5.0 CryptoAlertBot"
                }
            )

            response.raise_for_status()

            root = ET.fromstring(
                response.content
            )

            items = root.findall(
                ".//item"
            )

            for item in items:

                title_element = item.find(
                    "title"
                )

                date_element = item.find(
                    "pubDate"
                )

                link_element = item.find(
                    "link"
                )

                if title_element is None:

                    continue

                title = clean_text(
                    title_element.text
                    or ""
                )

                date_text = ""

                if date_element is not None:

                    date_text = (
                        date_element.text
                        or ""
                    )

                published = None

                try:

                    if date_text:

                        published = (
                            parsedate_to_datetime(
                                date_text
                            )
                        )

                except Exception:

                    published = None

                if published is not None:

                    if published < cutoff:

                        continue

                link = ""

                if link_element is not None:

                    link = (
                        link_element.text
                        or ""
                    )

                all_news.append(
                    {
                        "title": title,
                        "link": link
                    }
                )

        except Exception as e:

            print(
                f"Haber kaynağı alınamadı: {e}"
            )

    return all_news


# =========================================================
# COIN HABER ANALİZİ
# =========================================================

def analyze_news_for_coin(
    symbol,
    news
):

    base = symbol.replace(
        "USDT",
        ""
    ).lower()

    positive = 0
    negative = 0

    matched_titles = []

    # BTC / ETH gibi genel piyasa haberleri
    general_symbols = {
        "btc",
        "eth"
    }

    for item in news:

        title = item["title"]

        title_lower = title.lower()

        # Coin ismi başlıkta geçiyor mu?
        coin_match = (
            re.search(
                rf"\b{re.escape(base)}\b",
                title_lower
            )
            is not None
        )

        # BTC ve ETH için genel haberleri de al
        if not coin_match:

            if base not in general_symbols:

                continue

        pos_hits = 0
        neg_hits = 0

        for word in POSITIVE_WORDS:

            if word in title_lower:

                pos_hits += 1

        for word in NEGATIVE_WORDS:

            if word in title_lower:

                neg_hits += 1

        if pos_hits > 0 or neg_hits > 0:

            positive += pos_hits
            negative += neg_hits

            matched_titles.append(
                title
            )

    # Çok fazla haber varsa etkisini sınırlıyoruz
    positive = min(
        positive,
        3
    )

    negative = min(
        negative,
        3
    )

    if negative >= 2:

        sentiment = "OLUMSUZ"

    elif positive >= 2 and negative == 0:

        sentiment = "OLUMLU"

    elif positive > negative:

        sentiment = "HAFİF OLUMLU"

    elif negative > positive:

        sentiment = "HAFİF OLUMSUZ"

    else:

        sentiment = "NÖTR"

    return {
        "sentiment": sentiment,
        "positive": positive,
        "negative": negative,
        "titles": matched_titles[:2]
    }


# =========================================================
# BTC ANALİZİ
# =========================================================

def analyze_btc():

    try:

        candles = get_spot_klines(
            "BTCUSDT"
        )

        if not candles:

            return None

        closed = candles[:-1]

        closes = [
            float(x[4])
            for x in closed
        ]

        if len(closes) < 30:

            return None

        price = closes[-1]

        ema9 = calculate_ema(
            closes,
            9
        )

        ema21 = calculate_ema(
            closes,
            21
        )

        rsi = calculate_rsi(
            closes,
            14
        )

        change_6h = (
            (
                closes[-1]
                - closes[-7]
            )
            / closes[-7]
        ) * 100

        if (
            ema9 > ema21
            and price > ema9
        ):

            direction = "YUKARI"

        elif (
            ema9 < ema21
            and price < ema9
        ):

            direction = "AŞAĞI"

        else:

            direction = "NÖTR"

        return {
            "direction": direction,
            "price": price,
            "rsi": rsi,
            "change_6h": change_6h
        }

    except Exception as e:

        print(
            "BTC analiz hatası:",
            e
        )

        return None


# =========================================================
# BÜTÇE + KALDIRAÇ
# =========================================================

def choose_budget_and_leverage(
    score,
    news_sentiment,
    risk_percent
):

    # Önce fırsatın gücüne göre hedef bütçe
    if score >= 7:

        desired_budget = 40.0

    elif score >= 6:

        desired_budget = 30.0

    elif score >= 5:

        desired_budget = 20.0

    else:

        desired_budget = 10.0

    # Olumsuz haber varsa bütçeyi düşür
    if news_sentiment == "OLUMSUZ":

        desired_budget = min(
            desired_budget,
            10.0
        )

    elif news_sentiment == "HAFİF OLUMSUZ":

        desired_budget = min(
            desired_budget,
            20.0
        )

    # Kaldıraç seçimi
    #
    # Stop çok genişse yüksek kaldıraç kullanmıyoruz.

    if (
        score >= 7
        and risk_percent <= 0.80
    ):

        leverage = 10

    elif (
        score >= 6
        and risk_percent <= 1.00
    ):

        leverage = 8

    elif (
        score >= 5
        and risk_percent <= 1.30
    ):

        leverage = 6

    elif risk_percent <= 1.80:

        leverage = 5

    else:

        leverage = 3

    # Maksimum zarar hesabı
    #
    # Bütçe x kaldıraç x stop %
    # yaklaşık zararı verir.

    max_budget_by_risk = (
        MAX_RISK_DOLLARS
        /
        (
            leverage
            * risk_percent
            / 100
        )
    )

    actual_budget = min(
        desired_budget,
        max_budget_by_risk,
        MAX_BUDGET
    )

    # Çok küçük bir pozisyon çıkıyorsa
    # işlemi reddet
    if actual_budget < MIN_BUDGET:

        return None

    return {
        "desired_budget": desired_budget,
        "budget": actual_budget,
        "leverage": leverage
    }


# =========================================================
# İŞLEM PLANI
# =========================================================

def create_trade_plan(
    direction,
    price,
    support,
    resistance,
    volatility,
    score,
    news_sentiment
):

    if direction == "LONG":

        stop = support * 0.995

        # Stop aşırı uzaksa volatilite bazlı stop
        stop_distance = (
            (price - stop)
            / price
        ) * 100

        if (
            stop_distance > 3.0
            or stop >= price
        ):

            stop_distance = max(
                volatility * 0.8,
                1.0
            )

            stop = price * (
                1
                - stop_distance / 100
            )

        entry_low = price * 0.997
        entry_high = price * 1.003

        entry = (
            entry_low
            + entry_high
        ) / 2

        risk_percent = (
            (
                entry
                - stop
            )
            / entry
        ) * 100

        tp1 = entry * (
            1
            + risk_percent * 1.5 / 100
        )

        tp2 = entry * (
            1
            + risk_percent * 2.5 / 100
        )

        if resistance > entry:

            tp1 = min(
                tp1,
                resistance * 0.995
            )

            tp2 = min(
                tp2,
                resistance * 1.02
            )

    else:

        stop = resistance * 1.005

        stop_distance = (
            (stop - price)
            / price
        ) * 100

        if (
            stop_distance > 3.0
            or stop <= price
        ):

            stop_distance = max(
                volatility * 0.8,
                1.0
            )

            stop = price * (
                1
                + stop_distance / 100
            )

        entry_low = price * 0.997
        entry_high = price * 1.003

        entry = (
            entry_low
            + entry_high
        ) / 2

        risk_percent = (
            (
                stop
                - entry
            )
            / entry
        ) * 100

        tp1 = entry * (
            1
            - risk_percent * 1.5 / 100
        )

        tp2 = entry * (
            1
            - risk_percent * 2.5 / 100
        )

        if support < entry:

            tp1 = max(
                tp1,
                support * 1.005
            )

            tp2 = max(
                tp2,
                support * 0.98
            )

    if risk_percent <= 0:

        return None

    budget_info = choose_budget_and_leverage(
        score,
        news_sentiment,
        risk_percent
    )

    if budget_info is None:

        return None

    budget = budget_info["budget"]

    leverage = budget_info["leverage"]

    notional = (
        budget
        * leverage
    )

    estimated_loss = (
        notional
        * risk_percent
        / 100
    )

    tp1_profit = (
        notional
        * abs(
            tp1 - entry
        )
        / entry
    )

    tp2_profit = (
        notional
        * abs(
            tp2 - entry
        )
        / entry
    )

    return {
        "entry_low": entry_low,
        "entry_high": entry_high,
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "risk_percent": risk_percent,
        "position_size": budget,
        "leverage": leverage,
        "notional": notional,
        "estimated_loss": estimated_loss,
        "tp1_profit": tp1_profit,
        "tp2_profit": tp2_profit
    }


# =========================================================
# COIN ANALİZİ
# =========================================================

def analyze_coin(
    symbol,
    btc,
    news
):

    try:

        candles = get_spot_klines(
            symbol
        )

        if not candles or len(candles) < 50:

            return None

        closed = candles[:-1]

        closes = [
            float(x[4])
            for x in closed
        ]

        highs = [
            float(x[2])
            for x in closed
        ]

        lows = [
            float(x[3])
            for x in closed
        ]

        volumes = [
            float(x[5])
            for x in closed
        ]

        price = closes[-1]

        ema9 = calculate_ema(
            closes,
            9
        )

        ema21 = calculate_ema(
            closes,
            21
        )

        rsi = calculate_rsi(
            closes,
            14
        )

        if (
            ema9 is None
            or ema21 is None
            or rsi is None
        ):

            return None

        current_volume = volumes[-1]

        average_volume = statistics.mean(
            volumes[-21:-1]
        )

        if average_volume == 0:

            return None

        volume_ratio = (
            current_volume
            / average_volume
        )

        support = min(
            lows[-20:]
        )

        resistance = max(
            highs[-20:]
        )

        recent_ranges = []

        for i in range(-20, 0):

            candle_range = (
                (
                    highs[i]
                    - lows[i]
                )
                / closes[i]
            ) * 100

            recent_ranges.append(
                candle_range
            )

        volatility = statistics.mean(
            recent_ranges
        )

        # =================================================
        # HABER
        # =================================================

        news_result = analyze_news_for_coin(
            symbol,
            news
        )

        news_sentiment = (
            news_result["sentiment"]
        )

        # =================================================
        # PUAN
        # =================================================

        long_score = 0
        short_score = 0

        reasons_long = []
        reasons_short = []

        # EMA
        if ema9 > ema21:

            long_score += 1

            reasons_long.append(
                "Trend yukarı"
            )

        elif ema9 < ema21:

            short_score += 1

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
        if 50 <= rsi <= 68:

            long_score += 1

            reasons_long.append(
                "RSI uygun"
            )

        elif 32 <= rsi < 50:

            short_score += 1

            reasons_short.append(
                "RSI aşağı yönlü"
            )

        # Hacim
        if volume_ratio >= 1.5:

            if price > ema9:

                long_score += 1

                reasons_long.append(
                    "Hacim güçlü"
                )

            elif price < ema9:

                short_score += 1

                reasons_short.append(
                    "Satış hacmi güçlü"
                )

        # =================================================
        # FUTURES
        # =================================================

        funding = get_funding(
            symbol
        )

        open_interest = get_open_interest(
            symbol
        )

        oi_change = get_open_interest_history(
            symbol
        )

        long_short_ratio = get_long_short_ratio(
            symbol
        )

        # =================================================
        # FUNDING
        # =================================================

        if funding is not None:

            funding_percent = (
                funding * 100
            )

            # Aşırı pozitif funding
            # LONG için uyarı
            if funding_percent > 0.05:

                long_score -= 1

            # Aşırı negatif funding
            # SHORT için uyarı
            elif funding_percent < -0.05:

                short_score -= 1

        else:

            funding_percent = None

        # =================================================
        # OI
        # =================================================

        if oi_change is not None:

            if oi_change >= 2:

                if price > ema9:

                    long_score += 1

                    reasons_long.append(
                        "Vadeli işlemlerde ilgi artıyor"
                    )

                elif price < ema9:

                    short_score += 1

                    reasons_short.append(
                        "Vadeli satış ilgisi artıyor"
                    )

        # =================================================
        # LONG / SHORT
        # =================================================

        if long_short_ratio is not None:

            if long_short_ratio >= 1.20:

                long_score += 1

            elif long_short_ratio <= 0.83:

                short_score += 1

        # =================================================
        # BTC
        # =================================================

        if btc["direction"] == "YUKARI":

            long_score += 1

            reasons_long.append(
                "BTC destekliyor"
            )

            short_score -= 1

        elif btc["direction"] == "AŞAĞI":

            short_score += 1

            reasons_short.append(
                "BTC aşağı yönde"
            )

            long_score -= 1

        # =================================================
        # HABER ETKİSİ
        # =================================================

        if news_sentiment == "OLUMLU":

            long_score += 2

            reasons_long.append(
                "Haber akışı olumlu"
            )

        elif news_sentiment == "HAFİF OLUMLU":

            long_score += 1

            reasons_long.append(
                "Haber akışı olumlu"
            )

        elif news_sentiment == "OLUMSUZ":

            # Ciddi olumsuz haber varsa
            # LONG'u engelliyoruz.
            long_score -= 2

            short_score += 1

            reasons_short.append(
                "Olumsuz haber akışı"
            )

        elif news_sentiment == "HAFİF OLUMSUZ":

            long_score -= 1

            reasons_short.append(
                "Haber akışı zayıf"
            )

        # =================================================
        # YÖN
        # =================================================

        if (
            long_score >= 5
            and long_score > short_score
        ):

            direction = "LONG"

            score = long_score

            reasons = reasons_long

        elif (
            short_score >= 5
            and short_score > long_score
        ):

            direction = "SHORT"

            score = short_score

            reasons = reasons_short

        else:

            return None

        # =================================================
        # İŞLEM PLANI
        # =================================================

        plan = create_trade_plan(
            direction,
            price,
            support,
            resistance,
            volatility,
            score,
            news_sentiment
        )

        if plan is None:

            return None

        risk = abs(
            plan["entry"]
            - plan["stop"]
        )

        reward = abs(
            plan["tp1"]
            - plan["entry"]
        )

        if risk == 0:

            return None

        rr = reward / risk

        # En az 1.3 risk/getiri
        if rr < 1.3:

            return None

        # =================================================
        # CİDDİ OLUMSUZ HABERDE İŞLEM YOK
        # =================================================

        if news_sentiment == "OLUMSUZ":

            # SHORT için yine de çok güçlü
            # teknik şart gerekiyor
            if (
                direction == "LONG"
                or score < 6
            ):

                return None

        return {
            "symbol": symbol,
            "price": price,
            "direction": direction,
            "score": score,
            "rsi": rsi,
            "volume_ratio": volume_ratio,
            "funding": funding_percent,
            "open_interest": open_interest,
            "oi_change": oi_change,
            "long_short_ratio": long_short_ratio,
            "btc_direction": btc["direction"],
            "btc_rsi": btc["rsi"],
            "btc_change": btc["change_6h"],
            "news": news_result,
            "rr": rr,
            "reasons": reasons,
            "plan": plan
        }

    except Exception as e:

        print(
            f"{symbol} analiz hatası: {e}"
        )

        return None


# =========================================================
# HABER ÖZETİ
# =========================================================

def get_news_text(news_result):

    sentiment = (
        news_result["sentiment"]
    )

    titles = news_result["titles"]

    if sentiment == "OLUMLU":

        emoji = "🟢"

    elif sentiment == "OLUMSUZ":

        emoji = "🔴"

    elif sentiment in (
        "HAFİF OLUMLU",
        "HAFİF OLUMSUZ"
    ):

        emoji = "🟡"

    else:

        emoji = "⚪"

    text = (
        f"{emoji} {sentiment}"
    )

    if titles:

        text += "\n"

        for title in titles:

            # Telegram mesajını aşırı uzatmamak için
            if len(title) > 100:

                title = (
                    title[:97]
                    + "..."
                )

            text += (
                f"• {title}\n"
            )

    return text


# =========================================================
# ANA PROGRAM
# =========================================================

def main():

    print("Bot başladı.")

    # =====================================================
    # HABERLER
    # =====================================================

    print("Haberler taranıyor...")

    news = get_news()

    print(
        f"{len(news)} haber bulundu."
    )

    # =====================================================
    # BTC
    # =====================================================

    btc = analyze_btc()

    if btc is None:

        send_telegram(
            "⚠️ BTC verisi alınamadı.\n\n"
            "⏸️ WAIT"
        )

        return

    # =====================================================
    # COINLER
    # =====================================================

    tickers = get_24h_tickers()

    if not tickers:

        send_telegram(
            "⚠️ Binance piyasa verisi alınamadı.\n\n"
            "⏸️ WAIT"
        )

        return

    stablecoins = {
        "USDCUSDT",
        "FDUSDUSDT",
        "TUSDUSDT",
        "USDPUSDT",
        "DAIUSDT"
    }

    usdt_coins = [
        x
        for x in tickers
        if x["symbol"].endswith("USDT")
        and x["symbol"] not in stablecoins
    ]

    usdt_coins.sort(
        key=lambda x: float(
            x["quoteVolume"]
        ),
        reverse=True
    )

    top_coins = usdt_coins[:40]

    alerts = []

    for coin in top_coins:

        symbol = coin["symbol"]

        print(
            f"Analiz: {symbol}"
        )

        result = analyze_coin(
            symbol,
            btc,
            news
        )

        if result:

            alerts.append(
                result
            )

    # =====================================================
    # SIRALAMA
    # =====================================================

    alerts.sort(
        key=lambda x: (
            x["score"],
            x["rr"],
            x["volume_ratio"]
        ),
        reverse=True
    )

    # =====================================================
    # TELEGRAM
    # =====================================================

    if alerts:

        message = (
            "🚨 KRİPTO FIRSATLARI 🚨\n\n"

            f"💵 Sermaye: "
            f"${TOTAL_CAPITAL:.2f}\n\n"

            "🌐 BTC\n"

            f"Trend: "
            f"{btc['direction']}\n"

            f"RSI: "
            f"{btc['rsi']:.1f}\n"

            f"6s: "
            f"{btc['change_6h']:+.2f}%\n\n"
        )

        for alert in alerts[:MAX_ALERTS]:

            p = alert["plan"]

            if alert["direction"] == "LONG":

                emoji = "🟢"

            else:

                emoji = "🔴"

            news_text = get_news_text(
                alert["news"]
            )

            reasons = "\n".join(
                f"• {x}"
                for x in alert["reasons"][:5]
            )

            message += (

                f"{emoji} "
                f"{alert['direction']} — "
                f"{alert['symbol']}\n\n"

                f"⭐ Fırsat gücü: "
                f"{alert['score']}/8+\n"

                f"💰 Bütçe: "
                f"${p['position_size']:.2f}\n"

                f"⚡ Kaldıraç: "
                f"{p['leverage']}x\n\n"

                "📥 GİRİŞ\n"

                f"{p['entry_low']:g}"
                f" - "
                f"{p['entry_high']:g}\n\n"

                "🛑 STOP LOSS\n"

                f"{p['stop']:g}\n\n"

                "🎯 TP1\n"

                f"{p['tp1']:g}\n\n"

                "🎯 TP2\n"

                f"{p['tp2']:g}\n\n"

                f"💵 Stop olursa: "
                f"~${p['estimated_loss']:.2f}\n"

                f"📈 TP1 kârı: "
                f"~${p['tp1_profit']:.2f}\n"

                f"📈 TP2 kârı: "
                f"~${p['tp2_profit']:.2f}\n\n"

                f"📰 HABER\n"
                f"{news_text}\n\n"

                "📌 NEDEN?\n"
                f"{reasons}\n\n"

                f"📊 Risk/Getiri: "
                f"1:{alert['rr']:.2f}\n\n"

                "⚠️ Manuel işlem.\n"
                "Otomatik emir açılmaz.\n"

                "━━━━━━━━━━━━━━\n\n"
            )

    else:

        message = (

            "🟢 PİYASA TARAMASI TAMAMLANDI\n\n"

            f"💵 Sermaye: "
            f"${TOTAL_CAPITAL:.2f}\n\n"

            "🌐 BTC\n"

            f"Trend: "
            f"{btc['direction']}\n"

            f"RSI: "
            f"{btc['rsi']:.1f}\n"

            f"6s: "
            f"{btc['change_6h']:+.2f}%\n\n"

            f"📰 {len(news)} haber tarandı.\n"

            f"🔎 {len(top_coins)} coin tarandı.\n\n"

            "⏸️ WAIT\n\n"

            "Şu an yeterince güçlü "
            "bir fırsat bulunamadı.\n\n"

            "⚠️ İşlem açma."
        )

    send_telegram(
        message
    )


# =========================================================
# ÇALIŞTIR
# =========================================================

if __name__ == "__main__":

    main()
