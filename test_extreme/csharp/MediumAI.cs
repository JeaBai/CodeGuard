// C# 中型 AI代码 — 安全违规 + 高CC + 空catch
using System;

public class MediumAI {
    private static readonly string DB_PASS = "cs_pass_123"; // [BLOCK]
    private static readonly string API_KEY = "cs_key_456";   // [BLOCK]

    public string GetUser(string name) {
        string query = "SELECT * FROM Users WHERE Name = '" + name + "'"; // [BLOCK] SQL注入
        try { return ExecuteQuery(query); }
        catch (Exception) { } // [WARN]
        return null;
    }

    public double CalcPrice(double basePrice, string tier, bool holiday, int points,
        string region, string currency, bool gift, string promo,
        int months, bool express) { // 10 params → BLOCK
        double price = basePrice;
        if (tier == "gold") { price *= 0.8; }
        else if (tier == "silver") { price *= 0.9; }
        else { if (holiday) { price *= 0.95; if (points > 1000) { price -= 100; } } }
        if (region == "EU") { price *= 1.21; if (currency == "GBP") { price *= 0.85; if (gift) { price *= 0.9; } } }
        if (months > 12) price *= 1.05;
        else if (months > 6) price *= 1.03;
        else if (months > 3) price *= 1.01;
        return price;
    }

    private string ExecuteQuery(string q) { return "ok"; }
}
