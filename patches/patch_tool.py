#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MaiBot 主程序补丁安装工具（napcat-ai-tools 配套）

针对 MaiBot v1.0.4 主程序已修改的部分进行补丁安装：
  - 外部 planner 任务支持（maisaka.external.task / run_external_task，用于插件拉起 planner）
  - 防重复回复 / 防自言自语 / 防 replyer 幻觉 / 防死循环
  - 工具语义搜索兜底

特性：
  1. 幂等：已安装的补丁自动跳过，可重复执行
  2. 备份：覆盖前把原文件备份到 <MaiBot根目录>/patches_backup/<时间戳>/
  3. 回滚：安装过程中任一步骤失败，自动回滚本次所有改动，恢复到安装前状态
  4. 状态：status / uninstall 子命令，随时查看或还原

用法（在本仓库 patches/ 目录或仓库根目录执行）：
  python patch_tool.py status                 # 查看补丁安装状态
  python patch_tool.py install                # 安装补丁（已安装则跳过）
  python patch_tool.py install --force        # 覆盖已被外部修改的文件，强制重装
  python patch_tool.py uninstall              # 卸载补丁（从备份还原原文件）

可选参数 --target 指定 MaiBot 主程序根目录（含 src/ 与 prompts/ 的目录），
也可以通过环境变量 MAIBOT_HOME 指定；都不给时尝试从当前目录自动探测。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# ============================================================
# 补丁清单（target = 相对 MaiBot 根目录；source = 相对本脚本所在 patches/ 目录）
# ============================================================

PATCH_VERSION = "1.9.0"
MIN_MAIBOT_VERSION = "1.0.4"

PATCHES: List[Dict[str, str]] = [
    # --- 外部 planner 任务支持 + 防重复回复/自言自语（maisaka 核心） ---
    {
        "target": "src/maisaka/runtime.py",
        "source": "src/maisaka/runtime.py",
        "desc": "run_external_task 外部任务接口（插件触发外部 planner 的核心）+ 外部任务互斥锁",
    },
    {
        "target": "src/maisaka/reasoning_engine.py",
        "source": "src/maisaka/reasoning_engine.py",
        "desc": "reply 发送后强制结束循环防重复回复；outbound_send 消息标记 is_self_message",
    },
    {
        "target": "src/plugin_runtime/capabilities/core.py",
        "source": "src/plugin_runtime/capabilities/core.py",
        "desc": "注册 maisaka.external.task 能力实现（_cap_maisaka_external_task）",
    },
    {
        "target": "src/plugin_runtime/capabilities/registry.py",
        "source": "src/plugin_runtime/capabilities/registry.py",
        "desc": "能力注册表加入 maisaka.external.task",
    },
    # --- 防死循环 / 工具搜索兜底 ---
    {
        "target": "src/maisaka/builtin_tool/context.py",
        "source": "src/maisaka/builtin_tool/context.py",
        "desc": "outbound_send 消息标记 is_self_message",
    },
    {
        "target": "src/maisaka/builtin_tool/query_jargon.py",
        "source": "src/maisaka/builtin_tool/query_jargon.py",
        "desc": "同参数重复调用拦截，防止死循环",
    },
    {
        "target": "src/maisaka/builtin_tool/query_memory.py",
        "source": "src/maisaka/builtin_tool/query_memory.py",
        "desc": "同参数重复调用拦截，防止死循环",
    },
    {
        "target": "src/maisaka/builtin_tool/tool_search.py",
        "source": "src/maisaka/builtin_tool/tool_search.py",
        "desc": "关键词搜不到工具时用 AI 语义搜索兜底",
    },
    # --- replyer 看得见工具结果，防幻觉 ---
    {
        "target": "src/chat/replyer/maisaka_generator_base.py",
        "source": "src/chat/replyer/maisaka_generator_base.py",
        "desc": "replyer 能看到工具调用结果，避免编造数字等幻觉",
    },
    # --- 提示词 ---
    {
        "target": "prompts/zh-CN/maisaka_chat.prompt",
        "source": "prompts/zh-CN/maisaka_chat.prompt",
        "desc": "提示词加入不回复自己消息等规则 + napcat 工具使用规则",
    },
]

STATE_FILENAME = ".napcat-ai-tools-patches.json"
BACKUP_ROOTNAME = "patches_backup"


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def atomic_write(path: Path, data: bytes) -> None:
    """先写临时文件再原子替换，避免写一半留下损坏文件。"""
    tmp = path.with_name(path.name + f".patch_tmp_{os.getpid()}")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def find_maibot_root(explicit: Optional[str]) -> Optional[Path]:
    """定位 MaiBot 主程序根目录（含 src/maisaka 的目录）。"""
    candidates: List[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser().resolve())
    env = os.environ.get("MAIBOT_HOME")
    if env:
        candidates.append(Path(env).expanduser().resolve())
    candidates.append(Path.cwd().resolve())
    for cand in candidates:
        if (cand / "src" / "maisaka").is_dir():
            return cand
    return None


class PatchTool:
    def __init__(self, root: Path, patches_dir: Path, force: bool = False):
        self.root = root
        self.patches_dir = patches_dir
        self.force = force
        self.state_path = root / STATE_FILENAME
        self.state: Dict = {}
        # 本次运行的处理记录，用于失败回滚
        self._processed: List[Dict] = []

    # ---------- 状态文件 ----------

    def load_state(self) -> None:
        if self.state_path.exists():
            try:
                self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.state = {}
        else:
            self.state = {}

    def save_state(self, backup_dir: Optional[str]) -> None:
        files = {}
        for rel, info in self.state.get("files", {}).items():
            files[rel] = info
        payload = {
            "patch_version": PATCH_VERSION,
            "min_maibot_version": MIN_MAIBOT_VERSION,
            "installed_at": self.state.get("installed_at") or time.strftime("%Y-%m-%d %H:%M:%S"),
            "backup_dir": backup_dir or self.state.get("backup_dir"),
            "files": files,
        }
        atomic_write(self.state_path, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))

    # ---------- 单文件判定 ----------

    def file_status(self, entry: Dict[str, str]) -> str:
        """返回单个补丁文件的状态：
        installed           目标文件与补丁一致，已安装
        installed_modified  状态表里是已安装，但目标文件被外部改过
        missing_source      仓库里补丁文件缺失（异常）
        not_installed       未安装（目标缺失或内容不同）
        """
        bundled = self.patches_dir / entry["source"]
        target = self.root / entry["target"]
        if not bundled.is_file():
            return "missing_source"
        if not target.is_file():
            return "not_installed"
        bundled_sha = sha256_of(read_bytes(bundled))
        target_sha = sha256_of(read_bytes(target))
        if target_sha == bundled_sha:
            return "installed"
        rec = self.state.get("files", {}).get(entry["target"])
        if rec:
            # 状态文件里登记过该文件：说明由本工具安装过，内容对不上即安装后被外部修改
            return "installed_modified"
        # 未安装（目标缺失或内容不同）
        return "not_installed"

    # ---------- 备份 ----------

    def backup_file(self, target: Path, backup_dir: Path, rel: str) -> Optional[Path]:
        """备份单个目标文件，返回备份文件路径；目标不存在时返回 None。"""
        if not target.is_file():
            return None
        dest = backup_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, dest)
        return dest

    def restore_file(self, backup: Optional[Path], target: Path) -> None:
        """从备份恢复；backup 为 None 表示原文件本不存在，应删除。"""
        if backup is None:
            if target.exists():
                target.unlink()
        else:
            atomic_write(target, read_bytes(backup))

    # ---------- 子命令 ----------

    def status(self) -> int:
        print(f"MaiBot 主程序根目录: {self.root}")
        print(f"补丁版本: {PATCH_VERSION}（适配 MaiBot >= {MIN_MAIBOT_VERSION}）")
        if self.state:
            print(f"状态文件: {self.state_path}（{self.state.get('installed_at', '?')} 安装）")
        else:
            print("状态文件: 无（从未通过本工具安装过，或已卸载）")
        print("-" * 72)
        counts = {"installed": 0, "installed_modified": 0, "not_installed": 0, "missing_source": 0}
        for entry in PATCHES:
            st = self.file_status(entry)
            counts[st] += 1
            marks = {
                "installed": "[已安装]      ",
                "installed_modified": "[已装·被改]   ",
                "not_installed": "[未安装]      ",
                "missing_source": "[补丁缺失]    ",
            }
            print(f"{marks[st]} {entry['target']}")
            print(f"               └─ {entry['desc']}")
        print("-" * 72)
        if counts["missing_source"]:
            print("!! 仓库补丁文件缺失，请检查仓库完整性")
            return 2
        if counts["not_installed"] == 0 and counts["installed_modified"] == 0:
            print("全部补丁已安装。")
            return 0
        if counts["installed_modified"]:
            print("有补丁文件在安装后被外部修改过（install --force 可强制覆盖重装）。")
        else:
            print(f"有 {counts['not_installed']} 个补丁未安装，执行 install 命令安装。")
        return 1

    def install(self) -> int:
        print(f"MaiBot 主程序根目录: {self.root}")
        todo: List[Dict[str, str]] = []
        for entry in PATCHES:
            st = self.file_status(entry)
            if st == "installed":
                print(f"[跳过] 已安装: {entry['target']}")
            elif st == "installed_modified":
                if self.force:
                    todo.append(entry)
                else:
                    print(
                        f"[跳过] {entry['target']} 在补丁安装后被外部修改过，"
                        "为避免覆盖你的改动已跳过；确认要覆盖请加 --force"
                    )
            elif st == "missing_source":
                print(f"[错误] 仓库补丁文件缺失: {entry['source']}")
                return 2
            else:
                todo.append(entry)

        if not todo:
            if not self.state:
                # 全部已装但无状态文件（例如曾手动覆盖安装）→ 补写状态文件，便于后续 status/uninstall
                files = {}
                for entry in PATCHES:
                    files[entry["target"]] = {
                        "installed_sha256": sha256_of(read_bytes(self.patches_dir / entry["source"])),
                        "patch_version": PATCH_VERSION,
                        "backup": None,
                        "existed_before": True,
                    }
                self.state = {"installed_at": time.strftime("%Y-%m-%d %H:%M:%S"), "files": files}
                self.save_state(None)
                print("\n所有补丁均已安装（此前无安装记录），已补写状态文件，无需操作。")
            else:
                print("\n所有补丁均已安装，无需操作。")
            return 0

        backup_dir = self.root / BACKUP_ROOTNAME / time.strftime("%Y%m%d_%H%M%S")
        backup_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n开始安装 {len(todo)} 个补丁，备份目录: {backup_dir}")

        try:
            for entry in todo:
                rel = entry["target"]
                target = self.root / rel
                bundled = self.patches_dir / entry["source"]
                data = read_bytes(bundled)
                target.parent.mkdir(parents=True, exist_ok=True)

                backup_path = self.backup_file(target, backup_dir, rel)
                if backup_path is not None:
                    self._processed.append({"rel": rel, "backup": str(backup_path), "existed": True})
                else:
                    self._processed.append({"rel": rel, "backup": None, "existed": False})

                atomic_write(target, data)

                # 校验写入结果
                if sha256_of(read_bytes(target)) != sha256_of(data):
                    raise RuntimeError(f"写入后校验失败: {rel}")
                print(f"[完成] {rel} —— {entry['desc']}")
        except Exception as exc:  # noqa: BLE001 任一步失败 → 整体回滚
            print(f"\n!! 安装失败: {exc}", file=sys.stderr)
            print("!! 开始回滚本次全部改动 ...", file=sys.stderr)
            self._rollback()
            print("!! 已回滚到安装前状态。", file=sys.stderr)
            return 3

        # 更新状态文件
        self.load_state()
        files = self.state.get("files", {})
        for item in self._processed:
            rel = item["rel"]
            bundled_entry = next(p for p in PATCHES if p["target"] == rel)
            bundled_sha = sha256_of(read_bytes(self.patches_dir / bundled_entry["source"]))
            files[rel] = {
                "installed_sha256": bundled_sha,
                "patch_version": PATCH_VERSION,
                "backup": item["backup"],
                "existed_before": item["existed"],
            }
        self.state = {"installed_at": time.strftime("%Y-%m-%d %H:%M:%S"), "files": files}
        self.save_state(str(backup_dir))
        print(f"\n安装完成，共 {len(self._processed)} 个文件。状态已写入 {self.state_path}")
        print("提示：改动涉及 Python 源码，请重启 MaiBot 主程序后生效。")
        return 0

    def _rollback(self) -> None:
        """把本次已处理的文件恢复到安装前状态（逆序回滚）。"""
        for item in reversed(self._processed):
            target = self.root / item["rel"]
            backup = Path(item["backup"]) if item["backup"] else None
            try:
                self.restore_file(backup, target)
                print(f"  [回滚] {item['rel']}")
            except Exception as exc:  # noqa: BLE001
                print(f"  [回滚失败] {item['rel']}: {exc}（可手动从备份目录恢复）", file=sys.stderr)
        self._processed.clear()

    def uninstall(self) -> int:
        print(f"MaiBot 主程序根目录: {self.root}")
        self.load_state()
        files = self.state.get("files", {})
        if not files:
            # 没有状态文件：尝试按补丁内容反查（能识别出已安装的文件就还原不了原文件，只能提示）
            print("未找到补丁状态文件（可能从未安装，或已卸载）。")
            any_installed = any(self.file_status(e) == "installed" for e in PATCHES)
            if any_installed:
                print("检测到部分文件与补丁内容一致，但没有备份信息，无法自动还原。")
                print("如需还原请手动处理，或重新覆盖安装官方原版 MaiBot 文件。")
            return 1

        failed = 0
        restored = 0
        for rel, rec in files.items():
            target = self.root / rel
            backup = rec.get("backup")
            existed_before = rec.get("existed_before")
            try:
                if backup is None and existed_before is False:
                    # 补丁新建的文件（原本不存在）→ 卸载即删除
                    if target.exists():
                        target.unlink()
                    print(f"[还原] {rel}（原文件本不存在，已删除补丁文件）")
                elif backup is None:
                    # 原有文件但没有备份信息 → 拒绝删除，避免弄坏主程序
                    failed += 1
                    print(
                        f"[跳过] {rel}: 是主程序原有文件但没有备份记录，"
                        "无法自动还原；请用官方原版 MaiBot 对应文件覆盖",
                        file=sys.stderr,
                    )
                else:
                    self.restore_file(Path(backup), target)
                    restored += 1
                    print(f"[还原] {rel}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"[还原失败] {rel}: {exc}", file=sys.stderr)
        if failed:
            print(f"\n卸载完成但有 {failed} 个文件还原失败，请检查 patches_backup/ 目录。", file=sys.stderr)
            return 2
        try:
            self.state_path.unlink()
        except OSError:
            pass
        print(f"\n卸载完成，已还原 {restored}/{len(files)} 个文件，状态文件已删除。请重启 MaiBot 主程序。")
        return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="MaiBot 主程序补丁安装工具（napcat-ai-tools 配套，触发外部 planner 等修改）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n  python patch_tool.py status\n  python patch_tool.py install --target /home\n  python patch_tool.py uninstall\n",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("status", "查看补丁安装状态"),
        ("install", "安装补丁（已安装自动跳过，失败自动回滚）"),
        ("uninstall", "卸载补丁（从备份还原原文件）"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--target", help="MaiBot 主程序根目录（含 src/ 与 prompts/），也可用环境变量 MAIBOT_HOME")
        if name == "install":
            p.add_argument("--force", action="store_true", help="目标文件被外部修改时仍强制覆盖")
    args = parser.parse_args(argv)

    root = find_maibot_root(getattr(args, "target", None))
    if root is None:
        print("未能定位 MaiBot 主程序根目录（需要存在 src/maisaka/）。", file=sys.stderr)
        print("请用 --target 指定，或设置环境变量 MAIBOT_HOME，例如：", file=sys.stderr)
        print("  python patch_tool.py install --target /path/to/MaiBot", file=sys.stderr)
        return 2

    patches_dir = Path(__file__).resolve().parent
    tool = PatchTool(root, patches_dir, force=bool(getattr(args, "force", False)))
    tool.load_state()

    if args.command == "status":
        return tool.status()
    if args.command == "install":
        return tool.install()
    return tool.uninstall()


if __name__ == "__main__":
    sys.exit(main())
