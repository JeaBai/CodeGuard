// Java 中型 AI代码 — 安全违规 + 高CC + 空catch
public class MediumAI {
    private static final String DB_PASS = "pass123";  // [BLOCK]
    private static final String API_KEY = "sk-test";   // [BLOCK]
    
    public String getUser(String name) {
        String query = "SELECT * FROM users WHERE name = '" + name + "'"; // [BLOCK] SQL注入
        try { return executeQuery(query); }
        catch (Exception e) {} // [WARN]
        return null;
    }
    
    public double calcPrice(double base, String tier, boolean holiday, int points,
                            String region, String currency, boolean gift, String promo,
                            int months, boolean express) {  // 10 params → BLOCK
        double price = base;
        if (tier.equals("gold")) { price *= 0.8; }
        else if (tier.equals("silver")) { price *= 0.9; }
        else { if (holiday) { price *= 0.95; if (points > 1000) { price -= 100; } } }
        if (region.equals("EU")) { price *= 1.21; if (currency.equals("GBP")) { price *= 0.85; } }
        if (gift) { price *= 0.9; if (promo != null) { price *= 0.85; } }
        if (months > 12) price *= 1.05;
        else if (months > 6) price *= 1.03;
        else if (months > 3) price *= 1.01;
        return price;
    } // CC≈13 → WARN
    
    private String executeQuery(String q) { return "ok"; }
}
