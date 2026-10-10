"""설치된 정확한 버전의 배포 고지를 수집한다. 법적 검토 완료를 뜻하지 않는다."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from importlib import metadata
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
# lxml은 설치 의존성 조사에 포함하되 EXE 코드에는 넣지 않는다. 고지는 개발 환경까지 보존한다.
PACKAGES = ("img2pdf", "pikepdf", "pillow", "pywin32", "packaging", "lxml",
            "pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "pywin32-ctypes", "setuptools")


def collect() -> None:
    output = ROOT / "licenses"
    inventory = []
    for name in PACKAGES:
        dist = metadata.distribution(name)
        files = []
        for file in dist.files or ():
            parts = file.parts
            if not parts[0].endswith(".dist-info"):
                continue
            if not any(word in file.name.lower() for word in ("license", "copying", "notice")) and "licenses" not in parts:
                continue
            rel = Path(name, *parts[1:])
            src, dst = Path(dist.locate_file(file)), output / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            files.append({"path": rel.as_posix(), "sha256": hashlib.sha256(dst.read_bytes()).hexdigest()})
        if not files:
            raise RuntimeError(f"라이선스 원문을 찾지 못했어요: {name}")
        role = "excluded-runtime-dependency" if name == "lxml" else (
            "application-runtime" if name in PACKAGES[:5] else "build-tool")
        inventory.append({"name": name, "version": dist.version, "role": role,
                          "requires": dist.requires or [], "files": files})
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    (output / "python").mkdir(exist_ok=True)
    shutil.copyfile(python_license, output / "python" / "LICENSE.txt")
    for dll, folder in (("tcl90.dll", "tcl_library"), ("tcl9tk90.dll", "tk_library")):
        with ZipFile(Path(sys.base_prefix) / "DLLs" / dll) as archive:
            (output / "python" / f"{folder}-license.terms").write_bytes(archive.read(f"{folder}/license.terms"))
    # img2pdf의 LGPLv3는 GPLv3 전문도 함께 제공하도록 요구한다.
    shutil.copyfile(output / "pikepdf/licenses/third-party-licenses/GPL-3.0.txt", output / "GPL-3.0.txt")
    (output / "inventory.json").write_text(json.dumps({"python": sys.version.split()[0], "packages": inventory},
                                                     ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(inventory)}개 패키지의 라이선스와 Python 고지를 수집했어요.")


if __name__ == "__main__":
    collect()
