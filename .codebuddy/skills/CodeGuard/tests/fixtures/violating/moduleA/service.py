"""moduleA 服务 —— 故意包含 4 类违规，用于测试检测器。"""
import requests
from helper import _private_helper


def fetch(url):
    r = requests.get(url)
    return r.json()


def load_data():
    try:
        return open("../moduleB/data.json").read()
    except Exception:
        pass


def use():
    return _private_helper()
