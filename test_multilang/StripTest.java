/**
 * 剥离验证测试 — Java 版
 * 注释和字符串中包含大量控制流关键词
 *
 * // if (thisIsComment) { for (int i = 0; i < 10; i++) }
 * /* while (true) { switch (x) { case 1: break; } } */
 *
 * Expected CC = 3 (base 1 + 2 real if statements)
 */
public class StripTest {
    public String process(String input) {
        // "if you read this, you're blind"
        // 'switch on this: for loop, while loop, if statement'
        
        if (input == null) {          // CC +1 → real
            return "default";
        }
        
        /* block comment:
           if (this) { for (;;) { while (true) { switch (x) {} } } }
        */
        
        if (input.length() > 100) {   // CC +1 → real
            return "long";
        }
        
        // "strings with keywords: if for while switch catch"
        return "ok";
    }
}
