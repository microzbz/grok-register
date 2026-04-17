from __future__ import annotations

import json
import random
import re
import string
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ============================================================
# Cloudflare 临时邮箱 Worker 配置（从 config.json 加载）
# ============================================================

_config_path = Path(__file__).parent / "config.json"
_conf: Dict[str, Any] = {}
if _config_path.exists():
    with _config_path.open("r", encoding="utf-8") as _f:
        _conf = json.load(_f)

CLOUDFLARE_MAIL_API_BASE = str(
    _conf.get("cloudflare_mail_api_base")
    or _conf.get("cf_mail_api_base")
    or ""
).strip()
CLOUDFLARE_MAIL_ADMIN_PASSWORD = str(
    _conf.get("cloudflare_mail_admin_password")
    or _conf.get("cf_mail_admin_password")
    or ""
).strip()
CLOUDFLARE_MAIL_DOMAIN = str(
    _conf.get("cloudflare_mail_domain")
    or _conf.get("cf_mail_domain")
    or ""
).strip().lower()
PROXY = str(_conf.get("proxy", "") or "").strip()

_temp_email_cache: Dict[str, str] = {}


def get_email_and_token() -> Tuple[Optional[str], Optional[str]]:
    """
    创建 Cloudflare Worker 临时邮箱并返回 (email, mail_token)。
    供 DrissionPage_example.py 调用。
    """
    email, mail_token = create_temp_email()
    if email and mail_token:
        _temp_email_cache[email] = mail_token
        return email, mail_token
    return None, None


def get_oai_code(dev_token: str, email: str, timeout: int = 30) -> Optional[str]:
    """
    轮询 Cloudflare Worker 邮箱获取 OTP 验证码。
    供 DrissionPage_example.py 调用。
    """
    code = wait_for_verification_code(mail_token=dev_token, timeout=timeout, expected_email=email)
    if code:
        return code.replace("-", "")
    return code


def _create_http_session():
    """创建 HTTP 会话，优先使用 curl_cffi 伪装浏览器 TLS 指纹。"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    if curl_requests:
        session = curl_requests.Session()
        session.headers.update(headers)
        if PROXY:
            session.proxies = {"http": PROXY, "https": PROXY}
        return session, True

    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(headers)
    if PROXY:
        session.proxies = {"http": PROXY, "https": PROXY}
    return session, False


def _do_request(session, use_cffi: bool, method: str, url: str, **kwargs):
    if use_cffi:
        kwargs.setdefault("impersonate", "chrome131")
    return getattr(session, method)(url, **kwargs)


def _require_worker_config() -> Tuple[str, str, str]:
    api_base = CLOUDFLARE_MAIL_API_BASE.rstrip("/")
    admin_password = CLOUDFLARE_MAIL_ADMIN_PASSWORD
    domain = CLOUDFLARE_MAIL_DOMAIN

    missing = []
    if not api_base:
        missing.append("cloudflare_mail_api_base")
    if not admin_password:
        missing.append("cloudflare_mail_admin_password")
    if not domain:
        missing.append("cloudflare_mail_domain")

    if missing:
        raise ValueError(f"config.json 缺少 Cloudflare 邮箱配置: {', '.join(missing)}")

    return api_base, admin_password, domain


def _generate_local_part(length: int = 12) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


def create_temp_email() -> Tuple[str, str]:
    """创建 Cloudflare Worker 临时邮箱，返回 (email, mail_token)。"""
    api_base, admin_password, domain = _require_worker_config()
    session, use_cffi = _create_http_session()
    last_error: Exception = Exception("未知错误")

    for _ in range(5):
        mailbox_name = _generate_local_part()
        try:
            response = _do_request(
                session,
                use_cffi,
                "post",
                f"{api_base}/admin/new_address",
                json={"domain": domain, "name": mailbox_name},
                headers={"x-admin-auth": admin_password},
                timeout=15,
            )
            if response.status_code == 200:
                data = response.json()
                address = str(data.get("address") or "").strip().lower()
                jwt = str(data.get("jwt") or "").strip()
                if address and jwt:
                    print(f"[*] Cloudflare 临时邮箱创建成功: {address}")
                    return address, jwt
                raise Exception(f"创建邮箱响应缺少 address/jwt: {data}")

            if response.status_code == 400 and "Invalid mailbox name" in response.text:
                continue
            if response.status_code == 400 and "Domain mismatch" in response.text:
                raise Exception(f"邮箱域名不匹配，请检查 cloudflare_mail_domain={domain}")
            if response.status_code == 401:
                raise Exception("Cloudflare 邮箱 Worker 鉴权失败，请检查 cloudflare_mail_admin_password")

            raise Exception(f"创建邮箱失败: {response.status_code} - {response.text[:300]}")
        except Exception as exc:
            last_error = exc

    raise Exception(f"Cloudflare 邮箱创建失败: {last_error}")


def fetch_emails(mail_token: str, limit: int = 20) -> List[Dict[str, Any]]:
    """拉取 Cloudflare Worker 邮件列表。"""
    try:
        api_base, _, _ = _require_worker_config()
        session, use_cffi = _create_http_session()
        response = _do_request(
            session,
            use_cffi,
            "get",
            f"{api_base}/api/mails",
            params={"limit": limit, "offset": 0},
            headers={"Authorization": f"Bearer {mail_token}"},
            timeout=15,
        )
        if response.status_code == 200:
            data = response.json()
            results = data.get("results")
            if isinstance(results, list):
                return [item for item in results if isinstance(item, dict)]
        elif response.status_code in (401, 404, 410):
            return []
    except Exception:
        pass
    return []


def wait_for_verification_code(
    mail_token: str,
    timeout: int = 120,
    expected_email: Optional[str] = None,
) -> Optional[str]:
    """轮询 Worker 邮箱等待验证码邮件。"""
    start = time.time()
    seen_ids = set()
    normalized_expected_email = str(expected_email or "").strip().lower()

    while time.time() - start < timeout:
        messages = fetch_emails(mail_token)
        for msg in messages:
            message_id = str(msg.get("id") or "").strip()
            if not message_id or message_id in seen_ids:
                continue
            seen_ids.add(message_id)

            source = str(msg.get("source") or "").strip().lower()
            subject = str(msg.get("subject") or "")
            raw = str(msg.get("raw") or "")
            content = "\n".join([subject, raw]).strip()

            if normalized_expected_email and normalized_expected_email in source:
                continue

            code = extract_verification_code(content)
            if code:
                print(f"[*] 从 Cloudflare 邮箱提取到验证码: {code}")
                return code

        time.sleep(3)
    return None


def extract_verification_code(content: str) -> Optional[str]:
    """
    从邮件内容提取验证码。
    Grok/x.ai 常见格式：XXX-XXX 或 6 位数字。
    """
    if not content:
        return None

    match = re.search(r"(?<![A-Z0-9-])([A-Z0-9]{3}-[A-Z0-9]{3})(?![A-Z0-9-])", content)
    if match:
        return match.group(1)

    match = re.search(
        r"(?:verification code|验证码|your code)[:\s]*[<>\s]*([A-Z0-9]{3}-[A-Z0-9]{3})\b",
        content,
        re.IGNORECASE,
    )
    if match:
        return match.group(1)

    match = re.search(r"background-color:\s*#F3F3F3[^>]*>[\s\S]*?([A-Z0-9]{3}-[A-Z0-9]{3})[\s\S]*?</p>", content)
    if match:
        return match.group(1)

    match = re.search(r"Subject:.*?(\d{6})", content)
    if match and match.group(1) != "177010":
        return match.group(1)

    for code in re.findall(r">\s*(\d{6})\s*<", content):
        if code != "177010":
            return code

    for code in re.findall(r"(?<![&#\d])(\d{6})(?![&#\d])", content):
        if code != "177010":
            return code

    return None
