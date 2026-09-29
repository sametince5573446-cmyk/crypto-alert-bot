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

TOTAL_CAPITAL = 100.0

# Tek işlemde kullanılacak sermaye
TRADE_BUDGET = 20.0

# Maksimum kabul edilen sermaye riski
RISK_PERCENT = 1.0

# Aynı anda en fazla 5 sinyal gönder
MAX_ALERTS = 5


# =========================
# BINANCE
# =========================

def get_24h_tickers():

    url = f"{BASE_URL}/api/v3/ticker/24hr"

    r = session.get(url, timeout=20)
    r.raise_for_status()

    return r.json()


def get_klines(symbol):

    url = f"{BASE_URL}/api/v3/klines"

    params = {
        "symbol": symbol,
        "interval": "1h",
        "limit": 100
    }

    r = session.get(
        url,
        params=params,
        timeout=20
    )

    r.raise_for_status()

    return r.json()


# =========================
# EMA
# =========================

def calculate_ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    ema = statistics.mean(
        values[:period]
    )

    for price in values[period:]:

        ema = (
            (price - ema)
            * multiplier
        ) + ema

    return ema


# =========================
# RSI
# =========================

def calculate_rsi(values, period=14):

    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = (
            values[i] -
            values[i - 1]
        )

        if change > 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(abs(change))

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
            (avg_gain * (period - 1))
            + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1))
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


# =========================
# İŞLEM PLANI
# =========================

def create_trade_plan(
    direction,
    price,
    support,
    resistance,
    volatility
):

    max_risk = (
        TOTAL_CAPITAL *
        RISK_PERCENT /
        100
    )

    if direction == "LONG":

        # Stop desteğin biraz altında
        stop = support * 0.995

        # Desteğin çok yakın olması durumunda
        if stop >= price:

            stop = price * (
                1 - max(
                    volatility * 0.8,
                    1.5
                ) / 100
            )

        entry_low = price * 0.997
        entry_high = price * 1.003

        entry = (
            entry_low +
            entry_high
        ) / 2

        risk_percent = (
            (entry - stop)
            / entry
        ) * 100

        # İlk hedef riskin 1.5 katı
        tp1 = entry * (
            1 +
            (risk_percent * 1.5)
            / 100
        )

        # İkinci hedef riskin 2.5 katı
        tp2 = entry * (
            1 +
            (risk_percent * 2.5)
            / 100
        )

        # Direnci aşırı geçmesin
        if resistance > entry:

            tp1 = min(
                tp1,
                resistance * 0.995
            )

            tp2 = max(
                tp1 * 1.01,
                min(
                    tp2,
                    resistance * 1.02
                )
            )

    else:

        # SHORT
        stop = resistance * 1.005

        if stop <= price:

            stop = price * (
                1 +
                max(
                    volatility * 0.8,
                    1.5
                ) / 100
            )

        entry_low = price * 0.997
        entry_high = price * 1.003

        entry = (
            entry_low +
            entry_high
        ) / 2

        risk_percent = (
            (stop - entry)
            / entry
        ) * 100

        tp1 = entry * (
            1 -
            (risk_percent * 1.5)
            / 100
        )

        tp2 = entry * (
            1 -
            (risk_percent * 2.5)
            / 100
        )

        if support < entry:

            tp1 = max(
                tp1,
                support * 1.005
            )

            tp2 = min(
                tp1 * 0.99,
                max(
                    tp2,
                    support * 0.98
                )
            )

    if risk_percent <= 0:
        return None

    # Risk bazlı pozisyon büyüklüğü
    position_size = (
        max_risk /
        (risk_percent / 100)
    )

    # Tek işlem bütçesini geçme
    position_size = min(
        position_size,
        TRADE_BUDGET
    )

    # Şimdilik kontrollü kaldıraç
    leverage = 1

    if risk_percent <= 2:

        leverage = 3

    elif risk_percent <= 3:

        leverage = 2

    else:

        leverage = 1

    notional = (
        position_size *
        leverage
    )

    estimated_loss = (
        notional *
        risk_percent /
        100
    )

    tp1_percent = abs(
        tp1 - entry
    ) / entry * 100

    tp2_percent = abs(
        tp2 - entry
    ) / entry * 100

    tp1_profit = (
        notional *
        tp1_percent /
        100
    )

    tp2_profit = (
        notional *
        tp2_percent /
        100
    )

    return {
        "entry_low": entry_low,
        "entry_high": entry_high,
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "risk_percent": risk_percent,
        "position_size": position_size,
        "leverage": leverage,
        "notional": notional,
        "estimated_loss": estimated_loss,
        "tp1_profit": tp1_profit,
        "tp2_profit": tp2_profit
    }


# =========================
# COIN ANALİZİ
# =========================

def analyze_coin(symbol):

    try:

        candles = get_klines(symbol)

        if len(candles) < 50:
            return None

        # Son KAPANMIŞ mum
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

        # EMA
        ema9 = calculate_ema(
            closes,
            9
        )

        ema21 = calculate_ema(
            closes,
            21
        )

        # RSI
        rsi = calculate_rsi(
            closes,
            14
        )

        if ema9 is None or ema21 is None:
            return None

        if rsi is None:
            return None

        # Hacim
        current_volume = volumes[-1]

        previous_volumes = volumes[-21:-1]

        average_volume = statistics.mean(
            previous_volumes
        )

        if average_volume == 0:
            return None

        volume_ratio = (
            current_volume /
            average_volume
        )

        # Son 20 mumdan destek / direnç
        support = min(
            lows[-20:]
        )

        resistance = max(
            highs[-20:]
        )

        # Volatilite
        recent_ranges = []

        for i in range(
            -20,
            0
        ):

            candle_range = (
                (highs[i] - lows[i])
                / closes[i]
            ) * 100

            recent_ranges.append(
                candle_range
            )

        volatility = statistics.mean(
            recent_ranges
        )

        # =====================
        # PUANLAMA
        # =====================

        long_score = 0
        short_score = 0

        reasons_long = []
        reasons_short = []

        # EMA TREND
        if ema9 > ema21:

            long_score += 1
            reasons_long.append(
                "EMA9 > EMA21"
            )

        if ema9 < ema21:

            short_score += 1
            reasons_short.append(
                "EMA9 < EMA21"
            )

        # FİYAT EMA ÜZERİNDE
        if price > ema9:

            long_score += 1
            reasons_long.append(
                "Fiyat EMA9 üzerinde"
            )

        if price < ema9:

            short_score += 1
            reasons_short.append(
                "Fiyat EMA9 altında"
            )

        # RSI
        if 50 <= rsi <= 68:

            long_score += 1
            reasons_long.append(
                f"RSI uygun ({rsi:.1f})"
            )

        if 32 <= rsi <= 50:

            short_score += 1
            reasons_short.append(
                f"RSI uygun ({rsi:.1f})"
            )

        # HACİM
        if volume_ratio >= 1.5:

            if price > ema9:

                long_score += 1
                reasons_long.append(
                    f"Hacim {volume_ratio:.1f}x"
                )

            elif price < ema9:

                short_score += 1
                reasons_short.append(
                    f"Hacim {volume_ratio:.1f}x"
                )

        # =====================
        # YÖN BELİRLE
        # =====================

        if (
            long_score >= 3 and
            long_score > short_score
        ):

            direction = "LONG"
            score = long_score
            reasons = reasons_long

        elif (
            short_score >= 3 and
            short_score > long_score
        ):

            direction = "SHORT"
            score = short_score
            reasons = reasons_short

        else:

            return None

        plan = create_trade_plan(
            direction,
            price,
            support,
            resistance,
            volatility
        )

        if plan is None:
            return None

        # Risk/Getiri kontrolü
        risk = abs(
            plan["entry"] -
            plan["stop"]
        )

        reward = abs(
            plan["tp1"] -
            plan["entry"]
        )

        if risk == 0:
            return None

        rr = reward / risk

        # TP1 için en az 1.3 R
        if rr < 1.3:
            return None

        return {
            "symbol": symbol,
            "price": price,
            "direction": direction,
            "score": score,
            "rsi": rsi,
            "volume_ratio": volume_ratio,
            "ema9": ema9,
            "ema21": ema21,
            "support": support,
            "resistance": resistance,
            "rr": rr,
            "reasons": reasons,
            "plan": plan
        }

    except Exception:

        return None


# =========================
# PİYASA TARAMASI
# =========================

tickers = get_24h_tickers()

stablecoins = {
    "USDCUSDT",
    "FDUSDUSDT",
    "TUSDUSDT",
    "USDPUSDT",
    "DAIUSDT"
}

usdt_coins = [
    x for x in tickers
    if x["symbol"].endswith("USDT")
    and x["symbol"] not in stablecoins
]

usdt_coins.sort(
    key=lambda x: float(
        x["quoteVolume"]
    ),
    reverse=True
)

# Yüksek hacimli ilk 40 coin
top_coins = usdt_coins[:40]

alerts = []

for coin in top_coins:

    result = analyze_coin(
        coin["symbol"]
    )

    if result:
        alerts.append(result)


alerts.sort(
    key=lambda x: (
        x["score"],
        x["rr"],
        x["volume_ratio"]
    ),
    reverse=True
)


# =========================
# TELEGRAM
# =========================

if alerts:

    message = (
        "🚨 KRİPTO İŞLEM PLANI 🚨\n\n"
        f"💵 Sermaye: ${TOTAL_CAPITAL:.2f}\n"
        f"💰 İşlem bütçesi: ${TRADE_BUDGET:.2f}\n\n"
    )

    for alert in alerts[:MAX_ALERTS]:

        p = alert["plan"]

        reasons = "\n".join(
            f"• {x}"
            for x in alert["reasons"]
        )

        message += (
            f"{'🟢' if alert['direction'] == 'LONG' else '🔴'} "
            f"{alert['direction']}\n"
            f"🪙 {alert['symbol']}\n"
            f"💰 Fiyat: {alert['price']:g}$\n\n"

            f"📥 GİRİŞ\n"
            f"{p['entry_low']:g} - "
            f"{p['entry_high']:g}$\n\n"

            f"🛑 STOP\n"
            f"{p['stop']:g}$ "
            f"(-{p['risk_percent']:.2f}%)\n\n"

            f"🎯 TP1\n"
            f"{p['tp1']:g}$\n\n"

            f"🎯 TP2\n"
            f"{p['tp2']:g}$\n\n"

            f"💵 Ayrılan sermaye: "
            f"${p['position_size']:.2f}\n"

            f"⚡ Kaldıraç: "
            f"{p['leverage']}x\n"

            f"📊 Pozisyon büyüklüğü: "
            f"${p['notional']:.2f}\n"

            f"🔻 Stop zararı: "
            f"~${p['estimated_loss']:.2f}\n"

            f"📈 TP1 kârı: "
            f"~${p['tp1_profit']:.2f}\n"

            f"📈 TP2 kârı: "
            f"~${p['tp2_profit']:.2f}\n\n"

            f"📊 RSI: {alert['rsi']:.1f}\n"
            f"🔥 Hacim: {alert['volume_ratio']:.1f}x\n"
            f"📐 Risk/Getiri: "
            f"1:{alert['rr']:.2f}\n"
            f"⭐ Sinyal: "
            f"{alert['score']}/4\n\n"

            f"📌 NEDEN?\n"
            f"{reasons}\n\n"

            "⚠️ Otomatik emir açılmaz.\n"
            "İşlem manuel değerlendirilmelidir.\n"

            "━━━━━━━━━━━━━━\n\n"
        )

else:

    message = (
        "🟢 PİYASA TARAMASI TAMAMLANDI\n\n"
        f"💵 Sermaye: ${TOTAL_CAPITAL:.2f}\n"
        f"💰 İşlem bütçesi: ${TRADE_BUDGET:.2f}\n\n"

        "EMA + RSI + hacim + "
        "destek/direnç + risk/getiri "
        "kriterlerini sağlayan yeterince "
        "güçlü bir sinyal bulunamadı.\n\n"

        "⏸️ WAIT — İŞLEM YOK"
    )


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

print("Gelişmiş piyasa taraması tamamlandı.")
