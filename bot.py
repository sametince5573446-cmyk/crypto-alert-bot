import os
import json
import time
import subprocess
from datetime import datetime

import requests


# =========================================================
# TELEGRAM
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# =========================================================
# API
# =========================================================

DEX_BASE = "https://api.dexscreener.com"

SOLANA_RPC = "https://api.mainnet-beta.solana.com"


# =========================================================
# DOSYALAR
# =========================================================

STATE_FILE = "solana_alerts.json"
WALLET_FILE = "smart_wallets.json"


# =========================================================
# GENEL AYARLAR
# =========================================================

MAX_TOKENS = 100

REPEAT_HOURS = 24

MIN_LIQUIDITY = 10000

MIN_1H_VOLUME = 5000

MIN_1H_MOVE = 3

MAX_1H_MOVE = 25

MAX_24H_MOVE = 40

MIN_VOLUME_ACCELERATION = 2.5

MIN_SCORE = 7

MIN_PAIR_AGE_MINUTES = 5


# =========================================================
# SMART MONEY
# =========================================================

# Her pair için incelenecek maksimum işlem
MAX_WALLET_TRANSACTIONS = 20

# Bir cüzdanın takip listesine girebilmesi için
MIN_WALLET_SCORE = 5

# Başarılı erken giriş sayısı
SMART_SUCCESS_THRESHOLD = 2

# Bir tokenin erken alıcısı sayılacağı maksimum yükseliş
EARLY_BUY_MAX_MOVE = 15

# Daha sonra token bu seviyeye ulaşırsa başarılı giriş say
SUCCESS_MOVE = 30

# Aynı cüzdanın çok fazla işlem yapmasını önle
WALLET_COOLDOWN_SECONDS = 300


session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0 SolanaRadar/1.0"
})


# =========================================================
# GENEL YARDIMCI
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

    if not TELEGRAM_BOT_TOKEN:

        print("TELEGRAM_BOT_TOKEN yok.")

        return False

    if not TELEGRAM_CHAT_ID:

        print("TELEGRAM_CHAT_ID yok.")

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

        print(
            "Telegram hata:",
            response.text
        )

        return False

    except Exception as e:

        print(
            "Telegram bağlantı hatası:",
            e
        )

        return False


# =========================================================
# DOSYA OKUMA / YAZMA
# =========================================================

def load_json(filename):

    if not os.path.exists(filename):

        return {}

    try:

        with open(
            filename,
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(file)

    except Exception:

        return {}


def save_json(filename, data):

    try:

        with open(
            filename,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print(
            "Dosya kayıt hatası:",
            filename,
            e
        )


# =========================================================
# DEXSCREENER
# =========================================================

def get_latest_profiles():

    url = (
        f"{DEX_BASE}/token-profiles/latest/v1"
    )

    try:

        response = session.get(
            url,
            timeout=20
        )

        if response.status_code != 200:

            return []

        data = response.json()

        if not isinstance(data, list):

            return []

        return data

    except Exception as e:

        print(
            "Profiles hata:",
            e
        )

        return []


def get_token_pairs(addresses):

    if not addresses:

        return []

    address_text = ",".join(addresses)

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

            return []

        data = response.json()

        if not isinstance(data, list):

            return []

        return data

    except Exception as e:

        print(
            "Token pair hata:",
            e
        )

        return []


def get_exact_pair(pair_address):

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

    except Exception:

        return None


def choose_best_pair(pairs):

    if not pairs:

        return None

    solana_pairs = [

        pair
        for pair in pairs

        if pair.get("chainId") == "solana"

    ]

    if not solana_pairs:

        return None

    best = None

    best_liquidity = -1

    for pair in solana_pairs:

        liquidity = safe_float(
            (pair.get("liquidity") or {}).get("usd"),
            0
        )

        if liquidity > best_liquidity:

            best_liquidity = liquidity

            best = pair

    return best


# =========================================================
# PAIR VERİSİ
# =========================================================

def extract_pair_data(pair):

    if not pair:

        return None

    price_change = (
        pair.get("priceChange") or {}
    )

    volume = (
        pair.get("volume") or {}
    )

    txns = (
        pair.get("txns") or {}
    )

    liquidity_data = (
        pair.get("liquidity") or {}
    )

    base_token = (
        pair.get("baseToken") or {}
    )

    symbol = (
        base_token.get("symbol")
        or "UNKNOWN"
    )

    name = (
        base_token.get("name")
        or symbol
    )

    pair_address = pair.get(
        "pairAddress"
    )

    token_address = base_token.get(
        "address"
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

    tx_5m = txns.get("m5") or {}

    tx_15m = txns.get("m15") or {}

    tx_1h = txns.get("h1") or {}

    buys_5m = safe_int(
        tx_5m.get("buys")
    )

    sells_5m = safe_int(
        tx_5m.get("sells")
    )

    buys_15m = safe_int(
        tx_15m.get("buys")
    )

    sells_15m = safe_int(
        tx_15m.get("sells")
    )

    buys_1h = safe_int(
        tx_1h.get("buys")
    )

    sells_1h = safe_int(
        tx_1h.get("sells")
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

            pair_age_minutes = (
                now_ts()
                - (int(pair_created_at) / 1000)
            ) / 60

        except Exception:

            pass

    boosts = (
        pair.get("boosts") or {}
    )

    boost_active = safe_int(
        boosts.get("active")
    )

    info = (
        pair.get("info") or {}
    )

    socials = (
        info.get("socials") or []
    )

    return {

        "symbol": symbol,

        "name": name,

        "token_address": token_address,

        "pair_address": pair_address,

        "change_5m": change_5m,

        "change_1h": change_1h,

        "change_6h": change_6h,

        "change_24h": change_24h,

        "volume_5m": volume_5m,

        "volume_1h": volume_1h,

        "buys_5m": buys_5m,

        "sells_5m": sells_5m,

        "buys_15m": buys_15m,

        "sells_15m": sells_15m,

        "buys_1h": buys_1h,

        "sells_1h": sells_1h,

        "liquidity": liquidity,

        "pair_age_minutes":
            pair_age_minutes,

        "boost_active":
            boost_active,

        "socials":
            socials,

        "url":
            pair.get("url")
    }


# =========================================================
# ORANLAR
# =========================================================

def ratio(buys, sells):

    if sells <= 0:

        if buys > 0:

            return 99

        return None

    return buys / sells


def volume_acceleration(
    volume_5m,
    volume_1h
):

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
# SOLANA RPC
# =========================================================

def rpc_call(
    method,
    params
):

    payload = {

        "jsonrpc": "2.0",

        "id": 1,

        "method": method,

        "params": params
    }

    try:

        response = session.post(
            SOLANA_RPC,
            json=payload,
            timeout=25
        )

        if response.status_code != 200:

            return None

        data = response.json()

        return data.get("result")

    except Exception as e:

        print(
            "RPC hata:",
            e
        )

        return None


# =========================================================
# PAIR İŞLEMLERİ
# =========================================================

def get_pair_signatures(
    pair_address,
    limit=MAX_WALLET_TRANSACTIONS
):

    return rpc_call(

        "getSignaturesForAddress",

        [
            pair_address,

            {
                "limit": limit,

                "commitment": "confirmed"
            }
        ]
    )


def get_transaction(signature):

    return rpc_call(

        "getTransaction",

        [
            signature,

            {
                "encoding": "jsonParsed",

                "commitment": "confirmed",

                "maxSupportedTransactionVersion": 0
            }
        ]
    )


# =========================================================
# İŞLEMDEKİ SIGNER
# =========================================================

def get_transaction_signer(tx):

    try:

        message = (
            tx["transaction"]
            ["message"]
        )

        account_keys = (
            message
            ["accountKeys"]
        )

        for account in account_keys:

            if account.get(
                "signer"
            ):

                return account.get(
                    "pubkey"
                )

    except Exception:

        pass

    return None


# =========================================================
# TOKEN BALANCE DEĞİŞİMİ
# =========================================================

def token_balance_change(
    tx,
    token_address,
    owner
):

    try:

        meta = tx.get("meta")

        if not meta:

            return 0

        pre = (
            meta.get(
                "preTokenBalances"
            )
            or []
        )

        post = (
            meta.get(
                "postTokenBalances"
            )
            or []
        )

        pre_amount = 0

        post_amount = 0

        for item in pre:

            if (
                item.get("mint")
                == token_address
                and item.get("owner")
                == owner
            ):

                ui = (
                    item.get(
                        "uiTokenAmount"
                    )
                    or {}
                )

                pre_amount += (
                    safe_float(
                        ui.get(
                            "uiAmount"
                        ),
                        0
                    )
                )

        for item in post:

            if (
                item.get("mint")
                == token_address
                and item.get("owner")
                == owner
            ):

                ui = (
                    item.get(
                        "uiTokenAmount"
                    )
                    or {}
                )

                post_amount += (
                    safe_float(
                        ui.get(
                            "uiAmount"
                        ),
                        0
                    )
                )

        return post_amount - pre_amount

    except Exception:

        return 0


# =========================================================
# ERKEN ALICI CÜZDANLARI
# =========================================================

def discover_wallets(data):

    pair_address = data.get(
        "pair_address"
    )

    token_address = data.get(
        "token_address"
    )

    if not pair_address:
        return []

    if not token_address:
        return []

    signatures = get_pair_signatures(
        pair_address
    )

    if not signatures:

        return []

    wallets = []

    checked = 0

    for signature_data in signatures:

        signature = signature_data.get(
            "signature"
        )

        if not signature:

            continue

        tx = get_transaction(
            signature
        )

        if not tx:

            continue

        signer = get_transaction_signer(
            tx
        )

        if not signer:

            continue

        change = token_balance_change(
            tx,
            token_address,
            signer
        )

        # Token miktarı artıyorsa
        # olası alıcı
        if change > 0:

            wallets.append({
                "wallet": signer,

                "signature": signature,

                "change": change,

                "block_time":
                    tx.get(
                        "blockTime"
                    )
            })

        checked += 1

        if checked >= MAX_WALLET_TRANSACTIONS:

            break

        time.sleep(0.15)

    return wallets


# =========================================================
# SMART MONEY STATE
# =========================================================

def get_wallet_record(
    wallets,
    address
):

    if address not in wallets:

        wallets[address] = {

            "score": 0,

            "early_buys": 0,

            "successful_buys": 0,

            "coins_seen": 0,

            "last_seen": 0,

            "tokens": {}
        }

    return wallets[address]


# =========================================================
# CÜZDANLARI ÖĞREN
# =========================================================

def learn_wallets(
    data,
    wallets,
    state
):

    discovered = discover_wallets(
        data
    )

    if not discovered:

        return []

    token_address = data[
        "token_address"
    ]

    symbol = data[
        "symbol"
    ]

    current_move = data[
        "change_1h"
    ]

    if current_move is None:

        current_move = 0

    smart_now = []

    for item in discovered:

        wallet = item[
            "wallet"
        ]

        record = get_wallet_record(
            wallets,
            wallet
        )

        # Cooldown
        if (
            now_ts()
            - record.get(
                "last_seen",
                0
            )
            < WALLET_COOLDOWN_SECONDS
        ):

            continue

        record["last_seen"] = now_ts()

        record["coins_seen"] = (
            record.get(
                "coins_seen",
                0
            ) + 1
        )

        record["early_buys"] = (
            record.get(
                "early_buys",
                0
            ) + 1
        )

        # İlk giriş kaydı
        if token_address not in record[
            "tokens"
        ]:

            record[
                "tokens"
            ][token_address] = {

                "symbol": symbol,

                "entry_move":
                    current_move,

                "entry_time":
                    now_ts(),

                "success": False
            }

        # İlk etapta erken alıcı
        if current_move <= EARLY_BUY_MAX_MOVE:

            record["score"] = (
                record.get(
                    "score",
                    0
                ) + 1
            )

        # Başarılı eski kayıtları kontrol
        for old_token, trade in list(
            record["tokens"].items()
        ):

            if trade.get(
                "success"
            ):

                continue

            entry_move = safe_float(
                trade.get(
                    "entry_move"
                ),
                0
            )

            if (
                current_move >=
                entry_move + SUCCESS_MOVE
            ):

                trade["success"] = True

                record[
                    "successful_buys"
                ] = (
                    record.get(
                        "successful_buys",
                        0
                    ) + 1
                )

                record["score"] = (
                    record.get(
                        "score",
                        0
                    ) + 3
                )

        if (
            record.get(
                "score",
                0
            ) >= MIN_WALLET_SCORE
        ):

            smart_now.append(
                wallet
            )

    return smart_now


# =========================================================
# SMART MONEY SKORU
# =========================================================

def smart_money_score(
    discovered_wallets,
    wallets
):

    strong = []

    medium = []

    for wallet in discovered_wallets:

        record = wallets.get(
            wallet
        )

        if not record:

            continue

        score = record.get(
            "score",
            0
        )

        successful = record.get(
            "successful_buys",
            0
        )

        if (
            successful
            >= SMART_SUCCESS_THRESHOLD
        ):

            strong.append(wallet)

        elif score >= MIN_WALLET_SCORE:

            medium.append(wallet)

    score = 0

    if len(strong) >= 3:

        score += 4

    elif len(strong) >= 2:

        score += 3

    elif len(strong) >= 1:

        score += 2

    if len(medium) >= 3:

        score += 2

    elif len(medium) >= 2:

        score += 1

    return score, strong, medium


# =========================================================
# HACİM / LİKİDİTE DEĞİŞİMİ
# =========================================================

def state_changes(
    old,
    data
):

    volume_change = None

    liquidity_change = None

    old_volume = safe_float(
        old.get("volume_1h")
    )

    new_volume = safe_float(
        data.get("volume_1h")
    )

    old_liquidity = safe_float(
        old.get("liquidity")
    )

    new_liquidity = safe_float(
        data.get("liquidity")
    )

    if (
        old_volume
        and new_volume
        and old_volume > 0
    ):

        volume_change = (
            (
                new_volume
                - old_volume
            )
            / old_volume
        ) * 100

    if (
        old_liquidity
        and new_liquidity
        and old_liquidity > 0
    ):

        liquidity_change = (
            (
                new_liquidity
                - old_liquidity
            )
            / old_liquidity
        ) * 100

    return (
        volume_change,
        liquidity_change
    )


# =========================================================
# ANA ANALİZ
# =========================================================

def analyze(
    data,
    old,
    wallets
):

    score = 0

    reasons = []

    warnings = []

    # -----------------------------------------------------
    # VERİ
    # -----------------------------------------------------

    move_1h = data[
        "change_1h"
    ]

    move_5m = data[
        "change_5m"
    ]

    move_24h = data[
        "change_24h"
    ]

    volume_1h = data[
        "volume_1h"
    ]

    volume_5m = data[
        "volume_5m"
    ]

    liquidity = data[
        "liquidity"
    ]

    if move_1h is None:
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
    # PUMP KONTROL
    # -----------------------------------------------------

    if move_1h > MAX_1H_MOVE:
        return None

    if (
        move_24h is not None
        and move_24h > MAX_24H_MOVE
    ):
        return None

    # -----------------------------------------------------
    # YAŞ
    # -----------------------------------------------------

    age = data[
        "pair_age_minutes"
    ]

    if (
        age is not None
        and age < MIN_PAIR_AGE_MINUTES
    ):

        return None

    # -----------------------------------------------------
    # YÖN
    # -----------------------------------------------------

    if move_1h < MIN_1H_MOVE:
        return None

    if (
        move_5m is not None
        and move_5m <= -5
    ):

        return None

    # -----------------------------------------------------
    # HACİM
    # -----------------------------------------------------

    acceleration = (
        volume_acceleration(
            volume_5m,
            volume_1h
        )
    )

    if acceleration is not None:

        if acceleration >= 6:

            score += 3

            reasons.append(
                "Son dakikalarda hacim çok hızlandı."
            )

        elif acceleration >= 3:

            score += 2

            reasons.append(
                "Hacim belirgin şekilde hızlanıyor."
            )

        elif acceleration >= 2.5:

            score += 1

    # -----------------------------------------------------
    # ALICI / SATICI
    # -----------------------------------------------------

    r5 = ratio(
        data["buys_5m"],
        data["sells_5m"]
    )

    r15 = ratio(
        data["buys_15m"],
        data["sells_15m"]
    )

    r1 = ratio(
        data["buys_1h"],
        data["sells_1h"]
    )

    if r5 is not None:

        if r5 >= 3:

            score += 3

            reasons.append(
                "5 dakikada alıcı baskısı güçlü."
            )

        elif r5 >= 2:

            score += 2

            reasons.append(
                "5 dakikada alıcılar üstün."
            )

        elif r5 >= 1.2:

            score += 1

        elif r5 < 1:

            score -= 2

            warnings.append(
                "5 dakikada satıcılar üstün."
            )

    if r15 is not None:

        if r15 >= 2:

            score += 2

        elif r15 >= 1.3:

            score += 1

        elif r15 < 1:

            score -= 1

    if r1 is not None:

        if r1 >= 1.5:

            score += 2

        elif r1 >= 1.2:

            score += 1

        elif r1 < 1:

            score -= 1

    # -----------------------------------------------------
    # İŞLEM AKTİVİTESİ
    # -----------------------------------------------------

    total_5m = (
        data["buys_5m"]
        + data["sells_5m"]
    )

    if total_5m >= 300:

        score += 2

        reasons.append(
            "Son 5 dakikada işlem aktivitesi yüksek."
        )

    elif total_5m >= 100:

        score += 1

    # -----------------------------------------------------
    # FİYAT
    # -----------------------------------------------------

    if 5 <= move_1h <= 15:

        score += 2

        reasons.append(
            "Fiyat hareketi başladı fakat henüz aşırı değil."
        )

    elif 15 < move_1h <= 25:

        score += 1

        warnings.append(
            "Fiyat zaten yükselmiş durumda."
        )

    # -----------------------------------------------------
    # LİKİDİTE
    # -----------------------------------------------------

    if liquidity >= 50000:

        score += 2

    elif liquidity >= 25000:

        score += 1

    # -----------------------------------------------------
    # SOSYAL
    # -----------------------------------------------------

    if data["socials"]:

        score += 1

        reasons.append(
            "Token için sosyal bağlantılar mevcut."
        )

    # -----------------------------------------------------
    # BOOST
    # -----------------------------------------------------

    if data[
        "boost_active"
    ] > 0:

        score += 1

        reasons.append(
            "DEX Screener Boost aktif."
        )

    # -----------------------------------------------------
    # STATE
    # -----------------------------------------------------

    volume_change, liquidity_change = (
        state_changes(
            old,
            data
        )
    )

    if (
        liquidity_change is not None
    ):

        if liquidity_change <= -15:

            score -= 3

            warnings.append(
                "Likidite ciddi şekilde düşmüş."
            )

        elif liquidity_change >= 10:

            score += 1

            reasons.append(
                "Likidite artıyor."
            )

    if (
        volume_change is not None
        and volume_change >= 20
    ):

        score += 1

        reasons.append(
            "Önceki taramaya göre hacim artıyor."
        )

    # -----------------------------------------------------
    # SMART MONEY
    # -----------------------------------------------------

    discovered = discover_wallets(
        data
    )

    smart_score, strong_wallets, medium_wallets = (
        smart_money_score(
            discovered,
            wallets
        )
    )

    score += smart_score

    if len(strong_wallets) >= 3:

        reasons.append(
            f"{len(strong_wallets)} güçlü cüzdan hareket halinde."
        )

    elif len(strong_wallets) >= 1:

        reasons.append(
            f"{len(strong_wallets)} takip edilen güçlü cüzdan alım yapmış olabilir."
        )

    elif len(medium_wallets) >= 2:

        reasons.append(
            "Birden fazla takip edilen cüzdan görüldü."
        )

    # -----------------------------------------------------
    # SON FİLTRE
    # -----------------------------------------------------

    if (
        move_5m is not None
        and move_5m < -2
    ):

        warnings.append(
            "Son 5 dakikada geri çekilme var."
        )

    if r5 is not None and r5 < 0.9:

        return None

    if score < MIN_SCORE:

        return None

    return {

        "score": score,

        "reasons": reasons,

        "warnings": warnings,

        "ratio_5m": r5,

        "ratio_15m": r15,

        "ratio_1h": r1,

        "volume_acceleration":
            acceleration,

        "volume_change":
            volume_change,

        "liquidity_change":
            liquidity_change,

        "strong_wallets":
            strong_wallets,

        "medium_wallets":
            medium_wallets
    }


# =========================================================
# TELEGRAM MESAJ
# =========================================================

def build_message(
    data,
    analysis
):

    symbol = data[
        "symbol"
    ]

    message = (
        "🚨 ERKEN UYARI — SOLANA\n\n"
    )

    message += (
        f"🪙 {symbol}\n\n"
    )

    message += (
        f"📈 1 saat: "
        f"{format_percent(data['change_1h'])}\n"
    )

    if data[
        "change_5m"
    ] is not None:

        message += (
            f"📈 5 dakika: "
            f"{format_percent(data['change_5m'])}\n"
        )

    acceleration = analysis[
        "volume_acceleration"
    ]

    if acceleration is not None:

        message += (
            f"\n🔥 Hacim ivmesi: "
            f"{acceleration:.1f}x\n"
        )

    message += (
        f"\n👥 5dk Alıcı: "
        f"{data['buys_5m']}\n"

        f"🔻 5dk Satıcı: "
        f"{data['sells_5m']}\n"
    )

    r5 = analysis[
        "ratio_5m"
    ]

    if r5 is not None:

        message += (
            f"⚖️ Alıcı/Satıcı: "
            f"{r5:.1f}x\n"
        )

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
            "\n👥 15dk veri: "
            "VERİ YOK\n"
        )

    message += (
        f"\n💧 Likidite: "
        f"{format_money(data['liquidity'])}\n"
    )

    if (
        analysis[
            "liquidity_change"
        ] is not None
    ):

        message += (
            f"📊 Likidite: "
            f"{format_percent(analysis['liquidity_change'])}\n"
        )

    # -----------------------------------------------------
    # SMART MONEY
    # -----------------------------------------------------

    strong = analysis[
        "strong_wallets"
    ]

    medium = analysis[
        "medium_wallets"
    ]

    if strong or medium:

        message += (
            "\n👛 SMART MONEY\n"
        )

        message += (
            f"🟢 Güçlü: "
            f"{len(strong)}\n"
        )

        message += (
            f"🟡 Takip edilen: "
            f"{len(medium)}\n"
        )

    # -----------------------------------------------------
    # NEDEN
    # -----------------------------------------------------

    message += (
        "\n💡 Neden dikkat çekti?\n"
    )

    used = set()

    for reason in analysis[
        "reasons"
    ][:6]:

        if reason in used:

            continue

        used.add(reason)

        message += (
            f"• {reason}\n"
        )

    for warning in analysis[
        "warnings"
    ][:2]:

        message += (
            f"⚠️ {warning}\n"
        )

    score = analysis[
        "score"
    ]

    if score >= 10:

        level = (
            "🚀 ÇOK GÜÇLÜ"
        )

    elif score >= 8:

        level = (
            "🟢 GÜÇLÜ"
        )

    else:

        level = (
            "🟡 ERKEN AŞAMA"
        )

    message += (
        f"\n{level}\n\n"
    )

    message += (
        "⚠️ Meme coin — çok yüksek risk\n"
        "📍 Solana\n"
        "🔎 Phantom'dan kontratı kontrol et.\n"
    )

    if data["url"]:

        message += (
            "\n🔗 DEX Screener:\n"
            f"{data['url']}"
        )

    return message


# =========================================================
# GIT
# =========================================================

def git_save():

    try:

        subprocess.run(
            [
                "git",
                "config",
                "user.name",
                "crypto-alert-bot"
            ],
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
            [
                "git",
                "add",
                STATE_FILE,
                WALLET_FILE
            ],
            check=False
        )

        result = subprocess.run(
            [
                "git",
                "commit",
                "-m",
                "Update Solana radar state"
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

        print(
            "Git hata:",
            e
        )


# =========================================================
# ANA
# =========================================================

def main():

    print(
        "================================"
    )

    print(
        "SOLANA EARLY WARNING RADAR"
    )

    print(
        "SMART MONEY LEARNING AKTİF"
    )

    print(
        "================================"
    )

    state = load_json(
        STATE_FILE
    )

    wallets = load_json(
        WALLET_FILE
    )

    profiles = get_latest_profiles()

    if not profiles:

        print(
            "Token profilleri alınamadı."
        )

        return

    # -----------------------------------------------------
    # SOLANA TOKENLARI
    # -----------------------------------------------------

    selected = []

    seen = set()

    for profile in profiles:

        if profile.get(
            "chainId"
        ) != "solana":

            continue

        address = profile.get(
            "tokenAddress"
        )

        if not address:

            continue

        if address in seen:

            continue

        seen.add(address)

        selected.append(
            address
        )

        if len(selected) >= MAX_TOKENS:

            break

    print(
        f"{len(selected)} token taranıyor..."
    )

    # -----------------------------------------------------
    # 30'LU GRUPLAR
    # -----------------------------------------------------

    all_pairs = []

    for i in range(
        0,
        len(selected),
        30
    ):

        batch = selected[
            i:i + 30
        ]

        pairs = get_token_pairs(
            batch
        )

        all_pairs.extend(
            pairs
        )

        time.sleep(
            0.5
        )

    print(
        f"{len(all_pairs)} pair bulundu."
    )

    # -----------------------------------------------------
    # TOKEN → PAIR
    # -----------------------------------------------------

    grouped = {}

    for pair in all_pairs:

        base = (
            pair.get("baseToken")
            or {}
        )

        address = base.get(
            "address"
        )

        if not address:

            continue

        grouped.setdefault(
            address,
            []
        ).append(pair)

    alerts = 0

    # -----------------------------------------------------
    # ANALİZ
    # -----------------------------------------------------

    for token_address, pairs in grouped.items():

        best = choose_best_pair(
            pairs
        )

        if not best:

            continue

        pair_address = best.get(
            "pairAddress"
        )

        if not pair_address:

            continue

        quick = extract_pair_data(
            best
        )

        if not quick:

            continue

        # Hızlı filtre
        if (
            quick["liquidity"]
            is None
            or quick["liquidity"]
            < MIN_LIQUIDITY
        ):

            continue

        if (
            quick["volume_1h"]
            is None
            or quick["volume_1h"]
            < MIN_1H_VOLUME
        ):

            continue

        if (
            quick["change_1h"]
            is None
        ):

            continue

        if (
            quick["change_1h"]
            < MIN_1H_MOVE
        ):

            continue

        if (
            quick["change_1h"]
            > MAX_1H_MOVE
        ):

            continue

        # -------------------------------------------------
        # EXACT PAIR
        # -------------------------------------------------

        exact = get_exact_pair(
            pair_address
        )

        if not exact:

            continue

        data = extract_pair_data(
            exact
        )

        if not data:

            continue

        if (
            data["pair_address"]
            != pair_address
        ):

            continue

        # -------------------------------------------------
        # STATE
        # -------------------------------------------------

        key = pair_address

        old = state.get(
            key,
            {}
        )

        last_alert = safe_int(
            old.get(
                "last_alert",
                0
            )
        )

        # -------------------------------------------------
        # SMART MONEY ÖĞRENME
        # -------------------------------------------------

        try:

            learn_wallets(
                data,
                wallets,
                state
            )

        except Exception as e:

            print(
                "Wallet öğrenme hatası:",
                e
            )

        # -------------------------------------------------
        # ANALİZ
        # -------------------------------------------------

        try:

            analysis = analyze(
                data,
                old,
                wallets
            )

        except Exception as e:

            print(
                "Analiz hatası:",
                e
            )

            analysis = None

        # State
        state[key] = {

            **data,

            "last_seen":
                now_ts(),

            "last_alert":
                last_alert
        }

        # Sinyal yok
        if not analysis:

            continue

        # -------------------------------------------------
        # TEKRAR KONTROL
        # -------------------------------------------------

        if last_alert > 0:

            elapsed = (
                now_ts()
                - last_alert
            ) / 3600

            if elapsed < REPEAT_HOURS:

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

        sent = send_telegram(
            message
        )

        if sent:

            state[key][
                "last_alert"
            ] = now_ts()

            alerts += 1

        time.sleep(
            0.5
        )

    # -----------------------------------------------------
    # KAYDET
    # -----------------------------------------------------

    save_json(
        STATE_FILE,
        state
    )

    save_json(
        WALLET_FILE,
        wallets
    )

    print(
        "\nToplam alarm:",
        alerts
    )

    git_save()

    print(
        "Bot tamamlandı."
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    main()
