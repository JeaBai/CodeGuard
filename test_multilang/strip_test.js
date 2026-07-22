/**
 * 剥离验证测试 — 注释和字符串中藏了大量 if/for/while/switch
 * 如果剥离失败 → CC 会高达 20+（误报）
 * 如果剥离成功 → CC ≈ 2（只计真实的 1 个 if）
 *
 * // if this is a comment, should NOT be counted
 * // for each mistake we make, don't count this either
 * console.log("if you see this string, the regex is blind"); // string
 * const msg = `while this template literal contains keywords`; // template literal
 * /* switch on this: block comment with if for while * /（去掉空格）
 */

function simpleCheck(valid) {
    // This is the ONLY real control flow
    if (valid) {           // CC +1 → total CC = 2
        return "ok";
    }
    // All comments above should NOT affect CC
    // "if you're counting these, your stripping is broken"
    return "not ok";
}
// Expected CC = 2 (base 1 + 1 real if)
