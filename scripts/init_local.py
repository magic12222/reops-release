"""Create ignored local lab credentials without overwriting an existing .env."""
import secrets

from tools.system_tools import ROOT


def main():
    path = ROOT / ".env"
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(f"POSTGRES_PASSWORD={secrets.token_urlsafe(32)}\n")
            stream.write(f"REOPS_CONTROL_TOKEN={secrets.token_urlsafe(32)}\n")
    except FileExistsError:
        print("Existing .env preserved.")
    else:
        print("Created ignored .env with random local credentials. Keep this file private.")


if __name__ == "__main__":
    main()
