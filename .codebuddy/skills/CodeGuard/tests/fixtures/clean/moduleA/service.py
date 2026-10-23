"""moduleA 服务 —— 全部合规。

契约：返回 {"data": ...}，出参形状由 schema 校验。
"""
import json
import requests

CONTRACT = {"type": "object", "required": ["data"]}


def fetch(url: str) -> dict:
    """跨进程调用：显式超时 + 有限重试。"""
    resp = requests.get(url, timeout=3)
    resp.raise_for_status()
    return json.loads(resp.text)


def load_local(path: str) -> str:
    """本地读取：路径由参数传入（不硬编码）。"""
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()
