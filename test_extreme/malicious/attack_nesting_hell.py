"""
攻击测试1 — 嵌套地狱 + 跨行安全违规
嵌套深度 30+，跨行的 SQL 注入，字符串中的安全关键字
预期：CC BLOCK + nesting BLOCK + 跨行SQL注入仍然被检测
"""
PASSWORD = "attack_pass"  # [BLOCK]
# 跨行SQL注入 — 应该被检测
query = (
    "SELECT * FROM users "
    "WHERE name = '%s' "
    "AND password = '%s'"
) % (username, password)

def nest30(x):
    if x>0:
        if x>1:
            if x>2:
                if x>3:
                    if x>4:
                        if x>5:
                            if x>6:
                                if x>7:
                                    if x>8:
                                        if x>9:
                                            if x>10:
                                                if x>11:
                                                    if x>12:
                                                        if x>13:
                                                            if x>14:
                                                                if x>15:
                                                                    if x>16:
                                                                        if x>17:
                                                                            if x>18:
                                                                                if x>19:
                                                                                    if x>20:
                                                                                        if x>21:
                                                                                            if x>22:
                                                                                                if x>23:
                                                                                                    if x>24:
                                                                                                        if x>25:
                                                                                                            if x>26:
                                                                                                                if x>27:
                                                                                                                    if x>28:
                                                                                                                        if x>29:
                                                                                                                            return x
    return 0
