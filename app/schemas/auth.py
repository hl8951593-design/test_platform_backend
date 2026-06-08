from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64, description="用户名")
    avatar: str | None = Field(default=None, max_length=512, description="头像地址")
    account: str = Field(min_length=3, max_length=64, description="账号")
    password: str = Field(min_length=6, max_length=128, description="密码")
    phone: str = Field(min_length=5, max_length=32, description="手机号")
    email: EmailStr = Field(description="邮箱")


class LoginRequest(BaseModel):
    account: str = Field(min_length=3, max_length=64, description="账号")
    password: str = Field(min_length=6, max_length=128, description="密码")


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=1, description="刷新令牌")
