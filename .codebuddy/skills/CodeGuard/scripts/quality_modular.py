#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quality_modular.py — 模块化与接口设计检测器（CodeGuard v3.1.0 新增维度）

## 定位

CodeGuard 的核心使命是「**防止 AI 生成代码沦为死山代码**」。
死山最典型的成因不是"跑不起来"，而是**接口烂掉**：跨模块硬编码调用、
伸手拿别人内部变量、文档与接口各改各的、降级静默失败、构建不可复现。
这些在单次提交里看不出问题，累积到一定规模就再也改不动。

本模块把《模块化与接口设计手册》的**可自动检测部分**落成第三层防线。

## 与既有检测器的边界（**不重复造轮子**）

| 手册要点 | 已由谁覆盖 | 本模块是否重复实现 |
|---|---|---|
| §1 面向接口 / 分层 | `quality_arch.py`（SOLID_DIP / LAYER_VIOLATION / 循环依赖） | ❌ 不重复：本模块只查**层内路径耦合**与**私有符号越界** |
| §2.2 接口版本 | `api_compatibility.py` | ❌ 不重复 |
| §4.2 看门狗 | `quality_embedded._check_watchdog` | ❌ 不重复 |
| §4.4 静默吞异常 | `quality_security._check_empty_except` + `ERROR_HANDLING` | ❌ 不重复 |

本模块负责的是**9 条**此前无人覆盖的规则：

    MOD_CROSS_HARDCODE   §1.2  跨模块硬编码路径（依赖具体实现而非抽象）
    MOD_PRIVATE_ACCESS   §1.2  跨模块访问私有符号
    MOD_DUP_STEMS        §2.5  同名脚本 → import 归属歧义
    MOD_NO_INTERFACE_DOC §2.1  缺接口文档/模块索引（文档即契约）
    MOD_NO_TIMEOUT       §4.3  跨进程调用无超时
    MOD_NO_TEST_SPLIT    §5.1  单元/集成测试未分层
    MOD_NO_CONTRACT_TEST §6.1  无接口契约校验
    MOD_NO_LOCKFILE      §7.1  无依赖锁定
    MOD_FLOATING_DEP     §7.1  依赖版本浮动

## 三层防线联动

规则元数据统一登记在 `quality_rule_registry.RULE_SPECS`，因此：
  · 第一层 `constraint_injector` 会自动把它们注入生成前上下文
  · 第二层 `quality_mid_check` 会自动生成自查清单
无需在本模块里重复维护提示文本。

## 误报防线（重要）

实测踩过的坑，均已内建过滤 + 回归测试：
  · 压缩/第三方产物（`*.min.js`、vendor 目录、超长行）会被当成源码误报 → `_is_noise()` 挡掉
  · 跨语言同名（`mixer.c` 与 `mixer.py`）不是 import 歧义 → 同名判定用 (stem, 扩展名) 二元组
**误报率高的门禁会被团队主动绕过，等于没有门禁。**
"""
import os
import re

import quality_core as _core  # noqa: F401

MODULAR_VERSION = "1.0.0"

# 参与结构分析的代码扩展名（与 FileClassifier 的 source 类对齐）
_CODE_EXTS = {".py", ".c", ".h", ".cpp", ".hpp", ".cc", ".go", ".rs",
              ".java", ".ts", ".js"}

# 非模块目录：不作为"模块"参与跨模块判定
_NON_MODULE_DIRS = {
    ".git", ".codebuddy", ".workbuddy", ".code-guardian", ".github", "node_modules",
    "__pycache__", "docs", "doc", "文档", "build", "dist", "out", "target",
    "tests", "test", "scripts", "tools", "assets", "references", "rules",
    "_archive", ".venv", "venv", "env",
}

# 噪音过滤：压缩/生成产物与第三方库
_RE_MINIFIED = re.compile(r"\.min\.(?:js|css)$", re.I)
_VENDOR_HINTS = ("node_modules", "vendor", "third_party", "thirdparty",
                 "bower_components", "/_shared/js/", "/libs/", "/lib/",
                 "/_archive/", "/dist/", "/build/")

_RE_QUOTED = re.compile(r'["\']([^"\'\n]{2,200})["\']')
_RE_FROM_IMPORT = re.compile(r'^\s*from\s+([A-Za-z_][\w.]*)\s+import\s+([^\n#]+)', re.M)
_RE_TIMEOUT_API = re.compile(
    r"\b(requests\.(?:get|post|put|delete|request)|httpx\.\w+|"
    r"urllib\.request\.urlopen|subprocess\.(?:run|Popen|call|check_output)|"
    r"socket\.create_connection)\s*\(")
_RE_CONTRACT = re.compile(
    r"(jsonschema|pydantic|openapi|swagger|protobuf|avro|"
    r"_Static_assert|offsetof|接口契约|契约测试)", re.I)
_RE_INTERFACE_DOC = re.compile(
    r"(MODULE_INDEX|module_index|ICD|接口|openapi|swagger|\.proto$|"
    r"api\.(?:json|ya?ml)$)", re.I)


# ==========================================================================
# 扫描辅助
# ==========================================================================
def _is_noise(path):
    """压缩产物 / 第三方库 / 生成文件 —— 不作为自研源码参与判定。"""
    if _RE_MINIFIED.search(os.path.basename(path)):
        return True
    low = "/" + path.replace("\\", "/").lower() + "/"
    if any(h in low for h in _VENDOR_HINTS):
        return True
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for _ in range(3):
                line = fh.readline(6000)
                if not line:
                    break
                if len(line.rstrip("\r\n")) > 800:      # 超长行 = 压缩/生成产物
                    return True
    except OSError:
        pass
    return False


def _read(path, limit=200_000):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def _module_dirs(root):
    """顶层目录中「像模块」的那些（含源码且不在排除名单）。"""
    mods = set()
    try:
        entries = list(os.scandir(root))
    except OSError:
        return mods
    for e in entries:
        if not e.is_dir() or e.name in _NON_MODULE_DIRS or e.name.startswith("."):
            continue
        for _dirpath, _dirnames, filenames in os.walk(e.path):
            if any(os.path.splitext(f)[1].lower() in _CODE_EXTS for f in filenames):
                mods.add(e.name)
                break
            if len(mods) > 64:
                break
    return mods


def _module_of(filepath, root, modules):
    try:
        rel = os.path.relpath(filepath, root).replace("\\", "/")
    except ValueError:
        return None
    parts = rel.split("/")
    if len(parts) > 1 and parts[0] in modules:
        return parts[0]
    return None


def _rel(filepath, root):
    try:
        return os.path.relpath(filepath, root).replace("\\", "/")
    except ValueError:
        return filepath


def _project_root(source_files, root=None):
    if root and os.path.isdir(root):
        return os.path.abspath(root)
    if not source_files:
        return os.getcwd()
    # 取所有源文件的公共祖先
    try:
        return os.path.commonpath([os.path.abspath(f) for f in source_files])
    except (ValueError, TypeError):
        return os.getcwd()


# ==========================================================================
# 检测：跨模块调用（§1.2）
# ==========================================================================
def _check_cross_hardcode(files, root, modules, collector):
    """§1.2 跨模块硬编码路径 —— 直接依赖他模块的实现位置。"""
    for f in files:
        own = _module_of(f, root, modules)
        if own is None:
            continue
        text = _read(f)
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith(("#", "//", "*", '"""', "'''")):
                continue
            for s in _RE_QUOTED.findall(line):
                norm = s.replace("\\", "/")
                if ".." not in norm and not re.search(r"[A-Za-z]:[\\/]", norm):
                    continue
                hit = [m for m in modules if m != own and "/%s/" % m in norm]
                if hit or re.search(r"[A-Za-z]:[\\/]", norm):
                    which = ", ".join(hit) if hit else "绝对路径"
                    collector.add("warn", "modularity", f, i,
                                  "跨模块硬编码路径：引用了 %s（耦合到具体实现位置）" % which,
                                  "改为经该模块对外接口调用；路径由参数/配置注入，不写死在调用方",
                                  confidence=90)
                    break


def _check_private_access(files, root, modules, collector):
    """§1.2 跨模块访问私有符号 —— 绕过对外接口。"""
    stems = {}
    for f in files:
        stems.setdefault(os.path.splitext(os.path.basename(f))[0], set()).add(f)
    for f in files:
        own = _module_of(f, root, modules)
        text = _read(f)
        for m in _RE_FROM_IMPORT.finditer(text):
            mod, names = m.group(1), m.group(2)
            top = mod.split(".")[0]
            if top == own or top not in stems:
                continue
            # 只判本地模块：被导入模块须与本文件同属项目
            if not all(_module_of(x, root, modules) for x in stems[top]):
                continue
            if any(_module_of(x, root, modules) == own for x in stems[top]):
                pass  # 同模块内部 import 私有符号是正常的
            elif not any(_module_of(x, root, modules) != own for x in stems[top]):
                continue
            line = text[:m.start()].count("\n") + 1
            for nm in (n.strip().split(" as ")[0] for n in names.split(",")):
                if nm.startswith("_") and not nm.startswith("__"):
                    collector.add("block", "modularity", f, line,
                                  "跨模块访问私有符号：from %s import %s" % (mod, nm),
                                  "私有符号是实现细节；调用对方公开接口，或请对方向上提升该能力",
                                  confidence=85)
                    break


def _check_dup_stems(files, root, modules, collector):
    """§2.5 同名脚本 → import 归属歧义（仅同一扩展名内比较）。"""
    seen = {}
    for f in files:
        own = _module_of(f, root, modules)
        if own is None:
            continue
        stem = os.path.splitext(os.path.basename(f))[0]
        ext = os.path.splitext(f)[1].lower()
        seen.setdefault((stem, ext), set()).add(own)
    for (stem, ext), owners in sorted(seen.items()):
        if len(owners) > 1 and stem not in ("__init__", "main", "conftest", "mod"):
            collector.add("warn", "modularity", "<%s%s>" % (stem, ext), 0,
                          "同名脚本出现在多个模块：%s（import 归属歧义）"
                          % ", ".join(sorted(owners)),
                          "给跨模块可复用的脚本加模块前缀（如 <mod>_<name>%s）" % ext,
                          confidence=80)


# ==========================================================================
# 检测：文档与契约（§2.1 / §6.1）
# ==========================================================================
def _check_interface_doc(source_files, root, modules, collector):
    """§2.1 缺接口文档 / 模块索引 —— 文档即契约。"""
    if len(modules) < 2:
        return
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "__pycache__", "node_modules")]
        for fn in filenames:
            if _RE_INTERFACE_DOC.match(fn):
                found.append(os.path.join(dirpath, fn))
                break
        if found:
            break
    if not found:
        collector.add("warn", "modularity_doc", root, 0,
                      "未找到接口文档/模块索引（已识别 %d 个模块）" % len(modules),
                      "补模块索引与接口契约文档；索引应由脚本自动生成，避免手写漂移",
                      confidence=75)


def _check_contract_test(source_files, root, modules, collector):
    """§6.1 无接口契约校验 —— 文档与代码必然漂移。"""
    if len(modules) < 2:
        return
    for f in source_files:
        if _RE_CONTRACT.search(_read(f, 80_000)):
            return
    collector.add("warn", "contract", root, 0,
                  "未见接口契约校验痕迹（schema 校验 / 生成式契约 / 编译期断言）",
                  "软件：JSON Schema / IDL 生成 / 消费者驱动契约；"
                  "嵌入式：_Static_assert + offsetof 钉死结构体布局与协议文档一致",
                  confidence=70)


# ==========================================================================
# 检测：隔离与韧性（§4.3）
# ==========================================================================
def _check_timeout(files, root, modules, collector):
    """§4.3 跨进程调用无超时 —— 长尾会拖垮整体。"""
    for f in files:
        if os.path.splitext(f)[1].lower() != ".py":
            continue
        text = _read(f)
        for i, line in enumerate(text.splitlines(), 1):
            if _RE_TIMEOUT_API.search(line) and "timeout" not in line:
                collector.add("warn", "resilience", f, i,
                              "跨进程/网络调用未设置超时",
                              "加 timeout=，且须小于上游超时（逐层收敛）；配有限重试 + 退避",
                              confidence=85)


# ==========================================================================
# 检测：工程可复现（§7.1）
# ==========================================================================
def _check_test_split(root, modules, collector):
    """§5.1 单元/集成测试未分层。"""
    if len(modules) < 2:
        return
    tdirs = []
    for dirpath, dirnames, _files in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "__pycache__", "node_modules")]
        for d in list(dirnames):
            if d.lower() in ("test", "tests", "spec", "specs", "__tests__"):
                tdirs.append(os.path.join(dirpath, d))
    if not tdirs:
        return
    subs = set()
    for t in tdirs:
        try:
            subs |= {e.name.lower() for e in os.scandir(t) if e.is_dir()}
        except OSError:
            continue
    if not ({"unit", "integration"} & subs):
        collector.add("info", "test_strategy", tdirs[0], 0,
                      "测试目录未见 unit / integration 分层",
                      "按单元（不出进程/不连网/不碰硬件）与集成分层；"
                      "CI 分模块 job + fail-fast:false，避免单模块失败阻塞整体流水线",
                      confidence=70)


def _find_manifest(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "__pycache__", "node_modules", ".venv", "venv")]
        for fn in filenames:
            if fn.startswith("requirements") and fn.endswith(".txt") or fn == "pyproject.toml":
                out.append(os.path.join(dirpath, fn))
        if len(out) > 8:
            break
    return out


_LOCK_NAMES = {"poetry.lock", "Pipfile.lock", "uv.lock", "package-lock.json",
               "yarn.lock", "Cargo.lock", "pnpm-lock.yaml", "go.sum", "Gemfile.lock"}


def _check_lockfile(root, collector):
    """§7.1 无依赖锁定 —— 构建不可复现。"""
    manifests = _find_manifest(root)
    if not manifests:
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__", "node_modules")]
        if _LOCK_NAMES & set(filenames):
            return
    collector.add("warn", "reproducibility", manifests[0], 0,
                  "有依赖声明但未见 lockfile",
                  "生成并提交 lockfile 锁定精确版本；工具链按镜像 digest 固定，保证可复现构建",
                  confidence=70)


def _check_floating_deps(root, collector):
    """§7.1 依赖版本浮动 —— 锁定形同虚设。"""
    for f in _find_manifest(root):
        if not os.path.basename(f).startswith("requirements"):
            continue
        for i, line in enumerate(_read(f).splitlines(), 1):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if re.search(r"(>=|~=|!=|\*>|==\s*\*|\s\*\s*$)", s):
                collector.add("warn", "reproducibility", f, i,
                              "依赖版本浮动：%s" % s[:60],
                              "锁定精确版本（== 或 lockfile）；浮动版本会让两端构建结果不一致",
                              confidence=75)


# ==========================================================================
# 入口（与 quality_arch.check_architecture 同形）
# ==========================================================================
def check_modularity(source_files, collector, root=None):
    """模块化与接口设计检测（跨文件）。

    Args:
        source_files: 源码文件绝对路径列表（由 find_source_files 产出）
        collector:    IssueCollector 实例
        root:         项目根目录（可选；缺省时取源文件公共祖先）
    """
    root = _project_root(source_files, root)

    files = [f for f in source_files
             if os.path.splitext(f)[1].lower() in _CODE_EXTS and not _is_noise(f)]
    if not files:
        return

    modules = _module_dirs(root)

    _check_cross_hardcode(files, root, modules, collector)
    _check_private_access(files, root, modules, collector)
    _check_dup_stems(files, root, modules, collector)
    _check_interface_doc(source_files, root, modules, collector)
    _check_contract_test(source_files, root, modules, collector)
    _check_timeout(files, root, modules, collector)
    _check_test_split(root, modules, collector)
    _check_lockfile(root, collector)
    _check_floating_deps(root, collector)
