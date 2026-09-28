import io
import json
import threading
import unittest
from urllib.request import urlopen
from unittest.mock import patch
from deploy.kiosk_boot import Handler
from http.server import ThreadingHTTPServer


class KioskBootTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def test_wait_page_exists_before_backend_and_retries(self):
        with urlopen(self.url) as response:
            html = response.read().decode()
        self.assertIn('正在连接后台', html)
        self.assertIn('setInterval', html)
        with patch('deploy.kiosk_boot.urlopen', side_effect=OSError('not started')):
            with urlopen(self.url+'/ready') as response:
                self.assertFalse(json.load(response)['ready'])

    def test_ready_backend_is_reported(self):
        with patch('deploy.kiosk_boot.urlopen', return_value=io.BytesIO(b'{"ready": true}')):
            with urlopen(self.url+'/ready') as response:
                self.assertTrue(json.load(response)['ready'])
