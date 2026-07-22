// 自定义规则测试 — Java
// CUSTOM_NO_STATIC_SINGLETON + CUSTOM_NO_MAGIC_NUMBER
public class TestRules {
    // [BLOCK] 静态单例 — CUSTOM_NO_STATIC_SINGLETON
    public static TestRules INSTANCE = new TestRules();
    
    // [WARN] 魔法数字 — CUSTOM_NO_MAGIC_NUMBER (3, 7, 100)
    public double applyDiscount(double price) {
        if (price > 100) return price * 0.7;
        if (price > 50) return price * 0.85;
        return price;
    }
}
