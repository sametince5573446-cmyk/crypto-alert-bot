import os
import requests
import statistics

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

BASE_URL = "https://data-api.binance.vision"

session = requests.Session()


def get_24h_tickers():
    url = f"{BASE_URL}/api/v3/ticker/24hr"
    response = session.get(url, timeout=20)
    response.raise_for_status()
    return response.json()


def get_klines(symbol):
    url = f"{BASE_URL}/api/v3/klines"

    params = {
        "symbol": symbol,
        "interval": "1h",
        "limit": 21
    }

    response = session.get(url, params=params, timeout=20)
    response.raise_for_status()

    return response.json()


def analyze_coin(symbol):
    try:
        candles = get_klines(symbol)

        if len(candles) < 21:
            return None

        # Son kapanmış 20 saatin hacimleri
        previous_volumes = [
            float(candle[5])
            for candle in candles[:-1]
        ]

        current = candles[-1]

        current_open = float(current[1])
        current_close = float(current[4])
        current_volume = float(current[5])

        price_change = (
            (current_close - current_open)
            / current_open
        ) * 100

        average_volume = statistics.mean(previous_volumes)

        if average_volume == 0:
            return None

        volume_ratio = current_volume / average_volume

        # Alarm puanı
        score = 0

        if abs(price_change) >= 2:
            score += 1

        if abs(price_change) >= 4:
            score += 1

        if volume_ratio >= 2:
            score += 1

        if volume_ratio >= 4:
            score += 1

        # En az 3 puan yoksa alarm verme
        if score < 3:
            return None

        direction = "🟢 YUKARI" if price_change > 0 else "🔴 AŞAĞI"

        return {
            "symbol": symbol,
            "price": current_close,
            "change": price_change,
            "volume_ratio": volume_ratio,
            "score": score,
            "direction": direction
        }

    except Exception:
        return None


# --------------------------------------------------
# 1. Binance'ten 24 saatlik verileri al
# --------------------------------------------------

tickers = get_24h_tickers()

# USDT çiftlerini seç
usdt_coins = [
    x for x in tickers
    if x["symbol"].endswith("USDT")
]

# En yüksek işlem hacmine sahip ilk 40 coin
usdt_coins.sort(
    key=lambda x: float(x["quoteVolume"]),
    reverse=True
)

top_coins = usdt_coins[:40]


# --------------------------------------------------
# 2. Coinleri analiz et
# --------------------------------------------------

alerts = []

for coin in top_coins:

    symbol = coin["symbol"]

    # Stablecoin çiftlerini geç
    if symbol in [
        "USDCUSDT",
        "FDUSDUSDT",
        "TUSDUSDT",
        "USDPUSDT",
        "DAIUSDT"
    ]:
        continue

    result = analyze_coin(symbol)

    if result:
        alerts.append(result)


# En yüksek puanlılar üstte
alerts.sort(
    key=lambda x: (
        x["score"],
        x["volume_ratio"],
        abs(x["change"])
    ),
    reverse=True
)


# --------------------------------------------------
# 3. Telegram mesajı
# --------------------------------------------------

if alerts:

    message = "🚨 KRİPTO HAREKET ALARMI 🚨\n\n"

    for alert in alerts[:8]:

        message += (
            f"{alert['direction']}\n"
            f"🪙 {alert['symbol']}\n"
            f"💰 Fiyat: {alert['price']:g}\n"
            f"📈 1s değişim: {alert['change']:+.2f}%\n"
            f"📊 Hacim: normalin "
            f"{alert['volume_ratio']:.1f} katı\n"
            f"⭐ Alarm puanı: {alert['score']}/4\n\n"
        )

    message += (
        "⚠️ Bu otomatik bir piyasa alarmıdır.\n"
        "Alım-satım emri değildir.\n"
        "İşlem öncesi manuel inceleme yap."
    )

else:

    message = (
        "🟢 PİYASA TARAMASI TAMAMLANDI\n\n"
        "Şu anda belirlenen eşikleri "
        "aynı anda sağlayan güçlü bir hareket "
        "tespit edilmedi."
    )


# --------------------------------------------------
# 4. Telegram'a gönder
# --------------------------------------------------

telegram_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

response = session.post(
    telegram_url,
    data={
        "chat_id": CHAT_ID,
        "text": message
    },
    timeout=20
)

response.raise_for_status()

print("Piyasa taraması tamamlandı.")
