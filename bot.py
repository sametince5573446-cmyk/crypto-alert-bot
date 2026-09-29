import os
import requests
import statistics

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

SPOT_URL = "https://data-api.binance.vision"
FUTURES_URL = "https://fapi.binance.com"

session = requests.Session()

TOTAL_CAPITAL = 100.0
TRADE_BUDGET = 20.0
RISK_PERCENT = 1.0
MAX_ALERTS = 5


# =========================================================
# GENEL İSTEK
# =========================================================

def get_json(url, params=None):

    r = session.get(
        url,
        params=params,
        timeout=20
    )

    r.raise_for_status()

    return r.json()


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
# FUTURES VERİLERİ
# =========================================================

def get_futures_klines(symbol):

    return get_json(
        f"{FUTURES_URL}/fapi/v1/klines",
        {
            "symbol": symbol,
            "interval": "1h",
            "limit": 30
        }
    )


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

    except Exception:

        return None


def get_open_interest(symbol):

    try:

        data = get_json(
            f"{FUTURES_URL}/fapi/v1/openInterest",
            {
                "symbol": symbol
            }
        )

        return float(
            data["openInterest"]
        )

    except Exception:

        return None


# =========================================================
# EMA
# =========================================================

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
# BTC PİYASA FİLTRESİ
# =========================================================

def analyze_btc():

    try:

        candles = get_spot_klines(
            "BTCUSDT"
        )

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
                closes[-1] -
                closes[-7]
            )
            / closes[-7]
        ) * 100

        if ema9 > ema21 and price > ema9:

            direction = "YUKARI"

        elif ema9 < ema21 and price < ema9:

            direction = "AŞAĞI"

        else:

            direction = "NÖTR"

        return {
            "direction": direction,
            "price": price,
            "rsi": rsi,
            "change_6h": change_6h
        }

    except Exception:

        return None


# =========================================================
# İŞLEM PLANI
# =========================================================

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

        stop = support * 0.995

        if stop >= price:

            stop = price * (
                1 -
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
            (entry - stop)
            / entry
        ) * 100

        tp1 = entry * (
            1 +
            risk_percent * 1.5 / 100
        )

        tp2 = entry * (
            1 +
            risk_percent * 2.5 / 100
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
            risk_percent * 1.5 / 100
        )

        tp2 = entry * (
            1 -
            risk_percent * 2.5 / 100
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

    position_size = (
        max_risk /
        (risk_percent / 100)
    )

    position_size = min(
        position_size,
        TRADE_BUDGET
    )

    # Kontrollü kaldıraç
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

    tp1_profit = (
        notional *
        abs(tp1 - entry) /
        entry
    )

    tp2_profit = (
        notional *
        abs(tp2 - entry) /
        entry
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


# =========================================================
# COIN ANALİZİ
# =========================================================

def analyze_coin(
    symbol,
    btc
):

    try:

        candles = get_spot_klines(
            symbol
        )

        if len(candles) < 50:
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

        if ema9 is None or ema21 is None:
            return None

        if rsi is None:
            return None

        current_volume = volumes[-1]

        average_volume = statistics.mean(
            volumes[-21:-1]
        )

        if average_volume == 0:
            return None

        volume_ratio = (
            current_volume /
            average_volume
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
                    highs[i] -
                    lows[i]
                )
                /
                closes[i]
            ) * 100

            recent_ranges.append(
                candle_range
            )

        volatility = statistics.mean(
            recent_ranges
        )

        # =================================================
        # TEKNİK PUAN
        # =================================================

        long_score = 0
        short_score = 0

        reasons_long = []
        reasons_short = []

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

        if 50 <= rsi <= 68:

            long_score += 1

            reasons_long.append(
                f"RSI {rsi:.1f}"
            )

        if 32 <= rsi <= 50:

            short_score += 1

            reasons_short.append(
                f"RSI {rsi:.1f}"
            )

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

        # =================================================
        # FUTURES
        # =================================================

        funding = get_funding(symbol)

        open_interest = get_open_interest(
            symbol
        )

        futures_klines = get_futures_klines(
            symbol
        )

        oi_change = None

        if len(futures_klines) >= 3:

            # Futures hacmi yerine OI trendini
            # ayrıca ölçebilmek için mevcut
            # open interest bilgisini kullanıyoruz.
            # Geçmiş OI endpointi her sembolde
            # aynı şekilde erişilebilir olmayabileceği
            # için burada sadece mevcut OI gösteriliyor.
            oi_change = None

        # Funding değerlendirmesi
        funding_percent = None

        if funding is not None:

            funding_percent = (
                funding * 100
            )

            # Aşırı pozitif funding
            # LONG tarafına karşı uyarı
            if funding_percent > 0.05:

                long_score -= 1

                reasons_long.append(
                    "Funding yüksek"
                )

            # Aşırı negatif funding
            # SHORT tarafına karşı uyarı
            if funding_percent < -0.05:

                short_score -= 1

                reasons_short.append(
                    "Funding negatif"
                )

        # =================================================
        # BTC FİLTRESİ
        # =================================================

        btc_supports_long = (
            btc["direction"] == "YUKARI"
        )

        btc_supports_short = (
            btc["direction"] == "AŞAĞI"
        )

        # BTC yukarıysa LONG'a destek
        if btc_supports_long:

            long_score += 1

            reasons_long.append(
                "BTC trendi yukarı"
            )

        # BTC aşağıysa SHORT'a destek
        if btc_supports_short:

            short_score += 1

            reasons_short.append(
                "BTC trendi aşağı"
            )

        # BTC ters yöndeyse puan kır
        if btc["direction"] == "AŞAĞI":

            long_score -= 1

        if btc["direction"] == "YUKARI":

            short_score -= 1

        # =================================================
        # YÖN
        # =================================================

        if (
            long_score >= 4
            and long_score > short_score
        ):

            direction = "LONG"
            score = long_score
            reasons = reasons_long

        elif (
            short_score >= 4
            and short_score > long_score
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

        if rr < 1.3:
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
            "btc_direction": btc["direction"],
            "btc_rsi": btc["rsi"],
            "btc_change": btc["change_6h"],
            "rr": rr,
            "reasons": reasons,
            "plan": plan
        }

    except Exception:

        return None


# =========================================================
# BTC'Yİ ANALİZ ET
# =========================================================

btc = analyze_btc()

if btc is None:

    message = (
        "⚠️ BTC ANALİZİ ALINAMADI\n\n"
        "Piyasa filtresi çalışmadığı için "
        "işlem sinyali üretilmedi.\n\n"
        "⏸️ WAIT"
    )

else:

    # =====================================================
    # COINLER
    # =====================================================

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

    top_coins = usdt_coins[:40]

    alerts = []

    for coin in top_coins:

        result = analyze_coin(
            coin["symbol"],
            btc
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

    # =====================================================
    # TELEGRAM
    # =====================================================

    if alerts:

        message = (
            "🚨 KRİPTO İŞLEM PLANI 🚨\n\n"

            f"💵 Sermaye: "
            f"${TOTAL_CAPITAL:.2f}\n"

            f"💰 İşlem bütçesi: "
            f"${TRADE_BUDGET:.2f}\n\n"

            "🌐 BTC DURUMU\n"

            f"Trend: {btc['direction']}\n"

            f"RSI: {btc['rsi']:.1f}\n"

            f"6s değişim: "
            f"{btc['change_6h']:+.2f}%\n\n"

        )

        for alert in alerts[:MAX_ALERTS]:

            p = alert["plan"]

            reasons = "\n".join(
                f"• {x}"
                for x in alert["reasons"]
            )

            funding_text = (
                f"{alert['funding']:+.4f}%"
                if alert["funding"] is not None
                else "Veri yok"
            )

            oi_text = (
                f"{alert['open_interest']:,.2f}"
                if alert["open_interest"] is not None
                else "Veri yok"
            )

            message += (

                f"{'🟢' if alert['direction'] == 'LONG' else '🔴'} "
                f"{alert['direction']}\n"

                f"🪙 {alert['symbol']}\n"

                f"💰 Fiyat: "
                f"{alert['price']:g}$\n\n"

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

                f"📊 Pozisyon: "
                f"${p['notional']:.2f}\n"

                f"🔻 Stop zararı: "
                f"~${p['estimated_loss']:.2f}\n"

                f"📈 TP1 kârı: "
                f"~${p['tp1_profit']:.2f}\n"

                f"📈 TP2 kârı: "
                f"~${p['tp2_profit']:.2f}\n\n"

                "📊 TEKNİK\n"

                f"RSI: {alert['rsi']:.1f}\n"

                f"Hacim: "
                f"{alert['volume_ratio']:.1f}x\n"

                f"Risk/Getiri: "
                f"1:{alert['rr']:.2f}\n\n"

                "📊 FUTURES\n"

                f"Funding: "
                f"{funding_text}\n"

                f"Open Interest: "
                f"{oi_text}\n\n"

                "📌 NEDEN?\n"

                f"{reasons}\n\n"

                "⚠️ Otomatik emir açılmaz.\n"
                "Manuel değerlendirme içindir.\n"

                "━━━━━━━━━━━━━━\n\n"
            )

    else:

        message = (

            "🟢 PİYASA TARAMASI TAMAMLANDI\n\n"

            f"💵 Sermaye: "
            f"${TOTAL_CAPITAL:.2f}\n"

            f"💰 İşlem bütçesi: "
            f"${TRADE_BUDGET:.2f}\n\n"

            "🌐 BTC DURUMU\n"

            f"Trend: {btc['direction']}\n"

            f"
