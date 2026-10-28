"""HTTPS for urllib.

A PyInstaller build does not ship the system CA directory, so the default
SSL context fails with CERTIFICATE_VERIFY_FAILED. Prefer the OS trust store
via truststore when that package is installed; otherwise load Mozilla's CA
bundle from certifi (which the spec file packs next to the certifi package).
"""
import os, ssl, sys, urllib.request

def ca_bundle():
    """Path to certifi's cacert.pem. Raises OSError if the file was not packaged."""
    import certifi
    path = certifi.where()
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return path
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        alt = os.path.join(meipass, "certifi", "cacert.pem")
        if os.path.isfile(alt) and os.path.getsize(alt) > 0:
            return alt
    raise OSError(f"CA bundle missing (looked at {path}). PyInstaller must collect certifi's cacert.pem.")


def _pin_certifi_env():
    """Point libraries that honor these variables at the bundled bundle. Do not override a user setting."""
    try:
        ca = ca_bundle()
    except OSError:
        return
    os.environ.setdefault("SSL_CERT_FILE", ca)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", ca)


def certifi_context():
    return ssl.create_default_context(cafile=ca_bundle())


def _truststore_context():
    try:
        import truststore
    except ImportError:
        return None
    proto = getattr(ssl, "PROTOCOL_TLS_CLIENT", ssl.PROTOCOL_TLS)
    try:
        return truststore.SSLContext(proto)
    except Exception:
        return None


def ssl_context(prefer_os_store=True):
    """SSL context for urllib. OS store first, then certifi.where()."""
    if prefer_os_store:
        ctx = _truststore_context()
        if ctx is not None:
            return ctx
    return certifi_context()


def ssl_backend(prefer_os_store=True):
    if prefer_os_store and _truststore_context() is not None:
        return "truststore"
    return "certifi"


def urlopen(req, timeout=None):
    return urllib.request.urlopen(req, timeout=timeout, context=ssl_context())


def build_opener(*handlers):
    https = urllib.request.HTTPSHandler(context=ssl_context())
    return urllib.request.build_opener(https, *handlers)


_pin_certifi_env()
