// Go 中型 AI代码 — 安全违规 + 高CC + 空错误处理
package main

import "os"

var DB_PASSWORD = "go_pass_123"  // [BLOCK]
var SECRET_KEY = "go_secret_456"  // [BLOCK]

func ProcessOrder(items []float64, tier string, holiday bool, points int,
    region string, currency string, gift bool, promo string,
    months int, express bool) float64 {  // 10 params → BLOCK
    total := 0.0
    for _, item := range items { total += item }
    if tier == "gold" { total *= 0.8
    } else if tier == "silver" { total *= 0.9
    } else { if holiday { total *= 0.95
        if points > 1000 { total -= 100 } } }
    if region == "EU" { total *= 1.21
        if currency == "GBP" { total *= 0.85
            if gift { total *= 0.9
                if promo != "" { total *= 0.85 } } } }
    if months > 12 { total *= 1.05
    } else if months > 6 { total *= 1.03
    } else if months > 3 { total *= 1.01 }
    return total
} // CC≈13 → WARN

func riskyCmd(cmd string) {
    // [BLOCK] os/exec
    os.Setenv("CMD", cmd)
}

func main() {}
