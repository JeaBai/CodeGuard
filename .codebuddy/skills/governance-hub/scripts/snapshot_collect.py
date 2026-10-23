"""快照采集 — Git/文件哈希/CodeGuard 指标采集。"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from collections import defaultdict

from snapshot_store import _SKIP_DIRS, _SOURCE_EXTS, _log

# ============================================================
# Git 集成
# ============================================================

def _get_git_commit(project_root: str) -> str | None:
    """获取当前 git commit hash。"""
    try:
        result = subprocess.run(
            ["git", "-C", project_root, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def _is_git_repo(project_root: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", project_root, "rev-parse", "--git-dir"],
            capture_output=True, text=True, timeout=3,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


# ============================================================
# 文件哈希
# ============================================================

def _collect_file_hashes(project_root: str) -> dict[str, str]:
    """收集项目所有源码文件的 SHA256 哈希。"""
    hashes = {}
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for fname in sorted(filenames):
            ext = os.path.splitext(fname)[1].lower()
            if ext not in _SOURCE_EXTS:
                continue
            fpath = os.path.join(dirpath, fname)
            rel = os.path.relpath(fpath, project_root).replace("\\", "/")
            try:
                with open(fpath, "rb") as f:
                    hashes[rel] = "sha256:" + hashlib.sha256(f.read()).hexdigest()[:16]
            except (OSError, PermissionError):
                hashes[rel] = "sha256:ERROR"
    return hashes


def _hash_blueprint(project_root: str) -> str | None:
    """计算 architecture_blueprint.json 的哈希。"""
    bp_paths = [
        os.path.join(project_root, "architecture_blueprint.json"),
        os.path.join(project_root, ".codebuddy", "architecture_blueprint.json"),
    ]
    for bp in bp_paths:
        if os.path.isfile(bp):
            try:
                with open(bp, "rb") as f:
                    return "sha256:" + hashlib.sha256(f.read()).hexdigest()[:16]
            except OSError:
                pass
    return None


# ============================================================
# CodeGuard 指标采集
# ============================================================

def _collect_codeguard_metrics(project_root: str) -> dict:
    """调用 CodeGuard 的 quality_check.py 采集指标。"""
    metrics = {
        "total_files": 0, "total_functions": 0, "total_lines": 0,
        "max_complexity": 0, "avg_complexity": 0.0,
        "duplicate_blocks": 0, "duplicate_lines": 0,
        "architecture_cycles": 0, "global_vars": 0,
        "test_coverage": 0.0, "codeguard_blocks": 0, "codeguard_warns": 0,
        "by_language": {},
    }

    # 收集源文件
    all_files = []
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in _SOURCE_EXTS:
                all_files.append(os.path.join(dirpath, fname))

    metrics["total_files"] = len(all_files)

    # 按语言分组统计行数
    lang_stats: dict[str, dict] = defaultdict(lambda: {"files": 0, "lines": 0})
    for fpath in all_files:
        ext = os.path.splitext(fpath)[1].lower()
        lang_map = {".py": "python", ".js": "typescript", ".ts": "typescript",
                    ".tsx": "typescript", ".mjs": "typescript", ".java": "java",
                    ".go": "go", ".cs": "csharp", ".rs": "rust",
                    ".cpp": "c_cpp", ".c": "c_cpp", ".h": "c_cpp"}
        lang = lang_map.get(ext, "other")
        lang_stats[lang]["files"] += 1
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            loc = _count_loc(content)
            lang_stats[lang]["lines"] += loc
            metrics["total_lines"] += loc
        except (OSError, UnicodeDecodeError):
            pass

    metrics["by_language"] = {k: dict(v) for k, v in lang_stats.items()}

    # 调用 CodeGuard（如果可用）
    cg_metrics = _call_codeguard(project_root, all_files)
    metrics.update(cg_metrics)

    # 估算函数总数（Python AST）
    func_count = 0
    cc_list = []
    for fpath in all_files:
        if not fpath.endswith(".py"):
            continue
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            import ast
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_count += 1
                    from quality_core import compute_cyclomatic_complexity
                    try:
                        cc = compute_cyclomatic_complexity(node)
                        cc_list.append(cc)
                    except Exception:
                        pass
        except (SyntaxError, OSError):
            pass

    metrics["total_functions"] = func_count
    if cc_list:
        metrics["avg_complexity"] = round(sum(cc_list) / len(cc_list), 1)
        metrics["max_complexity"] = max(max(cc_list), metrics.get("max_complexity", 0))

    return metrics


def _count_loc(content: str) -> int:
    """统计代码行数（排除空行和注释行）。"""
    count = 0
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("//"):
            count += 1
    return count


def _call_codeguard(project_root: str, all_files: list[str]) -> dict:
    """调用 CodeGuard quality_check.run_quality_check() 获取门禁指标。"""
    result = {"codeguard_blocks": 0, "codeguard_warns": 0,
              "duplicate_blocks": 0, "duplicate_lines": 0,
              "architecture_cycles": 0, "global_vars": 0}

    try:
        # 添加 CodeGuard scripts 到路径
        cg_paths = [
            os.path.join(project_root, ".codebuddy", "skills", "CodeGuard", "scripts"),
        ]
        for p in cg_paths:
            if os.path.isdir(p) and p not in sys.path:
                sys.path.insert(0, p)

        from quality_core import IssueCollector, find_source_files, LAYER_PATTERNS
        from quality_arch import DependencyGraph

        collector = IssueCollector()

        # 查找源文件
        source_files = find_source_files(project_root)

        if source_files:
            # 用 CodeGuard 的 check_duplicates 和 check_architecture
            try:
                from quality_dup import check_duplicates
                check_duplicates(source_files, collector)
            except Exception:
                pass

            try:
                from quality_arch import build_dependency_graph
                graph = build_dependency_graph(source_files)
                graph.check_layer_violations(collector)
            except Exception:
                pass

            # 全局变量检测（Python 模块级赋值）
            for fpath in source_files:
                if not fpath.endswith(".py"):
                    continue
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    import ast
                    tree = ast.parse(content)
                    for node in ast.iter_child_nodes(tree):
                        if isinstance(node, ast.Assign):
                            for target in node.targets:
                                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                                    result["global_vars"] += 1
                except Exception:
                    pass

            summary = collector.summary()
            result["codeguard_blocks"] = summary.get("blocks", 0)
            result["codeguard_warns"] = summary.get("warnings", 0)

            # 统计重复和循环依赖
            for issue in collector.issues:
                if issue.get("category") == "duplication":
                    if issue.get("severity") == "block":
                        result["duplicate_blocks"] += 1
                    result["duplicate_lines"] += 1
                elif issue.get("category") == "architecture_cycle":
                    result["architecture_cycles"] += 1

    except Exception as e:
        _log(f"CodeGuard 指标采集部分失败: {e}")

    return result
