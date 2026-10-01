import os
import json
import time
import re
import subprocess
import requests
import feedparser

BINANCE = "https://data-api.binance.vision"
BYBIT = "https://api.bybit.com"
DEX = "https://api.dexscreener.com"
GECKO = "https://api.geckoterminal.com/api/v2"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

STATE_FILE = "bot_state.json"

MAX_RISK = 2.50
START_CAPITAL = 100.0

SPECIAL_COINS = ["XVGUSDT", "QNTUSDT"]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 CryptoRadar/2.0"
})


# ============================================================
# YARDIMCI
# ============================================================

def now():
    return int(time.time())


def get_json(url, params=None, timeout=15):
    r = session.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def fmt_price(x):
    x = float(x)

    if x >= 100:
        return f"{x:.2f}"
    if x >= 1:
        return f"{x:.4f}"
    if x >= 0.01:
        return f"{x:.5f}"
    if x >= 0.0001:
        return f"{x:.7f}"

    return f"{x:.10f}"


def clamp(x, minimum, maximum):
    return max(minimum, min(maximum, x))


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secret eksik.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        r = session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "disable_web_page_preview": "true"
            },
            timeout=15
        )

        print("Telegram:", r.status_code)

    except Exception as e:
        print("Telegram hata:", repr(e))


# ============================================================
# STATE
# ============================================================

def load_state():

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:

        return {
            "binance_alerts": {},
            "solana_alerts": {},
            "last_wait": 0
        }


def save_state(state):

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2
        )


def git_save_state():

    try:

        subprocess.run(
            ["git", "config", "user.name", "crypto-radar"],
            check=False
        )

        subprocess.run(
            [
                "git",
                "config",
                "user.email",
                "crypto-radar@users.noreply.github.com"
            ],
            check=False
        )

        subprocess.run(
            ["git", "add", STATE_FILE],
            check=False
        )

        subprocess.run(
            ["git", "commit", "-m", "update radar state"],
            check=False
        )

        subprocess.run(
            ["git", "push"],
            check=False
        )

    except Exception as e:
        print("Git state hata:", repr(e))


# ============================================================
# BINANCE SPOT
# ============================================================

def binance_exchange_info():

    data = get_json(
        f"{BINANCE}/api/v3/exchangeInfo"
    )

    result = {}

    for s in data.get("symbols", []):

        if (
            s.get("status") == "TRADING"
            and s.get("quoteAsset") == "USDT"
        ):
            result[s["symbol"]] = s

    return result


def binance_tickers():

    return get_json(
        f"{BINANCE}/api/v3/ticker/24hr"
    )


def binance_klines(symbol, interval):

    return get_json(
        f"{BINANCE}/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": 80
        }
    )


# ============================================================
# TEKNİK ANALİZ
# ============================================================

def ema(values, period):

    if len(values) < period:
        return None

    value = sum(values[:period]) / period
    multiplier = 2 / (period + 1)

    for price in values[period:]:
        value = (
            (price - value) * multiplier
            + value
        )

    return value


def rsi(values, period=14):

    if len(values) <= period:
        return 50

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = values[i] - values[i - 1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):

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

    return 100 - (100 / (1 + rs))


def candle_info(klines):

    closes = [
        float(x[4])
        for x in klines
    ]

    volumes = [
        float(x[5])
        for x in klines
    ]

    e9 = ema(closes, 9)
    e21 = ema(closes, 21)

    recent_volume = sum(volumes[-5:]) / 5

    old_volume = (
        sum(volumes[-20:-5]) / 15
        if len(volumes) >= 20
        else recent_volume
    )

    volume_ratio = (
        recent_volume / old_volume
        if old_volume
        else 1
    )

    change = (
        (closes[-1] - closes[-5])
        / closes[-5]
        * 100
    )

    return {
        "close": closes[-1],
        "ema9": e9,
        "ema21": e21,
        "rsi": rsi(closes),
        "volume_ratio": volume_ratio,
        "change": change,
        "high20": max(
            float(x[2])
            for x in klines[-20:]
        ),
        "low20": min(
            float(x[3])
            for x in klines[-20:]
        )
    }


def technical_signal(h1, h4):

    score = 0
    reasons = []

    bull1 = h1["ema9"] > h1["ema21"]
    bull4 = h4["ema9"] > h4["ema21"]

    bear1 = h1["ema9"] < h1["ema21"]
    bear4 = h4["ema9"] < h4["ema21"]

    if bull1 and bull4:

        direction = "LONG"

        score += 3

        reasons.append(
            "1H + 4H trend yukarı"
        )

    elif bear1 and bear4:

        direction = "SHORT"

        score += 3

        reasons.append(
            "1H + 4H trend aşağı"
        )

    else:

        return "WAIT", 0, [
            "1H ve 4H trend uyuşmuyor"
        ]

    # RSI

    if direction == "LONG":

        if 52 <= h1["rsi"] <= 68:

            score += 1

            reasons.append(
                "RSI yükselişi destekliyor"
            )

        elif h1["rsi"] > 75:

            score -= 1

            reasons.append(
                "RSI fazla yükselmiş"
            )

    if direction == "SHORT":

        if 32 <= h1["rsi"] <= 48:

            score += 1

            reasons.append(
                "RSI düşüşü destekliyor"
            )

        elif h1["rsi"] < 25:

            score -= 1

            reasons.append(
                "RSI fazla düşmüş"
            )

    # HACİM

    if h1["volume_ratio"] >= 1.5:

        score += 2

        reasons.append(
            "Hacim belirgin artıyor"
        )

    elif h1["volume_ratio"] >= 1.15:

        score += 1

        reasons.append(
            "Hacim destekliyor"
        )

    # MOMENTUM

    if direction == "LONG" and h1["change"] > 0:

        score += 1

        reasons.append(
            "Momentum alıcı tarafında"
        )

    elif direction == "SHORT" and h1["change"] < 0:

        score += 1

        reasons.append(
            "Momentum satıcı tarafında"
        )

    return direction, score, reasons


# ============================================================
# BYBIT FUTURES PROXY
# ============================================================

def bybit_request(path, params):

    return get_json(
        f"{BYBIT}{path}",
        params
    )


def bybit_kline(symbol, interval):

    try:

        data = bybit_request(
            "/v5/market/kline",
            {
                "category": "linear",
                "symbol": symbol,
                "interval": interval,
                "limit": 50
            }
        )

        if data.get("retCode") != 0:
            return None

        rows = data["result"]["list"]

        rows.reverse()

        return [
            [
                x[0],
                x[1],
                x[2],
                x[3],
                x[4],
                x[5]
            ]
            for x in rows
        ]

    except Exception:
        return None


def bybit_funding(symbol):

    try:

        data = bybit_request(
            "/v5/market/funding/history",
            {
                "category": "linear",
                "symbol": symbol,
                "limit": 1
            }
        )

        rows = data["result"]["list"]

        if not rows:
            return 0

        return float(
            rows[0].get(
                "fundingRate",
                0
            )
        )

    except Exception:
        return 0


def bybit_oi(symbol):

    try:

        data = bybit_request(
            "/v5/market/open-interest",
            {
                "category": "linear",
                "symbol": symbol,
                "intervalTime": "1h",
                "limit": 3
            }
        )

        rows = data["result"]["list"]

        if len(rows) < 2:
            return 0

        newest = float(
            rows[0]["openInterest"]
        )

        oldest = float(
            rows[-1]["openInterest"]
        )

        if oldest == 0:
            return 0

        return (
            (newest - oldest)
            / oldest
            * 100
        )

    except Exception:
        return 0


def bybit_derivatives(symbol):

    try:

        k1 = bybit_kline(
            symbol,
            "60"
        )

        k4 = bybit_kline(
            symbol,
            "240"
        )

        if not k1 or not k4:

            return {
                "available": False,
                "direction": "UNKNOWN",
                "funding": 0,
                "oi": 0
            }

        h1 = candle_info(k1)
        h4 = candle_info(k4)

        if (
            h1["ema9"] > h1["ema21"]
            and
            h4["ema9"] > h4["ema21"]
        ):
            direction = "LONG"

        elif (
            h1["ema9"] < h1["ema21"]
            and
            h4["ema9"] < h4["ema21"]
        ):
            direction = "SHORT"

        else:
            direction = "NEUTRAL"

        return {
            "available": True,
            "direction": direction,
            "funding": bybit_funding(symbol),
            "oi": bybit_oi(symbol)
        }

    except Exception:

        return {
            "available": False,
            "direction": "UNKNOWN",
            "funding": 0,
            "oi": 0
        }


# ============================================================
# HABER
# ============================================================

RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss"
]


def clean_html(text):

    text = re.sub(
        r"<[^>]+>",
        " ",
        text or ""
    )

    return re.sub(
        r"\s+",
        " ",
        text
    ).strip()


def coin_news(symbol):

    coin = symbol.replace(
        "USDT",
        ""
    ).upper()

    results = []

    for feed_url in RSS_FEEDS:

        try:

            feed = feedparser.parse(
                feed_url
            )

            for item in feed.entries[:30]:

                title = clean_html(
                    item.get(
                        "title",
                        ""
                    )
                )

                summary = clean_html(
                    item.get(
                        "summary",
                        ""
                    )
                )

                text = (
                    title
                    + " "
                    + summary
                ).upper()

                if (
                    coin in text
                    or f"${coin}" in text
                ):

                    results.append(title)

                if len(results) >= 2:
                    break

        except Exception:
            pass

        if len(results) >= 2:
            break

    if not results:

        return (
            "Coin'e özel güncel "
            "haber bulunamadı."
        )

    return " | ".join(
        results[:2]
    )


def news_effect(news):

    upper = news.upper()

    negative = [
        "HACK",
        "EXPLOIT",
        "SCAM",
        "SECURITY",
        "LAWSUIT",
        "DELIST",
        "ATTACK",
        "VULNERABILITY"
    ]

    positive = [
        "PARTNERSHIP",
        "LAUNCH",
        "LISTING",
        "ADOPTION",
        "UPGRADE",
        "MAINNET",
        "INTEGRATION",
        "ETF"
    ]

    if any(x in upper for x in negative):
        return -2

    if any(x in upper for x in positive):
        return 1

    return 0


# ============================================================
# İŞLEM HESAPLAMA
# ============================================================

def build_trade(
    symbol,
    price,
    direction,
    score,
    h1,
    deriv,
    reasons
):

    if direction not in [
        "LONG",
        "SHORT"
    ]:
        return None

    # Güce göre kaldıraç

    if score >= 9:

        leverage = 10
        target_budget = 40

    elif score >= 8:

        leverage = 8
        target_budget = 35

    elif score >= 7:

        leverage = 6
        target_budget = 30

    elif score >= 6:

        leverage = 5
        target_budget = 20

    else:

        leverage = 3
        target_budget = 10

    # Volatilite

    range_pct = (
        h1["high20"]
        - h1["low20"]
    ) / price

    if range_pct > 0.12:

        leverage = 3

    elif range_pct > 0.08:

        leverage = min(
            leverage,
            5
        )

    stop_pct = clamp(
        range_pct * 0.35,
        0.012,
        0.07
    )

    if direction == "LONG":

        entry = price

        stop = (
            entry
            * (1 - stop_pct)
        )

        tp1 = (
            entry
            * (1 + stop_pct * 1.4)
        )

        tp2 = (
            entry
            * (1 + stop_pct * 2.2)
        )

    else:

        entry = price

        stop = (
            entry
            * (1 + stop_pct)
        )

        tp1 = (
            entry
            * (1 - stop_pct * 1.4)
        )

        tp2 = (
            entry
            * (1 - stop_pct * 2.2)
        )

    # Maksimum yaklaşık $2.50 risk

    risk_ratio = abs(
        entry - stop
    ) / entry

    budget = min(
        target_budget,
        START_CAPITAL
    )

    if risk_ratio > 0:

        max_budget = (
            MAX_RISK
            / (
                risk_ratio
                * leverage
            )
        )

        budget = min(
            budget,
            max_budget
        )

    if budget < 5:
        return None

    # Bybit futures teyidi

    if deriv["available"]:

        if (
            deriv["direction"]
            == direction
        ):

            score += 1

            reasons.append(
                "Futures yönü destekliyor"
            )

        elif (
            deriv["direction"]
            in ["LONG", "SHORT"]
            and
            deriv["direction"]
            != direction
        ):

            score -= 1

            reasons.append(
                "Futures yönü ters"
            )

        if abs(
            deriv["oi"]
        ) >= 3:

            reasons.append(
                "Open Interest hareketli"
            )

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "leverage": leverage,
        "budget": budget,
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "loss": (
            budget
            * risk_ratio
            * leverage
        ),
        "profit1": (
            budget
            * abs(tp1 - entry)
            / entry
            * leverage
        ),
        "profit2": (
            budget
            * abs(tp2 - entry)
            / entry
            * leverage
        ),
        "reasons": reasons[:5]
    }


def strength(score):

    if score >= 7:
        return "🚀 ÇOK GÜÇLÜ"

    if score >= 6:
        return "🟢 GÜÇLÜ"

    return "🟡 ORTA GÜÇLÜ"


def format_trade(trade, news):

    lines = [

        "🚨 BINANCE RADAR",
        "",
        f"🪙 {trade['symbol']}",
        (
            f"📌 {trade['direction']} | "
            f"{strength(trade['score'])}"
        ),
        "",
        f"💰 Bütçe: ${trade['budget']:.2f}",
        f"⚙️ Kaldıraç: {trade['leverage']}x",
        "",
        f"🎯 Giriş: {fmt_price(trade['entry'])}",
        f"🛑 Stop: {fmt_price(trade['stop'])}",
        f"🎯 TP1: {fmt_price(trade['tp1'])}",
        f"🎯 TP2: {fmt_price(trade['tp2'])}",
        "",
        (
            f"❌ Tahmini zarar: "
            f"${trade['loss']:.2f}"
        ),
        (
            f"💵 TP1 kârı: "
            f"${trade['profit1']:.2f}"
        ),
        (
            f"💵 TP2 kârı: "
            f"${trade['profit2']:.2f}"
        ),
        "",
        "Neden:"
    ]

    for reason in trade["reasons"]:

        lines.append(
            f"• {reason}"
        )

    lines += [
        "",
        "📰 Coin haberi:",
        news[:500],
        "",
        (
            "⚠️ Otomatik işlem yapmaz. "
            "Manuel değerlendirme gerekir."
        )
    ]

    return "\n".join(lines)


# ============================================================
# BINANCE RADAR
# ============================================================

def binance_radar(state):

    print(
        "BINANCE RADAR BAŞLIYOR"
    )
    print(
        "-----------------------"
    )

    info = binance_exchange_info()
    tickers = binance_tickers()

    ticker_map = {}

    for x in tickers:

        symbol = x.get(
            "symbol"
        )

        if symbol in info:

            ticker_map[
                symbol
            ] = x

    candidates = []

    for symbol, x in ticker_map.items():

        try:

            price = float(
                x["lastPrice"]
            )

            change = float(
                x["priceChangePercent"]
            )

            volume = float(
                x["quoteVolume"]
            )

            if price <= 0:
                continue

            # +30 / -30 üstünü alma

            if abs(change) > 30:
                continue

            # Düşük hacimli coinleri alma

            if volume < 500000:
                continue

            candidates.append({
                "symbol": symbol,
                "price": price,
                "change": change,
                "volume": volume
            })

        except Exception:
            continue

    candidates.sort(
        key=lambda x: x["volume"],
        reverse=True
    )

    candidates = candidates[:100]

    # XVG ve QNT mutlaka ekleniyor

    for special in SPECIAL_COINS:

        if (
            special in ticker_map
            and
            not any(
                x["symbol"] == special
                for x in candidates
            )
        ):

            x = ticker_map[special]

            try:

                change = float(
                    x["priceChangePercent"]
                )

                if abs(change) <= 30:

                    candidates.append({
                        "symbol": special,
                        "price": float(
                            x["lastPrice"]
                        ),
                        "change": change,
                        "volume": float(
                            x["quoteVolume"]
                        )
                    })

            except Exception:
                pass

    alerts = []

    for index, coin in enumerate(
        candidates
    ):

        symbol = coin["symbol"]

        try:

            # Binance spot 1H

            k1 = binance_klines(
                symbol,
                "1h"
            )

            # Binance spot 4H

            k4 = binance_klines(
                symbol,
                "4h"
            )

            if not k1 or not k4:
                continue

            h1 = candle_info(k1)
            h4 = candle_info(k4)

            direction, score, reasons = (
                technical_signal(
                    h1,
                    h4
                )
            )

            if direction == "WAIT":
                continue

            # XVG / QNT önceliği

            if symbol in SPECIAL_COINS:

                score += 1

                reasons.append(
                    "Özel takip listesinde"
                )

            # Futures proxy sadece
            # teknik olarak adaylarda

            deriv = {
                "available": False,
                "direction": "UNKNOWN",
                "funding": 0,
                "oi": 0
            }

            if score >= 4:

                deriv = (
                    bybit_derivatives(
                        symbol
                    )
                )

            news = coin_news(
                symbol
            )

            effect = news_effect(
                news
            )

            if effect > 0:

                score += 1

                reasons.append(
                    "Olumlu coin haberi bulundu"
                )

            elif effect < 0:

                score -= 2

                reasons.append(
                    "Coin için risk haberi bulundu"
                )

            # 6 altı sinyal yok

            if score < 6:
                continue

            trade = build_trade(
                symbol,
                coin["price"],
                direction,
                score,
                h1,
                deriv,
                reasons
            )

            if not trade:
                continue

            # Aynı coin 1 saat tekrar yok

            last = state[
                "binance_alerts"
            ].get(
                symbol,
                0
            )

            if (
                now() - last
                < 3600
            ):
                continue

            alerts.append(
                (
                    trade,
                    news
                )
            )

            if len(alerts) >= 3:
                break

        except Exception as e:

            print(
                "Binance aday hata:",
                symbol,
                repr(e)
            )

    for trade, news in alerts:

        telegram(
            format_trade(
                trade,
                news
            )
        )

        state[
            "binance_alerts"
        ][
            trade["symbol"]
        ] = now()

    # Saatlik WAIT

    if (
        not alerts
        and
        now()
        - state.get(
            "last_wait",
            0
        )
        >= 3600
    ):

        telegram(
            "🟡 BINANCE RADAR\n\n"
            "Yeterince güçlü ve "
            "teyitli fırsat bulunamadı.\n\n"
            "Karar: WAIT ⏳"
        )

        state["last_wait"] = now()

    print(
        f"Binance: "
        f"{len(candidates)} aday, "
        f"{len(alerts)} alarm."
    )

    return state


# ============================================================
# SOLANA RADAR
# ============================================================

def solana_profiles():

    try:

        return get_json(
            f"{DEX}/token-profiles/latest/v1"
        )

    except Exception:

        return []


def solana_boosts():

    try:

        return get_json(
            f"{DEX}/token-boosts/latest/v1"
        )

    except Exception:

        return []


def new_solana_pools():

    try:

        data = get_json(
            f"{GECKO}/networks/solana/new_pools"
        )

        return data.get(
            "data",
            []
        )

    except Exception:

        return []


def solana_candidates():

    result = {}

    for x in solana_profiles():

        address = x.get(
            "tokenAddress"
        )

        if address:
            result[address] = True

    for x in solana_boosts():

        address = x.get(
            "tokenAddress"
        )

        if address:
            result[address] = True

    for x in new_solana_pools()[:50]:

        address = (
            x.get("attributes", {})
            .get("address")
        )

        if address:
            result[address] = True

    return list(result.keys())[:60]


def get_solana_pair(address):

    try:

        data = get_json(
            f"{DEX}/latest/dex/pairs/solana/{address}"
        )

        pairs = (
            data.get("pairs")
            or []
        )

        if not pairs:
            return None

        # TEK pair kullan.
        # Veriyi farklı pairlerden karıştırma.

        return pairs[0]

    except Exception:

        return None


def check_solana(pair):

    try:

        changes = (
            pair.get(
                "priceChange"
            )
            or {}
        )

        volumes = (
            pair.get(
                "volume"
            )
            or {}
        )

        txns = (
            pair.get(
                "txns"
            )
            or {}
        )

        liquidity = (
            pair.get(
                "liquidity"
            )
            or {}
        )

        p5 = changes.get(
            "m5"
        )

        p1h = changes.get(
            "h1"
        )

        p24 = changes.get(
            "h24"
        )

        if p5 is None or p1h is None:
            return None

        p5 = float(p5)
        p1h = float(p1h)
        p24 = float(p24 or 0)

        liq = float(
            liquidity.get(
                "usd"
            )
            or 0
        )

        volume5 = float(
            volumes.get(
                "m5"
            )
            or 0
        )

        volume1h = float(
            volumes.get(
                "h1"
            )
            or 0
        )

        # Yetersiz likidite

        if liq < 15000:
            return None

        # Zaten çok pompalanmış

        if p24 >= 40:
            return None

        if p1h >= 25:
            return None

        # Sert düşüşte erken fırsat deme

        if p5 <= -10:
            return None

        five = (
            txns.get("m5")
            or {}
        )

        buys = int(
            five.get(
                "buys",
                0
            )
            or 0
        )

        sells = int(
            five.get(
                "sells",
                0
            )
            or 0
        )

        total = buys + sells

        if total < 20:
            return None

        buy_ratio = (
            buys / total
        )

        if buy_ratio < 0.56:
            return None

        # Hacim hızlanması

        acceleration = 0

        if volume1h > 0:

            acceleration = (
                volume5
                * 12
                / volume1h
            )

        if acceleration < 0.6:
            return None

        score = 0
        reasons = []

        if 0 <= p5 <= 5:

            score += 1

            reasons.append(
                "Henüz aşırı yükselmemiş"
            )

        elif 5 < p5 <= 15:

            score += 2

            reasons.append(
                "Kısa vadeli hareket başladı"
            )

        if p1h > 0:

            score += 1

            reasons.append(
                "1 saatlik hareket pozitif"
            )

        if buy_ratio >= 0.60:

            score += 2

            reasons.append(
                "Alıcılar belirgin üstün"
            )

        if acceleration >= 1:

            score += 2

            reasons.append(
                "Hacim hızlanıyor"
            )

        if liq >= 30000:

            score += 1

            reasons.append(
                "Likidite daha yeterli"
            )

        if score < 6:
            return None

        return {
            "pair": pair,
            "score": score,
            "reasons": reasons
        }

    except Exception:

        return None


def format_solana(alert):

    pair = alert["pair"]

    symbol = (
        pair.get(
            "baseToken",
            {}
        )
        .get(
            "symbol",
            "?"
        )
    )

    change = (
        pair.get(
            "priceChange",
            {}
        )
    )

    liquidity = float(
        (
            pair.get(
                "liquidity"
            )
            or {}
        )
        .get(
            "usd",
            0
        )
        or 0
    )

    return (
        "🟣 SOLANA ERKEN HAREKET RADARI\n\n"
        f"🪙 {symbol}\n"
        f"📊 5m: {change.get('m5')}%\n"
        f"📊 1h: {change.get('h1')}%\n"
        f"💧 Likidite: ${liquidity:,.0f}\n"
        f"⭐ Skor: {alert['score']}/10\n\n"
        "Neden:\n"
        +
        "\n".join(
            f"• {x}"
            for x in alert["reasons"]
        )
        +
        "\n\n"
        f"Pair: {pair.get('pairAddress', '')}\n\n"
        "⚠️ Erken hareket tespiti "
        "kesin yükseliş garantisi değildir."
    )


def solana_radar(state):

    print(
        "SOLANA RADAR BAŞLIYOR"
    )

    candidates = (
        solana_candidates()
    )

    alerts = []
    checked = 0

    for address in candidates:

        try:

            pair = get_solana_pair(
                address
            )

            if not pair:
                continue

            checked += 1

            alert = check_solana(
                pair
            )

            if not alert:
                continue

            pair_address = pair.get(
                "pairAddress"
            )

            if not pair_address:
                continue

            last = state[
                "solana_alerts"
            ].get(
                pair_address,
                0
            )

            if (
                now() - last
                < 86400
            ):
                continue

            alerts.append(
                alert
            )

            state[
                "solana_alerts"
            ][
                pair_address
            ] = now()

            if len(alerts) >= 3:
                break

        except Exception as e:

            print(
                "Solana hata:",
                repr(e)
            )

    for alert in alerts:

        telegram(
            format_solana(
                alert
            )
        )

    print(
        f"Solana: "
        f"{len(candidates)} aday, "
        f"{checked} pair incelendi, "
        f"{len(alerts)} alarm."
    )

    return state


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "======================="
    )

    print(
        "BINANCE + SOLANA RADAR"
    )

    print(
        "======================="
    )

    state = load_state()

    try:

        state = binance_radar(
            state
        )

    except Exception as e:

        print(
            "BINANCE RADAR ERROR:",
            repr(e)
        )

        telegram(
            "⚠️ BINANCE RADAR HATA\n\n"
            "Binance spot veri kaynağına "
            "erişilemedi.\n"
            "GitHub Actions logunu kontrol et."
        )

    try:

        state = solana_radar(
            state
        )

    except Exception as e:

        print(
            "SOLANA RADAR ERROR:",
            repr(e)
        )

    save_state(state)

    git_save_state()

    print(
        "======================="
    )

    print(
        "BOT TAMAMLANDI"
    )

    print(
        "======================="
    )


if __name__ == "__main__":
    main()
