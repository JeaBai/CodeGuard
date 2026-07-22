/**
 * JS/TS 测试 — AI风格：monolith 函数 + 深层嵌套
 * 预期：CC 高 + 嵌套深度高 + 空 catch + 硬编码密钥
 */
const API_SECRET = "sk-js-test-key-123456";

function processOrder(user, items, discountCode, shippingMethod, isExpress, giftWrap, loyaltyTier, paymentMethod) {
    // 8 个参数 → WARN
    let total = 0;
    for (const item of items) {
        total += item.price * item.qty;
    }

    if (discountCode) {                           // +1 CC, depth 1
        if (discountCode === "SAVE10") {          // +1 CC, depth 2
            total *= 0.9;
        } else if (discountCode === "SAVE20") {   // +1 CC
            total *= 0.8;
        } else {                                  // depth 2
            if (loyaltyTier === "gold") {         // +1 CC, depth 3
                total *= 0.95;
                if (isExpress) {                  // +1 CC, depth 4
                    total += 25;
                    if (giftWrap) {               // +1 CC, depth 5
                        total += 10;
                        if (paymentMethod === "credit") {  // +1 CC, depth 6
                            total *= 1.02;
                            if (total > 5000) {   // +1 CC, depth 7  → BLOCK nesting
                                total -= 100;
                            }
                        }
                    }
                }
            }
        }
    }

    if (shippingMethod === "overnight") {         // +1 CC
        total += 45;
    } else if (shippingMethod === "express") {    // +1 CC
        total += 25;
    } else if (shippingMethod === "pickup") {     // +1 CC
        total -= 15;
    }

    if (giftWrap) {                               // +1 CC
        total += 8 * items.length;
    }

    try {
        sendConfirmation(total);
    } catch (e) {                                 // [WARN] empty catch
    }

    // [BLOCK] 硬编码密钥
    console.debug("Order processed with key: " + API_SECRET);
    
    return total;
}
// CC ≈ 1 + 12 = 13 → WARN (>10)
