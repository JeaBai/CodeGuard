#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fc-guardian MCP server 验收驱动：按 SKILL适配整改计划 P0-4 执行。

验收标准：
  1. 从 skill 根目录启动 `python scripts/mcp_server.py` 不报错
  2. 客户端 `tools/list` 能返回 `fc_scan`
  3. initialize 返回正确协议版本
  4. 实调 fc_scan 返回 exit_code + summary
"""
import json
import subprocess
import sys
from pathlib import Path

def run(skill_dir: Path, project_root: Path, requests):
    """以子进程方式跑 server，喂入 JSON-RPC 请求，收集响应。"""
    payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in requests) + "\n"
    proc = subprocess.run(
        [sys.executable, "scripts/mcp_server.py", "--project-root", str(project_root)],
        input=payload, capture_output=True, text=True, encoding="utf-8",
        cwd=str(skill_dir), timeout=180,
    )
    responses = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                responses.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return proc, responses


def main():
    skill_dir = Path(sys.argv[1]).resolve()
    project_root = Path(sys.argv[2]).resolve()
    print(f"skill   : {skill_dir}")
    print(f"project : {project_root}\n")

    reqs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "fc_scan", "arguments": {"path": ".", "format": "summary"}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "no_such_tool", "arguments": {}}},
    ]
    proc, resps = run(skill_dir, project_root, reqs)

    ok = True

    # 1) 启动不报错
    crashed = "Traceback" in (proc.stderr or "")
    print(f"[1] 启动无异常      : {'✅' if not crashed else '❌'}  "
          f"(stderr 非空: {bool((proc.stderr or '').strip())})")
    if crashed:
        print("    --- stderr ---");  print("    " + "\n    ".join((proc.stderr or "").splitlines()[:12])); ok = False
    # stderr 里的启动日志属正常输出，单独展示首行
    first_err = (proc.stderr or "").strip().splitlines()
    if first_err:
        print(f"    启动日志: {first_err[0][:100]}")

    by_id = {r.get("id"): r for r in resps}

    # 2) initialize
    init = (by_id.get(1) or {}).get("result") or {}
    proto = init.get("protocolVersion")
    print(f"[2] initialize 协议版本: {proto}  {'✅' if proto else '❌'}")
    if not proto: ok = False

    # 3) tools/list 含 fc_scan
    tools = ((by_id.get(2) or {}).get("result") or {}).get("tools") or []
    names = [t.get("name") for t in tools]
    has = "fc_scan" in names
    print(f"[3] tools/list 返回 fc_scan: {'✅' if has else '❌'}  工具={names}")
    if not has: ok = False

    # 3b) schema 完整性
    if has:
        t = next(t for t in tools if t["name"] == "fc_scan")
        sch = t.get("inputSchema") or {}
        props = sch.get("properties") or {}
        need = {"path", "format"} & set(props)
        print(f"    入参 schema: {sorted(props)}  必需={sch.get('required')}  "
              f"{'✅' if need == {'path', 'format'} else '⚠️'}")
        print(f"    入参含 path/format: {'✅' if need == {'path','format'} else '❌'}")

    # 4) resources/list
    res = ((by_id.get(3) or {}).get("result") or {}).get("resources") or []
    print(f"[4] resources/list: {[r.get('uri') for r in res]}  {'✅' if res else '❌'}")

    # 5) 实调 fc_scan
    call = by_id.get(4) or {}
    if call.get("error"):
        print(f"[5] fc_scan 实调: ❌ {call['error']}")
        ok = False
    else:
        content = ((call.get("result") or {}).get("content") or [{}])[0].get("text", "")
        try:
            data = json.loads(content)
            print(f"[5] fc_scan 实调: ✅ 判定={data.get('verdict')} "
                  f"exit_code={data.get('exit_code')} summary={data.get('summary')}")
            print(f"    分类计数: {dict(list((data.get('by_category') or {}).items())[:5])}")
        except Exception as e:
            print(f"[5] fc_scan 实调: ❌ 返回非 JSON: {e}\n    {content[:200]}")
            ok = False

    # 6) 未知工具应报错
    unk = by_id.get(5) or {}
    have_err = bool(unk.get("error"))
    print(f"[6] 未知工具返回错误: {'✅' if have_err else '❌'}  {unk.get('error', {}).get('message', '')}")
    if not have_err: ok = False

    print(f"\n{'='*56}\n验收结果: {'✅ 全部通过' if ok else '❌ 存在失败项'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
