"""使用临时合成视频验证标注身份、存储和预测导入边界。"""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from annotation_workbench.store import Store, Conflict, atomic, read, validate


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'data').mkdir()
        self.video = self.root / 'data/test.avi'
        writer = cv2.VideoWriter(str(self.video), cv2.VideoWriter_fourcc(*'MJPG'), 10, (160, 100))
        for i in range(40):
            image = np.full((100, 160, 3), 220, np.uint8)
            cv2.putText(image, str(i), (20, 55), cv2.FONT_HERSHEY_SIMPLEX, .8, (0, 0, 0), 2)
            writer.write(image)
        writer.release()
        self.store = Store(self.root)
        self.spec = dict(id='pilot', video='data/test.avi', segments=[dict(start=0, end=2, interval=.5)],
                         extras=[dict(time=.7, scene_id='S01')])
        self.data = self.store.create(self.spec)

    def test_sampling_before_filter_and_fingerprint(self):
        d = self.data['dataset']
        self.assertEqual([f['number'] for f in d['frames']], [0, 5, 7, 10, 15])
        self.assertEqual(d['frames'][2]['origin'], 'supplement')
        self.assertEqual(len(d['video']['sha256']), 64)
        self.assertEqual(d['sampling'], 'fixed_before_quality_filter')
        with self.assertRaises(ValueError):
            self.store.create(self.spec)

    def add_observation(self, ann):
        ann['tracks']['S01-L001'] = {'scene_id': 'S01', 'versions': {'V001': 'a complete line'}}
        obs = {'id':'O1', 'track_id':'S01-L001', 'version_id':'V001', 'visible_text':'a line',
               'regions': [[[1, 1], [40, 1], [40, 20], [1, 20]], [[60, 1], [100, 1], [100, 20], [60, 20]]],
               'visibility':'partial', 'change':'unchanged', 'confirmed':True}
        ann['frames']['F00000000']['observations'].append(obs)
        return obs

    def test_multiregion_identity_version_and_roundtrip(self):
        ann = copy.deepcopy(self.data['annotation'])
        self.add_observation(ann)
        frame = ann['frames']['F00000000']
        frame['status'], frame['reviewed'] = 'done', True
        result = self.store.save('pilot', ann)
        self.assertEqual(result['revision'], 1)
        loaded = self.store.load('pilot')['annotation']
        self.assertEqual(loaded, ann)
        backup = self.store.paths('pilot')[1].with_suffix('.previous.json')
        self.assertEqual(read(backup)['revision'], 0)
        obs = copy.deepcopy(frame['observations'][0]);obs['id'] = 'O2';obs['visible_text'] = ''
        obs['regions'] = [];obs['visibility'] = 'hidden'
        ann['frames']['F00000005']['observations'] = [obs]
        self.store.save('pilot', ann)
        self.assertEqual(len(self.store.load('pilot')['annotation']['tracks']), 1)

    def test_stale_save_rejected_without_overwrite(self):
        old = copy.deepcopy(self.data['annotation'])
        self.store.save('pilot', self.data['annotation'])
        with self.assertRaises(Conflict):
            self.store.save('pilot', old)
        self.assertEqual(self.store.load('pilot')['annotation']['revision'], 1)

    def test_validation_hidden_geometry_duplicates_reference(self):
        for change in ('hidden', 'outside', 'duplicate', 'reference', 'fingerprint'):
            ann = copy.deepcopy(self.data['annotation'])
            obs = self.add_observation(ann)
            first = ann['frames']['F00000000']
            first['status'], first['reviewed'] = 'done', True
            if change == 'hidden': obs['visibility'] = 'hidden'
            if change == 'outside': obs['regions'][0][0][0] = -1
            if change == 'duplicate': first['observations'].append(copy.deepcopy(obs))
            if change == 'reference': first['reference_id'] = 'F00000005'
            if change == 'fingerprint': ann['video_sha256'] = 'bad'
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.store.save('pilot', ann)

    def test_done_requires_frame_review_and_pair_event(self):
        ann = copy.deepcopy(self.data['annotation'])
        f = ann['frames']['F00000005']; f['status'] = 'done'
        with self.assertRaises(ValueError): self.store.save('pilot', ann)
        f['reviewed'] = True
        with self.assertRaises(ValueError): self.store.save('pilot', ann)
        f['events'] = ['unchanged']
        self.store.save('pilot', ann)

    def test_regenerate_preserves_annotation_and_checks_video(self):
        ann = copy.deepcopy(self.data['annotation'])
        self.add_observation(ann);self.store.save('pilot', ann)
        image = self.store.paths('pilot')[2] / 'F00000000.jpg'
        image.unlink();self.store.regenerate('pilot')
        self.assertTrue(image.exists())
        self.assertEqual(self.store.load('pilot')['annotation'], ann)
        with self.video.open('ab') as f: f.write(b'changed')
        with self.assertRaises(ValueError): self.store.regenerate('pilot')

    def test_run_import_exact_frames_original_coordinates_and_no_human_overwrite(self):
        run = self.root / 'runs/demo';(run / '06_ocr').mkdir(parents=True)
        video = self.data['dataset']['video']
        atomic(run / 'manifest.json', {'video':dict(video, name='test.avi')})
        image = cv2.imread(str(self.store.paths('pilot')[2] / 'F00000005.jpg'))
        cv2.imwrite(str(run / 'source.png'), image)
        box = dict(frame=5, source_path='source.png', source_poly=[[10,10],[80,10],[80,25],[10,25]],
                   poly=[[0,0],[70,0],[70,15],[0,15]], text='line', score=.9)
        atomic(run / '06_ocr/boxes.json', [box])
        before = copy.deepcopy(self.data['annotation'])
        result = self.store.import_run('pilot', 'runs/demo')
        self.assertEqual(result['imported'], 1)
        self.assertEqual(result['data']['annotation'], before)
        self.assertEqual(result['data']['predictions']['F00000005'][0]['regions'][0], box['source_poly'])
        image[:] = 0;cv2.imwrite(str(run / 'source.png'), image)
        with self.assertRaises(ValueError): self.store.import_run('pilot', 'runs/demo')

    def test_path_escape_and_invalid_sampling(self):
        with self.assertRaises(ValueError): self.store.resolve('../elsewhere')
        for key in ('../escape','bad/name'):
            with self.assertRaises(ValueError): self.store.paths(key)
        for value in (0, -1, float('nan')):
            spec = copy.deepcopy(self.spec);spec['id']='bad';spec['segments'][0]['interval']=value
            with self.assertRaises(ValueError): self.store.create(spec)


if __name__ == '__main__':
    unittest.main()
