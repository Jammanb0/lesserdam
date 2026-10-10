# 오픈소스 고지

이 프로그램은 아래 오픈소스 구성 요소를 사용합니다. 원문은 함께 제공하는
`licenses/`에 있습니다. 프로그램 아래쪽의 **오픈소스 고지…**에서도 읽을 수 있습니다.
프로젝트 자체 코드에는 루트의 `LICENSE`에 있는 MIT 라이선스가 적용됩니다.
아래 외부 구성 요소에는 각각의 라이선스가 적용됩니다.
의존성의 수정·재결합 및 이를 디버깅하기 위한 역공학에 관한 해당 라이선스상의 권리를 제한하지 않습니다.

## 실행에 사용되는 Python 패키지

| 구성 요소 | 검토한 버전 | 라이선스 / 원문 위치 |
| --- | --- | --- |
| img2pdf | 0.6.3 | LGPL-3.0-or-later, `licenses/img2pdf/licenses/LICENSE` 및 `licenses/GPL-3.0.txt` |
| pikepdf | 10.16.0 | MPL-2.0, `licenses/pikepdf/licenses/LICENSE.txt` |
| Pillow | 12.3.0 | MIT-CMU 및 포함된 코덱별 조건, `licenses/pillow/licenses/LICENSE` |
| pywin32 | 312 | PSF 계열 및 구성 요소별 고지, `licenses/pywin32/licenses/` |
| packaging | 26.3 | Apache-2.0 또는 BSD-2-Clause, `licenses/packaging/licenses/` |

lxml 6.1.3(pikepdf의 간접 의존성)은 개발 환경에 설치되지만 EXE 코드에는 넣지 않습니다.
이 앱에서 사용하는 pikepdf 처리 경로는 XMP 편집을 호출하지 않으며, 저장 시 XMP의 PDF 버전
자동 수정도 끕니다. 따라서 기존 XMP가 있는 파일도 lxml 없이 처리합니다.
개발 환경용 lxml의 BSD-3-Clause 및 번들 고지는 `licenses/lxml/`에 별도로 보존했습니다.
Windows wheel의 libiconv(LGPL-2.1)는 현재 EXE에 포함되지 않습니다.
향후 lxml을 EXE에 다시 넣으면 libiconv의 소스·재결합 조건을 다시 검토해야 합니다.

img2pdf의 저작권: Copyright (C) 2012-2021 Johannes Schauer Marin Rodrigues. 전체 저작권·기여자 표기는 해당 소스에 있습니다.
수정하지 않은 원본 소스는 다음 버전의 공식 배포 페이지에서 받을 수 있습니다.

- [img2pdf 0.6.3 소스](https://pypi.org/project/img2pdf/0.6.3/#files)
- [pikepdf 10.16.0 소스 — MPL 2.0](https://pypi.org/project/pikepdf/10.16.0/#files)

공개 배포 시에는 위 라이브러리의 정확한 소스와, 수정된 라이브러리를 사용해 프로그램을
다시 만들 수 있는 애플리케이션 코드·빌드 자료의 배포 위치도 함께 제공해야 합니다.

## Python 외에 포함되는 코드

- Python 3.14.7, Tcl/Tk 9.0.4: `licenses/python/`의 원문을 따릅니다.
- pikepdf의 qpdf 12.4.2: Apache-2.0. Windows wheel에는 JPEG, zlib, OpenSSL,
  Microsoft Visual C++ 런타임도 포함됩니다. 각각의 원문은
  `licenses/pikepdf/licenses/third-party-licenses/`에 있습니다.
  해당 폴더에는 다른 플랫폼·선택 기능에 관한 고지도 함께 보존했습니다.
- Pillow wheel의 통합 LICENSE에는 JPEG, TIFF, WebP, OpenJPEG, zlib-ng,
  libavif 및 그 하위 코덱, LittleCMS, FreeType 등의 고지가 들어 있습니다.
  포함 라이선스를 통째로 보존했으며 전부를 앱에서 직접 사용하는 것은 아닙니다.
  FreeType을 포함하는 배포에서는 FreeType License 선택 시 요구되는 출처 고지도 유지합니다:
  Portions of this software are copyright © The FreeType Project (https://freetype.org/). All rights reserved.
- CPython의 OpenSSL 3.5.7, Expat 2.8.2, libffi, liblzma, zstd, mpdecimal,
  zlib-ng와 Tcl의 zlib 1.3.2·LibTomMath도 사용됩니다. Python 배포본의 원문과
  `licenses/python/third-party/`에 추가 고지를 보존했습니다. 후자의 원문 URL과
  SHA-256은 `sources.json`에 있습니다. XZ 고지 중 GPL 도구·스크립트는 이 EXE에 포함되지 않습니다.
- Microsoft 런타임의 재배포 조건은 `licenses/python/LICENSE.txt`와
  pikepdf의 `microsoft-visual-cpp-runtime.txt`에 있습니다. 앱 자체의 MIT와 구별해야 합니다.
  최종 배포물에서 이들 조건을 충족하는지 배포 전에 확인해야 합니다.

## 빌드 도구

PyInstaller 6.22.3은 GPL-2.0-or-later와 bootloader 예외를 사용합니다.
이 예외는 PyInstaller 때문에 애플리케이션 전체에 GPL을 적용해야 하는 상황을 피하게 해 주지만,
img2pdf·pikepdf 등 다른 의존성의 조건까지 면제하지 않습니다.
런타임 훅은 Apache-2.0입니다. 원문은 `licenses/pyinstaller/licenses/COPYING.txt`에 있습니다.

빌드에 사용한 hooks-contrib 2026.8, altgraph 0.17.5, pefile 2024.8.26,
pywin32-ctypes 0.2.3, setuptools 84.0.0의 고지도 `licenses/`에 수집했습니다.
빌드 도구 전체가 EXE에 포함된다는 뜻은 아닙니다.

정확한 설치 버전과 수집한 원문의 SHA-256은 `licenses/inventory.json`에 기록했습니다.
