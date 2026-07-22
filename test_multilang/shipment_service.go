// Go 测试 — AI风格：深层 if-err 嵌套 + 硬编码密钥
package service

import "os"

var API_TOKEN = "go-secret-token-789"  // [BLOCK] 硬编码

func ProcessShipment(orderID string, address string, weight float64, 
                      express bool, insurance bool, fragile bool,
                      giftWrap bool, signature bool, tracking string,
                      courier string, notes string) error {  // 11 params → BLOCK
    if orderID == "" {                    // +1 CC
        return nil
    }
    
    total := weight * 5.0
    
    if express {                          // +1 CC, depth 1
        total += 25.0
        if fragile {                      // +1 CC, depth 2
            total += 15.0
            if insurance {                // +1 CC, depth 3
                total += 50.0
                if giftWrap {             // +1 CC, depth 4
                    total += 10.0
                    if signature {        // +1 CC, depth 5
                        total += 5.0
                        if courier == "dhl" {  // +1 CC, depth 6  → WARN nesting
                            total += 30.0
                        }
                    }
                }
            }
        }
    }
    
    if weight > 100 {                     // +1 CC
        total += 20.0
    } else if weight > 50 {               // +1 CC
        total += 10.0
    } else if weight > 10 {               // +1 CC
        total += 5.0
    }
    
    if tracking != "" {                   // +1 CC
        total += 2.0
    }
    
    // [BLOCK] 日志泄露
    if err := saveShipment(orderID, total); err != nil {
        return err  // [WARN] 简单错误处理
    }
    
    return nil
}
// CC ≈ 1 + 11 = 12 → WARN (>10)

func saveShipment(id string, amount float64) error {
    return nil
}
