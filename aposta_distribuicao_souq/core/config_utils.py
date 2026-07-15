from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "parametros.yaml"


def load_config(path: str | None = None) -> dict:
    path = Path(path or DEFAULT_CONFIG_PATH)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def save_config(data: dict, path: str | None = None) -> None:
    path = Path(path or DEFAULT_CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
