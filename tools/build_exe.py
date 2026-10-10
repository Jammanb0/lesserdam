"""아이콘과 라이선스 고지를 포함하는 Windows EXE 빌드."""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

from collect_licenses import collect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pdftool import APP_TITLE  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist" / "lesserdam")
    args = parser.parse_args()
    dest = args.dist.resolve()
    collect()
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
                    "--name", APP_TITLE, "--icon", "assets/app-icon-v3.ico",
                    # lxml은 pikepdf가 XMP 메타데이터를 다룰 때만 쓰고 이 앱은 그 기능을 쓰지 않는다.
                    # 빼면 lxml에 정적으로 들어 있는 libiconv(LGPL-2.1) 등도 배포물에서 빠진다.
                    "--exclude-module", "lxml",
                    "--add-data", "assets/app-icon-v3.ico;assets",
                    "--add-data", "LICENSE;.", "--add-data", "THIRD_PARTY_NOTICES.md;.", "--add-data", "licenses;licenses",
                    "--distpath", str(dest), "--workpath", "build/lesserdam", "--specpath", ".",
                    "app.py"], cwd=ROOT, check=True)
    shutil.copyfile(ROOT / "THIRD_PARTY_NOTICES.md", dest / "THIRD_PARTY_NOTICES.md")
    shutil.copyfile(ROOT / "LICENSE", dest / "LICENSE")
    shutil.copytree(ROOT / "licenses", dest / "licenses", dirs_exist_ok=True)
    exe = dest / f"{APP_TITLE}.exe"
    (dest / "SHA256SUMS.txt").write_text(f"{hashlib.sha256(exe.read_bytes()).hexdigest()}  {exe.name}\n", encoding="utf-8")
    print(f"빌드 완료: {exe}")


if __name__ == "__main__":
    main()
