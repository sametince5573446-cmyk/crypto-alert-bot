import os
import json
import time
import requests
from datetime import datetime, timezone, timedelta

# ============================================================
# AYARLAR
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

DEX_BASE = "https://api.dexscreener.com"
STATE_FILE = "solana_alerts.json"

# Aynı coin tekrar tekrar mesaj atmasın
REPEAT_HOURS = 24

# Erken uyarı sınırları
MIN_MOVE = 5.0
MAX_EARLY_MOVE = 25.0
MAX_PUMP = 40.0

# Likidite filtresi
MIN_LIQUIDITY = 10000

# Hacim filtresi
MIN_VOLUME_MULTIPLIER = 3.0

# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram bilgileri eksik.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": False
    }

    try:
        r = requests.post(url, json=payload, timeout=15)

        if r.ok:
            return True

        print("Telegram hata:", r.text)

    except Exception as e:
        print("Telegram bağlantı hatası:", e)

    return False


# ============================================================
# STATE
# ============================================================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print("State kayıt hatası:", e)


# ============================================================
# DEXSCREENER
# ============================================================

def get_token_pairs(chain="solana"):
    url = f"{DEX_BASE}/token-profiles/latest/v1"

    try:
        r = requests.get(url, timeout=15)

        if not r.ok:
            print("Token profile API hata:", r.status_code)
            return []

        data = r.json()

        if not isinstance(data, list):
            return []

        result = []

        for item in data:
            if item.get("chainId") == chain:
                result.append(item)

        return result

    except Exception as e:
        print("Token profile hata:", e)
        return []


def get_pairs_for_token(address):
    url = f"{DEX_BASE}/latest/dex/tokens/{address}"

    try:
        r = requests.get(url, timeout=15)

        if not r.ok:
            return []

        data = r.json()

        return data.get("pairs", []) or []

    except Exception as e:
        print("Pair API hata:", e)
        return []


# ============================================================
# YARDIMCI
# ============================================================

def safe_float(value, default=0.0):
    try:
        return float(value)
    except:
        return default


def format_money(value):
    if value >= 1000000:
        return f"${value / 1000000:.2f}M"

    if value >= 1000:
        return f"${value / 1000:.1f}K"

    return f"${value:.0f}"


def percent(value):
    return f"{value:.1f}%"


# ============================================================
# 5 DK / 15 DK HACİM
# ============================================================

def get_volume_acceleration(pair):
    """
    DEX Screener 5m ve 1h hacim verilerini kullanır.

    Amaç:
    - 5m hacim çok yükselmiş mi?
    - 5m hacim, 1h hacminin anlamlı bölümünü oluşturuyor mu?
    """

    volume = pair.get("volume") or {}

    v5 = safe_float(volume.get("m5"))
    v1h = safe_float(volume.get("h1"))

    if v1h <= 0:
        return 0.0, 0.0

    # 1 saatlik hacmin %25'i son 5 dakikada gerçekleşiyorsa
    # ciddi hızlanma kabul ediyoruz.
    ratio = (v5 * 12) / v1h

    return v5, ratio


# ============================================================
# İŞLEM ANALİZİ
# ============================================================

def get_transaction_data(pair):
    txns = pair.get("txns") or {}

    m5 = txns.get("m5") or {}
    m15 = txns.get("m15") or {}
    h1 = txns.get("h1") or {}

    buys_5 = int(safe_float(m5.get("buys")))
    sells_5 = int(safe_float(m5.get("sells")))

    buys_15 = int(safe_float(m15.get("buys")))
    sells_15 = int(safe_float(m15.get("sells")))

    buys_1h = int(safe_float(h1.get("buys")))
    sells_1h = int(safe_float(h1.get("sells")))

    return {
        "buys_5": buys_5,
        "sells_5": sells_5,
        "buys_15": buys_15,
        "sells_15": sells_15,
        "buys_1h": buys_1h,
        "sells_1h": sells_1h,
    }


# ============================================================
# ALICI / SATICI ORANI
# ============================================================

def buyer_seller_ratio(buys, sells):
    if sells <= 0:
        if buys > 0:
            return 99.0
        return 0.0

    return buys / sells


# ============================================================
# LİKİDİTE
# ============================================================

def liquidity_change(pair):
    """
    DEX Screener geçmiş likidite verisini her zaman sağlamayabilir.
    Bu nedenle mevcut likiditeyi döndürür.
    State üzerinden önceki değer varsa değişimi hesaplar.
    """

    liquidity = pair.get("liquidity") or {}

    usd = safe_float(liquidity.get("usd"))

    return usd


# ============================================================
# SOSYAL / BOOST
# ============================================================

def social_activity(pair):
    """
    Boost veya sosyal bağlantı varlığı ekstra puan verir.
    Fakat tek başına alarm oluşturmaz.
    """

    score = 0

    boosts = pair.get("boosts") or {}
    active_boosts = safe_float(boosts.get("active"))

    if active_boosts > 0:
        score += 1

    info = pair.get("info") or {}

    socials = info.get("socials") or []

    if len(socials) > 0:
        score += 1

    return score


# ============================================================
# ERKEN UYARI ANALİZİ
# ============================================================

def analyze_pair(pair, previous=None):

    base_token = pair.get("baseToken") or {}

    symbol = base_token.get("symbol", "UNKNOWN")
    address = base_token.get("address", "")

    if not address:
        return None

    price_change = pair.get("priceChange") or {}

    change_5m = safe_float(price_change.get("m5"))
    change_1h = safe_float(price_change.get("h1"))
    change_6h = safe_float(price_change.get("h6"))
    change_24h = safe_float(price_change.get("h24"))

    liquidity = liquidity_change(pair)

    volume = pair.get("volume") or {}

    volume_5m = safe_float(volume.get("m5"))
    volume_1h = safe_float(volume.get("h1"))

    # ========================================================
    # TEMEL FİLTRELER
    # ========================================================

    if liquidity < MIN_LIQUIDITY:
        return None

    # Zaten aşırı yükselmiş coinleri ele
    if change_24h >= MAX_PUMP:
        return None

    # Erken hareket başlamamışsa ilgilenme
    if change_1h < MIN_MOVE and change_5m < MIN_MOVE:
        return None

    # ========================================================
    # İŞLEMLER
    # ========================================================

    tx = get_transaction_data(pair)

    buys_5 = tx["buys_5"]
    sells_5 = tx["sells_5"]

    buys_15 = tx["buys_15"]
    sells_15 = tx["sells_15"]

    buys_1h = tx["buys_1h"]
    sells_1h = tx["sells_1h"]

    ratio_5 = buyer_seller_ratio(buys_5, sells_5)
    ratio_15 = buyer_seller_ratio(buys_15, sells_15)
    ratio_1h = buyer_seller_ratio(buys_1h, sells_1h)

    total_5 = buys_5 + sells_5
    total_15 = buys_15 + sells_15
    total_1h = buys_1h + sells_1h

    # İşlem sayısı çok düşükse erken alarm verme
    if total_5 < 20 and total_15 < 50:
        return None

    # ========================================================
    # HACİM İVMESİ
    # ========================================================

    volume_ratio = 0

    if volume_1h > 0:
        volume_ratio = (volume_5m * 12) / volume_1h

    volume_acceleration = "ZAYIF"

    if volume_ratio >= 3:
        volume_acceleration = "GÜÇLÜ"

    if volume_ratio >= 6:
        volume_acceleration = "ÇOK GÜÇLÜ"

    # ========================================================
    # SKOR
    # ========================================================

    score = 0

    reasons = []

    # --------------------------------------------------------
    # 1. Fiyat henüz aşırı yükselmemiş
    # --------------------------------------------------------

    if 5 <= change_1h <= 25:
        score += 2
        reasons.append("Fiyat henüz aşırı yükselmedi.")

    elif 25 < change_1h < 40:
        score -= 2

    # --------------------------------------------------------
    # 2. 5 dk hacim ivmesi
    # --------------------------------------------------------

    if volume_ratio >= 3:
        score += 2
        reasons.append("Son dakikalarda hacim hızlandı.")

    if volume_ratio >= 6:
        score += 1

    # --------------------------------------------------------
    # 3. Alıcı üstünlüğü
    # --------------------------------------------------------

    if ratio_5 >= 1.5:
        score += 2
        reasons.append("Kısa vadede alıcılar satıcılardan fazla.")

    if ratio_5 >= 2.5:
        score += 1

    # --------------------------------------------------------
    # 4. 15 dk teyit
    # --------------------------------------------------------

    if ratio_15 >= 1.5:
        score += 1
        reasons.append("15 dakikalık işlem akışında alıcı üstünlüğü var.")

    # --------------------------------------------------------
    # 5. 1 saat teyit
    # --------------------------------------------------------

    if ratio_1h >= 1.2:
        score += 1

    # --------------------------------------------------------
    # 6. İşlem sayısı
    # --------------------------------------------------------

    if total_5 >= 100:
        score += 1

    if total_5 >= 300:
        score += 1

    # --------------------------------------------------------
    # 7. Likidite
    # --------------------------------------------------------

    if liquidity >= 25000:
        score += 1

    # --------------------------------------------------------
    # 8. Sosyal hareket
    # --------------------------------------------------------

    social_score = social_activity(pair)

    if social_score >= 1:
        score += 1

    # ========================================================
    # LİKİDİTE DEĞİŞİMİ
    # ========================================================

    liquidity_change_percent = 0.0

    if previous:
        old_liquidity = safe_float(previous.get("liquidity"))

        if old_liquidity > 0:
            liquidity_change_percent = (
                (liquidity - old_liquidity) / old_liquidity
            ) * 100

    # Likidite ciddi düşüyorsa alarmı zayıflat
    if liquidity_change_percent <= -15:
        score -= 3
        reasons.append("Likiditede düşüş var.")

    elif liquidity_change_percent >= 10:
        score += 1
        reasons.append("Likidite artıyor.")

    # ========================================================
    # ALIŞ / SATIŞ DENGESİ KONTROLÜ
    # ========================================================

    if ratio_5 < 1.0:
        score -= 3

    if ratio_15 < 1.0:
        score -= 2

    # Son 5 dakikada satıcılar baskınsa alarm verme
    if buys_5 < sells_5 and volume_ratio >= 3:
        score -= 2

    # ========================================================
    # ÇOK YÜKSEK FİYAT HAREKETİ
    # ========================================================

    if change_1h >= 25:
        # Ancak ekstra güçlü teyit varsa tamamen silme
        if ratio_5 >= 2.5 and volume_ratio >= 6:
            score -= 1
        else:
            return None

    # ========================================================
    # SON KARAR
    # ========================================================

    if score < 7:
        return None

    # ========================================================
    # TEKRAR KONTROLÜ
    # ========================================================

    return {
        "symbol": symbol,
        "address": address,

        "change_5m": change_5m,
        "change_1h": change_1h,
        "change_6h": change_6h,
        "change_24h": change_24h,

        "liquidity": liquidity,
        "liquidity_change": liquidity_change_percent,

        "volume_5m": volume_5m,
        "volume_1h": volume_1h,
        "volume_ratio": volume_ratio,
        "volume_acceleration": volume_acceleration,

        "buys_5": buys_5,
        "sells_5": sells_5,

        "buys_15": buys_15,
        "sells_15": sells_15,

        "buys_1h": buys_1h,
        "sells_1h": sells_1h,

        "ratio_5": ratio_5,
        "ratio_15": ratio_15,
        "ratio_1h": ratio_1h,

        "score": score,
        "reasons": reasons,

        "pair_url": pair.get(
            "url",
            f"https://dexscreener.com/solana/{pair.get('pairAddress', address)}"
        ),

        "pair_address": pair.get("pairAddress", address)
    }


# ============================================================
# TELEGRAM MESAJI
# ============================================================

def build_message(data):

    if data["score"] >= 11:
        level = "🚀 ÇOK GÜÇLÜ ERKEN HAREKET"
    elif data["score"] >= 9:
        level = "🟢 GÜÇLÜ ERKEN HAREKET"
    else:
        level = "🟡 ERKEN AŞAMA"

    reasons = data["reasons"][:4]

    reason_text = ""

    for reason in reasons:
        reason_text += f"• {reason}\n"

    liquidity_change = data["liquidity_change"]

    if liquidity_change > 0:
        liquidity_text = f"+{liquidity_change:.1f}%"
    elif liquidity_change < 0:
        liquidity_text = f"{liquidity_change:.1f}%"
    else:
        liquidity_text = "Yeni veri"

    message = f"""
🚨 ERKEN UYARI — SOLANA

🪙 {data["symbol"]}

📈 Son 1s hareket: {percent(data["change_1h"])}
📈 Son 5dk hareket: {percent(data["change_5m"])}

🔥 Hacim: {data["volume_ratio"]:.1f}x
📊 5dk hacim ivmesi: {data["volume_acceleration"]}

👥 Alıcı: {data["buys_5"]}
🔻 Satıcı: {data["sells_5"]}
⚖️ Alıcı/Satıcı: {data["ratio_5"]:.1f}x

👥 15dk Alıcı: {data["buys_15"]}
🔻 15dk Satıcı: {data["sells_15"]}

💧 Likidite: {format_money(data["liquidity"])}
📊 Likidite değişimi: {liquidity_text}

💡 Neden dikkat çekti?
{reason_text}
{level}

⚠️ Meme coin — çok yüksek risk
📍 Solana
🔎 Phantom'dan kontrol et.

🔗 DEX Screener:
{data["pair_url"]}
"""

    return message.strip()


# ============================================================
# ANA TARAMA
# ============================================================

def main():

    print("======================================")
    print("SOLANA ERKEN UYARI BOTU")
    print("======================================")

    state = load_state()

    profiles = get_token_pairs()

    print("Token profilleri:", len(profiles))

    alerts = []

    now = datetime.now(timezone.utc)

    for profile in profiles:

        address = profile.get("tokenAddress")

        if not address:
            continue

        try:

            pairs = get_pairs_for_token(address)

            if not pairs:
                continue

            # Solana pairleri
            sol_pairs = [
                p for p in pairs
                if p.get("chainId") == "solana"
            ]

            if not sol_pairs:
                continue

            # En yüksek likiditeli pair
            sol_pairs.sort(
                key=lambda x: safe_float(
                    (x.get("liquidity") or {}).get("usd")
                ),
                reverse=True
            )

            pair = sol_pairs[0]

            result = analyze_pair(
                pair,
                state.get(address)
            )

            # Son veri state'e yaz
            liquidity = safe_float(
                (pair.get("liquidity") or {}).get("usd")
            )

            state[address] = {
                "symbol": (pair.get("baseToken") or {}).get(
                    "symbol",
                    "UNKNOWN"
                ),
                "liquidity": liquidity,
                "last_check": now.isoformat()
            }

            if result is None:
                continue

            # =================================================
            # TEKRAR ALARMI ENGELLE
            # =================================================

            old = state.get(address, {})

            last_alert = old.get("last_alert")

            if last_alert:

                try:
                    last_dt = datetime.fromisoformat(last_alert)

                    if now - last_dt < timedelta(hours=REPEAT_HOURS):
                        continue

                except:
                    pass

            # Alert kaydet
            state[address]["last_alert"] = now.isoformat()

            alerts.append(result)

        except Exception as e:
            print("Token analiz hata:", address, e)

        # API'yi gereksiz zorlamamak için
        time.sleep(0.15)

    # ========================================================
    # EN GÜÇLÜLERİ ÖNE AL
    # ========================================================

    alerts.sort(
        key=lambda x: (
            x["score"],
            x["volume_ratio"],
            x["ratio_5"]
        ),
        reverse=True
    )

    # En fazla 3 alarm
    alerts = alerts[:3]

    for alert in alerts:

        message = build_message(alert)

        print(message)

        send_telegram(message)

        time.sleep(1)

    save_state(state)

    print("--------------------------------------")
    print("Tarama tamamlandı.")
    print("Alarm sayısı:", len(alerts))
    print("--------------------------------------")


if __name__ == "__main__":
    main()
