"""Exercise the macOS launcher with fake tools; no packages, keys or network are used."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ZSH = shutil.which("zsh")
pytestmark = pytest.mark.skipif(ZSH is None, reason="macOS launcher requires zsh")


@pytest.fixture
def tools(tmp_path: Path):
    project, binary, home = (tmp_path / name for name in ("project", "bin", "home"))
    for path in (project, binary, home):
        path.mkdir()
    shutil.copy(ROOT / "setup_local.command", project / "setup_local.command")
    (project / "scripts").mkdir()
    (project / "scripts/test_fixture.mjs").write_text("// No real frontend test is run here.\n")
    (project / ".env").write_text("PRIVATE_PLACEHOLDER=preserve\n")
    log = tmp_path / "commands.log"
    python = tmp_path / "fake-python"
    python.write_text('#!/bin/sh\nprintf "venv-python %s\\n" "$*" >> "$SETUP_TEST_LOG"\n')
    python.chmod(0o755)

    def command(name: str, body: str):
        path = binary / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)
        return path

    command("make", 'printf "make %s\\n" "$*" >> "$SETUP_TEST_LOG"\n')
    create_venv = ('/bin/mkdir -p .venv/bin\n'
                   '/bin/cp "$SETUP_TEST_PYTHON" .venv/bin/python\n')

    def node(label="user-node", folder=binary):
        path = folder / "node"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/bin/sh\n'
                        f'printf "{label} %s\\n" "$*" >> "$SETUP_TEST_LOG"\n'
                        'if [ "$1" = "--help" ]; then printf "%s\\n" "--test-timeout"; fi\n')
        path.chmod(0o755)
        return path

    def run():
        result = subprocess.run([str(ZSH), "setup_local.command"], cwd=project,
                                env={"PATH": str(binary), "HOME": str(home),
                                     "SETUP_TEST_LOG": str(log),
                                     "SETUP_TEST_PYTHON": str(python)},
                                capture_output=True, text=True, timeout=5)
        commands = log.read_text() if log.exists() else ""
        assert (project / ".env").read_text() == "PRIVATE_PLACEHOLDER=preserve\n"
        return result, commands

    return command, node, run, create_venv, project, home


def test_uv_setup_uses_uv_installer_without_requiring_pip_and_prefers_user_node(tools):
    command, node, run, create_venv, _, home = tools
    node()
    node("bundled-node", home / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin")
    command("uv", 'printf "uv %s\\n" "$*" >> "$SETUP_TEST_LOG"\n'
            'if [ "$1" = "venv" ]; then\n' + create_venv + 'fi\n')
    result, commands = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "uv venv .venv --python 3.12" in commands
    assert "uv pip install --python .venv/bin/python -r requirements.txt" in commands
    assert "venv-python -m pip" not in commands and "bundled-node" not in commands
    assert "make check" in commands and "user-node --test --test-timeout=5000" in commands


def test_python_setup_has_a_pip_fallback_when_uv_is_absent(tools):
    command, node, run, create_venv, _, _ = tools
    node()
    command("python3.12", create_venv)
    result, commands = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "venv-python -m pip install -r requirements.txt" in commands
    assert "make check" in commands


def test_optional_bundled_node_is_used_only_when_path_has_no_node(tools):
    command, node, run, create_venv, _, home = tools
    node("bundled-node", home / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin")
    command("python3.12", create_venv)
    result, commands = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "bundled-node --test --test-timeout=5000" in commands


def test_missing_node_stops_before_any_environment_or_dependency_install(tools):
    command, _, run, _, project, _ = tools
    command("uv", 'printf "unexpected install\\n" >> "$SETUP_TEST_LOG"\n')
    result, commands = run()
    assert result.returncode != 0 and "Node.js is required" in result.stdout
    assert commands == "" and not (project / ".venv").exists()


def test_missing_python_has_a_clear_prerequisite_error(tools):
    _, node, run, _, project, _ = tools
    node()
    result, commands = run()
    assert result.returncode != 0 and "Python 3.12 is required" in result.stdout
    assert "make check" not in commands and not (project / ".venv").exists()


def test_old_node_stops_before_installing_dependencies(tools):
    command, _, run, _, project, _ = tools
    command("node", 'printf "%s\\n" "older node without the required test option"\n')
    result, commands = run()
    assert result.returncode != 0 and "must support --test-timeout" in result.stdout
    assert commands == "" and not (project / ".venv").exists()
