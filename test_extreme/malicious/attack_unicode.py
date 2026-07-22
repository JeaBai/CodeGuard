"""
攻击测试2 — Unicode混淆 + 零宽字符
Unicode全角字符、零宽连接符、同形异义字
预期：正常检测，Unicode字符不应干扰正则
"""
# 全角等号（视觉上像 = 但实际不是）
PASSWORD　＝　"attack_unicode"  # 全角＝不是正则匹配的=
# 正常等号 — 应该被检测
PASSWORD = "real_attack"  # [BLOCK] 应该被检测
# 零宽空格 \u200b 在关键字中
pa\u200bssword = "hidden"  # 零宽空格在变量名中 — 不应误报
