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

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

BINANCE_SPOT_URL = "https://data-api.binance.vision"
BINANCE_FUTURES_URL = "https://fapi.binance.com"

CAPITAL = 100.0
MAX_RISK_DOLLARS = 2.50

MAX_COINS = 100

SPECIAL_COINS = [
    "XVGUSDT",
    "QNTUSDT"
]

NEWS_HOURS = 12

SOLANA_STATE_FILE = "solana_alerts.json"

# Stop mesafesi maksimum %5
MAX_STOP_PERCENT = 5.0

# Minimum kaldıraç
MIN_LEVERAGE = 3

# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:
        requests.post(url, data=data, timeout=15)
    except Exception as e:
        print("Telegram hatası:", e)


# ============================================================
# BINANCE
# ============================================================

def get_24h_tickers():
    url = BINANCE_SPOT_URL + "/api/v3/ticker/24hr"

    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("Ticker hatası:", e)
        return []


def get_klines(symbol, interval="1h", limit=100):
    url = BINANCE_SPOT_URL + "/api/v3/klines"

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }

    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(symbol, "klines hatası:", e)
        return []


def get_funding(symbol):
    url = BINANCE_FUTURES_URL + "/fapi/v1/fundingRate"

    params = {
        "symbol": symbol,
        "limit": 1
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()

        data = r.json()

        if data:
            return float(data[-1]["fundingRate"])

    except Exception as e:
        print(symbol, "funding hatası:", e)

    return 0.0


def get_open_interest(symbol):
    url = BINANCE_FUTURES_URL + "/fapi/v1/openInterest"

    params = {
        "symbol": symbol
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()

        data = r.json()

        return float(data.get("openInterest", 0))

    except Exception as e:
        print(symbol, "OI hatası:", e)

    return 0.0


def get_open_interest_history(symbol):
    url = BINANCE_FUTURES_URL + "/futures/data/openInterestHist"

    params = {
        "symbol": symbol,
        "period": "1h",
        "limit": 3
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()

        data = r.json()

        if len(data) >= 2:
            old = float(data[-2]["sumOpenInterest"])
            new = float(data[-1]["sumOpenInterest"])

            if old > 0:
                return ((new - old) / old) * 100

    except Exception as e:
        print(symbol, "OI history hatası:", e)

    return 0.0


# ============================================================
# RSI
# ============================================================

def calculate_rsi(closes, period=14):

    if len(closes) <= period:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]

        if change >= 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


# ============================================================
# EMA
# ============================================================

def calculate_ema(values, period):

    if not values:
        return 0

    multiplier = 2 / (period + 1)

    ema = values[0]

    for value in values[1:]:
        ema = ((value - ema) * multiplier) + ema

    return ema


# ============================================================
# HABER
# ============================================================

POSITIVE_WORDS = [
    "etf",
    "approval",
    "approved",
    "partnership",
    "launch",
    "adoption",
    "listing",
    "bullish",
    "integration",
    "investment",
    "institutional",
    "upgrade",
    "mainnet"
]

NEGATIVE_WORDS = [
    "hack",
    "exploit",
    "scam",
    "lawsuit",
    "ban",
    "delist",
    "delisting",
    "hack",
    "stolen",
    "attack",
    "dump",
    "liquidation",
    "fraud"
]


def get_news():

    feeds = [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss"
    ]

    news = []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=NEWS_HOURS)

    for feed in feeds:

        try:
            r = requests.get(feed, timeout=15)

            root = ET.fromstring(r.content)

            for item in root.iter("item"):

                title = item.findtext("title", "")

                pub = item.findtext("pubDate", "")

                news.append({
                    "title": title,
                    "date": pub
                })

        except Exception as e:
            print("RSS hatası:", e)

    return news


def analyze_news(symbol, news):

    coin = symbol.replace("USDT", "").lower()

    positive = 0
    negative = 0
    related_title = None

    for item in news:

        title = item["title"].lower()

        if coin not in title:
            continue

        related_title = item["title"]

        for word in POSITIVE_WORDS:
            if word in title:
                positive += 1

        for word in NEGATIVE_WORDS:
            if word in title:
                negative += 1

    if negative > positive:
        return "NEGATİF", related_title

    if positive > negative:
        return "POZİTİF", related_title

    return "NÖTR", related_title


# ============================================================
# BTC ANALİZİ
# ============================================================

def analyze_btc():

    klines = get_klines("BTCUSDT", "1h", 100)

    if len(klines) < 30:
        return {
            "trend": "NÖTR",
            "rsi": 50,
            "change6h": 0
        }

    closes = [float(x[4]) for x in klines]

    ema9 = calculate_ema(closes[-60:], 9)
    ema21 = calculate_ema(closes[-60:], 21)

    rsi = calculate_rsi(closes)

    current = closes[-1]
    old = closes[-7]

    change6h = ((current - old) / old) * 100

    if ema9 > ema21 and rsi >= 50:
        trend = "YUKARI"

    elif ema9 < ema21 and rsi <= 50:
        trend = "AŞAĞI"

    else:
        trend = "NÖTR"

    return {
        "trend": trend,
        "rsi": rsi,
        "change6h": change6h
    }


# ============================================================
# COIN ANALİZİ
# ============================================================

def analyze_coin(symbol):

    klines = get_klines(symbol, "1h", 100)

    if len(klines) < 50:
        return None

    closes = [float(x[4]) for x in klines]
    volumes = [float(x[5]) for x in klines]

    current = closes[-1]

    change1h = ((closes[-1] - closes[-2]) / closes[-2]) * 100
    change6h = ((closes[-1] - closes[-7]) / closes[-7]) * 100
    change24h = ((closes[-1] - closes[-25]) / closes[-25]) * 100

    ema9 = calculate_ema(closes[-60:], 9)
    ema21 = calculate_ema(closes[-60:], 21)

    rsi = calculate_rsi(closes)

    recent_volume = volumes[-1]

    avg_volume = sum(volumes[-25:-1]) / 24

    if avg_volume > 0:
        volume_ratio = recent_volume / avg_volume
    else:
        volume_ratio = 0

    recent_high = max(closes[-25:])
    recent_low = min(closes[-25:])

    if ema9 > ema21:
        trend = "YUKARI"
    elif ema9 < ema21:
        trend = "AŞAĞI"
    else:
        trend = "NÖTR"

    # Aşırı hareketleri ele
    if abs(change6h) > 25:
        return None

    if rsi > 78 or rsi < 22:
        return None

    return {
        "symbol": symbol,
        "price": current,
        "change1h": change1h,
        "change6h": change6h,
        "change24h": change24h,
        "ema9": ema9,
        "ema21": ema21,
        "rsi": rsi,
        "volume_ratio": volume_ratio,
        "trend": trend,
        "support": recent_low,
        "resistance": recent_high
    }


# ============================================================
# SİNYAL PUANI
# ============================================================

def calculate_score(data, btc, news_sentiment):

    score = 0

    trend = data["trend"]
    change1h = data["change1h"]
    volume_ratio = data["volume_ratio"]
    rsi = data["rsi"]

    # Trend
    if trend == "YUKARI":
        score += 2

    elif trend == "AŞAĞI":
        score += 2

    # Momentum
    if abs(change1h) >= 1:
        score += 1

    if abs(change1h) >= 2:
        score += 1

    # Hacim
    if volume_ratio >= 2:
        score += 2

    elif volume_ratio >= 1.3:
        score += 1

    # RSI
    if 50 <= rsi <= 70:
        score += 1

    elif 30 <= rsi < 50:
        score += 1

    # BTC uyumu
    if trend == "YUKARI" and btc["trend"] == "YUKARI":
        score += 1

    if trend == "AŞAĞI" and btc["trend"] == "AŞAĞI":
        score += 1

    # Haber
    if news_sentiment == "POZİTİF":
        score += 1

    elif news_sentiment == "NEGATİF":
        score += 1

    return score


# ============================================================
# POZİSYON YÖNÜ
# ============================================================

def get_direction(data, btc):

    if data["trend"] == "YUKARI":

        if btc["trend"] in ["YUKARI", "NÖTR"]:
            return "LONG"

    if data["trend"] == "AŞAĞI":

        if btc["trend"] in ["AŞAĞI", "NÖTR"]:
            return "SHORT"

    return None


# ============================================================
# TRADE PLANI
# ============================================================

def create_trade_plan(data, direction, score):

    price = data["price"]
    support = data["support"]
    resistance = data["resistance"]

    # Daha sıkı stop hesaplaması
    if direction == "LONG":

        raw_stop = support

        distance = price - raw_stop

        if distance <= 0:
            return None

        stop_percent = (distance / price) * 100

        # Stop %5'ten büyükse kesinlikle gönderme
        if stop_percent > MAX_STOP_PERCENT:
            return None

        entry = price

        tp1 = entry + (distance * 1.5)
        tp2 = entry + (distance * 2.5)

    else:

        raw_stop = resistance

        distance = raw_stop - price

        if distance <= 0:
            return None

        stop_percent = (distance / price) * 100

        if stop_percent > MAX_STOP_PERCENT:
            return None

        entry = price

        tp1 = entry - (distance * 1.5)
        tp2 = entry - (distance * 2.5)

    # --------------------------------------------------------
    # Dinamik bütçe + kaldıraç
    # --------------------------------------------------------

    if score >= 7:

        desired_budget = 40
        leverage = 10

    elif score >= 6:

        desired_budget = 30
        leverage = 8

    elif score >= 5:

        desired_budget = 20
        leverage = 5

    else:

        desired_budget = 10
        leverage = 3

    # Stop oranına göre kaldıraç azalt
    if stop_percent > 4:

        leverage = 3

    elif stop_percent > 3:

        leverage = min(leverage, 5)

    elif stop_percent > 2:

        leverage = min(leverage, 6)

    # Asla 1x/2x verme
    leverage = max(leverage, MIN_LEVERAGE)

    # Maksimum risk hesabı
    max_budget_by_risk = MAX_RISK_DOLLARS / (
        (stop_percent / 100) * leverage
    )

    budget = min(
        desired_budget,
        max_budget_by_risk,
        CAPITAL
    )

    # Çok küçük bütçeli işlemleri ele
    if budget < 5:
        return None

    estimated_loss = budget * leverage * (stop_percent / 100)

    # Güvenlik kontrolü
    if estimated_loss > MAX_RISK_DOLLARS + 0.01:
        return None

    tp1_percent = abs((tp1 - entry) / entry) * 100
    tp2_percent = abs((tp2 - entry) / entry) * 100

    profit_tp1 = budget * leverage * (tp1_percent / 100)
    profit_tp2 = budget * leverage * (tp2_percent / 100)

    return {
        "entry": entry,
        "stop": raw_stop,
        "tp1": tp1,
        "tp2": tp2,
        "stop_percent": stop_percent,
        "budget": budget,
        "leverage": leverage,
        "estimated_loss": estimated_loss,
        "profit_tp1": profit_tp1,
        "profit_tp2": profit_tp2
    }


# ============================================================
# SOLANA RADAR
# ============================================================

def load_solana_state():

    if not os.path.exists(SOLANA_STATE_FILE):
        return {}

    try:

        with open(SOLANA_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    except:
        return {}


def save_solana_state(state):

    with open(SOLANA_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def commit_state():

    try:

        subprocess.run(
            ["git", "config", "user.name", "crypto-alert-bot"],
            check=False
        )

        subprocess.run(
            ["git", "config", "user.email", "crypto-alert-bot@users.noreply.github.com"],
            check=False
        )

        subprocess.run(
            ["git", "add", SOLANA_STATE_FILE],
            check=False
        )

        subprocess.run(
            ["git", "commit", "-m", "Update Solana alert state"],
            check=False
        )

        subprocess.run(
            ["git", "push"],
            check=False
        )

    except Exception as e:
        print("State commit hatası:", e)


def get_solana_profiles():

    urls = [
        "https://api.dexscreener.com/token-profiles/latest/v1",
        "https://api.dexscreener.com/token-boosts/latest/v1"
    ]

    addresses = []

    for url in urls:

        try:

            r = requests.get(url, timeout=15)

            if r.status_code != 200:
                continue

            data = r.json()

            for item in data:

                if item.get("chainId") != "solana":
                    continue

                address = item.get("tokenAddress")

                if address and address not in addresses:
                    addresses.append(address)

        except Exception as e:
            print("Solana profile hatası:", e)

    return addresses[:25]


def get_solana_pair(address):

    url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"

    try:

        r = requests.get(url, timeout=15)

        if r.status_code != 200:
            return None

        data = r.json()

        pairs = data.get("pairs", [])

        sol_pairs = [
            p for p in pairs
            if p.get("chainId") == "solana"
        ]

        if not sol_pairs:
            return None

        sol_pairs.sort(
            key=lambda x: float(
                x.get("liquidity", {}).get("usd", 0) or 0
            ),
            reverse=True
        )

        return sol_pairs[0]

    except Exception as e:

        print("Solana pair hatası:", e)

        return None


def analyze_solana():

    state = load_solana_state()

    now = datetime.now(timezone.utc)

    # Eski kayıtları temizle
    cleaned = {}

    for address, timestamp in state.items():

        try:

            old_time = datetime.fromisoformat(timestamp)

            if now - old_time < timedelta(hours=24):
                cleaned[address] = timestamp

        except:
            pass

    state = cleaned

    addresses = get_solana_profiles()

    alerts = []

    for address in addresses:

        if address in state:
            continue

        pair = get_solana_pair(address)

        if not pair:
            continue

        try:

            price_change = pair.get("priceChange", {})

            change1h = float(price_change.get("h1", 0) or 0)
            change6h = float(price_change.get("h6", 0) or 0)
            change24h = float(price_change.get("h24", 0) or 0)

            volume = pair.get("volume", {})

            volume1h = float(volume.get("h1", 0) or 0)
            volume24h = float(volume.get("h24", 0) or 0)

            if volume24h > 0:
                avg_1h = volume24h / 24
                volume_ratio = volume1h / avg_1h
            else:
                volume_ratio = 0

            liquidity = float(
                pair.get("liquidity", {}).get("usd", 0) or 0
            )

            txns = pair.get("txns", {}).get("h1", {})

            buys = int(txns.get("buys", 0) or 0)
            sells = int(txns.get("sells", 0) or 0)

            total_txns = buys + sells

            buyer_ratio = buys / max(sells, 1)

            # =================================================
            # ERKEN UYARI FİLTRELERİ
            # =================================================

            # Çoktan pump yapmış coin
            if change1h >= 25:
                continue

            if change6h >= 40:
                continue

            if change24h >= 100:
                continue

            # Negatif hareket
            if change1h <= 0:
                continue

            # Hacim hızlanması şart
            if volume_ratio < 1.8:
                continue

            # Minimum likidite
            if liquidity < 10000:
                continue

            # Minimum işlem
            if total_txns < 40:
                continue

            # Alıcı üstünlüğü
            if buyer_ratio < 1.15:
                continue

            score = 0

            # Fiyat
            if 3 <= change1h < 10:
                score += 3

            elif 10 <= change1h < 15:
                score += 2

            elif 15 <= change1h < 25:
                score += 1

            else:
                continue

            # Hacim
            if volume_ratio >= 5:
                score += 4

            elif volume_ratio >= 3:
                score += 3

            elif volume_ratio >= 1.8:
                score += 2

            # Alıcılar
            if buyer_ratio >= 2:
                score += 3

            elif buyer_ratio >= 1.5:
                score += 2

            else:
                score += 1

            # İşlem sayısı
            if total_txns >= 500:
                score += 2

            elif total_txns >= 100:
                score += 1

            # Likidite
            if liquidity >= 50000:
                score += 2

            else:
                score += 1

            # Boost / sosyal hareketlilik
            if pair.get("boosts"):
                score += 1

            if score < 9:
                continue

            base_token = pair.get("baseToken", {})

            name = base_token.get(
                "symbol",
                "UNKNOWN"
            )

            dex_url = pair.get("url", "")

            if change1h <= 10:
                stage = "🟢 ERKEN HAREKET"
            else:
                stage = "🟡 ERKEN AŞAMA"

            message = f"""
🚨 ERKEN UYARI — SOLANA

🪙 {name}
📈 Son hareket: {change1h:.1f}%
🔥 Hacim: Normalden {volume_ratio:.1f}x
👥 Alıcılar: {buys}
💧 Likidite: ${liquidity:,.0f}

💡 Neden dikkat çekti?
• Fiyat henüz aşırı yükselmedi.
• Hacim normalin üzerine çıktı.
• Alım hareketi güçlendi.
• İşlem sayısı hareketlendi.

{stage}

⚠️ Meme coin — çok yüksek risk
📍 Solana
🔎 Phantom'dan kontrol et.

🔗 DEX Screener:
{dex_url}
"""

            alerts.append(
                (
                    address,
                    message
                )
            )

        except Exception as e:

            print("Solana analiz hatası:", e)

    for address, message in alerts:

        send_telegram(message)

        state[address] = now.isoformat()

    save_solana_state(state)

    if alerts:
        commit_state()


# ============================================================
# ANA TARAMA
# ============================================================

def main():

    print("Bot başladı.")

    # --------------------------------------------------------
    # Haberleri çek
    # --------------------------------------------------------

    news = get_news()

    # --------------------------------------------------------
    # BTC
    # --------------------------------------------------------

    btc = analyze_btc()

    print(
        "BTC:",
        btc["trend"],
        "RSI:",
        round(btc["rsi"], 1)
    )

    # --------------------------------------------------------
    # Binance coinleri
    # --------------------------------------------------------

    tickers = get_24h_tickers()

    usdt_coins = []

    for item in tickers:

        symbol = item.get("symbol", "")

        if not symbol.endswith("USDT"):
            continue

        if symbol.endswith("UPUSDT") or symbol.endswith("DOWNUSDT"):
            continue

        try:

            volume = float(
                item.get("quoteVolume", 0)
            )

            usdt_coins.append(
                (
                    symbol,
                    volume
                )
            )

        except:
            pass

    usdt_coins.sort(
        key=lambda x: x[1],
        reverse=True
    )

    selected = [
        x[0]
        for x in usdt_coins[:MAX_COINS]
    ]

    # Özel coinleri garanti et
    for coin in SPECIAL_COINS:

        if coin not in selected:

            selected.append(coin)

    print(
        f"{len(selected)} coin taranacak."
    )

    opportunities = []

    for index, symbol in enumerate(selected, start=1):

        print(
            f"[{index}/{len(selected)}] {symbol}"
        )

        data = analyze_coin(symbol)

        if not data:
            continue

        direction = get_direction(
            data,
            btc
        )

        if not direction:
            continue

        sentiment, news_title = analyze_news(
            symbol,
            news
        )

        score = calculate_score(
            data,
            btc,
            sentiment
        )

        if score < 5:
            continue

        plan = create_trade_plan(
            data,
            direction,
            score
        )

        if not plan:
            print(
                symbol,
                "stop fazla geniş / risk uygun değil."
            )
            continue

        opportunities.append(
            (
                score,
                symbol,
                direction,
                data,
                plan,
                sentiment,
                news_title
            )
        )

    # --------------------------------------------------------
    # En güçlü fırsat
    # --------------------------------------------------------

    opportunities.sort(
        key=lambda x: x[0],
        reverse=True
    )

    if opportunities:

        score, symbol, direction, data, plan, sentiment, news_title = opportunities[0]

        if score >= 7:
            signal = "🚀 ÇOK GÜÇLÜ"

        elif score >= 6:
            signal = "🟢 GÜÇLÜ"

        else:
            signal = "🟡 ORTA GÜÇLÜ"

        why = []

        if data["trend"] == "YUKARI":
            why.append(
                "Kısa vadeli trend yukarı."
            )

        elif data["trend"] == "AŞAĞI":
            why.append(
                "Kısa vadeli trend aşağı."
            )

        if data["volume_ratio"] >= 1.5:
            why.append(
                "Hacim artışıyla birlikte hareket var."
            )

        if data["rsi"] >= 50:
            why.append(
                "Momentum alıcı tarafında."
            )

        else:
            why.append(
                "Momentum satıcı tarafında."
            )

        if sentiment == "POZİTİF":
            why.append(
                "Haber akışı olumlu."
            )

        elif sentiment == "NEGATİF":
            why.append(
                "Haber akışı negatif."
            )

        message = f"""
🚨 FIRSAT

🪙 {symbol}
📊 {direction}
🔥 Sinyal: {signal}

💵 Bütçe: ${plan["budget"]:.2f}
⚡ Kaldıraç: {plan["leverage"]}x

📍 Giriş: {plan["entry"]:.8f}
🛑 Stop: {plan["stop"]:.8f}
🎯 TP1: {plan["tp1"]:.8f}
🎯 TP2: {plan["tp2"]:.8f}

📏 Stop mesafesi: %{plan["stop_percent"]:.2f}

🔻 Tahmini zarar: ${plan["estimated_loss"]:.2f}
🟢 TP1 kâr: ${plan["profit_tp1"]:.2f}
🟢 TP2 kâr: ${plan["profit_tp2"]:.2f}

📰 Haber: {sentiment}
"""

        if news_title:
            message += f"\n📰 {news_title}\n"

        message += "\n💡 Neden?\n"

        for item in why:
            message += f"• {item}\n"

        message += """
⚠️ Manuel değerlendirme içindir.
Otomatik emir açılmaz.
"""

        send_telegram(message)

    else:

        message = f"""
🟢 PİYASA TARAMASI TAMAMLANDI

💵 Sermaye: ${CAPITAL:.2f}

🌐 BTC DURUMU
Trend: {btc["trend"]}
RSI: {btc["rsi"]:.1f}
6s değişim: {btc["change6h"]:+.2f}%

🔎 {len(selected)} coin tarandı.

⏸️ WAIT — Uygun işlem fırsatı bulunamadı.

📌 Filtre:
• Minimum 3x kaldıraç
• Maksimum %5 stop mesafesi
• Maksimum $2.50 planlanan zarar

⚠️ Otomatik emir açılmaz.
Manuel değerlendirme içindir.
"""

        send_telegram(message)

    # --------------------------------------------------------
    # Solana radar
    # --------------------------------------------------------

    try:
        analyze_solana()
    except Exception as e:
        print(
            "Solana radar hatası:",
            e
        )

    print("Bot tamamlandı.")


if __name__ == "__main__":
    main()
