"""Exercise Make setup with fake interpreters/installers; no downloads or live credentials."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def tools(tmp_path: Path, *, uv: bool, python_supported: bool) -> dict[str, str]:
    (tmp_path / "Makefile").write_text((ROOT / "Makefile").read_text())
    (tmp_path / ".env.example").write_text("BOSON_API_KEY=\nVOICE_ADAPTER=mock\n")
    binary = tmp_path / "tools"
    binary.mkdir()
    for command in ("cp", "chmod", "mkdir"):
        source = shutil.which(command)
        assert source
        (binary / command).symlink_to(source)
    stub = tmp_path / "venv-python"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    interpreter = binary / "python3"
    interpreter.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "-c" ]; then exit {0 if python_supported else 1}; fi\n'
        'if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then\n'
        '  mkdir -p "$3/bin"\n  cp "$VENV_STUB" "$3/bin/python"\n'
        '  chmod 755 "$3/bin/python"\nfi\n')
    interpreter.chmod(0o755)
    if uv:
        installer = binary / "uv"
        installer.write_text(
            '#!/bin/sh\nif [ "$1" = "venv" ]; then\n'
            '  mkdir -p "$2/bin"\n  cp "$VENV_STUB" "$2/bin/python"\n'
            '  chmod 755 "$2/bin/python"\nfi\nexit 0\n')
        installer.chmod(0o755)
    return {**os.environ, "PATH": str(binary), "VENV_STUB": str(stub)}


def setup(tmp_path: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    make = shutil.which("make")
    assert make
    return subprocess.run([make, "setup", f"MAKE={make}"], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=5)


@pytest.mark.parametrize(("existing", "use_uv"), [(False, True), (True, False)])
def test_setup_protects_new_or_existing_env_without_replacing_content(tmp_path, existing, use_uv):
    env = tools(tmp_path, uv=use_uv, python_supported=True)
    target = tmp_path / ".env"
    expected = "private-local-setting\n" if existing else (tmp_path / ".env.example").read_text()
    if existing:
        target.write_text(expected)
        target.chmod(0o644)
    result = setup(tmp_path, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert target.read_text() == expected
    assert target.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / ".venv/bin/python").exists()


def test_old_python_is_rejected_before_venv_or_env_is_modified(tmp_path):
    env = tools(tmp_path, uv=False, python_supported=False)
    target = tmp_path / ".env"
    target.write_text("unchanged-local-setting\n")
    target.chmod(0o644)
    result = setup(tmp_path, env)
    assert result.returncode != 0
    assert "Python 3.12 or newer is required" in result.stdout
    assert not (tmp_path / ".venv").exists()
    assert target.read_text() == "unchanged-local-setting\n"
    assert target.stat().st_mode & 0o777 == 0o644
