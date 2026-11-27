import csv
import re

from pathlib import Path
from functools import lru_cache


OUI_FILE = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "oui.csv"
)


@lru_cache(maxsize=1)
def load_oui_database() -> dict[str, str]:
    database = {}

    if not OUI_FILE.exists():
        return database

    with OUI_FILE.open(
        encoding="utf-8-sig",
        newline=""
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            prefix = row["Assignment"].strip().upper()
            vendor = row["Organization Name"].strip()
            database[prefix] = vendor

    return database


def get_vendor(mac: str | None) -> str | None:
    if not mac:
        return None

    normalized = mac.replace(":", "").replace("-", "").upper()

    if not re.fullmatch(r"[0-9A-F]{12}", normalized):
        return None

    if int(normalized[:2], 16) & 3:
        return None

    return load_oui_database().get(normalized[:6])
