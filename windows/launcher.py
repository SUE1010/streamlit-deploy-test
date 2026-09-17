"""PyInstaller entry point that boots the Streamlit app as a standalone app."""
import os
import sys
import pathlib


def _resource_path(name: str) -> str:
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, name)


def _skip_first_run_email_prompt() -> None:
    config_dir = pathlib.Path.home() / ".streamlit"
    config_dir.mkdir(parents=True, exist_ok=True)
    credentials_file = config_dir / "credentials.toml"
    if not credentials_file.exists():
        credentials_file.write_text('[general]\nemail = ""\n', encoding="utf-8")


if __name__ == "__main__":
    _skip_first_run_email_prompt()

    from streamlit.web import cli as stcli

    sys.argv = [
        "streamlit",
        "run",
        _resource_path("streamlit-chatbot.py"),
        "--global.developmentMode=false",
        "--server.headless=false",
    ]
    sys.exit(stcli.main())
