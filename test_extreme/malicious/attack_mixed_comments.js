/**
攻击测试4 — JS 混合注释+正则字面量+模板字符串
预期：剥离引擎正确处理所有噪声，不误报不崩溃
*/
// /* nested block comment start
/* this is still a block comment */
// if (this.should.not.count) { for (;;) {} }
const API_KEY = "sk-js-attack"; // [BLOCK] should be detected

// 正则字面量中的控制流关键词
const re = /if|for|while|switch|catch/gi; // should NOT be counted as CC
const re2 = /return\s+true/; // should NOT be counted

// 模板字符串中的关键词
const msg = `if you see this, for all that is good, while the switch is on`;
// should NOT be counted

function realIf(x) {
    // This is the ONLY real if
    if (x) { return true; }
    return false;
}
// CC should = 2 (base 1 + 1 real if)
