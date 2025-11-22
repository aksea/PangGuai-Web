# --- core/utils.py ---
import hashlib
import os
import random
import uuid

PASSWORD_SALT = os.getenv("PANGGUAI_PASSWORD_SALT", "pangguai_salt_v1")

# 增加旧代码中验证通过的 UA
REDMI_UA_POOL = [
    "Mozilla/5.0 (Linux; Android 10; Redmi K30 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.106 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 11; Redmi K30 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.85 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; M2012K11AC Build/SKQ1.211006.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.5481.63 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Redmi Note 12 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.5735.196 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 10; M2007J3SC Build/QP1A.190711.020) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; 22011211C Build/SKQ1.211006.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.5563.116 Mobile Safari/537.36",
]

def get_random_ua() -> str:
    return random.choice(REDMI_UA_POOL)

def generate_device_id() -> str:
    """生成 16 位十六进制 Device ID，模拟安卓设备标识"""
    return uuid.uuid4().hex[:16]

def hash_password(password: str) -> str:
    return hashlib.sha256((password + PASSWORD_SALT).encode("utf-8")).hexdigest()

def verify_password(password: str, stored_hash: str) -> bool:
    new_hash = hash_password(password)
    if new_hash == stored_hash: return True
    return hashlib.sha256(password.encode("utf-8")).hexdigest() == stored_hash

def sha256_encrypt(data: str) -> str:
    sha256 = hashlib.sha256()
    sha256.update(data.encode("utf-8"))
    return sha256.hexdigest()

def normalize_ua(_: str = "") -> str:
    """保持兼容的随机 UA 生成入口"""
    return get_random_ua()
