from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

from .runtime import background_process_options, mcp_command


def connect_codex() -> dict:
    executable = shutil.which("codex")
    if not executable:
        raise RuntimeError("未找到 Codex CLI")
    existing = subprocess.run([executable, "mcp", "get", "studyforge"], capture_output=True, text=True,
                              timeout=30, **background_process_options())
    command, args = mcp_command()
    if existing.returncode == 0:
        match = re.search(r"(?m)^\s*command:\s*(.*?)\s*$", existing.stdout)
        old_command = match[1] if match else ""
        old_name = Path(old_command).name.lower()
        correct_args = ("--mcp" in existing.stdout if args == ["--mcp"]
                        else "studyforge.mcp_server" in existing.stdout)
        if old_command == command and correct_args:
            return {"connected": True, "message": "Codex MCP 已配置；请重启 VS Code Codex 扩展并在对话中调用 studyforge 工具"}
        safe_legacy = old_name in ("python", "python.exe", "py", "py.exe") and "studyforge.mcp_server" in existing.stdout
        safe_installed = old_name == "studyforgebackend.exe" and "--mcp" in existing.stdout
        if not (safe_legacy or safe_installed):
            raise RuntimeError("Codex 已有自定义 studyforge 配置；为避免覆盖，请先核对 codex mcp get studyforge")
        removed = subprocess.run([executable, "mcp", "remove", "studyforge"], capture_output=True, text=True,
                                 timeout=30, **background_process_options())
        if removed.returncode:
            raise RuntimeError(removed.stderr.strip() or "旧 Codex MCP 配置无法替换")
    result = subprocess.run([executable, "mcp", "add", "studyforge", "--", command, *args],
                            capture_output=True, text=True, timeout=30, **background_process_options())
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Codex MCP 配置失败")
    return {"connected": True, "message": "Codex MCP 已配置；请重启 VS Code Codex 扩展，并在对话中要求调用 studyforge 工具"}


def connect_dsh() -> dict:
    home = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))
    profiles = [home / "profiles" / name for name in ("desktop", "web")]
    profiles = [profile for profile in profiles if profile.is_dir()]
    if not profiles:
        raise RuntimeError("没有找到 DSH Desktop 或 Web 的 profile；请先启动 DSH Desktop")
    command, args = mcp_command()
    command_yaml = yaml.safe_dump(Path(command).as_posix(), default_style='"').strip()
    args_yaml = yaml.safe_dump(args, default_flow_style=True).strip()
    addition = ("- insert:\n"
                "    - id: mcp-studyforge\n"
                "      name: '@deepseek-ai/dsh-mcp-client'\n"
                "      config:\n"
                "        serverName: studyforge\n"
                "        transport: stdio\n"
                f"        command: {command_yaml}\n"
                f"        args: {args_yaml}\n"
                "        failOnStartupError: false\n")
    updated = []
    for profile in profiles:
        patch_file = profile / "cordis.patch.yml"
        old = patch_file.read_text(encoding="utf-8") if patch_file.exists() else "[]\n"
        node = yaml.compose(old) if old.strip() else None
        if node is not None and not isinstance(node, yaml.nodes.SequenceNode):
            raise RuntimeError(f"Harness {profile.name} patch 文件不是列表，已停止修改")
        if "id: mcp-studyforge" in old:
            lines = old.splitlines(keepends=True)
            matches = [i for i, line in enumerate(lines) if re.match(r"^\s*- id: mcp-studyforge\s*$", line)]
            if len(matches) != 1:
                raise RuntimeError(f"Harness {profile.name} 的 StudyForge 配置无法安全迁移")
            index = matches[0]
            indentation = len(lines[index]) - len(lines[index].lstrip())
            end_index = index + 1
            while end_index < len(lines):
                line = lines[end_index]
                if line.lstrip().startswith("- ") and len(line) - len(line.lstrip()) <= indentation:
                    break
                end_index += 1
            start = sum(map(len, lines[:index]))
            end = sum(map(len, lines[:end_index]))
            section = old[start:end]
            section = re.sub(r"(?m)^([ \t]*command:)[ \t]*.*$", lambda m: f"{m[1]} {command_yaml}", section, count=1)
            if re.search(r"(?m)^[ \t]*args:", section):
                section = re.sub(r"(?m)^([ \t]*args:)[ \t]*.*$", lambda m: f"{m[1]} {args_yaml}", section, count=1)
            else:
                section = re.sub(r"(?m)^([ \t]*)command:.*$", lambda m: f"{m[0]}\n{m[1]}args: {args_yaml}", section, count=1)
            section = re.sub(r"(?m)^(\s*failOnStartupError:)\s*.*$", r"\g<1> false", section, count=1)
            if "command:" not in section or "failOnStartupError:" not in section:
                raise RuntimeError(f"Harness {profile.name} 的 StudyForge 配置缺少关键字段")
            candidate = old[:start] + section + old[end:]
            if candidate == old:
                continue
        else:
            candidate = addition if not old.strip() or old.strip() == "[]" else old.rstrip() + "\n" + addition
        yaml.compose(candidate)
        if patch_file.exists():
            backup = patch_file.with_name(f"{patch_file.name}.{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak")
            shutil.copyfile(patch_file, backup)
        temp = patch_file.with_suffix(".tmp")
        temp.write_text(candidate, encoding="utf-8")
        os.replace(temp, patch_file)
        updated.append(profile.name)
    return {"connected": True, "profiles": [profile.name for profile in profiles],
            "message": ("已配置 " + "、".join(updated) if updated else "现有配置已包含 StudyForge") +
            "；请重启 DSH Desktop，并在对话中调用 mcp__studyforge__list_projects"}
