from __future__ import annotations

import hashlib
import random
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# 红米机型 UA 池（保持 phoneBrand=Redmi 一致），随机分配降低指纹一致性。
REDMI_UA_POOL = [
    "Mozilla/5.0 (Linux; Android 11; M2012K11AC) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.88 Mobile Safari/537.36",  # K40
    "Mozilla/5.0 (Linux; Android 12; 22041211AC) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Mobile Safari/537.36",  # K50
    "Mozilla/5.0 (Linux; Android 11; 2201117TY) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.104 Mobile Safari/537.36",  # Note 11
    "Mozilla/5.0 (Linux; Android 13; 23049RAD8C) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Mobile Safari/537.36",  # Note 12
]


def get_random_ua() -> str:
    return random.choice(REDMI_UA_POOL)


@dataclass
class RunOptions:
    video: bool = True
    alipay: bool = True


def sha256_encrypt(data: str) -> str:
    sha256 = hashlib.sha256()
    sha256.update(data.encode("utf-8"))
    return sha256.hexdigest()


class PangGuaiRunner:
    """
    封装胖乖脚本为可复用类，保留时间间隔，按需推送日志。
    """

    def __init__(
        self,
        token: str,
        ua: str,
        options: Optional[RunOptions] = None,
        logger: Optional[Callable[[str], None]] = None,
    ) -> None:
        # 业务关键参数：用户鉴权 token + UA
        self.token = token
        self.ua = self._normalize_ua(ua)
        self.options = options or RunOptions()
        self.log = logger or (lambda msg: None)
        self.stop_flag = False
        self.excluded_task_codes = {
            "7328b1db-d001-4e6a-a9e6-6ae8d281ddbf",
            "e8f837b8-4317-4bf5-89ca-99f809bf9041",
            "65a4e35d-c8ae-4732-adb7-30f8788f2ea7",
            "73f9f146-4b9a-4d14-9d81-3a83f1204b74",
            "12e8c1e4-65d9-45f2-8cc1-16763e710036",
        }
        self.session = self._build_session()

    def stop(self) -> None:
        """外部调用此方法来终止任务"""
        self.stop_flag = True
        self.log("🛑 正在尝试停止任务，请稍候...")

    def _check_stop(self) -> None:
        if self.stop_flag:
            raise InterruptedError("用户手动停止任务")

    def _normalize_ua(self, ua: str) -> str:
        ua_str = (ua or "").strip()
        lower = ua_str.lower()
        is_pc = ("windows" in lower) or ("macintosh" in lower) or ("mac os" in lower)
        has_android = "android" in lower
        if not ua_str or (is_pc and not has_android):
            selected = get_random_ua()
            self.log(f"已自动切换为移动端 UA")
            return selected
        return ua_str

    def _build_session(self) -> requests.Session:
        """使用带重试的 Session，避免偶发 5xx/429 导致流程中断。"""
        session = requests.Session()
        retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def sign_android(self, timestamp: str, url: str) -> str:
        """生成安卓渠道签名，规则与参考脚本一致。"""
        return sha256_encrypt(
            "appSecret=nFU9pbG8YQoAe1kFh+E7eyrdlSLglwEJeA0wwHB1j5o=&channel=android_app"
            f"&timestamp={timestamp}&token={self.token}&version=1.60.3&{url[25:]}"
        )

    def sign_alipay(self, timestamp: str, url: str) -> str:
        """生成支付宝渠道签名。"""
        return sha256_encrypt(
            "appSecret=Ew+ZSuppXZoA9YzBHgHmRvzt0Bw1CpwlQQtSl49QNhY=&channel=alipay"
            f"&timestamp={timestamp}&token={self.token}&version=1.60.3&{url[25:]}"
        )

    def httprequests(self, url: str, data: Optional[Dict[str, str]] = None, method: str = "post") -> Optional[dict]:
        """统一封装 HTTP 请求：带签名、UA、超时和简单错误处理。"""
        t = str(int(time.time() * 1000))
        sign = self.sign_android(t, url)
        headers = {
            "Authorization": self.token,
            "Version": "1.60.3",
            "channel": "android_app",
            "phoneBrand": "Redmi",
            "timestamp": t,
            "sign": sign,
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Host": "userapi.qiekj.com",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "Origin": "https://userapi.qiekj.com",
            "X-Requested-With": "com.qiekj.user",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "User-Agent": self.ua,
        }
        try:
            if method == "get":
                res = self.session.get(url=url, headers=headers, timeout=10)
            else:
                res = self.session.post(url=url, headers=headers, data=data, timeout=10)
            if res.status_code != 200:
                self.log(f"[HTTP {method}] {url} 状态码 {res.status_code}，响应: {res.text}")
                return None
            res_json = res.json()
            if res_json.get("msg") == "未登录":
                raise RuntimeError("Token 失效，请重新登录")
            self.log(f"[HTTP {method}] {url} 返回: {res_json}")
            return res_json
        except Exception as exc:
            self.log(f"请求异常: {exc}")
            raise

    def get_username(self) -> Optional[str]:
        url = "https://userapi.qiekj.com/user/info"
        res = self.httprequests(url=url, data={"token": self.token}, method="post")
        if res and res.get("code") == 0:
            username = res["data"].get("userName")
            if username:
                self.log(f"用户：{username}")
            else:
                self.log("请去设置账号昵称")
            return username
        return None

    def balance(self) -> int:
        """获取积分余额，便于统计收益。"""
        url = "https://userapi.qiekj.com/user/balance"
        res = self.httprequests(url=url, data={"token": self.token}, method="post")
        if res and res.get("code") == 0:
            return int(res["data"]["integral"])
        return 0

    def do_signin(self) -> None:
        url = "https://userapi.qiekj.com/signin/doUserSignIn"
        res = self.httprequests(url=url, data={"activityId": "600001", "token": self.token}, method="post")
        if not res:
            return
        code = res.get("code")
        if code == 0:
            total = res["data"]["totalIntegral"]
            self.log(f"签到成功，获得积分 {total}")
        elif code == 33001:
            self.log("当天已经签过到了")
        else:
            self.log(f"签到出错: {res}")

    def home_browse(self) -> None:
        """首页上滑任务，完成后获得定时积分。"""
        url = "https://userapi.qiekj.com/task/queryByType"
        res = self.httprequests(url=url, data={"taskCode": "8b475b42-df8b-4039-b4c1-f9a0174a611a", "token": self.token}, method="post")
        if res and res.get("code") == 0 and res.get("data") is True:
            self.log("首页浏览成功，获得1积分")
        else:
            self.log("首页浏览失败")

    def shielding_query(self) -> None:
        """调用屏蔽查询接口，保持参考脚本中的步骤。"""
        url = "https://userapi.qiekj.com/shielding/query"
        res = self.httprequests(
            url=url,
            data={"shieldingResourceType": "1", "token": self.token},
            method="post",
        )
        if res:
            self.log("屏蔽查询完成")
        else:
            self.log("屏蔽查询失败，继续执行后续任务")

    def tx(self, task_code: str) -> bool:
        """执行普通任务项（兼容旧命名，推荐使用 complete_task_detail）。"""
        url = "https://userapi.qiekj.com/task/completed"
        res = self.httprequests(url=url, data={"taskCode": task_code, "token": self.token}, method="post")
        return bool(res and res.get("code") == 0 and res.get("data") is True)

    def complete_task_detail(self, task_code: str) -> dict:
        """执行任务并返回详细结果，用于更精细的控制与熔断。"""
        url = "https://userapi.qiekj.com/task/completed"
        res = self.httprequests(url=url, data={"taskCode": task_code, "token": self.token}, method="post")
        if not res:
            return {"success": False, "code": -999, "stop": False}
        if res.get("code") == 0 and res.get("data") is True:
            return {"success": True, "code": 0, "stop": False}
        if res.get("code") == -1:
            return {"success": False, "code": -1, "stop": True}
        # 其他失败（如 data=False 或其他 code）
        return {"success": False, "code": res.get("code"), "stop": False, "data": res.get("data")}

    def app_video_task(self, i: int) -> dict:
        """APP 视频任务，每次成功加积分，返回 dict 以控制循环。"""
        url = "https://userapi.qiekj.com/task/completed"
        res = self.httprequests(url=url, data={"taskCode": 2, "token": self.token}, method="post")
        if not res:
            return {"success": False, "stop": False}
        if res.get("code") == 0 and res.get("data") is True:
            self.log(f"第 {i} 次 APP 视频任务完成")
            return {"success": True, "stop": False}
        if res.get("code") == -1:
            self.log("APP 视频任务已结束/失效，停止循环")
            return {"success": False, "stop": True}
        self.log(f"APP 视频任务第 {i} 次失败")
        return {"success": False, "stop": False}

    def alipay_video_task(self, i: int, timestamp: str) -> bool:
        """支付宝渠道视频任务，需使用不同签名。"""
        url = "https://userapi.qiekj.com/task/completed"
        sign = self.sign_alipay(timestamp, url)
        headers = {
            "Authorization": self.token,
            "Version": "1.60.3",
            "channel": "alipay",
            "phoneBrand": "Redmi",
            "timestamp": timestamp,
            "sign": sign,
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Host": "userapi.qiekj.com",
            "Accept-Encoding": "gzip",
            "User-Agent": self.ua,
        }
        data = {"taskCode": 9, "token": self.token}
        try:
            res = self.session.post(url=url, headers=headers, data=data, timeout=10)
            res_json = res.json()
            if res.status_code == 200 and res_json.get("code") == 0 and res_json.get("data") is True:
                self.log(f"第 {i} 次支付宝视频")
                return True
        except Exception as exc:
            self.log(f"支付宝任务异常: {exc}")
        return False

    def get_tasks(self) -> list:
        """拉取任务列表，过滤已完成项。"""
        url = "https://userapi.qiekj.com/task/list"
        res = self.httprequests(url=url, data={"token": self.token}, method="post")
        if res and res.get("code") == 0:
            return res["data"].get("items", [])
        self.log("获取任务列表失败")
        return []

    def run(self) -> dict:
        """执行完整任务流程，支持中断，返回积分变化等汇总。"""
        username = None
        start_balance = 0
        try:
            # 1. 读取基础信息，记录开始积分
            username = self.get_username()
            start_balance = self.balance()
            self.log(f"开始执行任务，当前积分 {start_balance}")
            time.sleep(1)

            # 2. 签到 + 屏蔽查询 + 首屏任务，与参考脚本顺序一致
            self._check_stop()
            self.do_signin()
            time.sleep(1)

            self._check_stop()
            self.shielding_query()
            self.log("3s后开始执行任务")
            time.sleep(3)

            self._check_stop()
            self.home_browse()
            time.sleep(1)
            self._check_stop()

            # 3. 遍历任务列表，逐项执行；增加熔断与随机等待
            tasks = self.get_tasks()
            for item in tasks:
                self._check_stop()
                if item.get("completedStatus") == 0 and item.get("taskCode") not in self.excluded_task_codes:
                    title = item.get("title", "任务")
                    self.log(f"开始执行任务 —— {title}")
                    consecutive_failures = 0
                    limit = item.get("dailyTaskLimit", 1)
                    if limit == -1:
                        limit = 1
                    task_type = item.get("type")
                    for idx in range(limit):
                        self._check_stop()
                        result = self.complete_task_detail(task_code=item["taskCode"])
                        if result["success"]:
                            consecutive_failures = 0
                            self.log(f"  > 第 {idx + 1} 次成功")
                        else:
                            consecutive_failures += 1
                            if result["stop"]:
                                self.log("  > 任务已结束/失效，跳过后续")
                                break
                            self.log(f"  > 第 {idx + 1} 次失败 (code={result.get('code')}, data={result.get('data')})")
                            if consecutive_failures >= 3:
                                self.log("  > ⚠️ 连续失败3次，跳过此任务")
                                break
                        if task_type == 606:
                            wait_time = random.randint(18, 25)
                            self.log(f"  > 广告任务，模拟观看 {wait_time} 秒...")
                        elif task_type in [604, 605, 623, 7]:
                            wait_time = random.randint(5, 8)
                        else:
                            wait_time = random.randint(8, 12)
                        time.sleep(wait_time)
                    self.log(f"{title} 阶段结束")
                    time.sleep(2)

            # 4. 视频任务（APP + 支付宝），保持参考脚本的次数与间隔
            if self.options.video:
                self.log("开始 APP 视频循环任务...")
                for num in range(20):
                    self._check_stop()
                    res = self.app_video_task(i=num + 1)
                    if res.get("stop"):
                        break
                    sleep_t = random.randint(16, 22)
                    time.sleep(sleep_t)

            if self.options.alipay:
                self.log("开始 支付宝 视频循环任务...")
                for num in range(50):
                    self._check_stop()
                    t = str(int(time.time() * 1000))
                    if not self.alipay_video_task(i=num + 1, timestamp=t):
                        self.log("支付宝任务失败，尝试继续")
                    time.sleep(random.randint(16, 22))

        except InterruptedError as e:
            self.log(str(e))
        except Exception as e:
            self.log(f"任务异常中断: {e}")

        # 5. 结束收尾：等 3s，重新查询积分并计算本次收益
        time.sleep(3)
        end_balance = self.balance()
        gain = end_balance - start_balance
        self.log(f"任务结束，最新积分 {end_balance}，本次获得 {gain}")
        return {"username": username, "integral": end_balance, "gain": gain}
