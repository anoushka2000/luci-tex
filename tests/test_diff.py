from __future__ import annotations

import subprocess as sp
from pathlib import Path

import pytest

from luci import diff as diff_mod
from luci.cli import cli


def _init_git_repo(cwd: Path) -> None:
    sp.run(["git", "init"], cwd=cwd, check=True, capture_output=True)
    sp.run(
        [
            "git",
            "config",
            "user.email",
            "test@example.com",
        ],
        cwd=cwd,
        check=True,
    )
    sp.run(["git", "config", "user.name", "Test"], cwd=cwd, check=True)


def _commit_all(cwd: Path, msg: str) -> str:
    sp.run(["git", "add", "-A"], cwd=cwd, check=True)
    sp.run(["git", "commit", "-m", msg], cwd=cwd, check=True)
    res = sp.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return res.stdout.strip()


def test_diff_cli_old_vs_worktree(
    tmp_path: Path, latex_project, cli_runner, monkeypatch: pytest.MonkeyPatch
):
    # Setup project in git repo
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    # Create initial project files
    proj = latex_project
    old_ref = _commit_all(tmp_path, "init")

    # Change working copy content
    proj.main.write_text(
        proj.main.read_text() + "\nMore text in new version.\n",
        encoding="utf-8",
    )

    # Monkeypatch latexdiff to avoid external dependency
    def fake_latexdiff(old_tex: Path, new_tex: Path, out_tex: Path) -> None:
        out_tex.write_text(
            f"DIFF\nOLD:{old_tex.read_text()}\nNEW:{new_tex.read_text()}",
            encoding="utf-8",
        )

    monkeypatch.setattr(diff_mod, "run_latexdiff", fake_latexdiff)

    # Run CLI
    res = cli_runner.invoke(cli, ["diff", str(proj.main), old_ref, "--no-compile"])
    assert res.exit_code == 0, res.stdout

    outdir = tmp_path / f"{proj.main.stem}-diff"
    assert outdir.exists()
    # Check key artifacts
    assert (outdir / f"{proj.main.stem}_old.tex").exists()
    assert (outdir / f"{proj.main.stem}_new.tex").exists()
    assert (outdir / f"{proj.main.stem}_diff.tex").exists()
    # main.tex should NOT be present
    assert not (outdir / proj.main.name).exists()
    # Assets from archive should be present (flattened base name)
    assert (outdir / proj.img.name).exists()
    assert (outdir / proj.cls.name).exists()


def test_diff_cli_two_refs(
    tmp_path: Path, latex_project, cli_runner, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)

    proj = latex_project
    old_ref = _commit_all(tmp_path, "init")
    # Modify and commit new version
    proj.main.write_text(
        proj.main.read_text() + "\nSecond version.\n",
        encoding="utf-8",
    )
    new_ref = _commit_all(tmp_path, "v2")

    def fake_latexdiff(old_tex: Path, new_tex: Path, out_tex: Path) -> None:
        out_tex.write_text("OK", encoding="utf-8")

    monkeypatch.setattr(diff_mod, "run_latexdiff", fake_latexdiff)

    res = cli_runner.invoke(
        cli, ["diff", str(proj.main), old_ref, "--new", new_ref, "--no-compile"]
    )
    assert res.exit_code == 0, res.stdout

    outdir = tmp_path / f"{proj.main.stem}-diff"
    assert (outdir / f"{proj.main.stem}_diff.tex").exists()
    assert not (outdir / proj.main.name).exists()


def test_diff_custom_outdir(
    tmp_path: Path, latex_project, cli_runner, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    _init_git_repo(tmp_path)
    proj = latex_project
    old_ref = _commit_all(tmp_path, "init")

    # Monkeypatch latexdiff
    monkeypatch.setattr(
        diff_mod,
        "run_latexdiff",
        lambda a, b, c: c.write_text("X", encoding="utf-8"),
    )

    outdir = tmp_path / "custom_out"
    res = cli_runner.invoke(
        cli,
        [
            "diff",
            str(proj.main),
            old_ref,
            "--outdir",
            str(outdir),
            "--no-compile",
        ],
    )
    assert res.exit_code == 0, res.stdout
    assert outdir.exists()
    assert (outdir / f"{proj.main.stem}_diff.tex").exists()
    assert not (outdir / proj.main.name).exists()
