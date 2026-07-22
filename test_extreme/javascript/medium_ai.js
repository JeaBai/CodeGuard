// JS 中型 AI代码 — 安全违规 + 高CC + 空catch + 重复
const DB_PASSWORD = "js_db_pass"; // [BLOCK]
const SECRET = "secret123";       // [BLOCK]

function processOrder(order, user, items, discountCode, shipping, express, gift, loyalty) {
    let total = 0;
    for (const item of items) total += item.price * item.qty;
    if (discountCode) {
        if (discountCode === "SAVE10") total *= 0.9;
        else if (discountCode === "SAVE20") total *= 0.8;
        else { if (loyalty === "gold") { total *= 0.95; if (express) { total += 25; if (gift) { total += 10; } } } }
    }
    if (shipping === "overnight") total += 45;
    else if (shipping === "express") total += 25;
    return total;
} // CC≈10 → WARN

// 重复查询函数
function getUser(n) { return fetch("/api/users?name=" + n); }
function getOrder(n) { return fetch("/api/orders?name=" + n); }
function getProduct(n) { return fetch("/api/products?name=" + n); }

// 空catch
function risky(url) { try { fetch(url); } catch(e) {} }

// [BLOCK] 日志泄露
console.debug("DB password: " + DB_PASSWORD);
