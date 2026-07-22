/**
 * 真实人类编写的支付服务 — Java
 * 特点：接口抽象、依赖注入、职责单一、提前返回、结构化日志、完善的异常处理
 * 这是一个有 6 年经验的 Java 工程师写的生产级代码
 */
package com.example.payment;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.List;
import java.util.logging.Logger;

// ===== 接口（依赖倒置）=====
interface PaymentGateway {
    PaymentResult charge(BigDecimal amount, PaymentMethod method) throws PaymentException;
}

interface NotificationService {
    void sendReceipt(String email, PaymentResult result);
}

// ===== 值对象 =====
class PaymentMethod {
    private final String type;
    private final String lastFour;
    PaymentMethod(String type, String lastFour) { this.type = type; this.lastFour = lastFour; }
    boolean isCredit() { return "credit".equals(type); }
}

class PaymentResult {
    private final String transactionId;
    PaymentResult(String id) { this.transactionId = id; }
}

class PaymentException extends Exception {
    PaymentException(String msg, Throwable cause) { super(msg, cause); }
}

// ===== 折扣计算器（单一职责）=====
class DiscountCalculator {
    private static final BigDecimal TIER_RATE = new BigDecimal("0.95");
    private static final BigDecimal LOYALTY_RATE = new BigDecimal("0.98");
    
    public BigDecimal apply(BigDecimal amount, boolean isPremium, int loyaltyPoints) {
        BigDecimal discounted = amount;
        if (isPremium) {
            discounted = discounted.multiply(TIER_RATE);
        }
        if (loyaltyPoints > 1000) {
            discounted = discounted.multiply(LOYALTY_RATE);
        }
        return discounted.setScale(2, RoundingMode.HALF_UP);
    }
}

// ===== 主服务（业务编排，CC ≈ 4）=====
public class PaymentService {
    private static final Logger log = Logger.getLogger(PaymentService.class.getName());
    private final PaymentGateway gateway;
    private final NotificationService notifier;
    private final DiscountCalculator discountCalc;
    
    public PaymentService(PaymentGateway gateway, NotificationService notifier) {
        this.gateway = gateway;
        this.notifier = notifier;
        this.discountCalc = new DiscountCalculator();
    }
    
    public PaymentResult processPayment(String email, List<CartItem> items,
                                         PaymentMethod method, boolean isPremium,
                                         int loyaltyPoints) throws PaymentException {
        BigDecimal total = items.stream()
            .map(CartItem::getSubtotal)
            .reduce(BigDecimal.ZERO, BigDecimal::add);
        
        BigDecimal discounted = discountCalc.apply(total, isPremium, loyaltyPoints);
        
        try {
            PaymentResult result = gateway.charge(discounted, method);
            log.info("Payment succeeded: " + result);
            
            try {
                notifier.sendReceipt(email, result);
            } catch (Exception e) {
                log.warning("Receipt notification failed for " + email + ": " + e.getMessage());
                // 发送收据失败不应回滚支付
            }
            
            return result;
        } catch (PaymentException e) {
            log.severe("Payment failed for " + email);
            throw e;
        }
    }
}

class CartItem {
    private BigDecimal price;
    private int quantity;
    BigDecimal getSubtotal() { return price.multiply(BigDecimal.valueOf(quantity)); }
}
