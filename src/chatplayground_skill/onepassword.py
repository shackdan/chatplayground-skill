import json
import shutil
import subprocess
from typing import Callable, Optional

DEFAULT_ITEM = "automation"
TIMEOUT_S = 10


def get_credentials(
    item: str = DEFAULT_ITEM,
    run_fn: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Optional[tuple]:
    if shutil.which("op") is None:
        return None

    try:
        result = run_fn(
            ["op", "item", "get", item, "--fields", "label=username,label=password", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None

    try:
        data = json.loads(result.stdout)
        values = {f["label"]: f["value"] for f in data["fields"]}
        return (values["username"], values["password"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
