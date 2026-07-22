"""
AI 生成的数据处理器 — Python
特点：无类型标注、深层嵌套、硬编码路径、无错误处理、print调试、全局变量
"""
import json
import os

DB_PASSWORD = "admin123"  # [BLOCK]
OUTPUT_PATH = "/tmp/output"  # 硬编码路径
processed_count = 0  # 全局可变状态

def process_data(data):
    global processed_count
    results = []
    
    for item in data:
        if item:
            if "id" in item:
                if item["id"]:
                    if "value" in item:
                        if item["value"]:
                            if item["value"] > 100:
                                item["category"] = "high"
                            elif item["value"] > 50:
                                item["category"] = "medium"
                                if "meta" in item:
                                    if item["meta"]:
                                        if "priority" in item["meta"]:
                                            if item["meta"]["priority"] > 5:
                                                item["flagged"] = True
                            else:
                                item["category"] = "low"
                                # 深度8 → [BLOCK] nesting
                                try:
                                    item["normalized"] = item["value"] / 100
                                except:
                                    pass  # [WARN] 空异常处理
            
            # 保存文件
            filename = os.path.join(OUTPUT_PATH, f"{item.get('id', 'unknown')}.json")
            try:
                with open(filename, "w") as f:
                    json.dump(item, f)
            except:
                pass  # [WARN] 再次空异常
            
            results.append(item)
            processed_count += 1
    
    # [BLOCK] 安全 + 日志泄露
    print(f"Processed {processed_count} items, db password: {DB_PASSWORD}")
    return results
