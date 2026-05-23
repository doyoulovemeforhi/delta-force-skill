import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


CONFIG_FILE_NAME = "config.json"
_config_cache: Optional[Dict[str, Any]] = None


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _maybe_load_dotenv() -> None:
    """Load project root `.env` into os.environ (optional; requires python-dotenv)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(project_root() / ".env", override=False)


_maybe_load_dotenv()


def load_config() -> Dict[str, Any]:
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    config_path = project_root() / CONFIG_FILE_NAME
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as f:
            _config_cache = json.load(f)
    else:
        _config_cache = {}
    return _config_cache


def save_config(config: Dict[str, Any]) -> None:
    global _config_cache
    config_path = project_root() / CONFIG_FILE_NAME
    with config_path.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    _config_cache = config


def get_api_key() -> Optional[str]:
    gui_config = load_config().get("gui_agent", {})
    return (
        gui_config.get("api_key")
        or gui_config.get("DASHSCOPE_API_KEY")
        or os.environ.get("DASHSCOPE_API_KEY")
    )


def set_api_key(api_key: str, provider: str = "aliyun") -> None:
    config = load_config()
    config.setdefault("gui_agent", {})
    config["gui_agent"]["api_key"] = api_key
    config["gui_agent"]["provider"] = provider
    save_config(config)


def get_gui_agent_config() -> Dict[str, Any]:
    return load_config().get("gui_agent", {})


def get_swat_product_config() -> Dict[str, Any]:
    return load_config().get("swat_product", {})


def set_gui_agent_config(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
) -> None:
    config = load_config()
    gui_config = config.setdefault("gui_agent", {})
    if api_key is not None:
        gui_config["api_key"] = api_key
    if base_url is not None:
        gui_config["base_url"] = base_url
    if model is not None:
        gui_config["model"] = model
    if provider is not None:
        gui_config["provider"] = provider
    save_config(config)


def set_swat_product_config(
    cookie: Optional[str] = None,
    version: Optional[str] = None,
    swimlane: Optional[str] = None,
) -> None:
    config = load_config()
    swat_config = config.setdefault("swat_product", {})
    if cookie is not None:
        swat_config["cookie"] = cookie
    if version is not None:
        swat_config["version"] = version
    if swimlane is not None:
        swat_config["swimlane"] = swimlane
    save_config(config)
