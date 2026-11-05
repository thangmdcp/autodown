import json
import os
import subprocess
import unittest
from unittest.mock import patch, MagicMock
import render_api
import hashlib


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'API_KEY': 'test-secret', 'CLOUDINARY_CLOUD_NAME':'demo', 'CLOUDINARY_API_KEY':'123456', 'CLOUDINARY_API_SECRET':'old-secret', 'CLOUDINARY_ACCOUNTS_JSON':json.dumps({'new':{'api_key':'234567','api_secret':'new-secret'}})})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.resource = patch.object(render_api, 'resources', return_value=None)
        self.resource.start()
        self.addCleanup(self.resource.stop)
        self.client = render_api.app.test_client()
        self.headers = {'X-API-Key': 'test-secret'}
        self.body = {'url': 'https://www.facebook.com/reel/123456789', 'requestId': 'post12345678'}

    def test_health_is_small_public_and_never_starts_download(self):
        with patch.object(render_api.subprocess, 'Popen') as process:
            self.assertEqual(self.client.get('/healthz').get_json(), {'ok': True})
            process.assert_not_called()

    def test_no_key_or_config_disclosure(self):
        for path in ['/api/info', '/api/cloudinary_config', '/api/regenerate_key', '/']:
            response = self.client.get(path)
            self.assertNotIn(b'test-secret', response.data)
            self.assertNotEqual(response.status_code, 200)

    def test_auth_and_validation(self):
        self.assertEqual(self.client.post('/api/download', json=self.body).status_code, 401)
        for url in ['http://facebook.com/reel/1', 'https://facebook.com.evil.test/reel/1', 'https://127.0.0.1/x', 'https://user@facebook.com/reel/1', 'https://youtube.com/watch?v=1']:
            self.assertEqual(self.client.post('/api/download', headers=self.headers, json={**self.body,'url':url}).status_code, 400)

    def test_busy_does_not_wait_or_start_process(self):
        render_api._slot.acquire()
        render_api._slot.acquire()
        try:
            with patch.object(render_api.subprocess, 'Popen') as process:
                response = self.client.post('/api/download', headers=self.headers, json=self.body)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.get_json()['code'], 'MEDIA_BUSY')
                process.assert_not_called()
        finally:
            render_api._slot.release()
            render_api._slot.release()

    def test_capacity_is_authenticated_and_reports_two_slots(self):
        self.assertEqual(self.client.get('/api/health').status_code, 401)
        health = self.client.get('/api/health', headers=self.headers).get_json()
        self.assertEqual(health['maxConcurrentDownloads'], 2)
        self.assertEqual(health['availableSlots'], 2)

    def test_low_resources_wait_without_starting_child(self):
        with patch.object(render_api, 'resources', return_value='RAM thấp'), patch.object(render_api.subprocess, 'Popen') as process:
            response = self.client.post('/api/download', headers=self.headers, json=self.body)
            self.assertEqual(response.get_json()['code'], 'MEDIA_BUSY')
            process.assert_not_called()
            self.assertEqual(render_api._active, 0)

    def test_two_concurrent_children_and_third_waits(self):
        import threading
        entered = threading.Barrier(3)
        release = threading.Event()
        def communicate(*args, **kwargs):
            entered.wait(timeout=5)
            release.wait(timeout=5)
            return json.dumps({'success': True}), ''
        child = MagicMock()
        child.communicate.side_effect = communicate
        results = []
        def run():
            with render_api.app.test_client() as client:
                results.append(client.post('/api/download', headers=self.headers, json=self.body).status_code)
        with patch.object(render_api.subprocess, 'Popen', return_value=child):
            threads = [threading.Thread(target=run) for _ in range(2)]
            for thread in threads: thread.start()
            entered.wait(timeout=5)
            self.assertEqual(render_api._active, 2)
            self.assertEqual(self.client.post('/api/download', headers=self.headers, json=self.body).status_code, 503)
            release.set()
            for thread in threads: thread.join(timeout=5)
        self.assertEqual(results, [200, 200])
        self.assertEqual(render_api._active, 0)

    def test_child_payload_and_cleanup(self):
        child = MagicMock()
        child.communicate.return_value = (json.dumps({'success':True,'media':[]}), '')
        with patch.object(render_api.subprocess, 'Popen', return_value=child) as process, patch.object(render_api.shutil, 'rmtree') as clean:
            response = self.client.post('/api/download', headers=self.headers, json=self.body)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(json.loads(child.communicate.call_args.args[0]), {**self.body,'storageCloud':'demo'})
            self.assertTrue(process.call_args.kwargs['start_new_session'])
            clean.assert_called_once()
        self.assertTrue(render_api._slot.acquire(blocking=False))
        render_api._slot.release()

    def test_timeout_kills_process_group_and_releases_slot(self):
        child = MagicMock(pid=12345)
        child.communicate.side_effect = [subprocess.TimeoutExpired('download',270), ('','')]
        with patch.object(render_api.subprocess,'Popen',return_value=child), patch.object(render_api.os,'killpg') as kill:
            response=self.client.post('/api/download',headers=self.headers,json=self.body)
            self.assertEqual(response.status_code,504)
            kill.assert_called_once_with(12345,render_api.signal.SIGKILL)
        self.assertTrue(render_api._slot.acquire(blocking=False))
        render_api._slot.release()

    def test_existing_cloudinary_asset_reuses_video_and_only_probes_caption(self):
        import core
        import cloudinary.api
        import cloudinary.uploader
        source_hash=hashlib.sha256(self.body['url'].encode()).hexdigest()
        asset={'secure_url':'https://res.cloudinary.com/demo/video/upload/test.mp4','public_id':'postflow-fetch/video-post12345678','context':{'custom':{'source_sha256':source_hash}}}
        with patch.dict(os.environ,{'CLOUDINARY_CLOUD_NAME':'demo','CLOUDINARY_API_KEY':'x','CLOUDINARY_API_SECRET':'y'}), patch.object(cloudinary.api,'resource',return_value=asset), patch.object(core,'probe_one',return_value={'caption':'original caption'}) as probe, patch.object(cloudinary.uploader,'upload') as upload:
            payload=render_api.run_child(self.body,'/tmp/not-used')
            self.assertEqual(payload['caption'],'original caption')
            self.assertEqual(payload['media'][0]['public_id'],asset['public_id'])
            probe.assert_called_once()
            upload.assert_not_called()

    def test_conflicting_source_is_not_overwritten(self):
        import cloudinary.api
        with patch.dict(os.environ,{'CLOUDINARY_CLOUD_NAME':'demo','CLOUDINARY_API_KEY':'x','CLOUDINARY_API_SECRET':'y'}), patch.object(cloudinary.api,'resource',return_value={'context':{'custom':{'source_sha256':'another-source'}}}):
            self.assertEqual(render_api.run_child(self.body,'/tmp/not-used')['code'],'ASSET_CONFLICT')

    def test_new_account_is_pinned_in_child_payload_without_credentials(self):
        child = MagicMock()
        child.communicate.return_value = (json.dumps({'success':True}), '')
        with patch.object(render_api.subprocess, 'Popen', return_value=child):
            response = self.client.post('/api/download', headers=self.headers, json={**self.body, 'storageCloud':'new'})
            self.assertEqual(response.status_code, 200)
            payload=json.loads(child.communicate.call_args.args[0])
            self.assertEqual(payload, {**self.body,'storageCloud':'new'})
            self.assertNotIn('new-secret', json.dumps(payload))

    def test_unknown_cloud_never_starts_work_or_falls_back(self):
        with patch.object(render_api.subprocess, 'Popen') as process:
            response=self.client.post('/api/download',headers=self.headers,json={**self.body,'storageCloud':'unknown'})
            self.assertEqual(response.status_code,503)
            self.assertEqual(response.get_json()['code'],'STORAGE_NOT_CONFIGURED')
            process.assert_not_called()

    def test_storage_verification_is_authenticated_and_does_not_disclose_secrets(self):
        import cloudinary.api
        self.assertEqual(self.client.post('/api/storage-check',json={'storageCloud':'new'}).status_code,401)
        with patch.object(cloudinary.api,'ping',return_value={'status':'ok'}) as ping:
            response=self.client.post('/api/storage-check',headers=self.headers,json={'storageCloud':'new'})
            self.assertEqual(response.get_json(),{'storageRoutingVersion':1,'cloud':'new','verified':True})
            self.assertEqual(ping.call_args.kwargs['cloud_name'],'new')
            self.assertEqual(ping.call_args.kwargs['api_secret'],'new-secret')
            self.assertNotIn('new-secret',response.get_data(as_text=True))

    def test_old_and_new_credentials_do_not_replace_each_other(self):
        self.assertEqual(render_api.cloud_credentials()['cloud_name'],'demo')
        self.assertEqual(render_api.cloud_credentials('new')['api_secret'],'new-secret')
        self.assertEqual(render_api.cloud_credentials('demo')['api_secret'],'old-secret')
