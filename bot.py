import os, json, time
from xml.etree import ElementTree as ET
import requests

# ============================================================
# BINANCE + SOLANA RADAR
# Sadece analiz/uyarı üretir. OTOMATİK İŞLEM AÇMAZ.
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

BINANCE_SPOT = "https://data-api.binance.vision"
BINANCE_FAPI = "https://fapi.binance.com"
DEX = "https://api.dexscreener.com"
GECKO = "https://api.geckoterminal.com/api/v2"

CAPITAL = 100.0
MAX_RISK = 2.50
MAX_BINANCE_COINS = 100

SPECIAL = ["XVGUSDT", "QNTUSDT"]

# WAIT mesajı her taramada değil, en fazla saatte 1 kez.
WAIT_EVERY_MINUTES = 60

# Aynı Binance coininde tekrar sinyal için bekleme.
BINANCE_REPEAT_MINUTES = 60

# Solana aynı token için tekrar alarm bekleme.
SOL_REPEAT_HOURS = 24

STATE_FILE = "bot_state.json"


# ------------------------------------------------------------
# GENEL
# ------------------------------------------------------------

def get_json(url, params=None, timeout=15):
    r = requests.get(
        url,
        params=params,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    r.raise_for_status()
    return r.json()


def telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secret eksik.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        r = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text
            },
            timeout=15
        )
        print("Telegram:", r.status_code)
        return r.ok
    except Exception as e:
        print("Telegram ERROR:", e)
        return False


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "last_wait": 0,
            "binance_alerts": {},
            "sol_alerts": {}
        }


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def commit_state():
    """
    GitHub Actions permissions: contents: write gerekli.
    State dosyasını repo'ya kaydeder.
    """
    os.system('git config user.name "crypto-alert-bot"')
    os.system('git config user.email "crypto-alert-bot@users.noreply.github.com"')
    os.system("git add bot_state.json")
    result = os.system('git diff --cached --quiet')
    if result != 0:
        os.system('git commit -m "Update radar state"')
        os.system("git push")
    else:
        print("State değişmedi.")


# ------------------------------------------------------------
# TEKNİK İNDİKATÖRLER
# ------------------------------------------------------------

def ema(values, period):
    if len(values) < period:
        return None

    k = 2 / (period + 1)
    value = sum(values[:period]) / period

    for x in values[period:]:
        value = x * k + value * (1 - k)

    return value


def rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def fmt_price(price):
    if price >= 100:
        return f"{price:.2f}"
    if price >= 1:
        return f"{price:.4f}"
    if price >= 0.01:
        return f"{price:.6f}"
    return f"{price:.8f}"


def levels(price, side, stop_pct):
    stop_pct = max(0.015, min(stop_pct, 0.05))

    if side in ("LONG", "SPOT"):
        stop = price * (1 - stop_pct)
        tp1 = price * (1 + stop_pct * 1.5)
        tp2 = price * (1 + stop_pct * 2.5)

    else:  # SHORT
        stop = price * (1 + stop_pct)
        tp1 = price * (1 - stop_pct * 1.5)
        tp2 = price * (1 - stop_pct * 2.5)

    return stop, tp1, tp2, stop_pct


def budget_for(score, stop_pct, side):
    """
    Binance:
    SPOT -> kaldıraç yok.
    LONG/SHORT -> minimum 3x.
    Maksimum planlanan zarar yaklaşık $2.50.
    """

    if side == "SPOT":
        target = 20 if score >= 7 else 10
        budget = min(
            target,
            CAPITAL,
            MAX_RISK / max(stop_pct, 0.01)
        )
        return 1, round(budget, 2)

    leverage = 3
    target = 10

    if score >= 9:
        leverage, target = 10, 40
    elif score >= 8:
        leverage, target = 8, 35
    elif score >= 7:
        leverage, target = 6, 30
    elif score >= 6:
        leverage, target = 5, 20

    if stop_pct > 0.035:
        leverage = min(leverage, 5)

    if stop_pct > 0.045:
        leverage = 3

    # budget = margin.
    # zarar = margin x kaldıraç x stop yüzdesi
    max_by_risk = MAX_RISK / max(stop_pct * leverage, 0.01)

    budget = min(
        target,
        CAPITAL,
        max_by_risk
    )

    return leverage, round(budget, 2)


# ------------------------------------------------------------
# BINANCE HABER
# ------------------------------------------------------------

def coin_news(symbol):
    """
    Ücretsiz RSS.
    Sadece başlıkta coin adı/ticker geçen haberleri alır.
    İlgisiz Tether/OpenAI vb. haberleri coin haberine bağlamaz.
    """

    base = symbol.replace("USDT", "").lower()

    feeds = [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss"
    ]

    news = []

    for feed in feeds:
        try:
            response = requests.get(
                feed,
                timeout=8,
                headers={"User-Agent": "Mozilla/5.0"}
            )

            root = ET.fromstring(response.text)

            for item in root.iter():
                if not item.tag.lower().endswith("item"):
                    continue

                title = ""

                for child in item:
                    if child.tag.lower().endswith("title"):
                        title = (child.text or "").strip()
                        break

                if title and base in title.lower():
                    news.append(title)

        except Exception:
            continue

    return news[:2]


# ------------------------------------------------------------
# BINANCE RADAR
# ------------------------------------------------------------

def scan_binance():
    print("--------------------------------")
    print("BINANCE RADAR BAŞLIYOR")
    print("--------------------------------")

    # Spot 24h verisi
    spot = get_json(
        f"{BINANCE_SPOT}/api/v3/ticker/24hr"
    )

    # USDT çiftleri
    excluded = {
        "USDCUSDT",
        "FDUSDUSDT",
        "TUSDUSDT",
        "USDPUSDT",
        "DAIUSDT"
    }

    spot = [
        x for x in spot
        if x.get("symbol", "").endswith("USDT")
        and x.get("symbol") not in excluded
    ]

    # Aşırı pump/dump olanları ilk havuzdan çıkar.
    spot = [
        x for x in spot
        if abs(float(x.get("priceChangePercent", 0))) <= 30
    ]

    # Hacme göre sırala.
    spot.sort(
        key=lambda x: float(x.get("quoteVolume", 0)),
        reverse=True
    )

    symbols = [x["symbol"] for x in spot[:MAX_BINANCE_COINS]]

    # XVG ve QNT her zaman özel kontrol listesinde olsun.
    for special in SPECIAL:
        if special not in symbols:
            symbols.append(special)

    # Futures 24h
    futures_tickers = get_json(
        f"{BINANCE_FAPI}/fapi/v1/ticker/24hr"
    )

    futures_map = {
        x["symbol"]: x
        for x in futures_tickers
    }

    # BTC yönü
    btc_klines = get_json(
        f"{BINANCE_FAPI}/fapi/v1/klines",
        {
            "symbol": "BTCUSDT",
            "interval": "1h",
            "limit": 60
        }
    )

    btc_closes = [float(x[4]) for x in btc_klines]

    btc_ema9 = ema(btc_closes, 9)
    btc_ema21 = ema(btc_closes, 21)

    btc_direction = (
        "UP"
        if btc_ema9 and btc_ema21 and btc_ema9 > btc_ema21
        else "DOWN"
    )

    results = []

    print(f"{len(symbols)} Binance coin taranıyor...")

    for index, symbol in enumerate(symbols, 1):

        try:
            futures = futures_map.get(symbol)

            # Futures yoksa LONG/SHORT analizi yapılamaz.
            # Spot yine de analiz edilebilir ama fiyat verisini
            # spot ticker'dan alıyoruz.
            spot_item = next(
                (x for x in spot if x["symbol"] == symbol),
                None
            )

            if not spot_item:
                continue

            if not futures:
                continue

            change24 = float(
                futures.get("priceChangePercent", 0)
            )

            if abs(change24) > 30:
                continue

            # 1H
            k1 = get_json(
                f"{BINANCE_FAPI}/fapi/v1/klines",
                {
                    "symbol": symbol,
                    "interval": "1h",
                    "limit": 60
                }
            )

            # 4H
            k4 = get_json(
                f"{BINANCE_FAPI}/fapi/v1/klines",
                {
                    "symbol": symbol,
                    "interval": "4h",
                    "limit": 60
                }
            )

            c1 = [float(x[4]) for x in k1]
            c4 = [float(x[4]) for x in k4]
            v1 = [float(x[5]) for x in k1]

            if len(c1) < 30 or len(c4) < 30:
                continue

            e91 = ema(c1, 9)
            e211 = ema(c1, 21)

            e94 = ema(c4, 9)
            e214 = ema(c4, 21)

            current_rsi = rsi(c1)

            if not all([e91, e211, e94, e214, current_rsi]):
                continue

            trend1 = "UP" if e91 > e211 else "DOWN"
            trend4 = "UP" if e94 > e214 else "DOWN"

            aligned = trend1 == trend4

            # Son kapanmış 1H mum / önceki 20 mum ortalaması
            previous_volume = v1[-2]

            avg_volume = sum(v1[-22:-2]) / 20

            volume_ratio = (
                previous_volume / avg_volume
                if avg_volume > 0
                else 0
            )

            # Kısa vadeli momentum
            momentum = (
                (c1[-2] / c1[-4]) - 1
            ) * 100

            score = 0
            reasons = []

            # 1H + 4H trend
            if aligned:
                score += 2
                reasons.append("1H ve 4H trend uyumlu")

            # RSI
            if trend1 == "UP" and 50 <= current_rsi <= 68:
                score += 1
                reasons.append("RSI yükseliş bölgesinde")

            elif trend1 == "DOWN" and 32 <= current_rsi <= 50:
                score += 1
                reasons.append("RSI düşüş bölgesinde")

            # Hacim
            if volume_ratio >= 1.5:
                score += 2
                reasons.append("Hacim belirgin artıyor")

            elif volume_ratio >= 1.15:
                score += 1
                reasons.append("Hacim destekli")

            # BTC
            if trend1 == "UP" and btc_direction == "UP":
                score += 1
                reasons.append("BTC yönü destekliyor")

            elif trend1 == "DOWN" and btc_direction == "DOWN":
                score += 1
                reasons.append("BTC yönü destekliyor")

            # Momentum
            if abs(momentum) >= 0.5:
                score += 1
                reasons.append("Kısa vadeli momentum var")

            funding = 0.0
            oi_change = None

            # Ağır futures verilerini sadece güçlü adaylarda çağır.
            if score >= 4:

                try:
                    premium = get_json(
                        f"{BINANCE_FAPI}/fapi/v1/premiumIndex",
                        {"symbol": symbol}
                    )

                    funding = (
                        float(
                            premium.get("lastFundingRate", 0)
                        ) * 100
                    )

                except Exception:
                    funding = 0.0

                try:
                    oi_history = get_json(
                        f"{BINANCE_FAPI}/futures/data/openInterestHist",
                        {
                            "symbol": symbol,
                            "period": "1h",
                            "limit": 3
                        }
                    )

                    if len(oi_history) >= 2:

                        old_oi = float(
                            oi_history[-2]["sumOpenInterestValue"]
                        )

                        new_oi = float(
                            oi_history[-1]["sumOpenInterestValue"]
                        )

                        if old_oi > 0:
                            oi_change = (
                                (new_oi / old_oi) - 1
                            ) * 100

                except Exception:
                    oi_change = None

                # Funding çok şişik değilse puan.
                if trend1 == "UP" and funding < 0.05:
                    score += 1
                    reasons.append("Funding aşırı şişik değil")

                elif trend1 == "DOWN" and funding > -0.05:
                    score += 1
                    reasons.append("Funding short tarafını aşırı kalabalık göstermiyor")

                # OI artışı
                if oi_change is not None and oi_change > 0:
                    score += 1
                    reasons.append("Open Interest yükseliyor")

            # 1H ve 4H aynı değilse sinyal yok.
            if not aligned:
                continue

            # En az 6/10
            if score < 6:
                continue

            price = float(futures["lastPrice"])

            # LONG / SHORT / SPOT kararı
            #
            # DOWN:
            #   SHORT
            #
            # UP:
            #   güçlü futures şartları varsa LONG
            #   değilse SPOT
            if trend1 == "DOWN":
                side = "SHORT"

            else:
                if (
                    score >= 8
                    and oi_change is not None
                    and oi_change > 0
                    and funding < 0.08
                ):
                    side = "LONG"
                else:
                    side = "SPOT"

            # Stop mesafesi
            stop_pct = max(
                0.015,
                min(
                    0.05,
                    0.02 + abs(momentum) / 100 * 0.5
                )
            )

            leverage, budget = budget_for(
                score,
                stop_pct,
                side
            )

            stop, tp1, tp2, stop_pct = levels(
                price,
                side,
                stop_pct
            )

            notional = budget * leverage

            planned_loss = notional * stop_pct

            # Risk sınırı
            if planned_loss > MAX_RISK:
                continue

            if budget < 5:
                continue

            results.append({
                "symbol": symbol,
                "side": side,
                "score": score,
                "price": price,
                "stop": stop,
                "tp1": tp1,
                "tp2": tp2,
                "budget": budget,
                "leverage": leverage,
                "loss": planned_loss,
                "rsi": current_rsi,
                "volume_ratio": volume_ratio,
                "funding": funding,
                "oi_change": oi_change,
                "momentum": momentum,
                "reasons": reasons,
                "change24": change24
            })

        except Exception as e:
            print("BINANCE ERROR", symbol, "=>", e)

    # Önce skor, sonra özel coinler.
    results.sort(
        key=lambda x: (
            x["score"],
            1 if x["symbol"] in SPECIAL else 0
        ),
        reverse=True
    )

    print(
        f"Binance sonucu: {len(results)} güçlü aday."
    )

    return results, len(symbols), btc_direction


# ------------------------------------------------------------
# BINANCE TELEGRAM MESAJI
# ------------------------------------------------------------

def binance_message(result, total, btc_direction):

    if result is None:

        return f"""🔵 BINANCE RADAR

⚪ WAIT

🪙 Tarama: {total} coin
₿ BTC yönü: {"YUKARI" if btc_direction == "UP" else "AŞAĞI"}

Bu taramada SPOT / LONG / SHORT için yeterli şart aynı anda oluşmadı."""

    x = result

    if x["side"] == "SPOT":
        leverage_text = "Yok"
    else:
        leverage_text = f'{x["leverage"]}x'

    tp1_profit = (
        x["budget"]
        * x["leverage"]
        * abs(
            x["tp1"] / x["price"] - 1
        )
    )

    tp2_profit = (
        x["budget"]
        * x["leverage"]
        * abs(
            x["tp2"] / x["price"] - 1
        )
    )

    message = f"""🚨 BINANCE FIRSAT

🪙 {x["symbol"]}
📌 {x["side"]}

💰 Bütçe: ${x["budget"]:.2f}
⚙️ Kaldıraç: {leverage_text}

🎯 Giriş: {fmt_price(x["price"])}
🛑 Stop: {fmt_price(x["stop"])}
🥇 TP1: {fmt_price(x["tp1"])}
🥈 TP2: {fmt_price(x["tp2"])}

💵 Tahmini zarar: -${x["loss"]:.2f}
💰 TP1 tahmini: +${tp1_profit:.2f}
💰 TP2 tahmini: +${tp2_profit:.2f}

🔥 Skor: {x["score"]}/10
📊 RSI: {x["rsi"]:.1f}
📈 Hacim: {x["volume_ratio"]:.1f}x
₿ BTC: {"YUKARI" if btc_direction == "UP" else "AŞAĞI"}

💡 Neden?
"""

    for reason in x["reasons"][:5]:
        message += f"• {reason}\n"

    news = coin_news(x["symbol"])

    if news:
        message += "\n📰 Coin haberi:\n"

        for item in news:
            message += f"• {item[:180]}\n"

    message += (
        "\n⚠️ Otomatik işlem açmaz."
        "\nİşlemden önce Binance ekranında kontrol et."
    )

    return message


# ------------------------------------------------------------
# SOLANA KEŞİF
# ------------------------------------------------------------

def discover_solana_tokens():

    candidates = {}

    # DEX Screener kaynakları
    endpoints = [
        f"{DEX}/token-profiles/latest/v1",
        f"{DEX}/token-boosts/latest/v1"
    ]

    for endpoint in endpoints:

        try:

            data = get_json(endpoint)

            for item in data:

                if (
                    item.get("chainId") == "solana"
                    and item.get("tokenAddress")
                ):

                    candidates[item["tokenAddress"]] = item

        except Exception as e:
            print("DEX discovery ERROR:", e)

    # GeckoTerminal yeni pool kaynağı
    try:

        data = get_json(
            f"{GECKO}/networks/solana/new_pools",
            {"page": 1}
        )

        for item in data.get("data", []):

            relationships = item.get(
                "relationships",
                {}
            )

            base_token = relationships.get(
                "base_token",
                {}
            )

            token_data = base_token.get(
                "data",
                {}
            )

            token_id = token_data.get(
                "id",
                ""
            )

            if token_id.startswith("solana_"):

                address = token_id.split(
                    "_",
                    1
                )[1]

                if address:

                    candidates.setdefault(
                        address,
                        {
                            "chainId": "solana",
                            "tokenAddress": address,
                            "links": []
                        }
                    )

    except Exception as e:
        print("GeckoTerminal discovery ERROR:", e)

    print(
        f"Solana keşif adayı: {len(candidates)}"
    )

    return candidates


# ------------------------------------------------------------
# SOLANA RADAR
# ------------------------------------------------------------

def scan_solana(state):

    candidates = discover_solana_tokens()

    addresses = list(candidates.keys())[:100]

    if not addresses:
        return [], 0, 0

    pairs = []

    # DEX Screener maksimum 30 adreslik parçalarla.
    for start in range(
        0,
        len(addresses),
        30
    ):

        chunk = addresses[
            start:start + 30
        ]

        try:

            data = get_json(
                f"{DEX}/tokens/v1/solana/{','.join(chunk)}"
            )

            if isinstance(data, list):
                pairs.extend(data)

        except Exception as e:
            print(
                "DEX pair ERROR:",
                e
            )

    # Her token için en yüksek likiditeli pair
    best_pairs = {}

    for pair in pairs:

        if pair.get("chainId") != "solana":
            continue

        address = (
            pair.get("baseToken", {})
            .get("address")
        )

        if address not in candidates:
            continue

        liquidity = float(
            (pair.get("liquidity") or {})
            .get("usd") or 0
        )

        if liquidity < 10000:
            continue

        old = best_pairs.get(address)

        if old is None:

            best_pairs[address] = pair

        else:

            old_liquidity = float(
                (old.get("liquidity") or {})
                .get("usd") or 0
            )

            if liquidity > old_liquidity:
                best_pairs[address] = pair

    alerts = []

    for address, pair in best_pairs.items():

        try:

            price_change = (
                pair.get("priceChange") or {}
            )

            volume = (
                pair.get("volume") or {}
            )

            transactions = (
                pair.get("txns") or {}
            )

            h1 = float(
                price_change.get("h1") or 0
            )

            m5 = float(
                price_change.get("m5") or 0
            )

            h24 = float(
                price_change.get("h24") or 0
            )

            volume_h1 = float(
                volume.get("h1") or 0
            )

            volume_m5 = float(
                volume.get("m5") or 0
            )

            h1_tx = (
                transactions.get("h1")
                or {}
            )

            buys = int(
                h1_tx.get("buys") or 0
            )

            sells = int(
                h1_tx.get("sells") or 0
            )

            liquidity = float(
                (pair.get("liquidity") or {})
                .get("usd") or 0
            )

            # Erken hareket filtresi
            if h1 < 3:
                continue

            # Çoktan pump olmuşsa alma
            if h1 > 25:
                continue

            if h24 > 40:
                continue

            # Çok sert 5 dk düşüş varsa alma
            if m5 < -5:
                continue

            if volume_h1 < 5000:
                continue

            if volume_m5 <= 0:
                continue

            volume_acceleration = (
                volume_m5 * 12
            ) / volume_h1

            if volume_acceleration < 2:
                continue

            buy_sell_ratio = (
                buys / max(sells, 1)
            )

            if buy_sell_ratio < 1.05:
                continue

            score = 0

            # Fiyat henüz erken bölgede
            if 3 <= h1 <= 15:
                score += 2

            elif 15 < h1 <= 25:
                score += 1

            # Hacim ivmesi
            if volume_acceleration >= 3:
                score += 2

            elif volume_acceleration >= 2:
                score += 1

            # Alıcı/satıcı
            if buy_sell_ratio >= 1.5:
                score += 2

            elif buy_sell_ratio >= 1.15:
                score += 1

            # Likidite
            if liquidity >= 25000:
                score += 1

            # Sosyal link
            links = (
                candidates[address]
                .get("links")
                or []
            )

            if links:
                score += 1

            if score < 6:
                continue

            # 24 saat tekrar engeli
            last_alert = (
                state
                .get("sol_alerts", {})
                .get(address, 0)
            )

            if (
                time.time() - last_alert
                < SOL_REPEAT_HOURS * 3600
            ):
                continue

            name = (
                pair.get("baseToken", {})
                .get("symbol")
                or "UNKNOWN"
            )

            alerts.append({
                "name": name,
                "address": address,
                "h1": h1,
                "m5": m5,
                "h24": h24,
                "volume_h1": volume_h1,
                "volume_acceleration": volume_acceleration,
                "buys": buys,
                "sells": sells,
                "buy_sell_ratio": buy_sell_ratio,
                "liquidity": liquidity,
                "score": score,
                "url": pair.get("url")
            })

        except Exception as e:
            print(
                "SOLANA ANALYSIS ERROR:",
                e
            )

    alerts.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return (
        alerts[:3],
        len(candidates),
        len(best_pairs)
    )


# ------------------------------------------------------------
# SOLANA TELEGRAM
# ------------------------------------------------------------

def solana_message(alert):

    return f"""🚨 SOLANA ERKEN UYARI

🪙 {alert["name"]}

📈 1H hareket: {alert["h1"]:.1f}%
🔥 Hacim ivmesi: {alert["volume_acceleration"]:.1f}x

👥 Alıcı işlemleri: {alert["buys"]}
🔻 Satıcı işlemleri: {alert["sells"]}
⚖️ Alım/Satım: {alert["buy_sell_ratio"]:.1f}x

💧 Likidite: ${alert["liquidity"]:,.0f}

💡 Neden dikkat çekti?
• Fiyat henüz aşırı yükselmiş değil.
• Hacim hızlanıyor.
• Alım tarafı güçleniyor.
• Likidite filtresini geçti.

🟡 ERKEN AŞAMA
⚠️ Meme coin — çok yüksek risk
🔎 Phantom'dan kontratı kontrol et.

{alert["url"] or ""}"""


# ------------------------------------------------------------
# ANA PROGRAM
# ------------------------------------------------------------

def main():

    state = load_state()

    print("================================")
    print("BINANCE + SOLANA RADAR")
    print("================================")

    # ========================================================
    # BINANCE
    # ========================================================

    try:

        results, total, btc_direction = (
            scan_binance()
        )

        now = time.time()

        # Sonuçlar varsa en güçlü adayı gönder.
        if results:

            sent = False

            for result in results:

                symbol = result["symbol"]

                last = (
                    state
                    .get("binance_alerts", {})
                    .get(symbol, 0)
                )

                if (
                    now - last
                    >= BINANCE_REPEAT_MINUTES * 60
                ):

                    if telegram(
                        binance_message(
                            result,
                            total,
                            btc_direction
                        )
                    ):

                        state.setdefault(
                            "binance_alerts",
                            {}
                        )[symbol] = now

                        sent = True

                        # Aynı çalışmada tek Binance mesajı
                        break

            if not sent:

                print(
                    "Binance aday var ama "
                    "tekrar süresi dolmadı."
                )

        else:

            # WAIT her 60 dakikada bir
            if (
                now
                - state.get("last_wait", 0)
                >= WAIT_EVERY_MINUTES * 60
            ):

                if telegram(
                    binance_message(
                        None,
                        total,
                        btc_direction
                    )
                ):

                    state["last_wait"] = now

    except Exception as e:

        print(
            "BINANCE RADAR ERROR:",
            repr(e)
        )

        telegram(
            "⚠️ BINANCE RADAR HATA\n\n"
            "Tarama tamamlanamadı. "
            "GitHub Actions logunu kontrol et."
        )

    # ========================================================
    # SOLANA
    # ========================================================

    try:

        alerts, token_count, pair_count = (
            scan_solana(state)
        )

        print(
            f"Solana: {token_count} token adayı, "
            f"{pair_count} pair incelendi, "
            f"{len(alerts)} alarm."
        )

        for alert in alerts:

            if telegram(
                solana_message(alert)
            ):

                state.setdefault(
                    "sol_alerts",
                    {}
                )[alert["address"]] = time.time()

    except Exception as e:

        print(
            "SOLANA RADAR ERROR:",
            repr(e)
        )

        telegram(
            "⚠️ SOLANA RADAR HATA\n\n"
            "Tarama tamamlanamadı. "
            "GitHub Actions logunu kontrol et."
        )

    # ========================================================
    # STATE KAYDET
    # ========================================================

    save_state(state)

    print("State kaydedildi.")

    # GitHub'a state'i gönder
    try:
        commit_state()
    except Exception as e:
        print(
            "Git state gönderme hatası:",
            e
        )

    print("================================")
    print("BOT TAMAMLANDI")
    print("================================")


if __name__ == "__main__":
    main()
