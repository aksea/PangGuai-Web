# --- core/client.py ---
import time
import httpx
from typing import Optional, Dict, Any
from .utils import sha256_encrypt

class PangGuaiClient:
    """封装 HTTPX，处理签名、User-Agent 和自动重试"""
    
    def __init__(self, token: str, ua: str):
        self.token = token
        self.ua = ua
        self.headers = {
            "Authorization": token,
            "Version": "1.60.3",
            "phoneBrand": "Redmi",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Host": "userapi.qiekj.com",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "User-Agent": ua,
            "X-Requested-With": "com.qiekj.user",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
        # 配置重试
        transport = httpx.AsyncHTTPTransport(retries=3)
        self.client = httpx.AsyncClient(
            transport=transport, 
            timeout=15.0,
            follow_redirects=True
        )

    async def aclose(self):
        await self.client.aclose()

    def _sign_android(self, timestamp: str, url: str) -> str:
        # 注意：url 参数只取 path 之后的部分
        # 假设传入的是完整 URL 或 path，这里做简单处理
        if "userapi.qiekj.com" in url:
            path_part = url.split("userapi.qiekj.com")[1]
        else:
            path_part = url
            
        raw = (
            "appSecret=nFU9pbG8YQoAe1kFh+E7eyrdlSLglwEJeA0wwHB1j5o=&channel=android_app"
            f"&timestamp={timestamp}&token={self.token}&version=1.60.3&{path_part[1:]}" # 去掉开头的 /
        )
        return sha256_encrypt(raw)

    def _sign_alipay(self, timestamp: str, url: str) -> str:
        if "userapi.qiekj.com" in url:
            path_part = url.split("userapi.qiekj.com")[1]
        else:
            path_part = url

        raw = (
            "appSecret=Ew+ZSuppXZoA9YzBHgHmRvzt0Bw1CpwlQQtSl49QNhY=&channel=alipay"
            f"&timestamp={timestamp}&token={self.token}&version=1.60.3&{path_part[1:]}"
        )
        return sha256_encrypt(raw)

    async def request(
        self, 
        method: str, 
        url: str, 
        data: Optional[Dict[str, Any]] = None, 
        channel: str = "android_app"
    ) -> Optional[Dict]:
        """
        :param channel: 'android_app' or 'alipay'
        """
        timestamp = str(int(time.time() * 1000))
        
        # 动态 Header
        headers = self.headers.copy()
        headers["timestamp"] = timestamp
        headers["channel"] = channel
        
        if "completed" in url:
            headers["Referer"] = "https://userapi.qiekj.com/task/list"
        else:
            headers["Referer"] = "https://userapi.qiekj.com"
            
        headers["Origin"] = "https://userapi.qiekj.com"

        # 签名
        if channel == "alipay":
            headers["sign"] = self._sign_alipay(timestamp, url)
        else:
            headers["sign"] = self._sign_android(timestamp, url)

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