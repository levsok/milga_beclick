from pathlib import Path

from dotenv import load_dotenv


def load_environment():
    for filename in (".env", "notion.env"):
        env_path = Path(filename)
        if env_path.exists():
            load_dotenv(env_path, override=False)
