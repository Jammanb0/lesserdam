# PDF 변환 합치기

이미지를 PDF로 바꾸고, PDF와 이미지를 정한 순서대로 PDF 하나로 합치는 Windows 프로그램이에요.
설치 없이 exe 하나로 돌아가요.

## 지금 할 수 있는 것

- **① 이미지 → PDF**: 이미지 여러 개를 PDF 하나로, 또는 이미지마다 PDF 하나씩
- **② PDF 합치기**: PDF와 이미지를 목록 순서대로 PDF 하나로 (원래 파일은 그대로)
- 파일·폴더를 창에 끌어다 놓기, 줄을 끌어서 순서 바꾸기, 탐색기와 같은 이름순 정렬
- 이미지 쪽 크기: A4에 맞춤(가로로 긴 이미지는 가로 A4) / 원본 크기

## 개발 환경에서 실행

```
py -3.14 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python app.py
```

## exe 만들기

```
.venv\Scripts\pyinstaller --onefile --windowed --name "PDF 변환 합치기" app.py
```

`dist\PDF 변환 합치기.exe`가 생겨요.
