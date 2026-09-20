"""Read-only routes, stale data, safe errors and cached status without Windows dependencies."""

from http.client import HTTPConnection
import json
import os
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

import home_status


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'issues.jsonl').write_text('{}\n{}\n', encoding='utf-8')
        os.utime(root / 'issues.jsonl', (0, 0))
        (root / '.home-status-notes.json').write_text('["서비스 재등록 완료"]', encoding='utf-8')
        server = home_status.make_server(0, root, 'status.example:8443')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def request(path, method='GET', host='status.example:8443'):
            connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            connection.request(method, path, headers={'Host': host})
            response = connection.getresponse()
            code, body = response.status, response.read()
            assert response.getheader('Access-Control-Allow-Origin') is None
            connection.close()
            return code, body

        try:
            with patch.object(home_status, 'windows_status', return_value={'available': True}) as collect:
                assert request('/status')[0] == 200
                code, body = request('/status.json')
                assert code == 200
                data = json.loads(body)
                assert data['collections']['local']['issues']['rows'] == 2
                assert data['collections']['local']['issues']['stale']
                assert data['collections']['community']['issues']['missing']
                assert data['notes'] == ['서비스 재등록 완료']
                assert directory not in body.decode()
                assert request('/status.json')[0] == 200
                collect.assert_called_once()
                for path in ('/api/run', '/api/state', '/.env', '/..%2f.env'):
                    assert request(path)[0] == 404
                assert request('/status.json', host='attacker.example')[0] == 403
                assert request('/api/run', method='POST')[0] == 501
            with patch.object(home_status, 'windows_status', return_value={'available': False}):
                server.snapshot.expires = 0
                assert not json.loads(request('/status.json')[1])['system']['available']
            with patch.object(home_status.os, 'name', 'nt'), patch.object(
                    home_status.subprocess, 'run', side_effect=OSError('private path')):
                failure = home_status.windows_status()
                assert failure['available'] is False and 'private path' not in json.dumps(failure)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
    print('PASS: read-only status, host boundary, stale data, safe failures, cache')


if __name__ == '__main__':
    main()
