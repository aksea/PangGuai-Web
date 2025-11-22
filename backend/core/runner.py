# --- core/runner.py ---
import asyncio
import random
from typing import Callable, Dict, Optional, Any

from core.client import PangGuaiClient
from models import RunConfig

class AsyncPangGuaiRunner:
    def __init__(
        self, 
        config: RunConfig, 
        log_func: Callable[[str], None],
        stop_event: asyncio.Event
    ):
        self.token = config.token
        self.ua = config.ua
        self.device_id = config.device_id
        self.options = config.options
        self.log = log_func
        self.stop_event = stop_event
        self.client: Optional[PangGuaiClient] = None
        
        # === 白名单策略配置 ===
        # 1. 允许的任务类型：604(浏览), 605(小程序), 606(视频广告)
        self.ALLOWED_TYPES = {604, 605, 606}
        
        # 2. 敏感词黑名单：标题含这些词的一律不做
        self.SENSITIVE_KEYWORDS = ["认证", "绑卡", "充值", "开通", "办卡", "上传", "完善"]
        
        # 3. 兜底黑名单：即使类型符合，这些 ID 也不做
        self.excluded_task_codes = {
            "7", # 打开通知
        }

    async def _sleep(self, min_s: int, max_s: int = 0):
        """支持中断的智能睡眠"""
        seconds = min_s if max_s == 0 else random.randint(min_s, max_s)
        try:
            await asyncio.wait_for(self.stop_event.wait(), timeout=seconds)
            raise InterruptedError("任务被停止")
        except asyncio.TimeoutError:
            pass

    async def _check_stop(self):
        if self.stop_event.is_set():
            raise InterruptedError("任务被停止")

    async def run(self) -> Dict[str, Any]:
        self.client = PangGuaiClient(self.token, self.ua, self.device_id)
        start_balance = 0
        username = None
        
        def log_resp(tag: str, res: Optional[Dict[str, Any]]):
            if not res: return
            # 仅在 code!=0 时记录异常日志，保持控制台清爽
            if res.get("code") != 0:
                self.log(f"{tag} 异常: {res.get('msg')}")
        
        try:
            # 1. 初始化信息
            await self._check_stop()
            user_info = await self.client.request("post", "https://userapi.qiekj.com/user/info", {"token": self.token})
            if user_info and user_info.get("code") == 0:
                username = user_info["data"].get("userName")
            
            bal_res = await self.client.request("post", "https://userapi.qiekj.com/user/balance", {"token": self.token})
            if bal_res and bal_res.get("code") == 0:
                start_balance = int(bal_res["data"]["integral"])
            self.log(f"用户: {username}, 初始积分: {start_balance}")

            await self._sleep(1)

            # 2. 常规任务流程 (含视频广告)
            if self.options.general:
                self.log(">>> 开始基础日常任务")
                
                # 签到
                sign_res = await self.client.request("post", "https://userapi.qiekj.com/signin/doUserSignIn", 
                                                     {"activityId": "600001", "token": self.token})
                if sign_res:
                    if sign_res.get("code") == 0:
                        self.log(f"签到成功 +{sign_res['data'].get('totalIntegral')}")
                    elif sign_res.get("code") == 33001:
                        self.log("今日已签到")
                
                await self._sleep(2)

                # 屏蔽查询 & 首页浏览
                await self.client.request("post", "https://userapi.qiekj.com/shielding/query", 
                                         {"shieldingResourceType": "1", "token": self.token})
                
                home_res = await self.client.request("post", "https://userapi.qiekj.com/task/queryByType",
                                                    {"taskCode": "8b475b42-df8b-4039-b4c1-f9a0174a611a", "token": self.token})
                if home_res and home_res.get("code") == 0 and home_res.get("data") is True:
                    self.log("首页浏览 +1")
                
                await self._sleep(2)

                # --- 任务列表循环 (白名单模式) ---
                tasks_res = await self.client.request("post", "https://userapi.qiekj.com/task/list", {"token": self.token})
                items = tasks_res.get("data", {}).get("items", []) if tasks_res else []
                
                valid_count = 0
                for item in items:
                    await self._check_stop()
                    
                    t_title = item.get("title", "")
                    t_type = item.get("type")
                    t_code = item.get("taskCode")
                    t_status = item.get("completedStatus")

                    # --- 核心过滤逻辑 ---
                    if t_status != 0: continue # 已完成
                    
                    # 白名单类型过滤
                    if t_type not in self.ALLOWED_TYPES:
                        # self.log(f"跳过类型 {t_type}: {t_title}")
                        continue
                        
                    # 敏感词过滤
                    if any(k in t_title for k in self.SENSITIVE_KEYWORDS):
                        self.log(f"跳过敏感任务: {t_title}")
                        continue
                        
                    # ID 黑名单过滤
                    if t_code in self.excluded_task_codes:
                        continue

                    # --- 执行逻辑 ---
                    valid_count += 1
                    limit = max(1, item.get("dailyTaskLimit", 1))
                    self.log(f"执行: {t_title}")
                    
                    # 针对广告任务(606)增加等待时间
                    base_wait = 20 if t_type == 606 else 8
                    consecutive_no_reward = 0
                    
                    for idx in range(limit):
                        wait_t = random.randint(base_wait, base_wait + 5)
                        if idx > 0: self.log(f"  > 冷却 {wait_t}s ...")
                        else: await self._sleep(wait_t)
                        
                        do_res = await self.client.request("post", "https://userapi.qiekj.com/task/completed",
                                                          {"taskCode": t_code, "token": self.token})
                        
                        if not do_res: continue
                        
                        code = do_res.get("code")
                        data = do_res.get("data")
                        
                        if code == 0:
                            if data is True:
                                self.log(f"  > 第{idx+1}次完成 (+积分)")
                                consecutive_no_reward = 0
                            else:
                                consecutive_no_reward += 1
                                # self.log(f"  > 第{idx+1}次无奖励") 
                                if consecutive_no_reward >= 3:
                                    self.log("  > 多次无奖励，跳过此任务")
                                    break
                        elif code == -1:
                            self.log("  > 任务失效/达上限，跳过")
                            break
                        else:
                            log_resp(f"  > 任务{t_title}", do_res)
                            break
                        
                        await self._sleep(2)
                
                if valid_count == 0:
                    self.log("常规列表无待执行任务")

            else:
                self.log("跳过基础任务")

            await self._sleep(2)

            # 3. 支付宝隐藏任务 (TaskCode 9)
            if self.options.alipay:
                self.log(">>> 尝试支付宝隐藏任务 (x50)")
                fail_streak = 0
                success_count = 0
                for i in range(50):
                    if self.stop_event.is_set(): raise InterruptedError()
                    
                    res = await self.client.request("post", "https://userapi.qiekj.com/task/completed",
                                                   {"taskCode": 9, "token": self.token}, channel="alipay")
                    
                    code = res.get("code") if res else -1
                    data = res.get("data") if res else False
                    
                    if code == 0 and data is True:
                        success_count += 1
                        if success_count % 10 == 0: 
                            self.log(f"支付宝任务已完成 {success_count} 次")
                        fail_streak = 0
                    else:
                        fail_streak += 1
                        if fail_streak >= 3: 
                            self.log("支付宝接口失效或达上限，停止")
                            break
                    
                    await self._sleep(16, 22)

            # 结算
            await self._sleep(2)
            end_bal_res = await self.client.request("post", "https://userapi.qiekj.com/user/balance", {"token": self.token})
            end_balance = int(end_bal_res.get("data", {}).get("integral", 0)) if end_bal_res else start_balance
            gain = end_balance - start_balance
            self.log(f"任务结束。本次收益: {gain}, 余额: {end_balance}")
            
            return {"username": username, "integral": end_balance, "gain": gain}

        finally:
            if self.client:
                await self.client.aclose()