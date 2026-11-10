#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""HTTP contract tests for the public update-host verifier."""

import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

from scripts import bonsai_publish as publisher


class PublisherHttpTests(unittest.TestCase):
    def test_public_reads_identify_the_bonsai_publisher(self):
        payload = b"authenticated update bytes\n"
        requests = []

        class PublicHost(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(dict(self.headers))
                if self.headers.get("User-Agent") != "Zen-Bonsai-Update-Publisher/1.0":
                    self.send_response(403)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "update.mar"
            path.write_bytes(payload)
            with HTTPServer(("127.0.0.1", 0), PublicHost) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:

                    def local_open(request, timeout):
                        self.assertEqual(
                            request.full_url,
                            "https://updates.zen-bonsai.dev/update.mar",
                        )
                        # Exercise the real HTTP headers against a disposable host.
                        local = urllib.request.Request(
                            f"http://127.0.0.1:{server.server_port}/update.mar",
                            headers=dict(request.header_items()),
                        )
                        return urllib.request.urlopen(local, timeout=timeout)

                    publisher.check_public_file(
                        path, "update.mar", SimpleNamespace(open=local_open)
                    )
                finally:
                    server.shutdown()
                    thread.join(timeout=5)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["Cache-Control"], "no-cache")


if __name__ == "__main__":
    unittest.main()
