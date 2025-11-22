# --- core/utils.py ---
import hashlib
import random
import os

PASSWORD_SALT = os.getenv("PANGGUAI_PASSWORD_SALT", "pangguai_salt_v1")

# 红米机型 UA 池
REDMI_UA_POOL = [
    "Mozilla/5.0 (Linux; Android 11; M2012K11AC) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.88 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; 22041211AC) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 11; 2201117TY) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.104 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; 23049RAD8C) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Mobile Safari/537.36",
]

def get_random_ua() -> str:
    return random.choice(REDMI_UA_POOL)

def hash_password(password: str) -> str:
    return hashlib.sha256((password + PASSWORD_SALT).encode("utf-8")).hexdigest()

def verify_password(password: str, stored_hash: str) -> bool:
    new_hash = hash_password(password)
    if new_hash == stored_hash:
        return True
    # Legacy support
    legacy_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return legacy_hash == stored_hash

def sha256_encrypt(data: str) -> str:
    sha256 = hashlib.sha256()
    sha256.update(data.encode("utf-8"))
    return sha256.hexdigest()

def normalize_ua(ua: str) -> str:
    # 统一使用后端 UA 池，忽略前端 UA 输入
    return get_random_ua()
