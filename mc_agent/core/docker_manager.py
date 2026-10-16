"""Docker 控制模块：通过 docker CLI 管理无头 MC 客户端容器。

内存硬限制：--memory=1536m --memory-swap=2048m（见 config [mc]）。
使用 host 网络模式，避免容器与主程序网络不通。
"""

from __future__ import annotations

import asyncio
import json
import re


class DockerManager:
    def __init__(self, image: str, memory_limit: str, memory_swap: str, logger=None) -> None:
        self.image = image
        self.memory_limit = memory_limit
        self.memory_swap = memory_swap
        self.log = logger

    async def _run(self, *args: str, timeout: float = 60) -> tuple[bool, str]:
        cmd = ("docker", *args)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return False, f"docker 命令超时: {' '.join(args[:2])}..."
            text = out.decode("utf-8", errors="replace").strip()
            return proc.returncode == 0, text
        except FileNotFoundError:
            return False, "docker 命令不可用"
        except OSError as e:
            return False, f"docker 命令执行失败: {e}"

    async def image_exists(self) -> bool:
        ok, out = await self._run("images", "--format", "{{.Repository}}:{{.Tag}}")
        return ok and self.image in out.splitlines()

    async def container_exists(self, name: str) -> bool:
        ok, out = await self._run("ps", "-a", "--format", "{{.Names}}")
        return ok and name in out.splitlines()

    async def start_client(
        self,
        name: str,
        mc_server: str,
        mc_port: int,
        username: str,
        bot_http_port: int,
        plugin_http_port: int,
        offline_mode: bool,
    ) -> tuple[bool, str]:
        """启动 MC 客户端容器（限内存 + host 网络）。"""
        if await self.container_exists(name):
            await self.remove_container(name, force=True)
        args = [
            "run",
            "-d",
            "--name", name,
            "--memory", self.memory_limit,
            "--memory-swap", self.memory_swap,
            "--network", "host",
            "--restart", "unless-stopped",
            "-e", f"MC_SERVER={mc_server}",
            "-e", f"MC_PORT={mc_port}",
            "-e", f"BOT_NAME={username}",
            "-e", f"BOT_HTTP_PORT={bot_http_port}",
            "-e", f"PLUGIN_HTTP=http://127.0.0.1:{plugin_http_port}",
            "-e", f"MC_OFFLINE={'true' if offline_mode else 'false'}",
            "-e", f"CONTAINER_NAME={name}",
        ]
        ok, out = await self._run(*args, timeout=90)
        if not ok:
            return False, out
        return True, out.splitlines()[-1] if out else ""

    async def stop_client(self, name: str, timeout: float = 30) -> tuple[bool, str]:
        ok, out = await self._run("stop", "-t", str(int(timeout)), name)
        return ok, out

    async def remove_container(self, name: str, force: bool = False) -> tuple[bool, str]:
        args = ("rm", "-f") if force else ("rm",)
        return await self._run(*args, name)

    async def restart_container(self, name: str) -> tuple[bool, str]:
        return await self._run("restart", name, timeout=60)

    async def container_running(self, name: str) -> bool:
        ok, out = await self._run("ps", "--format", "{{.Names}}")
        return ok and name in out.splitlines()

    async def container_logs(self, name: str, tail: int = 50) -> str:
        ok, out = await self._run("logs", "--tail", str(tail), name)
        return out if ok else f"获取日志失败: {out}"

    async def memory_usage_mb(self, name: str) -> dict[str, Any]:
        """查询容器内存占用（MB）。返回 {"usage_mb": float|None, "limit_mb": float|None, "percent": float|None}"""
        ok, out = await self._run(
            "stats", "--no-stream", "--format",
            "{{.MemUsage}}|{{.MemPerc}}", name, timeout=30,
        )
        if not ok or "|" not in out:
            return {"usage_mb": None, "limit_mb": None, "percent": None}
        mem_usage, mem_perc = out.split("|", 1)
        usage, limit = mem_usage.split("/", 1) if "/" in mem_usage else (mem_usage, "")

        def to_mb(v: str) -> float | None:
            v = v.strip()
            m = re.match(r"([\d.]+)\s*(MiB|GiB|kB)", v)
            if not m:
                return None
            val, unit = float(m.group(1)), m.group(2)
            return val * 1024 if unit == "GiB" else (val / 1024 if unit == "kB" else val)

        perc = None
        pm = re.search(r"([\d.]+)%", mem_perc)
        if pm:
            perc = float(pm.group(1))
        return {"usage_mb": to_mb(usage), "limit_mb": to_mb(limit), "percent": perc}

    async def stats_all(self) -> list[dict[str, Any]]:
        """所有 mc-agent 容器的内存统计。"""
        results = []
        ok, out = await self._run(
            "ps", "--format", "{{.Names}}", "--filter", "name=mc-agent-"
        )
        if ok:
            for name in out.splitlines():
                name = name.strip()
                if not name:
                    continue
                mem = await self.memory_usage_mb(name)
                running = await self.container_running(name)
                results.append({"name": name, "running": running, **mem})
        return results

    async def docker_info(self) -> str:
        ok, out = await self._run("info", "--format", "{{.ServerVersion}}")
        return out if ok else out
