"""StarMoe Passport (Logto) 登录 + starmoe-api 存档接口，与 StarMoe Box 一致。"""
import base64, gzip, hashlib, json, os, secrets, time, urllib.parse, urllib.request, urllib.error
from .errors import StarMoeError, ERR_AUTH, ERR_AUTH_EXPIRED, ERR_NETWORK
from .tls import urlopen

ENDPOINT = os.environ.get("STARMOE_PASSPORT", "https://passport.star.moe")
RESOURCE = os.environ.get("STARMOE_API_RESOURCE", "https://passport.bdon.moe")
API_BASE = os.environ.get("STARMOE_API_BASE", "https://passport.bdon.moe")
# 默认借用 StarMoe Box（Android）的公开 Native App ID；建议站长另建一个桌面版 App 后用 STARMOE_APP_ID 覆盖
APP_ID = os.environ.get("STARMOE_APP_ID", "8qgrfp21mgcbkq5nvceaz")
SCHEME = "moe.starmoe.box"
REDIRECT = os.environ.get("STARMOE_REDIRECT", SCHEME + "://moe.starmoe.box/callback")
SCOPES = "openid offline_access profile saves:read saves:write"
DECK_URL = "https://bdon.moe/tools/deck"
UA = "StarMoeBox-iOS-Desktop/0.1 (Python)"


class ApiError(StarMoeError):
    def __init__(self, status, body):
        code = ERR_AUTH_EXPIRED if status == 401 else ERR_NETWORK
        super().__init__(code, f"HTTP {status}: {body[:300]}")
        self.status = status


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def auth_request():
    """生成 PKCE 授权请求。返回 {url, verifier, state}；verifier/state 只留在内存里。"""
    verifier = _b64(secrets.token_bytes(32))
    state = _b64(secrets.token_bytes(12))
    q = {"client_id": APP_ID, "redirect_uri": REDIRECT, "response_type": "code", "scope": SCOPES,
         "resource": RESOURCE, "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()),
         "code_challenge_method": "S256", "state": state, "prompt": "consent"}
    return {"url": ENDPOINT + "/oidc/auth?" + urllib.parse.urlencode(q), "verifier": verifier, "state": state}


def is_callback(url):
    return isinstance(url, str) and url.strip().lower().startswith(SCHEME + ":")


def exchange(callback_url, req):
    """用回调 URL 中的 code 换取令牌。req 为 auth_request() 的返回值。"""
    p = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(callback_url.strip()).query))
    if p.get("error"):
        raise StarMoeError(ERR_AUTH, f"授权被拒绝或失败：{p.get('error')} {p.get('error_description', '')}")
    if p.get("state") != req["state"] or "code" not in p:
        raise StarMoeError(ERR_AUTH, "回调地址无效或 state 不匹配（可能是旧的登录链接），请重新登录。")
    tok = _post_form(ENDPOINT + "/oidc/token", {
        "grant_type": "authorization_code", "client_id": APP_ID, "redirect_uri": REDIRECT,
        "code": p["code"], "code_verifier": req["verifier"], "resource": RESOURCE})
    return _stamp(tok)


def login_interactive():
    req = auth_request()
    print("1) 在浏览器打开下面的链接并登录 StarMoe 通行证：\n")
    print(req["url"])
    print("\n2) 登录后浏览器会尝试打开 moe.starmoe.box://… 并失败。"
          "请从地址栏或开发者工具(Network)复制这个完整 URL 粘贴到这里：")
    return exchange(input("> "), req)


def refresh(refresh_token):
    try:
        tok = _post_form(ENDPOINT + "/oidc/token", {"grant_type": "refresh_token", "client_id": APP_ID,
                                                     "refresh_token": refresh_token, "resource": RESOURCE})
    except ApiError as e:
        if e.status in (400, 401):
            raise StarMoeError(ERR_AUTH_EXPIRED, "登录已过期或已被撤销，请重新登录。") from e
        raise
    return _stamp(tok)


def _stamp(tok):
    tok["obtained_at"] = int(time.time())
    if tok.get("expires_in"):
        tok["expires_at"] = tok["obtained_at"] + int(tok["expires_in"])
    return tok


def id_claims(tok):
    """仅用于显示用户名：解出 id_token 的 payload（不做签名校验，不用于鉴权）。"""
    t = (tok or {}).get("id_token")
    if not t or t.count(".") != 2:
        return {}
    try:
        seg = t.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))
    except ValueError:
        return {}


def display_name(claims):
    return claims.get("username") or claims.get("name") or claims.get("email") or \
        (("用户 " + claims["sub"][:8]) if claims.get("sub") else "StarMoe 用户")


def _open(req, timeout):
    try:
        with urlopen(req, timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read()[:300].decode("utf8", "replace"))
    except (urllib.error.URLError, OSError) as e:
        raise StarMoeError(ERR_NETWORK, f"网络错误：{getattr(e, 'reason', e)}")


def _post_form(url, data):
    req = urllib.request.Request(url, urllib.parse.urlencode(data).encode(),
                                 {"Content-Type": "application/x-www-form-urlencoded", "User-Agent": UA})
    return json.loads(_open(req, 30))


def _call(method, path, token, body=None, headers=None):
    h = {"Authorization": "Bearer " + token, "Accept": "application/json", "User-Agent": UA, **(headers or {})}
    req = urllib.request.Request(API_BASE.rstrip("/") + path, body, h, method=method)
    t = _open(req, 120)
    return json.loads(t) if t else None


def upload(token, server, player_bytes):
    """PUT /api/me/saves/{intl|jp}，正文为 _player 原文的 gzip(9)。"""
    body = gzip.compress(player_bytes, 9)
    return _call("PUT", f"/api/me/saves/{server}", token, body,
                 {"Content-Type": "application/json", "Content-Encoding": "gzip"})


def list_saves(token):
    return _call("GET", "/api/me/saves", token)
