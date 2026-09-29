import os
import requests
import statistics

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

BASE_URL = "https://data-api.binance.vision"

session = requests.Session()

# =========================
# SİSTEM AYARLARI
# =========================

TOTAL_CAPITAL = 100.0       # Toplam sermaye
TRADE_BUDGET = 20.0         # Bir işlemde kullanılacak sermaye
RISK_PERCENT = 1.0          # Toplam sermayenin %1'i maksimum risk

# =========================
# BINANCE VERİLERİ
# =========================

def get_24h_tickers():

    url = f"{BASE_URL}/api/v3/ticker/24hr"

    response = session.get(
        url,
        timeout=20
    )

    response.raise_for_status()

    return response.json()


def get_klines(symbol):

    url = f"{BASE_URL}/api/v3/klines"

    params = {
        "symbol": symbol,
        "interval": "1h",
        "limit": 50
    }

    response = session.get(
        url,
        params=params,
        timeout=20
    )

    response.raise_for_status()

    return response.json()


# =========================
# İŞLEM PLANI HESAPLAMA
# =========================

def calculate_trade_plan(
    price,
    direction,
    volatility
):

    # Maksimum kabul edilen zarar
    max_risk = TOTAL_CAPITAL * (RISK_PERCENT / 100)

    # Volatiliteye göre stop mesafesi
    stop_percent = max(
        1.5,
        min(volatility * 1.2, 4.0)
    )

    if direction == "LONG":

        entry_low = price * 0.995
        entry_high = price * 1.005

        entry = (entry_low + entry_high) / 2

        stop = entry * (
            1 - stop_percent / 100
        )

        tp1 = entry * (
            1 + (stop_percent * 1.5) / 100
        )

        tp2 = entry * (
            1 + (stop_percent * 2.5) / 100
        )

    else:

        entry_low = price * 0.995
        entry_high = price * 1.005

        entry = (entry_low + entry_high) / 2

        stop = entry * (
            1 + stop_percent / 100
        )

        tp1 = entry * (
            1 - (stop_percent * 1.5) / 100
        )

        tp2 = entry * (
            1 - (stop_percent * 2.5) / 100
        )

    # Risk bazlı pozisyon büyüklüğü
    risk_distance = abs(
        entry - stop
    )

    risk_ratio = (
        risk_distance / entry
    )

    if risk_ratio == 0:
        return None

    position_size = max_risk / risk_ratio

    # İşlem bütçesini aşmasın
    position_size = min(
        position_size,
        TRADE_BUDGET
    )

    # Şimdilik maksimum 5x
    leverage = 1

    if position_size < TRADE_BUDGET:
        leverage = 1
    else:
        leverage = 3

    notional = position_size * leverage

    # Stop durumundaki yaklaşık zarar
    stop_loss_dollar = (
        notional * risk_ratio
    )

    # Kâr hesapları
    tp1_ratio = abs(
        tp1 - entry
    ) / entry

    tp2_ratio = abs(
        tp2 - entry
    ) / entry

    tp1_profit = (
        notional * tp1_ratio
    )

    tp2_profit = (
        notional * tp2_ratio
    )

    return {
        "entry_low": entry_low,
        "entry_high": entry_high,
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "stop_percent": stop_percent,
        "position_size": position_size,
        "leverage": leverage,
        "notional": notional,
        "risk": stop_loss_dollar,
        "tp1_profit": tp1_profit,
        "tp2_profit": tp2_profit
    }


# =========================
# COIN ANALİZİ
# =========================

def analyze_coin(symbol):

    try:

        candles = get_klines(symbol)

        if len(candles) < 25:
            return None

        # SON KAPANMIŞ MUM
        current = candles[-2]

        # Önceki kapanmış mumlar
        previous = candles[-22:-2]

        current_open = float(current[1])
        current_high = float(current[2])
        current_low = float(current[3])
        current_close = float(current[4])
        current_volume = float(current[5])

        previous_volumes = [
            float(candle[5])
            for candle in previous
        ]

        average_volume = statistics.mean(
            previous_volumes
        )

        if average_volume == 0:
            return None

        volume_ratio = (
            current_volume /
            average_volume
        )

        price_change = (
            (current_close - current_open)
            / current_open
        ) * 100

        # Mum volatilitesi
        volatility = (
            (current_high - current_low)
            / current_close
        ) * 100

        score = 0

        # Fiyat hareketi
        if abs(price_change) >= 2:
            score += 1

        if abs(price_change) >= 4:
            score += 1

        # Hacim
        if volume_ratio >= 2:
            score += 1

        if volume_ratio >= 4:
            score += 1

        # Yeterli sinyal yoksa işlem yok
        if score < 3:
            return None

        if price_change > 0:
            direction = "LONG"
            emoji = "🟢"
        else:
            direction = "SHORT"
            emoji = "🔴"

        trade_plan = calculate_trade_plan(
            current_close,
            direction,
            volatility
        )

        if not trade_plan:
            return None

        return {
            "symbol": symbol,
            "price": current_close,
            "change": price_change,
            "volume_ratio": volume_ratio,
            "score": score,
            "direction": direction,
            "emoji": emoji,
            "plan": trade_plan
        }

    except Exception:

        return None


# =========================
# PİYASA TARAMASI
# =========================

tickers = get_24h_tickers()

usdt_coins = [
    x for x in tickers
    if x["symbol"].endswith("USDT")
]

usdt_coins.sort(
    key=lambda x: float(
        x["quoteVolume"]
    ),
    reverse=True
)

# İlk 40 yüksek hacimli coin
top_coins = usdt_coins[:40]

alerts = []

for coin in top_coins:

    symbol = coin["symbol"]

    # Stablecoinleri çıkar
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


# Güçlüden zayıfa sırala
alerts.sort(
    key=lambda x: (
        x["score"],
        x["volume_ratio"],
        abs(x["change"])
    ),
    reverse=True
)


# =========================
# TELEGRAM MESAJI
# =========================

if alerts:

    message = (
        "🚨 KRİPTO İŞLEM SİNYALİ 🚨\n\n"
        f"💵 Toplam sermaye: ${TOTAL_CAPITAL:.2f}\n"
        f"💰 İşlem bütçesi: ${TRADE_BUDGET:.2f}\n\n"
    )

    for alert in alerts[:5]:

        plan = alert["plan"]

        message += (
            f"{alert['emoji']} {alert['direction']}\n"
            f"🪙 {alert['symbol']}\n"
            f"💰 Güncel fiyat: "
            f"{alert['price']:g}$\n\n"

            f"📥 Giriş: "
            f"{plan['entry_low']:g} - "
            f"{plan['entry_high']:g}$\n"

            f"🛑 STOP: "
            f"{plan['stop']:g}$ "
            f"(-{plan['stop_percent']:.2f}%)\n"

            f"🎯 TP1: "
            f"{plan['tp1']:g}$\n"

            f"🎯 TP2: "
            f"{plan['tp2']:g}$\n\n"

            f"💵 Ayrılacak sermaye: "
            f"${plan['position_size']:.2f}\n"

            f"⚡ Kaldıraç: "
            f"{plan['leverage']}x\n"

            f"📊 Pozisyon büyüklüğü: "
            f"${plan['notional']:.2f}\n"

            f"🔻 Stop olursa zarar: "
            f"-${plan['risk']:.2f}\n"

            f"📈 TP1 kârı: "
            f"+${plan['tp1_profit']:.2f}\n"

            f"📈 TP2 kârı: "
            f"+${plan['tp2_profit']:.2f}\n\n"

            f"📊 1s değişim: "
            f"{alert['change']:+.2f}%\n"

            f"🔥 Hacim: normalin "
            f"{alert['volume_ratio']:.1f} katı\n"

            f"⭐ Sinyal: "
            f"{alert['score']}/4\n\n"

            "⚠️ Bu bir otomatik emir değildir.\n"
            "İşlemi manuel olarak değerlendirin.\n\n"
            "━━━━━━━━━━━━━━\n\n"
        )

else:

    message = (
        "🟢 PİYASA TARAMASI TAMAMLANDI\n\n"
        f"💵 Sermaye: ${TOTAL_CAPITAL:.2f}\n"
        f"💰 İşlem bütçesi: ${TRADE_BUDGET:.2f}\n\n"
        "Şu anda belirlenen kriterleri "
        "sağlayan güçlü bir işlem sinyali "
        "tespit edilmedi.\n\n"
        "⏸️ İŞLEM YOK"
    )


# =========================
# TELEGRAM GÖNDER
# =========================

telegram_url = (
    f"https://api.telegram.org/"
    f"bot{TOKEN}/sendMessage"
)

response = session.post(
    telegram_url,
    data={
        "chat_id": CHAT_ID,
        "text": message
    },
    timeout=20
)

response.raise_for_status()

print("İşlem planlı piyasa taraması tamamlandı.")
