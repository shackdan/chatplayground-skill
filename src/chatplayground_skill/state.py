import json
import os
import stat
from pathlib import Path
from typing import Optional


def ensure_state_dir(state_dir: Path) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(state_dir, stat.S_IRWXU)


def _storage_state_path(state_dir: Path) -> Path:
    return state_dir / "storage_state.json"


def _threads_path(state_dir: Path) -> Path:
    return state_dir / "threads.json"


def _atomic_write(path: Path, content: str, mode: int) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content)
    os.chmod(tmp_path, mode)
    os.replace(tmp_path, path)


def has_valid_session(state_dir: Path) -> bool:
    path = _storage_state_path(state_dir)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    return bool(data.get("cookies"))


def save_storage_state(state_dir: Path, data: dict) -> None:
    ensure_state_dir(state_dir)
    _atomic_write(_storage_state_path(state_dir), json.dumps(data), stat.S_IRUSR | stat.S_IWUSR)


def load_storage_state(state_dir: Path) -> dict:
    path = _storage_state_path(state_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def load_threads(state_dir: Path) -> dict:
    path = _threads_path(state_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_threads(state_dir: Path, threads: dict) -> None:
    ensure_state_dir(state_dir)
    _atomic_write(_threads_path(state_dir), json.dumps(threads), stat.S_IRUSR | stat.S_IWUSR)


def get_thread_anchor(state_dir: Path, model: str) -> Optional[str]:
    return load_threads(state_dir).get(model)


def set_thread_anchor(state_dir: Path, model: str, anchor: str) -> None:
    threads = load_threads(state_dir)
    threads[model] = anchor
    save_threads(state_dir, threads)


def reset_thread(state_dir: Path, model: str) -> None:
    threads = load_threads(state_dir)
    if model in threads:
        del threads[model]
        save_threads(state_dir, threads)
