from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


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
        self.token = token
        self.ua = ua
        self.options = options or RunOptions()
        self.log = logger or (lambda msg: None)
        self.stop_flag = False
        self.notfin = {
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

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def sign_android(self, timestamp: str, url: str) -> str:
        return sha256_encrypt(
            "appSecret=nFU9pbG8YQoAe1kFh+E7eyrdlSLglwEJeA0wwHB1j5o=&channel=android_app"
            f"&timestamp={timestamp}&token={self.token}&version=1.60.3&{url[25:]}"
        )

    def sign_alipay(self, timestamp: str, url: str) -> str:
        return sha256_encrypt(
            "appSecret=Ew+ZSuppXZoA9YzBHgHmRvzt0Bw1CpwlQQtSl49QNhY=&channel=alipay"
            f"&timestamp={timestamp}&token={self.token}&version=1.60.3&{url[25:]}"
        )

    def httprequests(self, url: str, data: Optional[Dict[str, str]] = None, method: str = "post") -> Optional[dict]:
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
            "User-Agent": self.ua,
        }
        try:
            if method == "get":
                res = self.session.get(url=url, headers=headers, timeout=10)
            else:
                res = self.session.post(url=url, headers=headers, data=data, timeout=10)
            if res.status_code != 200:
                self.log(f"请求出错 {res.status_code}")
                return None
            res_json = res.json()
            if res_json.get("msg") == "未登录":
                raise RuntimeError("Token 失效，请重新登录")
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
        url = "https://userapi.qiekj.com/user/balance"
        res = self.httprequests(url=url, data={"token": self.token}, method="post")
        if res and res.get("code") == 0:
            return int(res["data"]["integral"])
        return 0

    def qd(self) -> None:
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

    def sy(self) -> None:
        url = "https://userapi.qiekj.com/task/queryByType"
        res = self.httprequests(url=url, data={"taskCode": "8b475b42-df8b-4039-b4c1-f9a0174a611a", "token": self.token}, method="post")
        if res and res.get("code") == 0 and res.get("data") is True:
            self.log("首页浏览成功，获得1积分")
        else:
            self.log("首页浏览失败")

    def tx(self, task_code: str) -> bool:
        url = "https://userapi.qiekj.com/task/completed"
        res = self.httprequests(url=url, data={"taskCode": task_code, "token": self.token}, method="post")
        return bool(res and res.get("code") == 0 and res.get("data") is True)

    def appvideo(self, i: int) -> bool:
        url = "https://userapi.qiekj.com/task/completed"
        res = self.httprequests(url=url, data={"taskCode": 2, "token": self.token}, method="post")
        if res and res.get("code") == 0 and res.get("data") is True:
            self.log(f"第 {i} 次 APP 视频任务完成")
            return True
        return False

    def zfbtask(self, i: int, timestamp: str) -> bool:
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
            username = self.get_username()
            start_balance = self.balance()
            self.log(f"开始执行任务，当前积分 {start_balance}")

            self._check_stop()
            self.qd()
            self._check_stop()
            self.sy()
            self._check_stop()

            tasks = self.get_tasks()
            for item in tasks:
                self._check_stop()
                if item.get("completedStatus") == 0 and item.get("taskCode") not in self.notfin:
                    title = item.get("title", "任务")
                    self.log(f"开始执行任务 —— {title}")
                    for _ in range(item.get("dailyTaskLimit", 1)):
                        self._check_stop()
                        ok = self.tx(task_code=item["taskCode"])
                        time.sleep(2)
                        if not ok:
                            self.log(f"{title} 执行出错，跳过")
                            break
                    self.log(f"{title} 完成")
                    time.sleep(1)

            if self.options.video:
                for num in range(20):
                    self._check_stop()
                    if not self.appvideo(i=num + 1):
                        break
                    time.sleep(15)

            if self.options.alipay:
                for num in range(50):
                    self._check_stop()
                    t = str(int(time.time() * 1000))
                    if not self.zfbtask(i=num + 1, timestamp=t):
                        break
                    time.sleep(15)

        except InterruptedError as e:
            self.log(str(e))
        except Exception as e:
            self.log(f"任务异常中断: {e}")

        end_balance = self.balance()
        gain = end_balance - start_balance
        self.log(f"任务结束，最新积分 {end_balance}，本次获得 {gain}")
        return {"username": username, "integral": end_balance, "gain": gain}
