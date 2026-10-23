"""moduleB 实现（接口 v1）。"""

API_VERSION = "v1"
# 旧调用方兼容：旧字段保留，新增字段置于末尾
def handle(payload: dict) -> dict:
    return {"ok": True, "payload": payload}
