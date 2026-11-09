"""真实 HTTP 上传/状态/产物/失败/重启测试；模型由可控 worker 替代。"""
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np
from fastapi.testclient import TestClient

from server.app import create_app
from server.jobs import Jobs


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        path = self.root / 'test.avi'
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 5, (160, 100))
        for _ in range(10):
            writer.write(np.full((100,160,3),200,np.uint8))
        writer.release()
        self.video = path.read_bytes()

    def worker(self, job):
        directory = self.root / 'runs' / job['id']
        directory.mkdir(parents=True)
        (directory / 'notes.txt').write_text('real artifact')
        (directory / 'secret.txt').write_text('private')
        (directory / 'manifest.json').write_text(json.dumps({'status':'done','items':[], 'stages':{},'outputs':{'notes_txt':'notes.txt'},'files':[{'path':'notes.txt'}]}))

    def upload(self, client, **config):
        return client.post('/api/jobs', files={'video':('test.avi',self.video,'video/x-msvideo')},data={'config':json.dumps(config)})

    def test_lifecycle_range_and_whitelist(self):
        with TestClient(create_app(self.root,self.worker)) as client:
            self.assertEqual(client.get('/').status_code,200)
            response = self.upload(client,roi=[0,0,160,100])
            self.assertEqual(response.status_code,201,response.text)
            identifier = response.json()['job_id']
            client.app.state.jobs.queue.join()
            self.assertEqual(client.get('/api/jobs/'+identifier).json()['status'],'done')
            response = client.get(f'/api/jobs/{identifier}/video',headers={'Range':'bytes=0-9'})
            self.assertEqual(response.status_code,206)
            self.assertEqual(len(response.content),10)
            base=f'/api/runs/{identifier}/files/'
            self.assertEqual(client.get(base+'notes.txt?download=true').text,'real artifact')
            self.assertEqual(client.get(base+'secret.txt').status_code,404)
            self.assertEqual(client.get(base+'%2e%2e%2fmanifest.json').status_code,404)
            self.assertEqual(client.post('/api/jobs',headers={'Origin':'https://evil.example'}).status_code,403)
        with TestClient(create_app(self.root,self.worker)) as client:
            self.assertEqual(client.get('/api/jobs/'+identifier).json()['status'],'done')
            self.assertEqual(len(client.get('/api/jobs').json()),1)

    def test_invalid_video_config_and_bounds(self):
        with TestClient(create_app(self.root,self.worker)) as client:
            for config in ({'roi':[0,0,161,100]},{'start_s':20},{'max_frames':301},{'roi':[0,0,2]},{'sample_interval_s':0}):
                self.assertEqual(self.upload(client,**config).status_code,422)
            self.assertEqual(client.post('/api/jobs', files={'video':('bad.mp4',b'invalid')}).status_code,422)
            self.assertEqual(client.get('/api/jobs/no-such-id').status_code,404)
            self.assertEqual(client.get('/api/jobs',headers={'Host':'evil.example'}).status_code,400)
            self.assertEqual(list((self.root/'data/jobs').glob('tmp*')),[])

    def test_worker_failure_and_restart_recovery(self):
        def fail(job):
            raise RuntimeError('deliberate failure')
        with TestClient(create_app(self.root,fail)) as client:
            identifier=self.upload(client).json()['job_id']
            client.app.state.jobs.queue.join()
            detail=client.get('/api/jobs/'+identifier).json()
            self.assertEqual(detail['status'],'failed')
            self.assertIn('deliberate failure',detail['error'])
            client.app.state.jobs.update(identifier,'running')
        jobs=Jobs(self.root,fail)
        self.addCleanup(jobs.close)
        self.assertEqual(jobs.get(identifier)['status'],'failed')
        self.assertIn('上次退出',jobs.get(identifier)['error'])


if __name__=='__main__':
    unittest.main()
