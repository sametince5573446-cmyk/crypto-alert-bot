import os
import requests

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

message = (
    "🤖 CRYPTO ALERT BOT\n\n"
    "✅ Sistem başarıyla çalışıyor!\n"
    "📱 Telegram bağlantısı aktif.\n"
    "📊 Bir sonraki aşamada Binance verilerini ekleyeceğiz."
)

response = requests.post(
    url,
    data={
        "chat_id": CHAT_ID,
        "text": message
    },
    timeout=15
)

response.raise_for_status()
print("Telegram mesajı gönderildi.")
