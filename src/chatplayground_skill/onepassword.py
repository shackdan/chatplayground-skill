import json
import shutil
import subprocess
from typing import Callable, Optional

DEFAULT_ITEM = "chatplayground.ai"
DEFAULT_VAULT = "automation"
TIMEOUT_S = 10


def get_credentials(
    item: str = DEFAULT_ITEM,
    vault: str = DEFAULT_VAULT,
    run_fn: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Optional[tuple]:
    if shutil.which("op") is None:
        return None

    try:
        result = run_fn(
            [
                "op",
                "item",
                "get",
                item,
                "--vault",
                vault,
                "--fields",
                "label=username,label=password",
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None

    try:
        # `op item get --fields ... --format json` returns a top-level
        # JSON array of field objects, not {"fields": [...]}.
        fields = json.loads(result.stdout)
        values = {f["label"]: f["value"] for f in fields}
        return (values["username"], values["password"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
