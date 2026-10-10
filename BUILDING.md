# 소스에서 EXE 만들기

Windows x64와 Python 3.14.7에서 확인한 빌드 방법입니다.
Python·패키지를 준비할 때는 인터넷 연결이 필요합니다.
한글·Office는 EXE 빌드에 필요하지 않고, 해당 문서를 실제 변환할 때 필요합니다.

## 배포 파일 구성

- `*-windows-x64.zip`: EXE, MIT 라이선스, 외부 구성 요소 고지와 원문
- `*-source.zip`: `app/`의 앱 소스·아이콘·빌드 도구와 `upstream/`의 의존성 소스
- `SHA256SUMS.txt`: 위 ZIP 파일의 SHA-256

소스 ZIP의 `SOURCE_MANIFEST.json`에는 앱 커밋, EXE 해시, 의존성 소스의
공식 다운로드 URL과 해시를 기록합니다. `upstream/`에는 수정하지 않은
img2pdf 0.6.3과 pikepdf 10.16.0 소스 배포본을 함께 제공합니다.

## 일반 빌드

소스 ZIP을 풀고 `app/` 폴더에서 PowerShell로 실행합니다.
Git에서 받은 경우 저장소 최상위 폴더에서 실행하면 됩니다.

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-build.txt
.venv\Scripts\python tools\build_exe.py
```

결과는 `dist\lesserdam\레서담 - PDF 변환 합치기.exe`입니다.
동일한 소스라도 빌드 시각·도구 환경에 따라 EXE 해시는 달라질 수 있습니다.

## 수정한 img2pdf로 다시 만들기

현재 EXE는 img2pdf를 내부에 묶습니다. EXE가 임의의 외부 img2pdf를 불러온다고
가정하지 않고, 수정한 라이브러리를 설치한 환경에서 EXE를 다시 만드는 방법을 제공합니다.
앱 소스는 MIT, img2pdf 소스는 LGPL-3.0-or-later를 따릅니다.

먼저 위의 일반 빌드 환경을 준비합니다. 소스 ZIP의 `app/`에서 아래 명령으로
라이브러리 소스를 풉니다.

```powershell
tar -xf ..\upstream\img2pdf-0.6.3.tar.gz -C ..\upstream
```

`..\upstream\img2pdf-0.6.3\src\img2pdf.py` 등을 원하는 대로 수정한 뒤 실행합니다.
앱이 쓰는 API를 유지하면 수정한 라이브러리를 넣어 빌드할 수 있습니다.

```powershell
.venv\Scripts\python -m pip install --force-reinstall --no-deps --no-cache-dir ..\upstream\img2pdf-0.6.3
.venv\Scripts\python -c "import img2pdf; print(img2pdf.__file__)"
.venv\Scripts\python tools\build_exe.py --dist dist\modified
```

이후 `requirements-build.txt`를 다시 설치하면 수정본이 공식 버전으로 바뀔 수 있으므로,
수정본을 마지막에 설치하세요. 라이브러리 설치에 필요한 빌드 도구는 해당 소스의
`pyproject.toml`에 따라 pip가 준비합니다. 출력 EXE는 일반 EXE처럼 직접 실행할 수 있으며
개발자 서명이나 별도 활성화 키를 요구하지 않습니다.

앱 소스만 Git에서 받은 경우에는 [img2pdf 공식 배포 페이지](https://pypi.org/project/img2pdf/0.6.3/#files)의
소스 배포본을 받아 같은 절차를 적용할 수 있습니다.
pikepdf의 소스와 MPL 2.0 원문도 소스 ZIP에 포함하며, 네이티브 빌드 방법은 해당 소스의
문서와 [공식 설치 안내](https://pikepdf.readthedocs.io/en/latest/installation.html)를 참고하세요.

## 결과 확인과 고지

빌드한 EXE로 가상 이미지의 변환·합치기·책갈피를 확인하세요.
개발 환경의 점검 방법은 [README](README.md#점검)에 있습니다.
배포할 때는 EXE ZIP과 같은 버전의 소스 ZIP, 해시 파일을 함께 제공하세요.
외부 구성 요소의 라이선스 원문과 [오픈소스 고지](THIRD_PARTY_NOTICES.md)도 유지해야 합니다.
Microsoft 런타임은 별도 재배포 조건이 적용되므로 빌드 성공만으로 배포 조건 충족을 판단하지 않습니다.
