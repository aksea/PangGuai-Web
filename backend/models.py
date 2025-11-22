# --- models.py ---
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field

class RegisterForm(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)

class LoginForm(BaseModel):
    username: str
    password: str

class PhoneCheck(BaseModel):
    phone: str = Field(..., pattern=r"^1[3-9]\d{9}$")

class TaskCreate(BaseModel):
    phone: str = Field(..., pattern=r"^1[3-9]\d{9}$", description="手机号")
    ua_mode: str = Field("auto", description="auto|custom")
    ua_value: Optional[str] = None

class LoginReport(BaseModel):
    phone: str = Field(..., pattern=r"^1[3-9]\d{9}$")
    token: str
    ua: Optional[str] = None

class UserStatus(BaseModel):
    nick: Optional[str]
    integral: int
    task_status: str

class TaskOptions(BaseModel):
    general: bool = True
    video: bool = True
    alipay: bool = True

class TaskResponse(BaseModel):
    id: str
    phone: str
    ua_mode: str
    ua: Optional[str]
    token: Optional[str]
    status: str
    error: Optional[str]
    created_at: int
    updated_at: int

# 内部使用的运行配置
class RunConfig(BaseModel):
    token: str
    ua: str
    device_id: Optional[str] = None
    options: TaskOptions
