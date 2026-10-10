"""직접 만든 시험 파일의 작성자 정보 제거. 사용자 문서에는 적용하지 않는다."""
from __future__ import annotations

import re
from pathlib import Path
from zipfile import ZipFile, is_zipfile


def clean_sample(path: Path) -> None:
    # 구형 Office OLE 파일에도 테마용 ZIP이 내장될 수 있어 is_zipfile만으로 판단하면 안 된다.
    with path.open("rb") as stream:
        header = stream.read(4)
    if header == b"PK\x03\x04" and is_zipfile(path):
        # OOXML·ODF·HWPX는 저장할 때 Office 사용자 이름을 다시 넣을 수 있다.
        with ZipFile(path) as archive:
            members = [(info, archive.read(info)) for info in archive.infolist()]
        part = path.with_name(path.name + ".metadata-tmp")
        try:
            with ZipFile(part, "w") as archive:
                for info, data in members:
                    if info.filename in ("docProps/core.xml", "docProps/app.xml", "meta.xml", "Contents/content.hpf"):
                        text = data.decode("utf-8")
                        text = re.sub(
                            r'(<(?:\w+:)?(?:creator|lastModifiedBy|initial-creator|Company|Manager)\b[^>]*>).*?(</[^>]+>)',
                            r'\1\2', text, flags=re.DOTALL)
                        text = re.sub(r'(<opf:meta\b[^>]*name="(?:creator|lastsaveby)"[^>]*>).*?(</opf:meta>)',
                                      r'\1\2', text, flags=re.DOTALL | re.IGNORECASE)
                        data = text.encode("utf-8")
                    archive.writestr(info, data)
            part.replace(path)
        finally:
            part.unlink(missing_ok=True)
    elif path.suffix.lower() == ".rtf":
        data = path.read_bytes()
        data = re.sub(rb'\{\\(?:author|operator)\s[^{}]*\}', b'', data)
        path.write_bytes(data)
    elif path.suffix.lower() == ".hwp":
        # Office 파일은 생성 시 RemovePersonalInformation으로 처리한다.
        # OLE를 직접 다시 저장하면 구형 Office 파일의 내부 검증값이 달라질 수 있다.
        _clean_ole(path)


def _clean_ole(path: Path) -> None:
    import pythoncom
    from win32com import storagecon as sc

    mode = sc.STGM_READWRITE | sc.STGM_SHARE_EXCLUSIVE
    storage = pythoncom.StgOpenStorage(str(path.resolve()), None, mode)
    # HWP의 사용자 정의 요약 스트림도 같은 Property Set 형식을 쓴다.
    for entry in storage.EnumElements():
        name = entry[0]
        ids = {14, 15} if name == "\x05DocumentSummaryInformation" else {4, 8}
        if name not in ("\x05SummaryInformation", "\x05DocumentSummaryInformation", "\x05HwpSummaryInformation"):
            continue
        stream = storage.OpenStream(name, None, mode)
        data = bytearray(stream.Read(1 << 20))
        if len(data) < 48:
            raise ValueError(f"시험 파일 요약 정보가 올바르지 않아요: {path.name}")
        section = int.from_bytes(data[44:48], "little")
        count = int.from_bytes(data[section + 4:section + 8], "little")
        for i in range(count):
            at = section + 8 + 8 * i
            prop = int.from_bytes(data[at:at + 4], "little")
            offset = section + int.from_bytes(data[at + 4:at + 8], "little")
            if prop not in ids:
                continue
            kind = int.from_bytes(data[offset:offset + 4], "little")
            if kind not in (30, 31):  # VT_LPSTR / VT_LPWSTR
                continue
            length = int.from_bytes(data[offset + 4:offset + 8], "little") * (2 if kind == 31 else 1)
            end = offset + 8 + length
            if end > len(data):
                raise ValueError("시험 파일의 요약 정보 길이가 올바르지 않아요")
            data[offset + 4:offset + 8] = (1).to_bytes(4, "little")
            data[offset + 8:end] = bytes(length)
        stream.Seek(0, 0)
        stream.Write(bytes(data))
        stream.Commit(0)
        stream = None
    storage.Commit(0)
