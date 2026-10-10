"""저장 실패·중지·프로세스 소유권 회귀 점검 (Office를 띄우지 않음)."""
import sys
import os
import tempfile
import threading
import unittest
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile, is_zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pdftool import core, office
from pdftool.gui.merge_tab import MergeTab
from sample_metadata import clean_sample


class SavingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = Path(self.tmp.name) / "결과.pdf"
        self.target.write_bytes(b"original")

    def test_failed_write_preserves_existing_file(self):
        def fail(part):
            part.write_bytes(b"incomplete")
            raise OSError("test failure")
        with self.assertRaises(core.SaveError):
            core.store(self.target, fail)
        self.assertEqual(self.target.read_bytes(), b"original")
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])

    def test_cancel_during_write_preserves_existing_file(self):
        cancel = threading.Event()
        def write(part):
            part.write_bytes(b"completed but cancelled")
            cancel.set()
        with self.assertRaises(core.Cancelled):
            core.store(self.target, write, cancel=cancel)
        self.assertEqual(self.target.read_bytes(), b"original")
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])

    def test_concurrent_saves_have_separate_temporary_files(self):
        barrier = threading.Barrier(2)
        parts = []
        def write(part):
            parts.append(part)
            part.write_bytes(b"complete")
            barrier.wait(timeout=5)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(core.store, self.target, write) for _ in range(2)]
            for f in futures:
                f.result(timeout=10)
        self.assertNotEqual(parts[0], parts[1])
        self.assertEqual(self.target.read_bytes(), b"complete")

    def test_cancel_at_end_of_image_conversion_does_not_save(self):
        cache = core.DocCache()
        session = core.Session(lambda _: None, cache)
        self.addCleanup(cache.clear)
        self.addCleanup(session.close)
        def convert(*args):
            session.cancel.set()
            return b"new content"
        with patch.object(core.images, "image_pdf_bytes", side_effect=convert):
            report = core.convert_each(session, [(core.Item(Path("sample.png"), "image"), self.target)], core.ImageOptions())
        self.assertTrue(report.stopped)
        self.assertEqual(report.saved, [])
        self.assertEqual(self.target.read_bytes(), b"original")

    def test_bookmark_failure_is_reported(self):
        pdf = Mock()
        pdf.open_outline.side_effect = ValueError("broken outline")
        with self.assertRaises(core.SaveError):
            core._bookmarks(pdf, [("row", 0, [("file", 0)])])

    def test_cleanup_keeps_active_cache_and_removes_abandoned_cache(self):
        with patch.object(core.tempfile, "gettempdir", return_value=self.tmp.name):
            cache = core.DocCache()
            self.addCleanup(cache.clear)
            (cache.dir / "result.pdf").write_bytes(b"cached")
            os.utime(cache.dir, (1, 1))
            core.clean_old_temp()
            self.assertTrue((cache.dir / "result.pdf").exists())
            cache._owner.close()  # 강제 종료로 잠금만 풀린 상황
            core.clean_old_temp()
            self.assertFalse(cache.dir.exists())

    def test_cleanup_keeps_legacy_directory_without_owner_marker(self):
        old = Path(self.tmp.name) / (core.TEMP_PREFIX + "legacy")
        old.mkdir()
        os.utime(old, (1, 1))
        with patch.object(core.tempfile, "gettempdir", return_value=self.tmp.name):
            core.clean_old_temp()
        self.assertTrue(old.exists())


class ProcessTests(unittest.TestCase):
    def test_no_process_guess_when_window_lookup_fails(self):
        app = Mock()
        app.Hwnd = 0
        with patch.object(office, "_pids", return_value={101, 202}):
            self.assertEqual(office._own_pids("excel", app, "EXCEL.EXE", {101}), set())

    def test_preexisting_process_is_never_owned(self):
        app = Mock(Hwnd=123)
        with patch("win32process.GetWindowThreadProcessId", return_value=(1, 101)), \
                patch.object(office, "_pids", return_value={101}):
            self.assertEqual(office._own_pids("excel", app, "EXCEL.EXE", {101}), set())

    def test_stop_during_com_start_is_honoured(self):
        off = office.Office()
        app = Mock()
        def launch(_):
            off.stop()
            return app
        with patch("win32com.client.DispatchEx", side_effect=launch), \
                patch.object(office, "_pids", return_value=set()), \
                patch.object(office, "_own_pids", return_value={202}), \
                patch.object(office, "_kill") as kill:
            with self.assertRaises(office.Stopped):
                off._start("excel")
            kill.assert_called_once_with({202})

    def test_shared_hwp_and_powerpoint_are_not_opened(self):
        for kind in ("hwp", "ppt"):
            with self.subTest(kind=kind), patch.object(office, "_pids", return_value={101}), \
                    patch("win32com.client.Dispatch") as dispatch:
                with self.assertRaises(office.DocError):
                    office.Office()._start(kind)
                dispatch.assert_not_called()


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def test_legacy_office_with_embedded_zip_is_not_rewritten_as_zip(self):
        data = BytesIO(b"\xd0\xcf\x11\xe0" + bytes(508))
        with ZipFile(data, "a") as archive:
            archive.writestr("theme/theme1.xml", "sample")
        path = self.base / "sample.doc"
        original = data.getvalue()
        path.write_bytes(original)
        self.assertTrue(is_zipfile(path))
        clean_sample(path)
        self.assertEqual(path.read_bytes(), original)

    def test_sample_author_removed_without_changing_document(self):
        path = self.base / "sample.docx"
        with ZipFile(path, "w") as archive:
            archive.writestr("docProps/core.xml", "<properties><dc:creator>Sample Author</dc:creator></properties>")
            archive.writestr("word/document.xml", "fictional document")
        clean_sample(path)
        with ZipFile(path) as archive:
            self.assertNotIn(b"Sample Author", archive.read("docProps/core.xml"))
            self.assertEqual(archive.read("word/document.xml"), b"fictional document")

    def test_merge_rejects_input_file_as_output(self):
        path = self.base / "source.pdf"
        path.write_bytes(b"original")
        tab = SimpleNamespace(folder=Mock(), filename=Mock(), app=Mock())
        tab.folder.get.return_value = str(self.base)
        tab.filename.get.return_value = path.name
        with patch("pdftool.gui.merge_tab.messagebox.showwarning"):
            self.assertIsNone(MergeTab._ask_target(tab, [SimpleNamespace(path=path)]))
        tab.app.plan_targets.assert_not_called()
        self.assertEqual(path.read_bytes(), b"original")

    def test_merge_routes_existing_output_through_collision_confirmation(self):
        path = self.base / "result.pdf"
        path.write_bytes(b"previous result")
        tab = SimpleNamespace(folder=Mock(), filename=Mock(), app=Mock())
        tab.folder.get.return_value = str(self.base)
        tab.filename.get.return_value = path.name
        renamed = self.base / "result (2).pdf"
        tab.app.plan_targets.return_value = [renamed]
        self.assertEqual(MergeTab._ask_target(tab, []), renamed)
        tab.app.plan_targets.assert_called_once_with([path])
        self.assertEqual(path.read_bytes(), b"previous result")


if __name__ == "__main__":
    unittest.main(verbosity=2)
