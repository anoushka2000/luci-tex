from __future__ import annotations

import shutil
import subprocess as sp
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import typer

from .archive import archive as make_archive


@contextmanager
def git_worktree_at(ref: str) -> Iterator[Path]:
    """Checkout a detached worktree at a git ref and yield its path.

    Ensures cleanup of the worktree even on failure.
    """
    with TemporaryDirectory() as td:
        tdp = Path(td)
        # Add detached worktree
        sp.run(
            ["git", "worktree", "add", "--detach", str(tdp), ref],
            check=True,
            stdout=sp.DEVNULL,
            stderr=sp.DEVNULL,
        )
        try:
            yield tdp
        finally:
            # Best-effort cleanup; ignore errors
            sp.run(
                ["git", "worktree", "remove", "--force", str(tdp)],
                check=False,
                stdout=sp.DEVNULL,
                stderr=sp.DEVNULL,
            )


def _git_repo_root() -> Path:
    res = sp.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    if res.returncode != 0:
        raise RuntimeError("Not inside a git repository")
    return Path(res.stdout.strip())


def _verify_git_ref(ref: str) -> None:
    res = sp.run(["git", "rev-parse", "--verify", ref], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Git reference not found: {ref}")


def _unzip_all(zip_path: Path, dest: Path) -> None:
    import zipfile

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest)


def _extract_main_from_zip(zip_path: Path, main_name: str, dest: Path) -> None:
    import zipfile

    with zipfile.ZipFile(zip_path, "r") as zf:
        with zf.open(main_name) as src, open(dest, "wb") as out:
            out.write(src.read())


def run_latexdiff(old_tex: Path, new_tex: Path, out_tex: Path) -> None:
    """Run latexdiff to produce a diff TeX file.

    Split out for test monkeypatching.
    """
    if shutil.which("latexdiff") is None:
        raise RuntimeError("latexdiff not found in PATH")
    res = sp.run(
        ["latexdiff", str(old_tex), str(new_tex)], capture_output=True, text=True
    )
    if res.returncode != 0:
        raise RuntimeError(f"latexdiff failed: {res.stderr.strip()}")
    out_tex.write_text(res.stdout, encoding="utf-8")


def compile_with_tectonic(tex: Path, cwd: Path) -> None:
    if shutil.which("tectonic") is None:
        raise RuntimeError("tectonic not found in PATH")
    res = sp.run(["tectonic", str(tex.name)], cwd=cwd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(
            f"tectonic failed to compile diff:\n{res.stdout}\n{res.stderr}"
        )


def _default_outdir(main: Path) -> Path:
    # Follow mkdiff.sh and example: main.tex -> main-diff/
    return Path(f"{main.stem}-diff")


def _make_archive_at(main: Path, workdir: Path | None, out_zip: Path) -> None:
    # Use luci.archive directly for deterministic behavior; no validation for speed
    main_path = main if workdir is None else workdir / main.name
    make_archive(main=main_path, output=out_zip, validate=False, bbl=False)


def diff(
    main: Path = typer.Argument(..., help="Path to main .tex file"),
    old: str = typer.Argument(..., help="Git ref for OLD version"),
    new: str | None = typer.Option(
        None, "--new", help="Optional git ref for NEW version; defaults to working tree"
    ),
    outdir: Path | None = typer.Option(
        None, "--outdir", help="Output directory (default: <main-stem>-diff)"
    ),
    compile: bool = typer.Option(
        True, "--compile/--no-compile", help="Compile the diff with tectonic"
    ),
    force: bool = typer.Option(
        False, "--force", help="Remove existing output directory if it exists"
    ),
):
    """Create a LaTeX diff between two versions of a project.

    - With only OLD: diffs OLD vs current working directory.
    - With OLD and --new NEW: diffs OLD vs NEW.
    Outputs to <main-stem>-diff/ by default.
    """
    # Ensure we are inside a git repo and refs exist
    _git_repo_root()
    _verify_git_ref(old)
    if new is not None:
        _verify_git_ref(new)

    out = outdir or _default_outdir(main)
    if out.exists():
        if force:
            if out.is_dir():
                shutil.rmtree(out)
            else:
                out.unlink()
        else:
            raise RuntimeError(f"Output already exists: {out}")
    out.mkdir(parents=True, exist_ok=True)

    # 1) OLD version archive and extract main -> main_old.tex
    with TemporaryDirectory() as td:
        td_zip = Path(td) / "old.zip"
        with git_worktree_at(old) as wtd:
            _make_archive_at(main, wtd, td_zip)
        _extract_main_from_zip(td_zip, main.name, out / f"{main.stem}_old.tex")

    # 2) NEW version archive and extract all + main -> main_new.tex
    with TemporaryDirectory() as td2:
        td_zip2 = Path(td2) / "new.zip"
        if new is None:
            _make_archive_at(main, None, td_zip2)
        else:
            with git_worktree_at(new) as wtn:
                _make_archive_at(main, wtn, td_zip2)
        _unzip_all(td_zip2, out)
        # Ensure main.tex is not present in outdir, per requirement
        maybe_main = out / main.name
        if maybe_main.exists():
            maybe_main.unlink()
        _extract_main_from_zip(td_zip2, main.name, out / f"{main.stem}_new.tex")

    # 3) latexdiff -> <stem>_diff.tex
    diff_tex = out / f"{main.stem}_diff.tex"
    run_latexdiff(out / f"{main.stem}_old.tex", out / f"{main.stem}_new.tex", diff_tex)

    # 4) Compile if requested
    if compile:
        compile_with_tectonic(diff_tex, cwd=out)
