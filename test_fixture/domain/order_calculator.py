"""Domain层：订单计算 - 测试圈复杂度和嵌套深度"""
from typing import Optional


def calculate_order_total(
    items: list,
    discount_code: Optional[str],
    tax_rate: float,
    shipping_method: str,
    is_member: bool,
    coupon: Optional[str],
    loyalty_points: int  # 7 个参数 → [WARN] 参数过多
) -> float:
    """圈复杂度极高的函数 - 应该触发复杂度警告"""
    subtotal = sum(item.get("price", 0) for item in items)
    
    # 分支 1
    if discount_code == "SAVE10":
        subtotal *= 0.9
    elif discount_code == "SAVE20":
        subtotal *= 0.8
    elif discount_code == "VIP":
        subtotal *= 0.7
    else:
        # 分支 2 - 嵌套开始
        if is_member:
            subtotal *= 0.95
            # 分支 3 - 二层嵌套
            if loyalty_points > 1000:
                subtotal -= 50
                # 分支 4 - 三层嵌套
                if shipping_method == "express":
                    subtotal += 20
                    # 分支 5 - 四层嵌套
                    if subtotal > 500:
                        subtotal -= 10
                        # 分支 6 - 五层嵌套
                        if coupon == "BONUS":
                            subtotal *= 0.95
                            # 分支 7 - 六层嵌套 → [BLOCK] 嵌套深度
                            if tax_rate > 0.1:
                                subtotal += 5
    
    # 分支 8
    if shipping_method == "pickup":
        subtotal -= 15
    elif shipping_method == "standard":
        subtotal += 10
    elif shipping_method == "overnight":
        subtotal += 30
    
    # 分支 9
    tax = subtotal * tax_rate
    total = subtotal + tax
    
    # 分支 10
    if total < 0:
        total = 0
    # 分支 11
    elif total > 10000:
        total = 10000
    
    return total


# ============ 违规代码块：重复代码 ============
def format_currency_usd(amount: float) -> str:
    symbol = "$"
    if amount < 0:
        symbol = "-$"
        amount = abs(amount)
    return f"{symbol}{amount:,.2f}"


def format_currency_eur(amount: float) -> str:
    symbol = "€"
    if amount < 0:
        symbol = "-€"
        amount = abs(amount)
    return f"{symbol}{amount:,.2f}"


def format_currency_gbp(amount: float) -> str:
    symbol = "£"
    if amount < 0:
        symbol = "-£"
        amount = abs(amount)
    return f"{symbol}{amount:,.2f}"
