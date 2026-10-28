"""HTTPS CA bundle: frozen PyInstaller builds have no system CA directory.

Runs offline.  python tests/test_tls.py
"""
import os, ssl, sys, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import certifi
from starmoe_ios import api, keyfetch, tls

ok = 0
ca = tls.ca_bundle()
assert ca == certifi.where() or os.path.basename(ca) == "cacert.pem"
assert os.path.isfile(ca) and os.path.getsize(ca) > 10000
ref = ssl.create_default_context(cafile=certifi.where())
pinned = tls.ssl_context(prefer_os_store=False)
assert pinned.get_ca_certs() == ref.get_ca_certs()
assert tls.certifi_context().get_ca_certs() == ref.get_ca_certs()
assert os.environ.get("SSL_CERT_FILE")
assert os.environ.get("REQUESTS_CA_BUNDLE")
ok += 1

# truststore 不可用时必须回到 certifi，而不是空的默认上下文
real = tls._truststore_context
tls._truststore_context = lambda: None
try:
    fallen = tls.ssl_context()
    assert fallen.get_ca_certs() == ref.get_ca_certs()
    assert tls.ssl_backend() == "certifi"
finally:
    tls._truststore_context = real
ok += 1

ctx = tls.ssl_context()
try:
    import truststore
except ImportError:
    truststore = None
if truststore is not None and tls._truststore_context() is not None:
    assert isinstance(ctx, truststore.SSLContext)
    assert tls.ssl_backend() == "truststore"
else:
    assert ctx.get_ca_certs() == ref.get_ca_certs()
    assert tls.ssl_backend() == "certifi"
ok += 1

handlers = [h for h in keyfetch._opener.handlers if isinstance(h, urllib.request.HTTPSHandler)]
assert len(handlers) == 1 and handlers[0]._context is not None
opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=tls.ssl_context(prefer_os_store=False)),
                                      keyfetch._SafeRedirect)
h = [x for x in opener.handlers if isinstance(x, urllib.request.HTTPSHandler)]
assert len(h) == 1 and h[0]._context.get_ca_certs() == ref.get_ca_certs()
ok += 1

seen = {}
class _Body:
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def read(self):
        return b"{}"

orig_urlopen = urllib.request.urlopen
def fake_urlopen(req, timeout=None, context=None, **kw):
    seen["context"] = context
    seen["timeout"] = timeout
    seen["url"] = req.full_url
    return _Body()

urllib.request.urlopen = fake_urlopen
try:
    assert api._open(urllib.request.Request("https://passport.star.moe/oidc/token"), 12) == b"{}"
finally:
    urllib.request.urlopen = orig_urlopen
assert seen["timeout"] == 12 and seen["url"].startswith("https://")
got = seen["context"]
assert got is not None
if truststore is not None and isinstance(got, truststore.SSLContext):
    pass
else:
    assert got.get_ca_certs() == ref.get_ca_certs()
ok += 1

print(f"TLS OK ({ok} cases) backend={tls.ssl_backend()} ca={ca}")
