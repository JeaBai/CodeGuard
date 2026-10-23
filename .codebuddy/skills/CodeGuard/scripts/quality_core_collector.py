"""问题收集器 IssueCollector — 置信度评分 + 行级豁免预检。"""
import os
from collections import defaultdict

from quality_core_utils import _log
import quality_rule_registry as _registry

# ============================================================
# 问题收集器
# ============================================================

class IssueCollector:
    """问题收集器（v2.0: 支持置信度评分）

    v2.0.12: 增加 codeguard:ignore 行级豁免预检过滤器。
    在所有检测模块报告 issue 前检查目标行 ±3 行范围内是否存在
    '# codeguard: ignore' 或 '# noqa' 豁免标记，若存在则跳过该 issue。
    覆盖 quality_dup / quality_checks / quality_security 全部调用路径。
    """
    def __init__(self):
        self.issues = []
        self.stats = defaultdict(int)
        # v3.0.0: 置信度从统一注册表派生（消除硬编码，修复 D5）
        self.confidence_base = dict(_registry.CONFIDENCE_BASE)
        # v2.0.12: 文件内容缓存（LRU ≤64），避免豁免检查重复 I/O
        self._file_lines_cache = {}
    
    def _is_ignored(self, filepath, line):
        """检查问题行是否被 codeguard:ignore 或 noqa 豁免标记覆盖。

        读取目标文件（缓存），检查 line ±3 行范围内是否存在
        '# codeguard: ignore' 或 '# noqa' 标记。

        返回 True 表示该 issue 应被豁免跳过。
        """
        if line <= 0:
            # 文件级问题（line=0 或负数）不适用行级豁免
            return False
        
        # 读取并缓存文件行内容
        if filepath not in self._file_lines_cache:
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    self._file_lines_cache[filepath] = f.readlines()
            except (OSError, UnicodeDecodeError):
                self._file_lines_cache[filepath] = []
            # LRU 淘汰：超过 64 个文件时删除最旧条目
            if len(self._file_lines_cache) > 64:
                oldest = next(iter(self._file_lines_cache))
                del self._file_lines_cache[oldest]
        
        lines = self._file_lines_cache.get(filepath, [])
        if not lines:
            return False
        
        # 检查 line±6 行范围（0-indexed，line 是 1-indexed）— v2.0.14 从 ±3 扩展到 ±6
        check_start = max(0, line - 7)
        check_end = min(len(lines), line + 5)
        
        for i in range(check_start, check_end):
            stripped_line = lines[i].strip()
            if '# codeguard: ignore' in stripped_line or '# noqa' in stripped_line:
                return True
            # v2.0.14: 支持块级豁免标记 # codeguard: ignore-block
            if '# codeguard: ignore-block' in stripped_line and i < line + 6:
                return True
        
        return False
    
    def add(self, severity, category, filepath, line, message, *args, **kwargs):
        """添加问题记录（v2.0.12: 增加 codeguard:ignore 行级豁免预检）

        在记录任何 issue 之前先检查目标行是否有豁免标记。
        有豁免 → 跳过（仅日志记录用于审计），确保 31 条已知豁免项被正确过滤。
        """
        # ---- v2.0.14: intent_protection 预检 ----
        try:
            from intent_protection import check_protected as _cp
            ip_result = _cp(filepath, line, category)
            if ip_result.get("protected"):
                action = ip_result.get("action", "skip")
                pid = ip_result.get("protection_id", "?")
                if action == "skip":
                    _log(f"[CodeGuard] 意图保护: [{category}] {os.path.basename(filepath)}:{line} "
                         f"— 保护项 {pid}，跳过")
                    return
                elif action == "downgrade_to_info":
                    severity = "info"
                    message += f" [保护项 {pid}: 用户已确认为有意设计]"
                elif action == "report_with_note":
                    message += f" [保护项 {pid}: 用户已确认为有意设计]"
        except (ImportError, ModuleNotFoundError):
            pass  # intent_protection 未安装，静默通过
        except Exception as _e:
            _log(f"[CodeGuard] 意图保护检查异常: {_e}，跳过预检")

        # ---- v2.0.12: codeguard:ignore 行级豁免预检 ----
        if self._is_ignored(filepath, line):
            _log(f"[CodeGuard] 豁免: [{category}] {os.path.basename(filepath)}:{line} "
                 f"— 存在 # codeguard:ignore / # noqa 标记，跳过")
            return
        
        suggestion = args[0] if len(args) > 0 else kwargs.get("suggestion", "")
        confidence = args[1] if len(args) > 1 else kwargs.get("confidence", None)
        if confidence is None:
            confidence = self.confidence_base.get(category, 80)
        
        # v3.0.0: 闭环映射 — 记录 rule_id（显式传入优先，否则 category 唯一映射时自动反查）
        rule_id = kwargs.get("rule_id")
        if rule_id is None:
            ids = _registry.get_rule_ids_by_category(category)
            if len(ids) == 1:
                rule_id = ids[0]
        
        issue = {
            "severity": severity,
            "category": category,
            "file": filepath,
            "line": line,
            "message": message,
            "suggestion": suggestion,
            "confidence": confidence,
        }
        if rule_id is not None:
            issue["rule_id"] = rule_id
        self.issues.append(issue)
        self.stats[severity] += 1
    
    def has_blocks(self):
        return self.stats.get("block", 0) > 0
    
    def has_warns(self):
        return self.stats.get("warn", 0) > 0
    
    def summary(self):
        avg_conf = 0
        if self.issues:
            avg_conf = sum(i.get("confidence", 80) for i in self.issues) // len(self.issues)
        return {
            "total_issues": len(self.issues),
            "blocks": self.stats.get("block", 0),
            "warnings": self.stats.get("warn", 0),
            "info": self.stats.get("info", 0),
            "avg_confidence": avg_conf
        }
