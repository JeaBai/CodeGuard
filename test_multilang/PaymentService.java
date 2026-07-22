/**
 * Java 测试 — AI风格：巨无霸 Service 类 + 高风险方法
 * 预期：CC 高 + 嵌套深 + 空 catch + 硬编码密码
 */
public class PaymentService {
    private static final String DB_PASSWORD = "admin123!@#";  // [BLOCK] 硬编码

    public double calculatePayment(double amount, String type, boolean isPremium,
                                    boolean isHoliday, int loyaltyPoints, String region,
                                    String currency, boolean giftCard, String promoCode,
                                    int installmentMonths) {  // 10 params → BLOCK
        double total = amount;
        
        if (type.equals("credit")) {                              // +1 CC, depth 1
            total *= 1.03;
        } else if (type.equals("debit")) {                        // +1 CC
            total *= 1.01;
        } else {                                                  // depth 1
            if (isPremium) {                                      // +1 CC, depth 2
                total *= 0.98;
            }
        }
        
        if (isHoliday) {                                          // +1 CC, depth 1
            total *= 0.95;
            if (loyaltyPoints > 1000) {                           // +1 CC, depth 2
                total -= 100;
                if (region.equals("EU")) {                        // +1 CC, depth 3
                    total *= 1.21;
                    if (currency.equals("GBP")) {                 // +1 CC, depth 4
                        total *= 0.85;
                    }
                }
            }
        }
        
        if (giftCard) {                                           // +1 CC
            total *= 0.9;
        }
        
        if (promoCode != null && !promoCode.isEmpty()) {          // +1 CC
            total *= 0.85;
        }
        
        if (installmentMonths > 12) {                             // +1 CC
            total *= 1.05;
        } else if (installmentMonths > 6) {                       // +1 CC
            total *= 1.03;
        } else if (installmentMonths > 3) {                       // +1 CC
            total *= 1.01;
        }
        
        try {
            processTransaction(total);
        } catch (Exception e) {
            // [WARN] empty catch
        }
        
        return total;
    }
    // CC ≈ 1 + 14 = 15 → BLOCK (>15)
    
    public void processTransaction(double amount) {}
    public void validatePayment() {}
    public void refundPayment() {}
    public void cancelPayment() {}
    public void getPaymentHistory() {}
    public void exportPayments() {}
    public void sendReceipt() {}
    public void checkStatus() {}
    public void updatePayment() {}
    public void schedulePayment() {}
    public void retryPayment() {}
    public void archivePayment() {}
    public void restorePayment() {}
    public void splitPayment() {}
    public void mergePayments() {}
    public void calculateTax() {}
    // 16 public methods → WARN (>15)
}
