# --- core/runner.py ---
import asyncio
import random
import time
from typing import Callable, Dict, Optional, Any
from .client import PangGuaiClient
from .utils import normalize_ua
from ..models import RunConfig

class AsyncPangGuaiRunner:
    def __init__(
        self, 
        config: RunConfig, 
        log_func: Callable[[str], None],
        stop_event: asyncio.Event
    ):
        self.token = config.token
        self.ua = normalize_ua(config.ua)
        self.options = config.options
        self.log = log_func
        self.stop_event = stop_event
        self.client: Optional[PangGuaiClient] = None
        
        self.excluded_task_codes = {
            "7328b1db-d001-4e6a-a9e6-6ae8d281ddbf",
            "e8f837b8-4317-4bf5-89ca-99f809bf9041",
            "65a4e35d-c8ae-4732-adb7-30f8788f2ea7",
            "73f9f146-4b9a-4d14-9d81-3a83f1204b74",
            "12e8c1e4-65d9-45f2-8cc1-16763e710036",
        }

    async def _sleep(self, min_s: int, max_s: int = 0):
        """支持中断的智能睡眠"""
        seconds = min_s if max_s == 0 else random.randint(min_s, max_s)
        try:
            # 如果 stop_event 被设置，这里会立即返回(或抛出超时)
            # wait_for 配合 event.wait() 实现"睡x秒，但可随时被打断"
            await asyncio.wait_for(self.stop_event.wait(), timeout=seconds)
            raise InterruptedError("任务被停止")
        except asyncio.TimeoutError:
            # 正常睡醒
            pass

    async def _check_stop(self):
        if self.stop_event.is_set():
            raise InterruptedError("任务被停止")

    async def run(self) -> Dict[str, Any]:
        self.client = PangGuaiClient(self.token, self.ua)
        start_balance = 0
        username = None
        
        try:
            # 1. 初始化信息
            user_info = await self.client.request("post", "https://userapi.qiekj.com/user/info", {"token": self.token})
            if user_info and user_info.get("code") == 0:
                username = user_info["data"].get("userName")
                self.log(f"用户: {username}")
            
            bal_res = await self.client.request("post", "https://userapi.qiekj.com/user/balance", {"token": self.token})
            if bal_res and bal_res.get("code") == 0:
                start_balance = int(bal_res["data"]["integral"])
                self.log(f"当前积分: {start_balance}")

            await self._check_stop()
            await self._sleep(1)

            if self.options.general:
                self.log("开始常规任务...")
                sign_res = await self.client.request("post", "https://userapi.qiekj.com/signin/doUserSignIn", 
                                                     {"activityId": "600001", "token": self.token})
                if sign_res:
                    code = sign_res.get("code")
                    if code == 0:
                        self.log(f"签到成功，积分 {sign_res['data']['totalIntegral']}")
                    elif code == 33001:
                        self.log("今日已签到")
                
                await self._check_stop()
                await self._sleep(2)

                await self.client.request("post", "https://userapi.qiekj.com/shielding/query", 
                                         {"shieldingResourceType": "1", "token": self.token})
                self.log("屏蔽查询完成")
                await self._sleep(3)

                home_res = await self.client.request("post", "https://userapi.qiekj.com/task/queryByType",
                                                    {"taskCode": "8b475b42-df8b-4039-b4c1-f9a0174a611a", "token": self.token})
                if home_res and home_res.get("code") == 0 and home_res.get("data") is True:
                    self.log("首页浏览成功")
                
                await self._sleep(2)

                tasks_res = await self.client.request("post", "https://userapi.qiekj.com/task/list", {"token": self.token})
                items = tasks_res["data"].get("items", []) if (tasks_res and tasks_res.get("code")==0) else []
                
                for item in items:
                    await self._check_stop()
                    if item.get("completedStatus") == 0 and item.get("taskCode") not in self.excluded_task_codes:
                        title = item.get("title", "未知任务")
                        self.log(f"执行任务: {title}")
                        
                        limit = item.get("dailyTaskLimit", 1)
                        if limit == -1: limit = 1
                        task_type = item.get("type")
                        
                        consecutive_failures = 0
                        for idx in range(limit):
                            await self._check_stop()
                            wait_t = random.randint(18, 25) if task_type == 606 else random.randint(6, 10)
                            self.log(f"  > 模拟浏览 {wait_t}s...")
                            await self._sleep(wait_t)
                            
                            do_res = await self.client.request("post", "https://userapi.qiekj.com/task/completed",
                                                              {"taskCode": item["taskCode"], "token": self.token})
                            
                            if not do_res:
                                consecutive_failures += 1
                            elif do_res.get("code") == 0 and do_res.get("data") is True:
                                self.log(f"  > 第 {idx+1} 次成功")
                                consecutive_failures = 0
                            elif do_res.get("code") == -1:
                                self.log("  > 任务失效/结束，跳过")
                                break
                            else:
                                self.log(f"  > 失败: {do_res.get('code')}")
                                consecutive_failures += 1
                            
                            if consecutive_failures >= 3:
                                self.log("  > 连续失败3次，跳过")
                                break
                            
                            await self._sleep(2, 5)
            else:
                self.log("跳过常规任务")

            await self._check_stop()

            # 5. 视频任务
            if self.options.video:
                self.log("开始 APP 视频任务...")
                for i in range(20):
                    await self._check_stop()
                    v_res = await self.client.request("post", "https://userapi.qiekj.com/task/completed",
                                                     {"taskCode": 2, "token": self.token})
                    if v_res and v_res.get("code") == 0 and v_res.get("data") is True:
                        self.log(f"视频 {i+1} 成功")
                    elif v_res and v_res.get("code") == -1:
                        self.log("视频任务结束")
                        break
                    
                    await self._sleep(16, 22)

            # 6. 支付宝任务 (切换 channel)
            if self.options.alipay:
                self.log("开始支付宝视频任务...")
                fail_streak = 0
                for i in range(50):
                    await self._check_stop()
                    # 特殊: 支付宝任务 taskCode=9
                    ali_res = await self.client.request("post", "https://userapi.qiekj.com/task/completed",
                                                       {"taskCode": 9, "token": self.token}, channel="alipay")
                    
                    if ali_res and ali_res.get("code") == 0 and ali_res.get("data") is True:
                        self.log(f"支付宝视频 {i+1} 成功")
                        fail_streak = 0
                    else:
                        fail_streak += 1
                        msg = ali_res.get("msg") if ali_res else "请求失败"
                        self.log(f"支付宝视频 {i+1} 失败: {msg}")
                        if fail_streak >= 3:
                            break
                    
                    await self._sleep(16, 22)

            # 结算
            await self._sleep(3)
            end_bal_res = await self.client.request("post", "https://userapi.qiekj.com/user/balance", {"token": self.token})
            end_balance = int(end_bal_res["data"]["integral"]) if end_bal_res else start_balance
            gain = end_balance - start_balance
            self.log(f"任务结束。当前积分: {end_balance}, 本次收益: {gain}")

            return {"username": username, "integral": end_balance, "gain": gain}

        finally:
            await self.client.aclose()
