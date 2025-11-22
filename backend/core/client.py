# --- core/client.py ---
import time
import httpx
from typing import Optional, Dict, Any
from .utils import sha256_encrypt

class PangGuaiClient:
    """
    封装 HTTPX
    严格对齐 `胖乖0903.py` 的签名逻辑和 Header 结构
    """

    def __init__(self, token: str, ua: str, device_id: Optional[str] = None):
        self.token = token
        self.ua = ua
        self.device_id = device_id
        # 保持与旧代码一致的重试逻辑
        transport = httpx.AsyncHTTPTransport(retries=3)
        self.client = httpx.AsyncClient(
            transport=transport,
            timeout=15.0,
            follow_redirects=True
        )

    async def aclose(self):
        await self.client.aclose()

    def _sign_common(self, timestamp: str, url: str, channel: str, secret: str) -> str:
        """
        签名逻辑修正：必须保留路径开头的斜杠 /
        旧代码逻辑：url[25:] -> /task/completed
        """
        # 移除域名部分，保留后面的所有内容（包括开头的 /）
        path_part = url.replace("https://userapi.qiekj.com", "")
        
        # 确保 path_part 以 / 开头 (防止传入的 url 本身不规范)
        if not path_part.startswith("/"):
            path_part = "/" + path_part

        raw = (
            f"appSecret={secret}&channel={channel}"
            f"&timestamp={timestamp}&token={self.token}&version=1.60.3&{path_part}"
        )
        return sha256_encrypt(raw)

    def _get_headers(self, channel: str, timestamp: str, sign: str) -> Dict[str, str]:
        """
        Header 构造修正：
        1. 移除 Origin, Referer, X-Requested-With 等网页特征头
        2. 严格复刻旧代码的字段
        """
        headers = {
            "Authorization": self.token,
            "Version": "1.60.3",
            "channel": channel,
            "phoneBrand": "Redmi",
            "timestamp": timestamp,
            "sign": sign,
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Host": "userapi.qiekj.com",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "User-Agent": self.ua,
        }
        return headers

    async def request(
        self,
        method: str,
        url: str,
        data: Optional[Dict[str, Any]] = None,
        channel: str = "android_app",
    ) -> Optional[Dict]:
        timestamp = str(int(time.time() * 1000))
        
        # 1. 计算签名 (Secret 区分)
        if channel == "alipay":
            secret = "Ew+ZSuppXZoA9YzBHgHmRvzt0Bw1CpwlQQtSl49QNhY="
            sign = self._sign_common(timestamp, url, "alipay", secret)
        else:
            secret = "nFU9pbG8YQoAe1kFh+E7eyrdlSLglwEJeA0wwHB1j5o="
            sign = self._sign_common(timestamp, url, "android_app", secret)

        # 2. 获取纯净的 Headers
        headers = self._get_headers(channel, timestamp, sign)

        try:
            if method.lower() == "get":
                resp = await self.client.get(url, headers=headers)
            else:
                resp = await self.client.post(url, headers=headers, data=data)

            if resp.status_code != 200:
                # 记录非200状态，辅助调试
                # print(f"HTTP Error: {resp.status_code} {resp.text}")
                return None

            res_json = resp.json()
            
            # 处理 Token 失效
            if res_json.get("msg") == "未登录":
                raise RuntimeError("Token 失效")

            return res_json
        except httpx.RequestError:
            return None
        except Exception:
            raise
