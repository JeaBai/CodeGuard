/**
 * AI 生成的支付服务 — Java
 * 特点：所有逻辑堆一个类、硬编码密钥、深层嵌套、SQL拼接、空catch、打印泄漏
 * 这是典型的一次性 prompt 输出，未经任何重构
 */
package com.example.payment;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.util.List;

// [BLOCK] 硬编码数据库密码
public class AIPaymentService {
    private static final String DB_URL = "jdbc:mysql://localhost:3306/pay";
    private static final String DB_USER = "admin";
    private static final String DB_PASS = "SuperSecret123!";
    private static final String STRIPE_KEY = "sk_live_abc123xyz";  // [BLOCK]
    
    // 22个方法 → WARN (>15)
    public void processPayment(String email, List<Object> items, String type,
                                boolean premium, int points, String region,
                                String currency, boolean gift, String promo,
                                int months) {  // 10 params → BLOCK
        
        double total = 0;
        for (Object item : items) { total += 100; }
        
        // 深层嵌套开始
        if (type.equals("credit")) {
            total *= 1.03;
        } else if (type.equals("debit")) {
            total *= 1.01;
        } else {
            if (premium) {
                total *= 0.98;
                if (points > 1000) {
                    total -= 100;
                    if (region.equals("EU")) {
                        total *= 1.21;
                        if (currency.equals("GBP")) {
                            total *= 0.85;
                            if (gift) {
                                total *= 0.9;
                                if (promo != null) {
                                    total *= 0.85;  // 深度6 → WARN
                                }
                            }
                        }
                    }
                }
            }
        }
        
        if (months > 12) total *= 1.05;
        else if (months > 6) total *= 1.03;
        else if (months > 3) total *= 1.01;
        
        // [BLOCK] SQL注入
        Connection conn = null;
        try {
            conn = DriverManager.getConnection(DB_URL, DB_USER, DB_PASS);
            conn.createStatement().execute(
                "INSERT INTO payments VALUES ('" + email + "', " + total + ")"
            );
        } catch (Exception e) {
            // [WARN] 空catch + [BLOCK] 日志泄露
            System.out.println("Payment failed with password: " + DB_PASS);
        }
        
        // [BLOCK] 重复SQL注入模式
        try {
            ResultSet rs = conn.createStatement().executeQuery(
                "SELECT * FROM users WHERE email = '" + email + "'"
            );
        } catch (Exception ex) {}  // [WARN] 空catch
    }
    
    public void refundPayment() {}
    public void cancelPayment() {}
    public void getHistory() {}
    public void exportReport() {}
    public void sendEmail() {}
    public void validateCard() {}
    public void checkFraud() {}
    public void calculateFee() {}
    public void applyTax() {}
    public void convertCurrency() {}
    public void schedulePayment() {}
    public void retryPayment() {}
    public void splitPayment() {}
    public void mergePayment() {}
    public void archivePayment() {}
    public void restorePayment() {}
    public void auditPayment() {}
    public void reconcilePayment() {}
    public void notifyPayment() {}
    public void logPayment() {}
    public void cachePayment() {}
}
