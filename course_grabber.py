#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""四川大学SCU_URP自动化抢课。

This script reuses ``scu_login.py`` for login, queries course lists, polls for
available seats, and submits the same two-step flow as the browser:

1. POST /student/courseSelect/selectCourse/checkInputCodeAndSubmit
2. POST /student/courseSelect/selectCourses/waitingfor

After a real submit it can verify the result by checking the quit-course page
and the failed-course page. A course is treated as truly successful only when it
appears on the quit-course page.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import requests

from scu_login import ScuUrpClient, create_logged_in_client


INDEX_PATH = "/student/courseSelect/courseSelect/index#iframe-xk"
SUBMIT_PATH = "/student/courseSelect/selectCourse/checkInputCodeAndSubmit"
WAITINGFOR_PATH = "/student/courseSelect/selectCourses/waitingfor"
QUIT_PATH = "/student/courseSelect/quitCourse/index"
FAILED_PATH = "/student/courseSelect/courseSelectFailed/index"

TRANSIENT_STATUS = {502, 503, 504}

CATEGORY_INFO: dict[str, dict[str, str]] = {
    "intent": {"path_part": "intentCourse", "dealType": "1", "label": "意向/预选课程"},
    "plan": {"path_part": "planCourse", "dealType": "2", "label": "计划课程"},
    "school": {"path_part": "schoolCourse", "dealType": "3", "label": "校任选课程"},
    "depart": {"path_part": "departCourse", "dealType": "4", "label": "院系课程"},
    "free": {"path_part": "freeCourse", "dealType": "5", "label": "自由课程"},
}


@dataclass
class CourseTarget:
    category: str
    course_id: str
    kcm: str = ""
    kch: str = ""
    kxh: str = ""
    zxjxjhh: str = ""
    teacher: str = ""
    rest: Optional[int] = None
    raw: dict[str, Any] | None = None

    @property
    def display_name(self) -> str:
        bits = [self.kcm or "未知课程", self.course_id]
        if self.teacher:
            bits.append(self.teacher)
        if self.rest is not None:
            bits.append(f"余量={self.rest}")
        return " | ".join(bits)


@dataclass
class ConfirmResult:
    status: str  # selected / failed / unknown / skipped
    selected: bool = False
    failed: bool = False
    message: str = ""


def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def html_unescape_min(text: str) -> str:
    return (
        str(text)
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )


def html_to_text(html: str) -> str:
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html_unescape_min(text)).strip()


def extract_input_value(html: str, input_id_or_name: str) -> str:
    patterns = [
        rf"<input[^>]*(?:\bid|\bname)=['\"]{re.escape(input_id_or_name)}['\"][^>]*>",
        rf"<input[^>]*\bname=['\"]{re.escape(input_id_or_name)}['\"][^>]*>",
    ]
    for pat in patterns:
        m = re.search(pat, html, flags=re.I)
        if not m:
            continue
        v = re.search(r"\bvalue=['\"]([^'\"]*)['\"]", m.group(0), flags=re.I)
        if v:
            return html_unescape_min(v.group(1))
    return ""


def extract_hidden_inputs(html: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in re.finditer(r"<input[^>]+type=['\"]hidden['\"][^>]*>", html, flags=re.I):
        tag = m.group(0)
        name = re.search(r"\bname=['\"]([^'\"]+)['\"]", tag, flags=re.I)
        value = re.search(r"\bvalue=['\"]([^'\"]*)['\"]", tag, flags=re.I)
        if name:
            out[html_unescape_min(name.group(1))] = html_unescape_min(value.group(1) if value else "")
    return out


def extract_tab_paths(index_html: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for category, info in CATEGORY_INFO.items():
        part = info["path_part"]
        m = re.search(rf"kc\(this,\s*['\"]([^'\"]*/{part}/index\?[^'\"]+)['\"]\)", index_html)
        if m:
            found[category] = html_unescape_min(m.group(1))
    return found


def encode_kcms(text: str) -> str:
    # Browser JS uses charCodeAt(i) + "," for every character.
    return "".join(f"{ord(ch)}," for ch in str(text))


def as_int_or_none(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value)))
    except Exception:
        return None


def csv_values(value: str) -> list[str]:
    return [x.strip() for x in str(value or "").split(",") if x.strip()]


def single_or_empty(value: str) -> str:
    vals = csv_values(value)
    return vals[0] if len(vals) == 1 else ""


def split_course_id(course_id: str) -> tuple[str, str, str]:
    parts = course_id.split("_", 2)
    if len(parts) == 2:
        return parts[0], parts[1], ""
    if len(parts) != 3:
        raise SystemExit("--course-id 格式应为 kch_kxh 或 kch_kxh_zxjxjhh，例如 107121000_01")
    return parts[0], parts[1], parts[2]


def course_id_key(course_id: str) -> str:
    kch, kxh, _ = split_course_id(course_id)
    return f"{kch}_{kxh}"


def course_target_key(c: CourseTarget) -> str:
    return f"{c.kch}_{c.kxh}"


def course_id_is_full(course_id: str) -> bool:
    return len(course_id.split("_", 2)) == 3


def args_with_course_id_filters(args: argparse.Namespace) -> argparse.Namespace:
    """Use --course-id values like 888006010A07_01 as query filters too.

    URP submit still needs the full kcIds returned by courseList, but users only
    need to type kch_kxh. This helper derives kch/kxh for narrowing courseList.
    """
    ids = csv_values(getattr(args, "course_id", ""))
    if not ids:
        return args
    kchs = csv_values(getattr(args, "kch", ""))
    kxhs = csv_values(getattr(args, "kxh", ""))
    for cid in ids:
        try:
            kch, kxh, _ = split_course_id(cid)
        except SystemExit:
            continue
        if kch and kch not in kchs:
            kchs.append(kch)
        if kxh and kxh not in kxhs:
            kxhs.append(kxh)
    data = dict(vars(args))
    if not getattr(args, "kch", "") and kchs:
        data["kch"] = ",".join(kchs)
    if not getattr(args, "kxh", "") and kxhs:
        data["kxh"] = ",".join(kxhs)
    return argparse.Namespace(**data)


def iter_dict_courses(data: Any) -> Iterable[dict[str, Any]]:
    """Yield course dictionaries from common URP courseList response shapes."""
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                yield item
        return
    if not isinstance(data, dict):
        return

    for key, value in data.items():
        if key in {"kchlist", "kylMap"}:
            continue
        if key == "yxkclist" and isinstance(value, str):
            continue
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    yield item
        elif isinstance(value, dict):
            for sub in value.values():
                if isinstance(sub, list):
                    for item in sub:
                        if isinstance(item, dict):
                            yield item


def normalize_course(category: str, item: dict[str, Any]) -> Optional[CourseTarget]:
    if category == "plan":
        kch = str(item.get("courseNum") or item.get("kch") or "")
        kxh = str(item.get("classNum") or item.get("kxh") or "")
        zxjxjhh = str(item.get("termCode") or item.get("zxjxjhh") or "")
    else:
        kch = str(item.get("kch") or item.get("courseNum") or "")
        kxh = str(item.get("kxh") or item.get("classNum") or "")
        zxjxjhh = str(item.get("zxjxjhh") or item.get("termCode") or "")

    if not (kch and kxh and zxjxjhh):
        return None

    return CourseTarget(
        category=category,
        course_id=f"{kch}_{kxh}_{zxjxjhh}",
        kcm=str(item.get("kcm") or item.get("courseName") or ""),
        kch=kch,
        kxh=kxh,
        zxjxjhh=zxjxjhh,
        teacher=str(item.get("skjs") or item.get("teacherName") or ""),
        rest=as_int_or_none(item.get("bkskyl")),
        raw=item,
    )


class CourseGrabber:
    def __init__(self, client: ScuUrpClient, *, verbose: bool = True, retries: int = 4) -> None:
        self.client = client
        self.verbose = verbose
        self.retries = retries
        self.index_html = ""
        self.token = ""
        self.tab_paths: dict[str, str] = {}
        self.page_html_cache: dict[str, str] = {}
        self.form_cache: dict[str, dict[str, str]] = {}

    def log(self, msg: str) -> None:
        if self.verbose:
            print(f"[{now()}] {msg}", flush=True)

    def request(self, method: str, path_or_url: str, **kwargs: Any) -> requests.Response:
        """Request with retry for transient 502/503/504/network failures."""
        last_exc: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = self.client.request(method, path_or_url, **kwargs)
                if resp.status_code in TRANSIENT_STATUS:
                    raise requests.HTTPError(f"{resp.status_code} transient", response=resp)
                return resp
            except (requests.RequestException, requests.HTTPError) as exc:
                last_exc = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status not in TRANSIENT_STATUS and attempt >= 2:
                    raise
                sleep_s = min(2.0 * attempt, 8.0) + random.uniform(0, 0.8)
                self.log(f"请求失败/重试 status={status} attempt={attempt}/{self.retries}，{sleep_s:.1f}s 后重试")
                time.sleep(sleep_s)
        assert last_exc is not None
        raise last_exc

    def load_index(self) -> None:
        resp = self.request("GET", INDEX_PATH)
        resp.raise_for_status()
        self.index_html = resp.text
        self.token = extract_input_value(resp.text, "tokenValue")
        self.tab_paths = extract_tab_paths(resp.text)
        if not self.token:
            raise RuntimeError("未找到选课页面 tokenValue")
        self.log(f"已读取选课 token={self.token[:8]}..., tabs={','.join(self.tab_paths) or 'none'}")

    def category_path(self, category: str) -> str:
        if not self.index_html:
            self.load_index()
        if category in self.tab_paths:
            return self.tab_paths[category]
        fajhh = self.extract_fajhh()
        part = CATEGORY_INFO[category]["path_part"]
        extra = "&fj=0" if category == "free" else ""
        return f"/student/courseSelect/{part}/index?fajhh={fajhh}{extra}"

    def extract_fajhh(self) -> str:
        for html in [self.index_html, *self.page_html_cache.values()]:
            m = re.search(r"fajhh=([0-9A-Za-z_-]+)", html)
            if m:
                return m.group(1)
            v = extract_input_value(html, "fajhh")
            if v:
                return v
        raise RuntimeError("未找到 fajhh，请先打开选课页面或手动指定 --fajhh")

    def load_category_page(self, category: str) -> str:
        if category in self.page_html_cache:
            return self.page_html_cache[category]
        path = self.category_path(category)
        resp = self.request("GET", path, headers={"Referer": self.client.url(INDEX_PATH)})
        resp.raise_for_status()
        self.page_html_cache[category] = resp.text
        self.form_cache[category] = extract_hidden_inputs(resp.text)
        self.log(f"已加载 {CATEGORY_INFO[category]['label']} 页面")
        return resp.text

    def query_payload(self, category: str, args: argparse.Namespace) -> dict[str, str]:
        self.load_category_page(category)
        hidden = self.form_cache.get(category, {})
        fajhh = args.fajhh or hidden.get("fajhh") or self.extract_fajhh()
        xq, jc = "0", "0"

        if category == "intent":
            return {"fajhh": fajhh, "mxbj": "0"}
        if category == "plan":
            return {
                "fajhh": fajhh,
                "jhxn": args.jhxn or "",
                "kcsxdm": args.kcsxdm or "",
                "kch": single_or_empty(args.kch),
                "kcm": args.name or "",
                "kxh": single_or_empty(args.kxh),
                "kclbdm": args.kclbdm or "",
                "kclbdm2": args.kclbdm2 or "",
                "kzh": args.kzh or "",
                "xqh": args.xqh or "",
                "xq": xq,
                "jc": jc,
            }
        if category == "free":
            return {
                "kkxsh": args.kkxsh or "",
                "kch": single_or_empty(args.kch),
                "kcm": args.name or "",
                "skjs": args.teacher or "",
                "xq": xq,
                "jc": jc,
                "kclbdm": args.kclbdm or "",
                "kclbdm2": args.kclbdm2 or "",
                "vt": args.vt or "",
                "fj": args.fj,
            }
        if category == "school":
            return {
                "fajhh": fajhh,
                "searchtj": args.search or args.name or single_or_empty(args.kch),
                "xq": xq,
                "jc": jc,
                "kclbdm": args.kclbdm or "",
                "kclbdm2": args.kclbdm2 or "",
                "kzmc": args.kzmc or "",
            }
        if category == "depart":
            return {
                "searchtj": args.search or args.name or single_or_empty(args.kch),
                "xq": xq,
                "jc": jc,
                "kclbdm": args.kclbdm or "",
                "kclbdm2": args.kclbdm2 or "",
            }
        raise ValueError(category)

    def query_courses(self, category: str, args: argparse.Namespace) -> list[CourseTarget]:
        part = CATEGORY_INFO[category]["path_part"]
        endpoint = f"/student/courseSelect/{part}/courseList"
        referer = self.client.url(self.category_path(category))

        effective_args = args_with_course_id_filters(args)
        query_args = [effective_args]
        kxhs = csv_values(effective_args.kxh)
        # Some URP endpoints miss classes when kxh is not a single value.
        if len(kxhs) > 1:
            query_args = [argparse.Namespace(**{**vars(effective_args), "kxh": kxh}) for kxh in kxhs]

        raw_payloads: list[Any] = []
        courses: list[CourseTarget] = []
        seen: set[str] = set()
        for qargs in query_args:
            resp = self.request(
                "POST",
                endpoint,
                data=self.query_payload(category, qargs),
                headers={"Referer": referer, "X-Requested-With": "XMLHttpRequest"},
            )
            resp.raise_for_status()
            data = resp.json()
            raw_payloads.append(data)
            for item in iter_dict_courses(data):
                c = normalize_course(category, item)
                if c and c.course_id not in seen and self.match_course(c, args):
                    seen.add(c.course_id)
                    courses.append(c)

        if getattr(args, "dump_json", ""):
            dump_obj = raw_payloads[0] if len(raw_payloads) == 1 else raw_payloads
            Path(args.dump_json).write_text(json.dumps(dump_obj, ensure_ascii=False, indent=2), encoding="utf-8")
            self.log(f"已写入 courseList JSON: {Path(args.dump_json).resolve()}")
        return courses

    @staticmethod
    def match_course(c: CourseTarget, args: argparse.Namespace) -> bool:
        course_ids = csv_values(args.course_id)
        effective_args = args_with_course_id_filters(args)
        kchs = csv_values(effective_args.kch)
        kxhs = csv_values(effective_args.kxh)
        if course_ids:
            wanted_full = set(course_ids)
            wanted_short = {course_id_key(x) for x in course_ids}
            if c.course_id not in wanted_full and course_target_key(c) not in wanted_short:
                return False
        if kchs and c.kch not in kchs:
            return False
        if kxhs and c.kxh not in kxhs:
            return False
        if args.name and args.name not in c.kcm:
            return False
        if args.teacher and args.teacher not in c.teacher:
            return False
        return True

    def build_submit_payload(self, category: str, target: CourseTarget, args: argparse.Namespace) -> dict[str, str]:
        self.load_category_page(category)
        form = dict(self.form_cache.get(category) or {})
        form["dealType"] = form.get("dealType") or CATEGORY_INFO[category]["dealType"]
        form["kcIds"] = target.course_id

        class_no = target.kxh
        kcms_text = args.submit_name or (f"{target.kcm}_{class_no}" if target.kcm else f"{target.kch}_{class_no}")
        form["kcms"] = encode_kcms(kcms_text)
        form.setdefault("sj", "0_0")
        if category == "free":
            form.setdefault("fj", args.fj)
        if args.fajhh:
            form["fajhh"] = args.fajhh

        form["inputCode"] = args.input_code or ""
        form["tokenValue"] = self.token
        return form

    def submit(self, category: str, target: CourseTarget, args: argparse.Namespace) -> dict[str, Any]:
        payload = self.build_submit_payload(category, target, args)
        if args.dry_run:
            self.log("dry-run：不真实提交，仅打印 payload")
            safe = dict(payload)
            safe["tokenValue"] = safe.get("tokenValue", "")[:8] + "..."
            print(json.dumps(safe, ensure_ascii=False, indent=2))
            return {"result": "dry-run", "final_status": "dry-run", "token": self.token}

        resp = self.request(
            "POST",
            SUBMIT_PATH,
            data=payload,
            headers={
                "Referer": self.client.url(INDEX_PATH),
                "X-Requested-With": "XMLHttpRequest",
                "Origin": self.client.base_origin,
            },
        )
        resp.raise_for_status()
        try:
            data: dict[str, Any] = resp.json()
        except Exception:
            data = {"result": resp.text[:1000]}

        if data.get("token"):
            self.token = str(data["token"])

        # Browser behavior: after checkInputCodeAndSubmit returns ok, submit the
        # iframe form to WAITINGFOR_PATH. Without this step, it is not a real selection.
        if data.get("result") == "ok" and not getattr(args, "skip_waitingfor", False):
            waiting_payload = {k: v for k, v in payload.items() if k not in {"inputCode", "tokenValue"}}
            wait_resp = self.request(
                "POST",
                WAITINGFOR_PATH,
                data=waiting_payload,
                headers={"Referer": self.client.url(self.category_path(category)), "Origin": self.client.base_origin},
                allow_redirects=True,
                timeout=60,
            )
            data["waitingfor_status"] = wait_resp.status_code
            data["waitingfor_url"] = wait_resp.url
            data["waitingfor_text"] = html_to_text(wait_resp.text)[:1200]

        if getattr(args, "confirm", True) and data.get("result") == "ok" and not args.dry_run:
            confirm = self.confirm_submit(target, attempts=getattr(args, "confirm_attempts", 4))
            data["final_status"] = confirm.status
            data["confirmed_selected"] = confirm.selected
            data["confirmed_failed"] = confirm.failed
            data["confirm_message"] = confirm.message
        elif data.get("result") == "ok":
            data["final_status"] = "unchecked"
        else:
            data["final_status"] = "rejected"
        return data

    def confirm_submit(self, target: CourseTarget, *, attempts: int = 4) -> ConfirmResult:
        """Confirm final result: selected if course appears on quit page; failed if on failed page."""
        for i in range(1, max(1, attempts) + 1):
            if i > 1:
                time.sleep(min(2 * i, 8))
            try:
                quit_resp = self.request("GET", QUIT_PATH)
                quit_resp.raise_for_status()
                quit_text = html_to_text(quit_resp.text)
                if target.kch in quit_text and target.kxh in quit_text:
                    return ConfirmResult("selected", selected=True, message="已在已选课程中确认找到")

                failed_resp = self.request("GET", FAILED_PATH)
                failed_resp.raise_for_status()
                failed_text = html_to_text(failed_resp.text)
                idx = failed_text.find(target.kch)
                if idx >= 0:
                    snippet = failed_text[max(0, idx - 120): idx + 320]
                    if not target.kxh or target.kxh in snippet:
                        return ConfirmResult("failed", failed=True, message=snippet)
            except Exception as exc:
                self.log(f"确认选课状态失败 attempt={i}/{attempts}: {exc!r}")
        return ConfirmResult("unknown", message="暂时无法确认最终选课状态")

    def grab(self, category: str, args: argparse.Namespace) -> int:
        self.load_index()

        if args.course_id and len(csv_values(args.course_id)) == 1 and course_id_is_full(args.course_id):
            kch, kxh, zx = split_course_id(args.course_id)
            direct = CourseTarget(category, args.course_id, args.name or args.submit_name or "", kch, kxh, zx)
            if args.no_poll:
                self.log(f"直接提交：{direct.display_name}")
                result = self.submit(category, direct, args)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0 if result.get("final_status") in {"selected", "unchecked", "dry-run"} else 2

        attempt = 0
        while True:
            attempt += 1
            try:
                courses = self.query_courses(category, args)
            except Exception as exc:
                self.log(f"第 {attempt} 次查询失败：{exc!r}")
                courses = []
            available = [c for c in courses if c.rest is None or c.rest > 0]

            if courses:
                summary = "; ".join(c.display_name for c in courses[:5])
                self.log(f"第 {attempt} 次查询到 {len(courses)} 门课程，可提交 {len(available)} 门：{summary}")
            else:
                self.log(f"第 {attempt} 次未匹配到课程")

            for target in available:
                self.log(f"提交目标：{target.display_name}")
                result = self.submit(category, target, args)
                print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
                status = str(result.get("final_status", ""))
                if status == "dry-run":
                    return 0
                if status in {"selected", "unchecked"}:
                    self.log("抢课成功" if status == "selected" else "已提交，但暂时无法确认")
                    return 0
                self.log(f"提交失败/未选中 final_status={status}, result={str(result.get('result', ''))[:120]}")

            if args.once or (args.max_attempts and attempt >= args.max_attempts):
                return 2
            time.sleep(max(0.2, args.interval + random.uniform(0, args.jitter)))


def create_client_with_retry(args: argparse.Namespace) -> ScuUrpClient:
    kwargs: dict[str, Any] = {
        "max_attempts": args.max_login_attempts,
        "debug_captcha_dir": args.debug_captcha_dir,
        "verbose": not args.quiet_login,
    }
    if args.username:
        kwargs["username"] = args.username
    if args.password:
        kwargs["password"] = args.password

    last_exc: Exception | None = None
    for i in range(1, args.login_retries + 1):
        try:
            return create_logged_in_client(**kwargs)
        except Exception as exc:
            last_exc = exc
            sleep_s = min(4 * i, 20) + random.uniform(0, 1.5)
            print(f"[{now()}] 登录失败 attempt={i}/{args.login_retries}: {exc!r}，{sleep_s:.1f}s 后重试", flush=True)
            time.sleep(sleep_s)
    assert last_exc is not None
    raise last_exc


def print_courses(courses: list[CourseTarget], *, limit: int) -> None:
    for idx, c in enumerate(courses[:limit], 1):
        print(f"{idx:03d}. {c.display_name}")
    if len(courses) > limit:
        print(f"... 还有 {len(courses) - limit} 条，使用 --limit 调整")


def add_common_sub_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--category", choices=sorted(CATEGORY_INFO), default="plan")
    sp.add_argument("--fajhh", default="")
    sp.add_argument("--course-id", default="", help="课程 ID，可用 kch_kxh，多个用逗号分隔，也可使用完整 kch_kxh_zxjxjhh")
    sp.add_argument("--kch", default="", help="课程号，多个用逗号分隔")
    sp.add_argument("--kxh", default="", help="课序号，多个用逗号分隔")
    sp.add_argument("--name", default="", help="课程名称")
    sp.add_argument("--teacher", default="", help="教师姓名")
    sp.add_argument("--search", default="", help="按名称/教师模糊搜索")
    sp.add_argument("--kkxsh", default="", help="开课院系号")
    sp.add_argument("--kclbdm", default="")
    sp.add_argument("--kclbdm2", default="")
    sp.add_argument("--kzh", default="")
    sp.add_argument("--xqh", default="")
    sp.add_argument("--kzmc", default="")
    sp.add_argument("--jhxn", default="")
    sp.add_argument("--kcsxdm", default="")
    sp.add_argument("--vt", default="")
    sp.add_argument("--fj", default="0")
    sp.add_argument("--dump-json", default="")
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--submit-name", default="", help="提交时覆盖 kcms，通常为 课程名_教师名")
    sp.add_argument("--input-code", default="", help="选课提交验证码，通常无需填写")
    sp.add_argument("--skip-waitingfor", action="store_true", help="提交后跳过 waitingfor 确认步骤")
    sp.add_argument("--no-confirm", dest="confirm", action="store_false", help="不检查已选/失败页面确认结果")
    sp.set_defaults(confirm=True)
    sp.add_argument("--confirm-attempts", type=int, default=4, help="确认结果重试次数")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="四川大学SCU_URP自动化抢课")
    p.add_argument("--username", default=None, help="覆盖 scu_login.py/env 中的用户名")
    p.add_argument("--password", default=None, help="覆盖 scu_login.py/env 中的密码")
    p.add_argument("--max-login-attempts", type=int, default=10)
    p.add_argument("--login-retries", type=int, default=6, help="登录遇到 502/网络错误时的重试次数")
    p.add_argument("--quiet-login", action="store_true")
    p.add_argument("--debug-captcha-dir", default="")

    sub = p.add_subparsers(dest="command", required=True)
    for name in ["list", "grab", "submit"]:
        add_common_sub_args(sub.add_parser(name))

    sub.choices["grab"].add_argument("--interval", type=float, default=1.2)
    sub.choices["grab"].add_argument("--jitter", type=float, default=0.3)
    sub.choices["grab"].add_argument("--max-attempts", type=int, default=0, help="0 表示一直轮询")
    sub.choices["grab"].add_argument("--once", action="store_true")
    sub.choices["grab"].add_argument("--no-poll", action="store_true", help="不轮询，直接按 --course-id 提交")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    client = create_client_with_retry(args)
    grabber = CourseGrabber(client)

    if args.command == "list":
        grabber.load_index()
        print_courses(grabber.query_courses(args.category, args), limit=args.limit)
        return 0

    if args.command == "submit":
        grabber.load_index()
        if not args.course_id:
            raise SystemExit("submit 需要 --course-id")
        if len(csv_values(args.course_id)) != 1:
            raise SystemExit("submit 只支持单个 --course-id；多个目标请使用 grab")
        if course_id_is_full(args.course_id):
            kch, kxh, zx = split_course_id(args.course_id)
            target = CourseTarget(args.category, args.course_id, args.name or args.submit_name, kch, kxh, zx)
        else:
            matches = grabber.query_courses(args.category, args)
            if not matches:
                raise SystemExit(f"未找到 course-id 对应课程：{args.course_id}")
            target = matches[0]
        print(json.dumps(grabber.submit(args.category, target, args), ensure_ascii=False, indent=2))
        return 0

    if args.command == "grab":
        if not (args.course_id or args.kch or args.name):
            raise SystemExit("grab 至少需要 --course-id、--kch 或 --name 之一")
        return grabber.grab(args.category, args)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

