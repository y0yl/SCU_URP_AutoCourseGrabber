#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
???????? URP ??????

???
- ? Python requests ???
- ?? ddddocr ??????
- ??????????? OCR??????????/??????
- ?? ScuUrpClient ????????????????? session?

????
  python .\scu_login.py
  python .\scu_login.py --max-login-attempts 10
  python .\scu_login.py --debug-captcha-dir .\captcha_debug

?????
  from scu_login import create_logged_in_client

  client = create_logged_in_client()
  resp = client.get("/index")
  session = client.session        # ?????????
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple
from urllib.parse import urljoin

import requests

try:
    from PIL import Image, ImageFilter, ImageOps
except Exception:  # pragma: no cover
    Image = None
    ImageFilter = None
    ImageOps = None

try:
    import ddddocr
except Exception:  # pragma: no cover
    ddddocr = None


BASE_ORIGIN = "http://zhjw.scu.edu.cn"
LOGIN_PATH = "/login"
SECURITY_CHECK_PATH = "/j_spring_security_check"
CAPTCHA_PATH = "/img/captcha.jpg"
URP_MD5_SALT = "{Urp602019}"

DEFAULT_USERNAME = os.getenv("SCU_USERNAME", "")
DEFAULT_PASSWORD = os.getenv("SCU_PASSWORD", "")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class LoginError(RuntimeError):
    """?????????????"""


@dataclass(slots=True)
class LoginResult:
    ok: bool
    url: str
    attempts: int
    last_captcha: str = ""
    message: str = ""


@dataclass(slots=True)
class CaptchaResult:
    code: Optional[str]
    details: list[Tuple[str, str]] = field(default_factory=list)


# -----------------------------
# URP password hashing
# -----------------------------

def _md5_hex(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def urp_hex_md5(text: str, ver: Optional[str] = None) -> str:
    # ?? md5.min.js ???ver == "1.8" ????????? {Urp602019}
    return _md5_hex(text if ver == "1.8" else text + URP_MD5_SALT)


def build_encrypted_password(plain_password: str) -> str:
    # ?? onclick ???
    # hex_md5(hex_md5(pwd), '1.8') + '*' + hex_md5(hex_md5(pwd, '1.8'), '1.8')
    left = urp_hex_md5(urp_hex_md5(plain_password), "1.8")
    right = urp_hex_md5(urp_hex_md5(plain_password, "1.8"), "1.8")
    return f"{left}*{right}"


def extract_input_value(html: str, input_id: str) -> str:
    match = re.search(rf'<input[^>]*\bid=["\']{re.escape(input_id)}["\'][^>]*>', html, re.I)
    if not match:
        return ""
    value = re.search(r'\bvalue=["\']([^"\']*)["\']', match.group(0), re.I)
    return value.group(1) if value else ""


# -----------------------------
# CAPTCHA OCR
# -----------------------------

def clean_captcha_text(text: Any) -> str:
    text = re.sub(r"[^0-9A-Za-z]", "", str(text).strip())
    if len(text) > 4:
        candidates = re.findall(r"[0-9A-Za-z]{4}", text)
        text = candidates[-1] if candidates else text[:4]
    return text.lower()


def is_valid_captcha(code: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-z]{4}", code or ""))


def image_to_png_bytes(img: "Image.Image") -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def red_mask_image(image_bytes: bytes, *, scale: int = 3, threshold: int = 95, bold: bool = True, crop: bool = False) -> bytes:
    """???????????????????????"""
    if Image is None:
        return image_bytes

    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    width, height = img.size
    out = Image.new("L", (width, height), 255)
    src = img.load()
    dst = out.load()
    xs: list[int] = []
    ys: list[int] = []

    for y in range(height):
        for x in range(width):
            r, g, b = src[x, y]
            # ?/????R ???? G/B?????????????
            if r >= threshold and r > g * 1.18 and r > b * 1.18:
                dst[x, y] = 0
                xs.append(x)
                ys.append(y)

    if bold and ImageFilter is not None:
        out = out.filter(ImageFilter.MinFilter(3))

    if crop and xs and ys:
        pad = 3
        out = out.crop((
            max(min(xs) - pad, 0),
            max(min(ys) - pad, 0),
            min(max(xs) + pad + 1, width),
            min(max(ys) + pad + 1, height),
        ))

    if scale > 1:
        out = out.resize((out.width * scale, out.height * scale), Image.Resampling.NEAREST)
    return image_to_png_bytes(out)


def gray_threshold_image(image_bytes: bytes, *, scale: int = 2, threshold: int = 175) -> bytes:
    """??????????????????"""
    if Image is None or ImageOps is None:
        return image_bytes
    img = Image.open(BytesIO(image_bytes)).convert("L")
    img = ImageOps.autocontrast(img)
    img = img.point(lambda p: 0 if p < threshold else 255)
    if ImageFilter is not None:
        img = img.filter(ImageFilter.MedianFilter(3))
    if scale > 1:
        img = img.resize((img.width * scale, img.height * scale), Image.Resampling.NEAREST)
    return image_to_png_bytes(img)


def slow_captcha_variants(image_bytes: bytes) -> Iterable[Tuple[str, bytes]]:
    # ?????????????????? ddddocr ?????
    yield "red_mask_x3", red_mask_image(image_bytes, scale=3, threshold=95, bold=True, crop=False)
    yield "red_mask_crop_x4", red_mask_image(image_bytes, scale=4, threshold=90, bold=True, crop=True)
    yield "red_mask_th110_x3", red_mask_image(image_bytes, scale=3, threshold=110, bold=False, crop=False)
    yield "gray_threshold_x2", gray_threshold_image(image_bytes, scale=2, threshold=175)


@dataclass
class DdddCaptchaSolver:
    """ddddocr ???????

    fast=True ??????? OCR?????? 4 ??????????
    ??????????? OCR ???????????????
    """

    debug_dir: str = ""
    fast: bool = True
    max_fallback_variants: int = 4
    _ocr: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if ddddocr is None:
            raise LoginError("ddddocr ????????pip install -r requirements.txt")
        self._ocr = ddddocr.DdddOcr(show_ad=False)
        if self.debug_dir:
            Path(self.debug_dir).mkdir(parents=True, exist_ok=True)

    def _classify(self, name: str, image_bytes: bytes, seq: int, idx: int) -> Tuple[str, str]:
        if self.debug_dir:
            suffix = "jpg" if name == "original" else "png"
            Path(self.debug_dir, f"captcha_{seq:03d}_{idx}_{name}.{suffix}").write_bytes(image_bytes)
        try:
            raw = self._ocr.classification(image_bytes)
        except Exception as exc:
            raw = f"ERR:{exc}"
        return name, clean_captcha_text(raw)

    def recognize(self, image_bytes: bytes, seq: int = 0) -> CaptchaResult:
        details: list[Tuple[str, str]] = []

        # ??????????????????????????????? 5 ?????
        name, code = self._classify("original", image_bytes, seq, 0)
        details.append((name, code))
        if self.fast and is_valid_captcha(code):
            return CaptchaResult(code=code, details=details)

        # ???????????????????? 4 ?????
        for idx, (variant_name, variant_bytes) in enumerate(slow_captcha_variants(image_bytes), start=1):
            if idx > self.max_fallback_variants:
                break
            name, code = self._classify(variant_name, variant_bytes, seq, idx)
            details.append((name, code))
            if is_valid_captcha(code):
                return CaptchaResult(code=code, details=details)

        return CaptchaResult(code=None, details=details)


# -----------------------------
# Reusable client interface
# -----------------------------

class ScuUrpClient:
    """????????????

    ???????????????
      client = create_logged_in_client()
      client.get('/index')
      client.post('/student/...', data={...})
      client.session  # ??????? requests.Session
    """

    def __init__(
        self,
        username: str = DEFAULT_USERNAME,
        password: str = DEFAULT_PASSWORD,
        *,
        solver: Optional[DdddCaptchaSolver] = None,
        base_origin: str = BASE_ORIGIN,
        timeout: int = 20,
        verbose: bool = True,
    ) -> None:
        self.username = username
        self.password = password
        self.base_origin = base_origin.rstrip("/")
        self.login_url = self.base_origin + LOGIN_PATH
        self.timeout = timeout
        self.verbose = verbose
        self.solver = solver or DdddCaptchaSolver()
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.captcha_seq = 0
        self.last_login_result: Optional[LoginResult] = None

    def url(self, path_or_url: str) -> str:
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            return path_or_url
        return urljoin(self.base_origin + "/", path_or_url.lstrip("/"))

    def request(self, method: str, path_or_url: str, *, ensure_login: bool = False, **kwargs: Any) -> requests.Response:
        if ensure_login:
            self.ensure_logged_in()
        kwargs.setdefault("timeout", self.timeout)
        return self.session.request(method, self.url(path_or_url), **kwargs)

    def get(self, path_or_url: str, *, ensure_login: bool = True, **kwargs: Any) -> requests.Response:
        return self.request("GET", path_or_url, ensure_login=ensure_login, **kwargs)

    def post(self, path_or_url: str, *, ensure_login: bool = True, **kwargs: Any) -> requests.Response:
        return self.request("POST", path_or_url, ensure_login=ensure_login, **kwargs)

    def fetch_login_page(self) -> Tuple[str, str]:
        resp = self.request("GET", self.login_url, ensure_login=False)
        resp.raise_for_status()
        return resp.text, extract_input_value(resp.text, "tokenValue")

    def fetch_captcha(self) -> bytes:
        # ?? query ???? refreshCaptcha()???? session ?????????
        captcha_url = self.url(CAPTCHA_PATH) + f"?{random.randint(0, 99999999)}"
        resp = self.request("GET", captcha_url, ensure_login=False, headers={"Referer": self.login_url})
        resp.raise_for_status()
        return resp.content

    def solve_captcha(self, max_refresh: int = 2) -> str:
        for _ in range(max_refresh):
            self.captcha_seq += 1
            result = self.solver.recognize(self.fetch_captcha(), seq=self.captcha_seq)
            self._log(f"[captcha] #{self.captcha_seq} {result.details} -> {result.code or 'invalid; refresh'}")
            if result.code:
                return result.code
        raise LoginError(f"?? OCR ?? {max_refresh} ???????? 4 ???")

    def submit_login(self, token_value: str, captcha: str) -> requests.Response:
        data: Dict[str, str] = {
            "lang": "zh",
            "tokenValue": token_value,
            "j_username": self.username,
            "j_password": build_encrypted_password(self.password),
            "j_captcha": captcha,
        }
        return self.request(
            "POST",
            SECURITY_CHECK_PATH,
            ensure_login=False,
            data=data,
            headers={
                "Referer": self.login_url,
                "Origin": self.base_origin,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            allow_redirects=True,
            timeout=25,
        )

    def login(self, max_attempts: int = 10) -> LoginResult:
        last_html = ""
        last_code = ""
        for attempt in range(1, max_attempts + 1):
            self._log(f"[login] attempt {attempt}")
            _html, token_value = self.fetch_login_page()
            if not token_value:
                self._log("[login] tokenValue not found; continue")

            last_code = self.solve_captcha(max_refresh=2)
            resp = self.submit_login(token_value, last_code)
            last_html = resp.text[:1200]

            if self.is_login_success(resp):
                result = LoginResult(True, resp.url, attempt, last_code, "login success")
                self.last_login_result = result
                self._log(f"[login] success, url={resp.url}")
                return result

            reason = self.extract_error_message(resp.text) or resp.url
            self._log(f"[login] failed: captcha={last_code}, reason={reason}")
            time.sleep(0.15)

        result = LoginResult(False, self.login_url, max_attempts, last_code, last_html)
        self.last_login_result = result
        raise LoginError("??????????????????\n" + last_html)

    def ensure_logged_in(self) -> None:
        if self.last_login_result and self.last_login_result.ok:
            return
        self.login()

    def save_cookies(self, path: str | os.PathLike[str]) -> None:
        cookies = requests.utils.dict_from_cookiejar(self.session.cookies)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        self._log(f"[cookies] saved to {Path(path).resolve()}")

    def load_cookies(self, path: str | os.PathLike[str]) -> bool:
        p = Path(path)
        if not p.exists():
            return False
        with p.open("r", encoding="utf-8") as f:
            cookies = json.load(f)
        self.session.cookies.update(cookies)
        return True

    @staticmethod
    def is_login_success(resp: requests.Response) -> bool:
        final_url = resp.url.lower()
        body = resp.text
        if "errorcode" in final_url or "/login" in final_url:
            return False
        if "j_spring_security_check" in final_url:
            return False
        if 'id="input_username"' in body or 'name="j_username"' in body:
            return False
        return True

    @staticmethod
    def extract_error_message(html: str) -> str:
        text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
        text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        for key in ["???", "??", "??", "??", "??", "???", "invalid", "badCaptcha"]:
            idx = text.find(key)
            if idx >= 0:
                return text[max(0, idx - 80): idx + 180]
        return ""

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message)


# Backward-compatible alias for old imports.
ScuUrpLogin = ScuUrpClient


def create_logged_in_client(
    username: str = DEFAULT_USERNAME,
    password: str = DEFAULT_PASSWORD,
    *,
    max_attempts: int = 10,
    debug_captcha_dir: str = "",
    verbose: bool = True,
) -> ScuUrpClient:
    """???????????????????? ScuUrpClient?"""
    solver = DdddCaptchaSolver(debug_dir=debug_captcha_dir)
    client = ScuUrpClient(username=username, password=password, solver=solver, verbose=verbose)
    client.login(max_attempts=max_attempts)
    return client


# -----------------------------
# CLI
# -----------------------------

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SCU URP login client using local ddddocr")
    parser.add_argument("--username", default=os.getenv("SCU_USERNAME", DEFAULT_USERNAME))
    parser.add_argument("--password", default=os.getenv("SCU_PASSWORD", DEFAULT_PASSWORD))
    parser.add_argument("--max-login-attempts", type=int, default=10)
    parser.add_argument("--debug-captcha-dir", default="", help="save captcha variants for debugging")
    parser.add_argument("--save-cookies", default="scu_urp_cookies.json", help="empty string disables saving")
    parser.add_argument("--quiet", action="store_true", help="suppress progress logs")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    client = create_logged_in_client(
        username=args.username,
        password=args.password,
        max_attempts=args.max_login_attempts,
        debug_captcha_dir=args.debug_captcha_dir,
        verbose=not args.quiet,
    )
    if args.save_cookies:
        client.save_cookies(args.save_cookies)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
