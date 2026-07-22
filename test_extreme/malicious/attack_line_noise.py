"""
攻击测试5 — 行噪声攻击
超长行、二进制字符、控制字符
预期：引擎不崩溃，正常处理
"""
# 超长行 — 2000+ 字符
long_string = "A" * 2000
# 二进制字符
binary_data = b"\x00\x01\x02\xff\xfe\xfd"  
# 控制字符
control_chars = "\x00\x1b\x07\x08"
# 混合后正常代码仍应被检测
PASSWORD = "after_noise"  # [BLOCK]
