"""本地 API 的保存冲突、视频 seek 与访问边界。"""
import json
from http.server import ThreadingHTTPServer
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from annotation_workbench.server import handler
import test_store


class ServerTests(unittest.TestCase):
    def setUp(self):
        fixture = test_store.StoreTests('test_sampling_before_filter_and_fingerprint')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.store = fixture.store
        base = handler(self.store)
        class QuietHandler(base):
            def log_message(self, *_): pass
        self.server = ThreadingHTTPServer(('127.0.0.1',0),QuietHandler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def request(self, path, data=None, headers=None):
        extra = {'Content-Type':'application/json'} if data is not None else {}
        extra.update(headers or {})
        return urlopen(Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,headers=extra),timeout=5)

    def test_save_export_conflict_and_missing_image(self):
        with self.request('/api/tasks/pilot') as response: data=json.load(response)
        original = json.loads(json.dumps(data['annotation']))
        with self.request('/api/tasks/pilot/save',original) as response:
            self.assertEqual(json.load(response)['revision'],1)
        with self.assertRaises(HTTPError) as error: self.request('/api/tasks/pilot/save',original)
        self.assertEqual(error.exception.code,409)
        with self.request('/api/tasks/pilot/export') as response:
            self.assertEqual(json.load(response)['annotation']['revision'],1)
        self.store.paths('pilot')[2].joinpath('F00000000.jpg').unlink()
        with self.assertRaises(HTTPError) as error:self.request('/api/tasks/pilot/image/F00000000')
        self.assertEqual(error.exception.code,404)

    def test_video_byte_ranges(self):
        path=self.store.resolve('data/test.avi');video=path.read_bytes()
        with self.request('/api/tasks/pilot/video',headers={'Range':'bytes=10-31'}) as response:
            self.assertEqual(response.status,206)
            self.assertEqual(response.read(),video[10:32])
            self.assertEqual(response.headers['Content-Range'],f'bytes 10-31/{len(video)}')
        with self.request('/api/tasks/pilot/video',headers={'Range':'bytes=-8'}) as response:
            self.assertEqual(response.read(),video[-8:])
        with self.assertRaises(HTTPError) as error:self.request('/api/tasks/pilot/video',headers={'Range':'bytes=9999999999-'})
        self.assertEqual(error.exception.code,416)

    def test_cross_site_write_and_arbitrary_file_rejected(self):
        data=self.store.load('pilot')['annotation']
        for headers in ({'Origin':'https://example.com'},{'Host':'evil.example'}):
            with self.assertRaises(HTTPError) as error:self.request('/api/tasks/pilot/save',data,headers)
            self.assertEqual(error.exception.code,403)
        with self.assertRaises(HTTPError) as error:self.request('/pixi.toml')
        self.assertEqual(error.exception.code,404)


if __name__ == '__main__': unittest.main()
