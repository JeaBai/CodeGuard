// JS 大型 AI代码 — 大量重复 + 安全违规 + 高CC + 日志泄露
const DB_PASS = "admin123";
const API_KEY = "sk-large-js";
const SMTP_PASS = "mail123";

// 重复发送函数 (10个)
function sendEmail1(to) { console.log("sending to " + to + " key: " + API_KEY); }
function sendEmail2(to) { console.log("sending to " + to + " key: " + API_KEY); }
function sendEmail3(to) { console.log("sending to " + to + " key: " + API_KEY); }
function sendEmail4(to) { console.log("sending to " + to + " key: " + API_KEY); }
function sendEmail5(to) { console.log("sending to " + to + " key: " + API_KEY); }
function sendEmail6(to) { console.log("sending to " + to + " key: " + API_KEY); }
function sendEmail7(to) { console.log("sending to " + to + " key: " + API_KEY); }
function sendEmail8(to) { console.log("sending to " + to + " key: " + API_KEY); }
function sendEmail9(to) { console.log("sending to " + to + " key: " + API_KEY); }
function sendEmail10(to) { console.log("sending to " + to + " key: " + API_KEY); }

// 高CC函数
function megaProcess(data, config, flags, mode, tier, payment, shipping, extras, loyalty, region) {
    let r = 0;
    if (data) {
        if (data > 0) {
            if (data > 100) {
                if (tier === "gold") {
                    if (flags) {
                        if (mode === "express") { r = data * 0.5; }
                        else if (mode === "overnight") { r = data * 0.3; }
                        else { r = data * 0.7; }
                    }
                }
            } else if (data > 50) {
                if (tier === "silver") { r = data * 0.6; }
                else { r = data * 0.8; }
            }
        }
    }
    if (loyalty) r -= loyalty;
    return Math.max(0, r);
}

// 空catch
function riskyOp(cmd) { try { eval(cmd); } catch(e) {} }
function riskyOp2(cmd) { try { new Function(cmd)(); } catch(e) {} }

// 日志泄露
function debugInfo(user, pass) {
    console.debug("User: " + user + " Pass: " + pass);
    console.debug("API Key: " + API_KEY);
}
