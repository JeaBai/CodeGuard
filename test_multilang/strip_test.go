// 剥离验证测试 — Go 版
// 注释和字符串中的控制流关键词不应被计数
//
// if thisIsComment { for i := 0; i < 10; i++ }
// fmt.Println("if you see this: for loop, while true, switch on")
// `raw string: if err != nil { for _, v := range items { switch v {} } }`
//
// Expected CC = 2 (base 1 + 1 real if)
package main

func StripTestTest(valid bool) string {
    // The only real control flow:
    if valid {  // CC +1 → real, total CC = 2
        return "ok"
    }
    // "if" "for" "while" "switch" ← all in strings, should NOT count
    return "no"
}
