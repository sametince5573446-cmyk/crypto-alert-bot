import os
import requests

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

def get_price(symbol):
    url = "https://data-api.binance.vision/api/v3/ticker/24hr"
    response = requests.get(
        url,
        params={"symbol": symbol},
        timeout=15
    )
    response.raise_for_status()
    return response.json()

coins = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "SUIUSDT",
    "PEPEUSDT"
]

message = "📊 BINANCE PİYASA RAPORU\n\n"

for coin in coins:
    try:
        data = get_price(coin)

        price = float(data["lastPrice"])
        change = float(data["priceChangePercent"])
        volume = float(data["quoteVolume"])

        emoji = "🟢" if change >= 0 else "🔴"

        message += (
            f"{emoji} {coin}\n"
            f"Fiyat: {price:g}\n"
            f"24s: {change:+.2f}%\n"
            f"Hacim: ${volume:,.0f}\n\n"
        )

    except Exception as e:
        message += f"⚠️ {coin}: Veri alınamadı\n\n"

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

response = requests.post(
    url,
    data={
        "chat_id": CHAT_ID,
        "text": message
    },
    timeout=15
)

response.raise_for_status()

print("Binance verileri Telegram'a gönderildi.")
