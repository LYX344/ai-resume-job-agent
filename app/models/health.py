from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    app_name: str
    app_env: str
    app_version: str


class RedisHealthResponse(BaseModel):
    status: str
    redis: str


class MySQLHealthResponse(BaseModel):
    status: str
    mysql: str
