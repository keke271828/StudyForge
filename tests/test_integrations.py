from pathlib import Path
import asyncio

from studyforge import integrations, mcp_server
from studyforge.ai import save_settings
from studyforge import runtime
from types import SimpleNamespace
import yaml


def test_dsh_patch_preserves_existing_entries(tmp_path, monkeypatch):
    home = tmp_path / "dsh"
    profile = home / "profiles" / "web"
    profile.mkdir(parents=True)
    desktop = home / "profiles" / "desktop"
    desktop.mkdir(parents=True)
    desktop_patch = desktop / "cordis.patch.yml"
    desktop_patch.write_text("# desktop profile\n- id: existing-desktop\n  name: example\n", encoding="utf-8")
    patch = profile / "cordis.patch.yml"
    old = "# keep this comment\n- insert:\n    - id: existing\n      name: example\n"
    patch.write_text(old, encoding="utf-8")
    monkeypatch.setenv("DSH_HOME", str(home))
    monkeypatch.setattr(integrations.shutil, "which", lambda name: "dsh.exe")
    result = integrations.connect_dsh()
    assert result["connected"]
    assert patch.read_text(encoding="utf-8").startswith(old)
    assert patch.read_text(encoding="utf-8").count("mcp-studyforge") == 1
    assert desktop_patch.read_text(encoding="utf-8").count("mcp-studyforge") == 1
    assert "python.exe" in desktop_patch.read_text(encoding="utf-8")
    assert list(profile.glob("*.bak"))
    integrations.connect_dsh()
    assert patch.read_text(encoding="utf-8").count("mcp-studyforge") == 1
    assert desktop_patch.read_text(encoding="utf-8").count("mcp-studyforge") == 1


def test_dsh_patch_repairs_legacy_python_command(tmp_path, monkeypatch):
    home = tmp_path / "dsh"
    profile = home / "profiles" / "desktop"
    profile.mkdir(parents=True)
    patch = profile / "cordis.patch.yml"
    patch.write_text("- insert:\n    - id: unrelated\n      config:\n        command: keep-me\n"
                     "    - id: mcp-studyforge\n      config:\n        command: python\n"
                     "        failOnStartupError: true\n- insert:\n    - id: another\n",
                     encoding="utf-8")
    monkeypatch.setenv("DSH_HOME", str(home))
    integrations.connect_dsh()
    result = patch.read_text(encoding="utf-8")
    assert "command: keep-me" in result
    assert "failOnStartupError: false" in result
    assert "command: python\n" not in result
    assert "- id: another" in result
    assert result.count("mcp-studyforge") == 1


def test_mcp_grading_uses_selected_provider(monkeypatch):
    selected = []
    async def chosen(provider=None, model=None, effort=None):
        from studyforge.ai import default_provider
        selected.append(provider or default_provider())
        return object()
    monkeypatch.setattr(mcp_server, "assessment_client", chosen)
    save_settings({"chat_provider": "codex"})
    asyncio.run(mcp_server.grading_client())
    save_settings({"chat_provider": "deepseek"})
    asyncio.run(mcp_server.grading_client())
    assert selected == ["codex", "deepseek"]


def test_installed_mcp_uses_bundled_executable(monkeypatch):
    monkeypatch.setattr(runtime.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(runtime.sys, 'executable', 'C:/Apps/StudyForge/resources/backend/StudyForgeBackend.exe')
    command, args = runtime.mcp_command()
    assert command.endswith('StudyForgeBackend.exe')
    assert args == ['--mcp']


def test_dsh_migrates_python_arguments_to_frozen_mcp(tmp_path, monkeypatch):
    profile = tmp_path / 'profiles' / 'desktop'
    profile.mkdir(parents=True)
    patch = profile / 'cordis.patch.yml'
    patch.write_text('- insert:\n    - id: mcp-studyforge\n      config:\n'
                     '        command: python\n        args: [-m, studyforge.mcp_server]\n'
                     '        failOnStartupError: false\n', encoding='utf-8')
    monkeypatch.setenv('DSH_HOME', str(tmp_path))
    monkeypatch.setattr(integrations, 'mcp_command', lambda: ('C:/应用/StudyForgeBackend.exe', ['--mcp']))
    integrations.connect_dsh()
    config = yaml.safe_load(patch.read_text(encoding='utf-8'))[0]['insert'][0]['config']
    assert config['command'] == 'C:/应用/StudyForgeBackend.exe'
    assert config['args'] == ['--mcp']
    after = patch.read_text(encoding='utf-8')
    integrations.connect_dsh()
    assert patch.read_text(encoding='utf-8') == after


def test_codex_migrates_known_python_entry_to_frozen_mcp(monkeypatch):
    calls = []
    monkeypatch.setattr(integrations.shutil, 'which', lambda _: 'codex.exe')
    monkeypatch.setattr(integrations, 'mcp_command', lambda: ('C:/Apps/StudyForgeBackend.exe', ['--mcp']))
    def run(command, **options):
        calls.append(command)
        output = 'command: C:/Python312/python.exe\nargs: -m studyforge.mcp_server\n' if command[2] == 'get' else ''
        return SimpleNamespace(returncode=0, stdout=output, stderr='')
    monkeypatch.setattr(integrations.subprocess, 'run', run)
    assert integrations.connect_codex()['connected']
    assert calls[-1][-2:] == ['C:/Apps/StudyForgeBackend.exe', '--mcp']


def test_codex_preserves_custom_entry(monkeypatch):
    calls = []
    monkeypatch.setattr(integrations.shutil, 'which', lambda _: 'codex.exe')
    def run(command, **options):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout='command: C:/Tools/custom.exe\nargs: custom\n', stderr='')
    monkeypatch.setattr(integrations.subprocess, 'run', run)
    import pytest
    with pytest.raises(RuntimeError, match='自定义'):
        integrations.connect_codex()
    assert len(calls) == 1
