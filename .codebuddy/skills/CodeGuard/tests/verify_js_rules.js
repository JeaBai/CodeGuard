#!/usr/bin/env node
/**
 * CodeGuard P2-4: JS 规则验证测试集
 * 用于验证 GOLD_NO_CONSOLE_LOG / GOLD_NO_ANY_TYPE (TS) / GOLD_NO_SYNC_IO / GOLD_USE_STRICT_EQUAL
 * 
 * 包含植入的违规样本和合法样本，用于验证规则触发精度。
 */

// === TP 样本（应触发规则） ===

// GOLD_NO_CONSOLE_LOG: 应触发 block
function debugData(data) {
    console.log(data);    // [违规] 生产代码中的 console.log
    console.warn(data);   // [违规] console.warn
    console.error(data);  // [违规] console.error
}

// GOLD_NO_SYNC_IO: 应触发 block
const fs = require('fs');
function loadConfig() {
    const data = fs.readFileSync('/etc/config.json', 'utf-8');  // [违规]
    fs.writeFileSync('/tmp/log.txt', 'hello');                   // [违规]
}

// GOLD_USE_STRICT_EQUAL: 应触发 warn
function compareValues(a, b) {
    if (a == b) return true;   // [违规] 应使用 ===
    if (a != null) return a;   // [违规] 应使用 !==
}


// === TN 样本（不应触发规则） ===

// 合法：使用 === 
function safeCompare(x, y) {
    return x === y;  // ✅ OK
}

// 合法：使用 fs/promises
async function safeRead() {
    const { readFile } = require('fs/promises');
    return await readFile('/etc/hosts', 'utf-8');  // ✅ OK
}

// 合法：使用日志库
const logger = require('winston');
function safeLog(data) {
    logger.info(data);  // ✅ OK（非 console.log）
}

module.exports = { debugData, loadConfig, compareValues, safeCompare, safeRead, safeLog };
