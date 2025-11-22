# --- core/client.py ---
import time
import httpx
from typing import Optional, Dict, Any
from .utils import sha256_encrypt

class PangGuaiClient:
    """封装 HTTPX，请求按渠道精确构造 Header 并处理签名"""

    def __init__(self, token: str, ua: str):
        self.token = token
        self.ua = ua
        transport = httpx.AsyncHTTPTransport(retries=3)
        self.client = httpx.AsyncClient(
            transport=transport,
            timeout=15.0,
            follow_redirects=True,
            http2=True
        )

    async def aclose(self):
        await self.client.aclose()

    def _sign_common(self, timestamp: str, url: str, channel: str, secret: str) -> str:
        if "userapi.qiekj.com" in url:
            path_part = url.split("userapi.qiekj.com")[1]
        else:
            path_part = url
        clean_path = path_part[1:] if path_part.startswith("/") else path_part
        raw = (
            f"appSecret={secret}&channel={channel}"
            f"&timestamp={timestamp}&token={self.token}&version=1.60.3&{clean_path}"
        )
        return sha256_encrypt(raw)

    def _get_headers(self, channel: str, timestamp: str, sign: str, url: str) -> Dict[str, str]:
        headers = {
            "Authorization": self.token,
            "Version": "1.60.3",
            "channel": channel,
            "phoneBrand": "Redmi",
            "timestamp": timestamp,
            "sign": sign,
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Host": "userapi.qiekj.com",
            "Accept-Encoding": "gzip",
            "User-Agent": self.ua,
        }

        if channel == "alipay":
            # 支付宝渠道：保持最小化 Header，避免被判跨域
            return headers

        headers["Connection"] = "Keep-Alive"
        headers["X-Requested-With"] = "com.qiekj.user"
        headers["Sec-Fetch-Site"] = "same-origin"
        headers["Sec-Fetch-Mode"] = "cors"
        headers["Sec-Fetch-Dest"] = "empty"
        headers["Origin"] = "https://userapi.qiekj.com"
        headers["Referer"] = (
            "https://userapi.qiekj.com/task/list" if "completed" in url else "https://userapi.qiekj.com"
        )
        return headers

    async def request(
        self,
        method: str,
        url: str,
        data: Optional[Dict[str, Any]] = None,
        channel: str = "android_app",
    ) -> Optional[Dict]:
        timestamp = str(int(time.time() * 1000))
        if channel == "alipay":
            secret = "Ew+ZSuppXZoA9YzBHgHmRvzt0Bw1CpwlQQtSl49QNhY="
            sign = self._sign_common(timestamp, url, "alipay", secret)
        else:
            secret = "nFU9pbG8YQoAe1kFh+E7eyrdlSLglwEJeA0wwHB1j5o="
            sign = self._sign_common(timestamp, url, "android_app", secret)

        headers = self._get_headers(channel, timestamp, sign, url)

        try:
            if method.lower() == "get":
                resp = await self.client.get(url, headers=headers)
            else:
                resp = await self.client.post(url, headers=headers, data=data)

            if resp.status_code != 200:
                return None

            res_json = resp.json()
            if res_json.get("msg") == "未登录":
                raise RuntimeError("Token 失效")

            return res_json
        except httpx.RequestError:
            return None
        except Exception:
            raise
