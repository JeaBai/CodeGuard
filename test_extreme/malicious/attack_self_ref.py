"""
攻击测试3 — 自引用/循环引用代码
检测引擎是否会被循环引用搞崩溃
"""
import os
# 循环引用
import sys
sys.modules[__name__] = type(sys)(__name__)
# 检测引擎应该能处理这种恶意import
API_KEY = "sk-recursive-test"  # [BLOCK]
