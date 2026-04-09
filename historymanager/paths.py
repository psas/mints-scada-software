# historymanager/paths.py

from __future__ import annotations

from pathlib import Path

from .models import BaseDirs, RunPaths, SNAPSHOTS_DIRNAME

RAW_ROOT_DIRNAME = ".ignitionraw"
RAWBAK_ROOT_DIRNAME = ".ignitionrawbak"
HISTORY_ROOT_DIRNAME = "ignitionhistory"


_MODULE_DIR = Path(__file__).resolve().parent
_DEFAULT_PROJECT_ROOT = _MODULE_DIR.parent


def get_project_root(project_root: str | Path | None = None) -> Path:
    """Return the project root used by history storage.

    By default this resolves relative to the historymanager package location,
    not the current working directory.
    """
    if project_root is None:
        return _DEFAULT_PROJECT_ROOT
    return Path(project_root).expanduser().resolve()


def get_base_dirs(project_root: str | Path | None = None) -> BaseDirs:
    root = get_project_root(project_root)
    return BaseDirs(
        project_root=root,
        raw_root=root / RAW_ROOT_DIRNAME,
        rawbak_root=root / RAWBAK_ROOT_DIRNAME,
        history_root=root / HISTORY_ROOT_DIRNAME,
    )


def ensure_base_dirs(project_root: str | Path | None = None) -> BaseDirs:
    base_dirs = get_base_dirs(project_root)
    base_dirs.raw_root.mkdir(parents=True, exist_ok=True)
    base_dirs.rawbak_root.mkdir(parents=True, exist_ok=True)
    base_dirs.history_root.mkdir(parents=True, exist_ok=True)
    return base_dirs


def build_run_paths(run_id: str, project_root: str | Path | None = None) -> RunPaths:
    base_dirs = get_base_dirs(project_root)
    history_dir = base_dirs.history_root / run_id
    return RunPaths(
        run_id=run_id,
        raw_dir=base_dirs.raw_root / run_id,
        rawbak_dir=base_dirs.rawbak_root / run_id,
        history_dir=history_dir,
        snapshots_dir=history_dir / SNAPSHOTS_DIRNAME,
    )