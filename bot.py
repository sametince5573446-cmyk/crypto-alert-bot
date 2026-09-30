import os
import json
import time
import subprocess
from datetime import datetime, timezone

import requests


# =========================================================
# AYARLAR
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

DEX_BASE = "https://api.dexscreener.com"

STATE_FILE = "solana_alerts.json"

# Kaç token taranacak
MAX_TOKENS = 100

# Aynı coin tekrar kaç saat içinde alarm vermesin?
REPEAT_HOURS = 24

# Minimum likidite
MIN_LIQUIDITY = 10000

# Çoktan yükselmiş coinleri ele
MAX_1H_MOVE = 25
MAX_24H_MOVE = 40

# Minimum erken hareket
MIN_1H_MOVE = 3

# Minimum hacim
MIN_1H_VOLUME = 5000

# Hacim ivmesi
MIN_VOLUME_ACCELERATION = 2.5

# Minimum alıcı üstünlüğü
MIN_BUY_SELL_RATIO = 1.20

# Minimum puan
MIN_SCORE = 7

# Çok yeni pair için bekleme
MIN_PAIR_AGE_MINUTES = 5


session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 CryptoAlertBot/1.0"
})


# =========================================================
# GENEL FONKSİYONLAR
# =========================================================

def safe_float(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def now_ts():
    return int(time.time())


def format_money(value):
    if value is None:
        return "VERİ YOK"

    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"

    if value >= 1_000:
        return f"${value / 1_000:.1f}K"

    return f"${value:.0f}"


def format_percent(value):
    if value is None:
        return "VERİ YOK"

    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}%"


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram bilgileri bulunamadı.")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True
    }

    try:
        response = session.post(
            url,
            json=data,
            timeout=20
        )

        if response.status_code == 200:
            return True

        print("Telegram hata:", response.text)
        return False

    except Exception as e:
        print("Telegram bağlantı hatası:", e)
        return False


# =========================================================
# STATE
# =========================================================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            return json.load(f)

    except Exception:
        return {}


def save_state(state):
    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2
        )


# =========================================================
# DEX SCREENER API
# =========================================================

def get_latest_profiles():
    url = f"{DEX_BASE}/token-profiles/latest/v1"

    try:
        response = session.get(
            url,
            timeout=20
        )

        if response.status_code != 200:
            print("Token profiles hata:", response.status_code)
            return []

        data = response.json()

        if not isinstance(data, list):
            return []

        return data

    except Exception as e:
        print("Profiles hata:", e)
        return []


def get_token_pairs(token_addresses):
    """
    Aynı anda maksimum 30 token sorgulanır.
    """

    if not token_addresses:
        return []

    address_text = ",".join(token_addresses)

    url = (
        f"{DEX_BASE}/tokens/v1/solana/"
        f"{address_text}"
    )

    try:
        response = session.get(
            url,
            timeout=20
        )

        if response.status_code != 200:
            print(
                "Token pairs hata:",
                response.status_code
            )
            return []

        data = response.json()

        if not isinstance(data, list):
            return []

        return data

    except Exception as e:
        print("Token pairs hata:", e)
        return []


def get_exact_pair(pair_address):
    """
    Son kontrolde aynı pair adresini tekrar sorgular.
    Böylece başka pair'in verisiyle karışma ihtimali azalır.
    """

    if not pair_address:
        return None

    url = (
        f"{DEX_BASE}/latest/dex/pairs/"
        f"solana/{pair_address}"
    )

    try:
        response = session.get(
            url,
            timeout=20
        )

        if response.status_code != 200:
            return None

        data = response.json()

        pairs = data.get("pairs")

        if not pairs:
            return None

        return pairs[0]

    except Exception as e:
        print("Exact pair hata:", e)
        return None


# =========================================================
# PAIR SEÇİMİ
# =========================================================

def choose_best_pair(pairs):
    """
    Aynı tokenın birden fazla pool'u olabilir.
    En yüksek likiditeli Solana pair seçilir.
    """

    if not pairs:
        return None

    solana_pairs = [
        p for p in pairs
        if p.get("chainId") == "solana"
    ]

    if not solana_pairs:
        return None

    best = None
    best_liquidity = -1

    for pair in solana_pairs:
        liquidity = safe_float(
            pair.get("liquidity", {}).get("usd"),
            0
        )

        if liquidity > best_liquidity:
            best_liquidity = liquidity
            best = pair

    return best


# =========================================================
# VERİ ÇIKARMA
# =========================================================

def extract_pair_data(pair):
    if not pair:
        return None

    price_change = pair.get("priceChange") or {}
    volume = pair.get("volume") or {}
    txns = pair.get("txns") or {}
    liquidity_data = pair.get("liquidity") or {}

    base_token = pair.get("baseToken") or {}

    symbol = base_token.get("symbol") or "UNKNOWN"
    name = base_token.get("name") or symbol

    pair_address = pair.get("pairAddress")

    price_usd = safe_float(
        pair.get("priceUsd")
    )

    change_5m = safe_float(
        price_change.get("m5")
    )

    change_1h = safe_float(
        price_change.get("h1")
    )

    change_6h = safe_float(
        price_change.get("h6")
    )

    change_24h = safe_float(
        price_change.get("h24")
    )

    volume_5m = safe_float(
        volume.get("m5")
    )

    volume_1h = safe_float(
        volume.get("h1")
    )

    volume_6h = safe_float(
        volume.get("h6")
    )

    volume_24h = safe_float(
        volume.get("h24")
    )

    tx_5m = txns.get("m5") or {}
    tx_15m = txns.get("m15") or {}
    tx_1h = txns.get("h1") or {}

    buys_5m = safe_int(
        tx_5m.get("buys"),
        0
    )

    sells_5m = safe_int(
        tx_5m.get("sells"),
        0
    )

    buys_15m = safe_int(
        tx_15m.get("buys"),
        0
    )

    sells_15m = safe_int(
        tx_15m.get("sells"),
        0
    )

    buys_1h = safe_int(
        tx_1h.get("buys"),
        0
    )

    sells_1h = safe_int(
        tx_1h.get("sells"),
        0
    )

    liquidity = safe_float(
        liquidity_data.get("usd")
    )

    pair_created_at = pair.get(
        "pairCreatedAt"
    )

    pair_age_minutes = None

    if pair_created_at:
        try:
            created_ms = int(pair_created_at)

            # DEX timestamp milisaniye
            created_seconds = created_ms / 1000

            pair_age_minutes = (
                now_ts() - created_seconds
            ) / 60

        except Exception:
            pair_age_minutes = None

    info = pair.get("info") or {}

    websites = info.get("websites") or []
    socials = info.get("socials") or []

    boosts = pair.get("boosts") or {}

    boost_active = safe_int(
        boosts.get("active"),
        0
    )

    return {
        "symbol": symbol,
        "name": name,
        "pair_address": pair_address,

        "price_usd": price_usd,

        "change_5m": change_5m,
        "change_1h": change_1h,
        "change_6h": change_6h,
        "change_24h": change_24h,

        "volume_5m": volume_5m,
        "volume_1h": volume_1h,
        "volume_6h": volume_6h,
        "volume_24h": volume_24h,

        "buys_5m": buys_5m,
        "sells_5m": sells_5m,

        "buys_15m": buys_15m,
        "sells_15m": sells_15m,

        "buys_1h": buys_1h,
        "sells_1h": sells_1h,

        "liquidity": liquidity,

        "pair_age_minutes": pair_age_minutes,

        "boost_active": boost_active,

        "websites": websites,
        "socials": socials,

        "url": pair.get("url")
    }


# =========================================================
# ORANLAR
# =========================================================

def ratio(buys, sells):
    if sells <= 0:
        if buys > 0:
            return 99.0
        return None

    return buys / sells


def calculate_volume_acceleration(volume_5m, volume_1h):
    """
    5 dakikalık hacmi 1 saate yayarak yaklaşık hız ölçer.

    Örneğin:
    5m = 10K
    1h = 60K

    10K * 12 / 60K = 2x
    """

    if volume_5m is None:
        return None

    if volume_1h is None:
        return None

    if volume_1h <= 0:
        return None

    return (
        volume_5m * 12
    ) / volume_1h


# =========================================================
# STATE'TEN HACİM/LİKİDİTE DEĞİŞİMİ
# =========================================================

def calculate_state_changes(old, current):
    old_volume = safe_float(
        old.get("volume_1h")
    )

    current_volume = safe_float(
        current.get("volume_1h")
    )

    old_liquidity = safe_float(
        old.get("liquidity")
    )

    current_liquidity = safe_float(
        current.get("liquidity")
    )

    volume_change = None
    liquidity_change = None

    if (
        old_volume is not None
        and current_volume is not None
        and old_volume > 0
    ):
        volume_change = (
            (current_volume - old_volume)
            / old_volume
        ) * 100

    if (
        old_liquidity is not None
        and current_liquidity is not None
        and old_liquidity > 0
    ):
        liquidity_change = (
            (current_liquidity - old_liquidity)
            / old_liquidity
        ) * 100

    return volume_change, liquidity_change


# =========================================================
# SİNYAL ANALİZİ
# =========================================================

def analyze(data, old_state):
    if not data:
        return None

    score = 0
    reasons = []
    warnings = []

    change_5m = data["change_5m"]
    change_1h = data["change_1h"]
    change_24h = data["change_24h"]

    volume_5m = data["volume_5m"]
    volume_1h = data["volume_1h"]

    liquidity = data["liquidity"]

    buys_5m = data["buys_5m"]
    sells_5m = data["sells_5m"]

    buys_15m = data["buys_15m"]
    sells_15m = data["sells_15m"]

    buys_1h = data["buys_1h"]
    sells_1h = data["sells_1h"]

    pair_age = data["pair_age_minutes"]

    # -----------------------------------------------------
    # GEREKLİ VERİLER
    # -----------------------------------------------------

    if change_1h is None:
        return None

    if volume_1h is None:
        return None

    if liquidity is None:
        return None

    if volume_1h < MIN_1H_VOLUME:
        return None

    if liquidity < MIN_LIQUIDITY:
        return None

    # -----------------------------------------------------
    # AŞIRI PUMP KONTROLÜ
    # -----------------------------------------------------

    if change_1h > MAX_1H_MOVE:
        return None

    if (
        change_24h is not None
        and change_24h > MAX_24H_MOVE
    ):
        return None

    # -----------------------------------------------------
    # ÇOK YENİ PAIR
    # -----------------------------------------------------

    if pair_age is not None:
        if pair_age < MIN_PAIR_AGE_MINUTES:
            return None

    # -----------------------------------------------------
    # FİYAT YÖNÜ
    # -----------------------------------------------------

    if change_1h < MIN_1H_MOVE:
        return None

    if (
        change_5m is not None
        and change_5m <= -5
    ):
        return None

    # -----------------------------------------------------
    # HACİM İVME
    # -----------------------------------------------------

    volume_acceleration = (
        calculate_volume_acceleration(
            volume_5m,
            volume_1h
        )
    )

    if volume_acceleration is not None:

        if volume_acceleration >= 6:
            score += 3
            reasons.append(
                "Son dakikalarda hacim çok hızlı artıyor."
            )

        elif volume_acceleration >= 3:
            score += 2
            reasons.append(
                "Hacim belirgin şekilde hızlandı."
            )

        elif volume_acceleration >= MIN_VOLUME_ACCELERATION:
            score += 1
            reasons.append(
                "Hacim normalin üzerinde."
            )

    # -----------------------------------------------------
    # 5 DK ALICI / SATICI
    # -----------------------------------------------------

    ratio_5m = ratio(
        buys_5m,
        sells_5m
    )

    if ratio_5m is not None:

        if ratio_5m >= 3:
            score += 3
            reasons.append(
                "Son 5 dakikada alıcı işlemleri belirgin üstün."
            )

        elif ratio_5m >= 2:
            score += 2
            reasons.append(
                "Son 5 dakikada alıcılar satıcılardan fazla."
            )

        elif ratio_5m >= MIN_BUY_SELL_RATIO:
            score += 1

        elif ratio_5m < 1:
            score -= 2
            warnings.append(
                "Son 5 dakikada satıcı işlemleri üstün."
            )

    # -----------------------------------------------------
    # 15 DK ALICI / SATICI
    # -----------------------------------------------------

    ratio_15m = None

    if buys_15m > 0 or sells_15m > 0:

        ratio_15m = ratio(
            buys_15m,
            sells_15m
        )

        if ratio_15m is not None:

            if ratio_15m >= 2:
                score += 2
                reasons.append(
                    "15 dakikalık alıcı/satıcı dengesi pozitif."
                )

            elif ratio_15m >= 1.3:
                score += 1

            elif ratio_15m < 1:
                score -= 1

    # -----------------------------------------------------
    # 1 SAAT ALICI / SATICI
    # -----------------------------------------------------

    ratio_1h = ratio(
        buys_1h,
        sells_1h
    )

    if ratio_1h is not None:

        if ratio_1h >= 1.5:
            score += 2

        elif ratio_1h >= 1.2:
            score += 1

        elif ratio_1h < 1:
            score -= 1

    # -----------------------------------------------------
    # 5 DK İŞLEM SAYISI
    # -----------------------------------------------------

    total_5m = (
        buys_5m +
        sells_5m
    )

    if total_5m >= 300:
        score += 2
        reasons.append(
            "Son 5 dakikada işlem aktivitesi yüksek."
        )

    elif total_5m >= 100:
        score += 1

    # -----------------------------------------------------
    # FİYAT HAREKETİ
    # -----------------------------------------------------

    if (
        change_1h is not None
        and 5 <= change_1h <= 15
    ):
        score += 2
        reasons.append(
            "Fiyat hareketi başladı ancak henüz aşırı yükselmedi."
        )

    elif (
        change_1h is not None
        and 15 < change_1h <= 25
    ):
        score += 1
        warnings.append(
            "Coin yükselmiş durumda; giriş riski arttı."
        )

    # -----------------------------------------------------
    # LİKİDİTE
    # -----------------------------------------------------

    if liquidity >= 50000:
        score += 2

    elif liquidity >= 25000:
        score += 1

    # -----------------------------------------------------
    # BOOST / SOSYAL
    # -----------------------------------------------------

    if data["boost_active"] > 0:
        score += 1
        reasons.append(
            "DEX Screener üzerinde aktif Boost bulunuyor."
        )

    if data["socials"]:
        score += 1
        reasons.append(
            "Token için sosyal medya bağlantısı mevcut."
        )

    # -----------------------------------------------------
    # STATE DEĞİŞİMİ
    # -----------------------------------------------------

    volume_change = None
    liquidity_change = None

    if old_state:
        volume_change, liquidity_change = (
            calculate_state_changes(
                old_state,
                data
            )
        )

        if (
            liquidity_change is not None
            and liquidity_change <= -15
        ):
            score -= 3
            warnings.append(
                "Likidite ciddi şekilde azalmış."
            )

        elif (
            liquidity_change is not None
            and liquidity_change >= 10
        ):
            score += 1
            reasons.append(
                "Likiditede artış görülüyor."
            )

        if (
            volume_change is not None
            and volume_change >= 20
        ):
            score += 1
            reasons.append(
                "Son taramaya göre hacim artıyor."
            )

    # -----------------------------------------------------
    # SON KONTROLLER
    # -----------------------------------------------------

    if score < MIN_SCORE:
        return None

    if (
        change_5m is not None
        and change_5m < -2
    ):
        warnings.append(
            "Son 5 dakikada kısa vadeli geri çekilme var."
        )

    # Aşırı satıcı baskısı
    if (
        ratio_5m is not None
        and ratio_5m < 0.9
    ):
        return None

    return {
        "score": score,
        "reasons": reasons,
        "warnings": warnings,
        "ratio_5m": ratio_5m,
        "ratio_15m": ratio_15m,
        "ratio_1h": ratio_1h,
        "volume_acceleration": volume_acceleration,
        "volume_change": volume_change,
        "liquidity_change": liquidity_change
    }


# =========================================================
# TELEGRAM MESAJI
# =========================================================

def build_message(data, analysis):
    symbol = data["symbol"]

    change_1h = data["change_1h"]
    change_5m = data["change_5m"]

    volume_acceleration = (
        analysis["volume_acceleration"]
    )

    ratio_5m = analysis["ratio_5m"]

    liquidity = data["liquidity"]

    liquidity_change = (
        analysis["liquidity_change"]
    )

    message = (
        "🚨 ERKEN UYARI — SOLANA\n\n"
        f"🪙 {symbol}\n\n"
    )

    message += (
        f"📈 1 saat: {format_percent(change_1h)}\n"
    )

    if change_5m is not None:
        message += (
            f"📈 5 dakika: "
            f"{format_percent(change_5m)}\n"
        )

    if volume_acceleration is not None:
        message += (
            f"\n🔥 Hacim ivmesi: "
            f"{volume_acceleration:.1f}x\n"
        )

    message += (
        f"\n👥 5dk Alıcı: "
        f"{data['buys_5m']}\n"
        f"🔻 5dk Satıcı: "
        f"{data['sells_5m']}\n"
    )

    if ratio_5m is not None:
        message += (
            f"⚖️ Alıcı/Satıcı: "
            f"{ratio_5m:.1f}x\n"
        )

    # 15 dk verisi gerçekten varsa göster
    if (
        data["buys_15m"] > 0
        or data["sells_15m"] > 0
    ):
        message += (
            f"\n👥 15dk Alıcı: "
            f"{data['buys_15m']}\n"
            f"🔻 15dk Satıcı: "
            f"{data['sells_15m']}\n"
        )
    else:
        message += (
            "\n👥 15dk işlem verisi: "
            "VERİ YOK\n"
        )

    message += (
        f"\n💧 Likidite: "
        f"{format_money(liquidity)}\n"
    )

    if liquidity_change is not None:
        message += (
            f"📊 Likidite değişimi: "
            f"{format_percent(liquidity_change)}\n"
        )
    else:
        message += (
            "📊 Likidite değişimi: "
            "İlk veri\n"
        )

    message += "\n💡 Neden dikkat çekti?\n"

    for reason in analysis["reasons"][:5]:
        message += f"• {reason}\n"

    for warning in analysis["warnings"][:2]:
        message += f"⚠️ {warning}\n"

    score = analysis["score"]

    if score >= 9:
        level = "🚀 ÇOK GÜÇLÜ"
    elif score >= 8:
        level = "🟢 GÜÇLÜ"
    else:
        level = "🟡 ERKEN AŞAMA"

    message += (
        f"\n{level}\n\n"
        "⚠️ Meme coin — çok yüksek risk\n"
        "📍 Solana\n"
        "🔎 Phantom'dan kontrat adresini kontrol et.\n"
    )

    if data["url"]:
        message += (
            "\n🔗 DEX Screener:\n"
            f"{data['url']}"
        )

    return message


# =========================================================
# GIT STATE KAYDETME
# =========================================================

def git_save_state():
    try:
        subprocess.run(
            ["git", "config", "user.name", "crypto-alert-bot"],
            check=False
        )

        subprocess.run(
            [
                "git",
                "config",
                "user.email",
                "crypto-alert-bot@users.noreply.github.com"
            ],
            check=False
        )

        subprocess.run(
            ["git", "add", STATE_FILE],
            check=False
        )

        result = subprocess.run(
            [
                "git",
                "commit",
                "-m",
                "Update Solana alert state"
            ],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode == 0:
            subprocess.run(
                ["git", "push"],
                check=False
            )

    except Exception as e:
        print("Git state kayıt hatası:", e)


# =========================================================
# ANA BOT
# =========================================================

def main():

    print("================================")
    print("SOLANA ERKEN UYARI BOTU")
    print("================================")

    state = load_state()

    profiles = get_latest_profiles()

    if not profiles:
        print("Token profili alınamadı.")
        return

    # Sadece Solana
    solana_profiles = []

    seen_addresses = set()

    for profile in profiles:

        if profile.get("chainId") != "solana":
            continue

        address = profile.get("tokenAddress")

        if not address:
            continue

        if address in seen_addresses:
            continue

        seen_addresses.add(address)

        solana_profiles.append(profile)

        if len(solana_profiles) >= MAX_TOKENS:
            break

    print(
        f"{len(solana_profiles)} Solana token taranacak."
    )

    # -----------------------------------------------------
    # TOKENLARI 30'LU GRUPLAR HALİNDE ÇEK
    # -----------------------------------------------------

    all_pairs = []

    for i in range(
        0,
        len(solana_profiles),
        30
    ):

        batch = solana_profiles[
            i:i + 30
        ]

        addresses = [
            x["tokenAddress"]
            for x in batch
        ]

        pairs = get_token_pairs(
            addresses
        )

        all_pairs.extend(pairs)

        time.sleep(0.3)

    print(
        f"{len(all_pairs)} pair bulundu."
    )

    # -----------------------------------------------------
    # TOKEN BAZINDA EN İYİ PAIR
    # -----------------------------------------------------

    token_pairs = {}

    for pair in all_pairs:

        base = pair.get("baseToken") or {}
        address = base.get("address")

        if not address:
            continue

        if address not in token_pairs:
            token_pairs[address] = []

        token_pairs[address].append(pair)

    alerts_sent = 0

    # -----------------------------------------------------
    # ANALİZ
    # -----------------------------------------------------

    for token_address, pairs in token_pairs.items():

        best_pair = choose_best_pair(
            pairs
        )

        if not best_pair:
            continue

        pair_address = best_pair.get(
            "pairAddress"
        )

        if not pair_address:
            continue

        # Önce hızlı filtre
        quick_data = extract_pair_data(
            best_pair
        )

        if not quick_data:
            continue

        if (
            quick_data["liquidity"] is None
            or quick_data["liquidity"] < MIN_LIQUIDITY
        ):
            continue

        if (
            quick_data["volume_1h"] is None
            or quick_data["volume_1h"] < MIN_1H_VOLUME
        ):
            continue

        if (
            quick_data["change_1h"] is None
        ):
            continue

        if (
            quick_data["change_1h"]
            < MIN_1H_MOVE
        ):
            continue

        if (
            quick_data["change_1h"]
            > MAX_1H_MOVE
        ):
            continue

        # -------------------------------------------------
        # EXACT PAIR
        # -------------------------------------------------

        exact_pair = get_exact_pair(
            pair_address
        )

        if not exact_pair:
            continue

        data = extract_pair_data(
            exact_pair
        )

        if not data:
            continue

        # Pair değişmişse tekrar kontrol
        if (
            data["pair_address"]
            != pair_address
        ):
            continue

        # -------------------------------------------------
        # ESKİ STATE
        # -------------------------------------------------

        state_key = pair_address

        old_state = state.get(
            state_key,
            {}
        )

        # -------------------------------------------------
        # AYNI COIN TEKRAR KONTROLÜ
        # -------------------------------------------------

        last_alert = safe_int(
            old_state.get(
                "last_alert",
                0
            ),
            0
        )

        hours_since_alert = (
            now_ts() - last_alert
        ) / 3600

        if (
            last_alert > 0
            and hours_since_alert
            < REPEAT_HOURS
        ):
            # State'i güncelle ama alarm verme
            state[state_key] = {
                **data,
                "last_seen": now_ts(),
                "last_alert": last_alert
            }

            continue

        # -------------------------------------------------
        # ANALİZ
        # -------------------------------------------------

        analysis = analyze(
            data,
            old_state
        )

        # -------------------------------------------------
        # STATE GÜNCELLE
        # -------------------------------------------------

        state[state_key] = {
            **data,
            "last_seen": now_ts(),
            "last_alert": last_alert
        }

        if not analysis:
            continue

        # -------------------------------------------------
        # TELEGRAM
        # -------------------------------------------------

        message = build_message(
            data,
            analysis
        )

        print(
            "\nALARM:",
            data["symbol"],
            "Score:",
            analysis["score"]
        )

        if send_telegram(message):

            state[state_key][
                "last_alert"
            ] = now_ts()

            alerts_sent += 1

        time.sleep(0.4)

    # -----------------------------------------------------
    # STATE KAYDET
    # -----------------------------------------------------

    save_state(state)

    print(
        f"\nToplam alarm: {alerts_sent}"
    )

    # GitHub Actions state'i sonraki çalışmaya taşısın
    git_save_state()

    print("Bot tamamlandı.")


if __name__ == "__main__":
    main()
