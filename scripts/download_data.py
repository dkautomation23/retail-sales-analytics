"""Download UCI Online Retail II (CC BY 4.0) into data/raw/ and verify it.

    python scripts/download_data.py

The archive is not committed: it is a 45 MB third-party file. Its sha256 is
pinned below so a silently changed upstream file fails loudly instead of
producing different numbers.
"""
import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
SHA256 = "572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb"
RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
ARCHIVE = RAW / "online_retail_ii.zip"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    if not ARCHIVE.exists():
        print(f"downloading {URL}")
        urllib.request.urlretrieve(URL, ARCHIVE)
    actual = sha256(ARCHIVE)
    if SHA256 and actual != SHA256:
        print(f"sha256 mismatch: expected {SHA256}, got {actual}", file=sys.stderr)
        return 1
    print(f"sha256 {actual} ok")
    with zipfile.ZipFile(ARCHIVE) as outer:
        outer.extractall(RAW)
    print("files:", ", ".join(sorted(p.name for p in RAW.iterdir() if p.name != ".keep")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
