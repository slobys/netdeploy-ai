"""Exercise native authenticated link lookup with real local HTTP, never a VPS."""
import json
import os
from pathlib import Path
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows .NET client")
ROOT = Path(__file__).resolve().parents[1]
TOKEN = "test-only-native-panel-token"
DESTINATION = "https://hiddify.example.invalid/admin/v2/quick-setup"


@pytest.fixture(scope="module")
def native_lookup(tmp_path_factory):
    work = tmp_path_factory.mktemp("native-browser")
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    if not compiler.exists():
        pytest.skip("Requires .NET Framework compiler")
    harness = work / "Probe.cs"
    harness.write_text("""
using System;
internal static class Launcher {
    internal static Uri Panel;
    internal static bool Local(Uri uri) {
        return uri.Scheme == Panel.Scheme && uri.Host == Panel.Host && uri.Port == Panel.Port;
    }
}
class Probe {
    static void Main(string[] args) {
        Launcher.Panel = new Uri(args[0]);
        try { Console.WriteLine("OK:" + HiddifyBrowser.ReadLink(new Uri(args[1]), args[2]).GetAwaiter().GetResult().AbsoluteUri); }
        catch (Exception) { Console.WriteLine("REJECTED"); }
    }
}
""", encoding="utf-8")
    executable = work / "Probe.exe"
    subprocess.run([str(compiler), "/nologo", "/reference:System.Net.Http.dll",
                    "/reference:System.Web.Extensions.dll", f"/out:{executable}", str(harness),
                    str(ROOT / "packaging/windows/HiddifyBrowser.cs")], check=True, capture_output=True)
    return executable


@pytest.mark.parametrize("status,url,job,token,accepted,expected_requests", [
    (200, DESTINATION, "a1b2c3d4e5f6a7b8", TOKEN, True, 1),
    (401, DESTINATION, "a1b2c3d4e5f6a7b8", TOKEN, False, 1),
    (302, DESTINATION, "a1b2c3d4e5f6a7b8", TOKEN, False, 1),
    (200, "http://hiddify.example.invalid/", "a1b2c3d4e5f6a7b8", TOKEN, False, 1),
    (200, "https://user:secret@hiddify.example.invalid/", "a1b2c3d4e5f6a7b8", TOKEN, False, 1),
    (200, DESTINATION, "invalid", TOKEN, False, 0),
    (200, DESTINATION, "a1b2c3d4e5f6a7b8", "", False, 0),
])
def test_native_lookup_preserves_auth_and_rejects_unsafe_links(
    native_lookup, status, url, job, token, accepted, expected_requests
):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers.get("X-Admin-Token")))
            self.send_response(status if len(requests) == 1 else 200)
            self.send_header("Content-Type", "application/json")
            # Following this response would transmit the token to an unintended route.
            self.send_header("Location", "/credential-trap")
            self.end_headers()
            self.wfile.write(json.dumps({"url": url, "tls_verified": True}).encode())

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    panel = f"http://127.0.0.1:{server.server_port}/"
    try:
        result = subprocess.run([str(native_lookup), panel,
                                 panel + "static/hiddify-launch.html#" + job, token],
                                check=True, capture_output=True, text=True, timeout=10)
        assert result.stdout.strip() == ("OK:" + DESTINATION if accepted else "REJECTED")
        assert len(requests) == expected_requests
        if requests:
            assert requests == [("/api/jobs/a1b2c3d4e5f6a7b8/hiddify-admin", TOKEN)]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
