"""真实 Chromium 操作测试；浏览器和 Node 缺失时跳过，不安装依赖。"""
from http.server import ThreadingHTTPServer
from pathlib import Path
import shutil
import subprocess
import threading
import unittest

from annotation_workbench.server import handler
from annotation_workbench.store import atomic
import test_store


class BrowserTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node') and Path('/usr/bin/google-chrome').exists(), '需要现有 Node 与 Chrome')
    def test_annotation_browser(self):
        fixture = test_store.StoreTests('test_sampling_before_filter_and_fingerprint')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        store = fixture.store
        atomic(store.paths('pilot')[2] / 'predictions.json', {'F00000000':[
            {'id':'p1','text':'first line','regions':[[[10,10],[120,10],[120,30],[10,30]]],
             'score':.9,'source':'synthetic','frame':0}]})
        server = ThreadingHTTPServer(('127.0.0.1',0),handler(store))
        thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        script = Path(__file__).with_name('browser_smoke.mjs')
        result = subprocess.run(['node',str(script),'--url',f'http://127.0.0.1:{server.server_port}',
                                 '--task','pilot'],capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
        print(result.stdout.strip())


if __name__ == '__main__':
    unittest.main()
