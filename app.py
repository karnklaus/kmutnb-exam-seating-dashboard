from __future__ import annotations

import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

ENG_URL = "https://www.eng.kmutnb.ac.th/eservice/exam/seating"
SCIBASE_URL = "http://www.scibase.kmutnb.ac.th/examroom/datatrain.html"
SCIBASE_API_URL = "http://www.scibase.kmutnb.ac.th/examroom/datatrain.php"
SOURCE_TIMEOUT_SEC = 20
CACHE_TTL_SEC = 600

_cache: dict[str, tuple[float, dict[str, Any]]] = {}


@dataclass
class SeatingRecord:
    source: str
    student_id: str = ""
    student_name: str = ""
    subject_code: str = ""
    subject_name: str = ""
    exam_date: str = ""
    exam_time: str = ""
    building: str = ""
    room: str = ""
    seat_no: str = ""
    raw_text: str = ""


def _normalize_student_id(student_id: str) -> str:
    return re.sub(r"\D", "", student_id.strip())


def _is_valid_student_id(student_id: str) -> bool:
    return bool(re.fullmatch(r"\d{13}", student_id))


def _cached_get(student_id: str) -> dict[str, Any] | None:
    item = _cache.get(student_id)
    if not item:
        return None
    created_at, payload = item
    if (time.time() - created_at) > CACHE_TTL_SEC:
        _cache.pop(student_id, None)
        return None
    return payload


def _cached_set(student_id: str, payload: dict[str, Any]) -> None:
    _cache[student_id] = (time.time(), payload)


def _extract_value(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip(" :\n\t")
    return ""


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _to_gregorian_date(thai_date: str) -> str:
    months = {
        "ม.ค.": 1,
        "ก.พ.": 2,
        "มี.ค.": 3,
        "เม.ย.": 4,
        "พ.ค.": 5,
        "มิ.ย.": 6,
        "ก.ค.": 7,
        "ส.ค.": 8,
        "ก.ย.": 9,
        "ต.ค.": 10,
        "พ.ย.": 11,
        "ธ.ค.": 12,
    }
    m = re.search(r"(\d{1,2})\s*([ก-๙\.]+)\s*(\d{4})", thai_date)
    if not m:
        return thai_date
    day = int(m.group(1))
    month_name = m.group(2)
    year = int(m.group(3))
    month = months.get(month_name)
    if not month:
        return thai_date
    year = year - 543 if year > 2400 else year
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return thai_date


def _ordinal_suffix(day: int) -> str:
    if 11 <= (day % 100) <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


def _format_english_full_date(date_value: str) -> str:
    # Accept either YYYY-MM-DD or Thai short-date and return:
    # Wednesday, 18th of March 2026
    date_obj: datetime | None = None

    iso_match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", date_value.strip())
    if iso_match:
        try:
            date_obj = datetime(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
        except ValueError:
            date_obj = None

    if date_obj is None:
        normalized = _to_gregorian_date(date_value)
        iso_match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", normalized.strip())
        if iso_match:
            try:
                date_obj = datetime(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
            except ValueError:
                date_obj = None

    if date_obj is None:
        return date_value

    day = date_obj.day
    return f"{date_obj.strftime('%A')}, {day}{_ordinal_suffix(day)} of {date_obj.strftime('%B %Y')}"


def _parse_candidate_text(source: str, text: str, student_id: str) -> SeatingRecord | None:
    clean = _clean_text(text)
    if student_id not in clean:
        return None

    record = SeatingRecord(source=source, student_id=student_id, raw_text=clean)
    record.student_name = _extract_value(clean, [
        r"(?:ชื่อ(?:-สกุล)?|Name)\s*[:\-]\s*([^\|,;]+)",
    ])
    record.subject_code = _extract_value(clean, [
        r"(?:รหัสวิชา|Subject\s*Code)\s*[:\-]\s*([A-Za-z0-9\-]+)",
    ])
    record.subject_name = _extract_value(clean, [
        r"(?:วิชา|Subject)\s*[:\-]\s*([^\|,;]+)",
    ])
    record.exam_date = _extract_value(clean, [
        r"(?:วันที่สอบ|Date)\s*[:\-]\s*([^\|,;]+)",
    ])
    record.exam_time = _extract_value(clean, [
        r"(?:เวลาสอบ|Time)\s*[:\-]\s*([^\|,;]+)",
    ])
    record.building = _extract_value(clean, [
        r"(?:อาคาร|Building)\s*[:\-]\s*([^\|,;]+)",
    ])
    record.room = _extract_value(clean, [
        r"(?:ห้องสอบ|ห้อง|Room)\s*[:\-]\s*([^\|,;]+)",
    ])
    record.seat_no = _extract_value(clean, [
        r"(?:เลขที่นั่ง|ที่นั่ง|Seat\s*No\.?)\s*[:\-]\s*([A-Za-z0-9\-]+)",
    ])
    return record


def _records_from_table_rows(source: str, soup: BeautifulSoup, student_id: str) -> list[SeatingRecord]:
    records: list[SeatingRecord] = []
    for row in soup.select("tr"):
        row_text = _clean_text(row.get_text(" ", strip=True))
        if not row_text or student_id not in row_text:
            continue

        cells = [_clean_text(c.get_text(" ", strip=True)) for c in row.select("th,td")]
        candidate = SeatingRecord(source=source, student_id=student_id, raw_text=row_text)

        # Attempt positional mapping when table is dense.
        if len(cells) >= 4:
            for cell in cells:
                if student_id in cell:
                    continue
                if not candidate.seat_no and re.fullmatch(r"[A-Za-z]?\d{1,4}", cell):
                    candidate.seat_no = cell
                elif not candidate.room and ("ห้อง" in cell or re.search(r"room", cell, re.I)):
                    candidate.room = cell
                elif not candidate.subject_code and re.fullmatch(r"[A-Za-z]{2,}\d{2,}", cell):
                    candidate.subject_code = cell

        parsed = _parse_candidate_text(source, row_text, student_id) or candidate
        records.append(parsed)

    return records


def _parse_eng_html(html: str, student_id: str) -> list[SeatingRecord]:
    soup = BeautifulSoup(html, "html.parser")
    text = _clean_text(soup.get_text(" ", strip=True))
    if student_id not in text:
        return []

    records: list[SeatingRecord] = []

    # Pattern from card-style output:
    # 010123118 Computer Networks S.1 Wednesday, 18th of March 2026 [13:00 - 16:00]
    # Room : 88-603-4 | Seat: J6 ...
    pattern = re.compile(
        r"(?:Exam\s+Schedule\s+)?(?P<code>\d{6,10})\s+"
        r"(?P<name>.+?)\s+"
        r"(?P<date>(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),.+?\d{4})\s*"
        r"\[(?P<time>\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2})\]\s*"
        r"Room\s*:\s*(?P<room>[A-Za-z0-9\-]+)\s*\|\s*Seat\s*:\s*(?P<seat>[A-Za-z0-9\-]+)",
        re.IGNORECASE,
    )
    for m in pattern.finditer(text):
        full_room = _clean_text(m.group("room"))
        building = ""
        room_only = full_room
        room_match = re.fullmatch(r"(\d{2})-(.+)", full_room)
        if room_match:
            building = room_match.group(1)
            room_only = room_match.group(2)

        records.append(
            SeatingRecord(
                source="ENG",
                student_id=student_id,
                subject_code=_clean_text(m.group("code")),
                subject_name=_clean_text(re.sub(r"^Exam\s+Schedule\s+", "", m.group("name"), flags=re.I)),
                exam_date=_clean_text(m.group("date")),
                exam_time=_clean_text(m.group("time")),
                building=building,
                room=room_only,
                seat_no=_clean_text(m.group("seat")),
                raw_text=_clean_text(m.group(0)),
            )
        )

    if records:
        return records

    # fallback: old generic parser
    fallback = _records_from_table_rows("ENG", soup, student_id)
    if fallback:
        return fallback
    parsed = _parse_candidate_text("ENG", text, student_id)
    return [parsed] if parsed else []


def _parse_scibase_html(html: str, student_id: str) -> list[SeatingRecord]:
    soup = BeautifulSoup(html, "html.parser")
    all_text = _clean_text(soup.get_text(" ", strip=True))

    student_name = _extract_value(
        all_text,
        [r"ของ\s*([ก-๙A-Za-z\.\s]+?)\s*รหัสนักศึกษา", r"(?:ชื่อ|Name)\s*[:\-]\s*([^\|,;]+)"],
    )

    records: list[SeatingRecord] = []
    rows = soup.select("tr")
    header_index: dict[str, int] = {}

    for row in rows:
        headers = [_clean_text(c.get_text(" ", strip=True)) for c in row.select("th")]
        if not headers:
            continue
        if any("รหัสวิชาที่สอบ" in h for h in headers):
            for idx, h in enumerate(headers):
                header_index[h] = idx
            break

    if not header_index:
        return records

    def _cell(cells: list[str], key: str, default: str = "") -> str:
        for h, idx in header_index.items():
            if key in h and idx < len(cells):
                return cells[idx]
        return default

    for row in rows:
        cells = [_clean_text(c.get_text(" ", strip=True)) for c in row.select("td")]
        if len(cells) < 4:
            continue

        date_value = _cell(cells, "วันที่สอบ", cells[0] if cells else "")
        if not re.search(r"\d{1,2}\s*[ก-๙\.]+\s*\d{4}", date_value):
            continue

        exam_date = _format_english_full_date(date_value)
        exam_time = _cell(cells, "เวลาสอบ", cells[1] if len(cells) > 1 else "")
        subject_code = _cell(cells, "รหัสวิชาที่สอบ", cells[2] if len(cells) > 2 else "")
        subject_name = _cell(cells, "วิชาที่สอบ", cells[3] if len(cells) > 3 else "")
        # Keep subject name column clean in case parser accidentally captures code.
        if subject_name == subject_code and len(cells) > 3:
            subject_name = cells[3]
        seat_row = _cell(cells, "แถวที่นั่ง", "")
        seat_col = _cell(cells, "ลำดับที่นั่ง", "")
        room = _cell(cells, "ห้องสอบ", "")
        building = _cell(cells, "อาคาร", "")

        seat_no = ""
        if seat_row or seat_col:
            seat_no = f"{seat_row}-{seat_col}".strip("-")

        records.append(
            SeatingRecord(
                source="SCIBASE",
                student_id=student_id,
                student_name=student_name,
                subject_code=subject_code,
                subject_name=subject_name,
                exam_date=exam_date,
                exam_time=exam_time,
                building=building,
                room=room,
                seat_no=seat_no,
                raw_text=" | ".join(cells),
            )
        )

    if records:
        return records

    # Positional fallback for old fixed SCIBASE table layout.
    for row in rows:
        cells = [_clean_text(c.get_text(" ", strip=True)) for c in row.select("td")]
        if len(cells) < 10:
            continue
        if not re.search(r"\d{1,2}\s*[ก-๙\.]+\s*\d{4}", cells[0]):
            continue
        records.append(
            SeatingRecord(
                source="SCIBASE",
                student_id=student_id,
                student_name=student_name,
                subject_code=cells[2],
                subject_name=cells[3],
                exam_date=_format_english_full_date(cells[0]),
                exam_time=cells[1],
                building=cells[9],
                room=cells[7],
                seat_no=f"{cells[5]}-{cells[6]}".strip("-"),
                raw_text=" | ".join(cells),
            )
        )
    return records


def _build_form_attempts(base_url: str, html: str, student_id: str) -> list[tuple[str, str, dict[str, str]]]:
    soup = BeautifulSoup(html, "html.parser")
    attempts: list[tuple[str, str, dict[str, str]]] = []

    for form in soup.select("form"):
        method = (form.get("method") or "get").strip().lower()
        action = (form.get("action") or "").strip()
        submit_url = urljoin(base_url, action) if action else base_url

        payload: dict[str, str] = {}
        text_like_fields: list[str] = []
        hidden_fields: list[tuple[str, str]] = []

        for inp in form.select("input"):
            name = (inp.get("name") or "").strip()
            if not name:
                continue
            inp_type = (inp.get("type") or "text").strip().lower()
            value = (inp.get("value") or "").strip()

            if inp_type in {"hidden"}:
                hidden_fields.append((name, value))
            elif inp_type in {"text", "search", "number"}:
                text_like_fields.append(name)
            elif inp_type in {"submit", "button"} and name:
                payload[name] = value

        for k, v in hidden_fields:
            payload[k] = v

        # Fill student id in likely field names first.
        preferred_names = [
            "student_id", "studentid", "studentcode", "student_code",
            "stdcode", "std_code", "txt_student_id", "txtStudentID", "id",
        ]
        picked = False
        for name in preferred_names:
            if name in text_like_fields:
                payload[name] = student_id
                picked = True
                break

        if not picked and text_like_fields:
            payload[text_like_fields[0]] = student_id

        if payload:
            attempts.append((method, submit_url, payload))

    return attempts


def _query_source(url: str, source_name: str, student_id: str) -> tuple[list[SeatingRecord], str | None]:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ExamSeatDashboard/1.0)",
    }

    payload_candidates = [
        {"student_id": student_id},
        {"studentid": student_id},
        {"studentCode": student_id},
        {"studentcode": student_id},
        {"student_code": student_id},
        {"studentno": student_id},
        {"student_no": student_id},
        {"stdid": student_id},
        {"txt_student_id": student_id},
        {"txtStudentID": student_id},
        {"txt_stdid": student_id},
        {"txtStdID": student_id},
        {"student": student_id},
        {"std_id": student_id},
        {"stdcode": student_id},
        {"std_code": student_id},
        {"code_student": student_id},
        {"r_student": student_id},
        {"id": student_id},
        {"q": student_id},
        {"keyword": student_id},
        {"search": student_id},
        {"code": student_id},
    ]

    attempts: list[tuple[str, str]] = []

    session = requests.Session()

    # SCIBASE uses AJAX GET datatrain.php?IDcard=<student_id>
    if source_name == "SCIBASE":
        try:
            resp = session.get(
                SCIBASE_API_URL,
                params={"IDcard": student_id},
                timeout=SOURCE_TIMEOUT_SEC,
                headers=headers,
            )
            resp.encoding = resp.apparent_encoding or resp.encoding or "utf-8"
            records = _parse_scibase_html(resp.text, student_id)
            if records:
                return records, None
            # If no records, continue to fallback flow below.
        except Exception as exc:
            return [], f"{source_name}: cannot open datatrain.php ({exc})"

    try:
        base_resp = session.get(url, timeout=SOURCE_TIMEOUT_SEC, headers=headers)
        base_resp.encoding = base_resp.apparent_encoding or base_resp.encoding
        if source_name == "SCIBASE" and "รหัสนักศึกษา" not in base_resp.text:
            base_resp.encoding = "tis-620"
        attempts.append(("GET(base)", base_resp.text))
    except Exception as exc:
        return [], f"{source_name}: cannot open page ({exc})"

    # Submit discovered forms using real action/method/input names from source page.
    for method, submit_url, payload in _build_form_attempts(url, base_resp.text, student_id):
        try:
            if method == "post":
                resp = session.post(submit_url, data=payload, timeout=SOURCE_TIMEOUT_SEC, headers=headers)
            else:
                resp = session.get(submit_url, params=payload, timeout=SOURCE_TIMEOUT_SEC, headers=headers)
            resp.encoding = resp.apparent_encoding or resp.encoding
            if source_name == "SCIBASE" and "รหัสนักศึกษา" not in resp.text:
                resp.encoding = "tis-620"
            attempts.append((f"FORM-{method.upper()}({submit_url}, {payload})", resp.text))
        except Exception:
            pass

    for payload in payload_candidates:
        try:
            get_resp = session.get(url, params=payload, timeout=SOURCE_TIMEOUT_SEC, headers=headers)
            get_resp.encoding = get_resp.apparent_encoding or get_resp.encoding
            if source_name == "SCIBASE" and "รหัสนักศึกษา" not in get_resp.text:
                get_resp.encoding = "tis-620"
            attempts.append((f"GET({payload})", get_resp.text))
        except Exception:
            pass

        try:
            post_resp = session.post(url, data=payload, timeout=SOURCE_TIMEOUT_SEC, headers=headers)
            post_resp.encoding = post_resp.apparent_encoding or post_resp.encoding
            if source_name == "SCIBASE" and "รหัสนักศึกษา" not in post_resp.text:
                post_resp.encoding = "tis-620"
            attempts.append((f"POST({payload})", post_resp.text))
        except Exception:
            pass

    collected: list[SeatingRecord] = []
    seen_raw: set[str] = set()

    for _, html in attempts:
        if source_name == "ENG":
            parsed_records = _parse_eng_html(html, student_id)
        elif source_name == "SCIBASE":
            parsed_records = _parse_scibase_html(html, student_id)
        else:
            soup = BeautifulSoup(html, "html.parser")
            parsed_records = _records_from_table_rows(source_name, soup, student_id)
            plain = _clean_text(soup.get_text(" ", strip=True))
            parsed = _parse_candidate_text(source_name, plain, student_id)
            if parsed:
                parsed_records.append(parsed)

        for rec in parsed_records:
            if rec.raw_text and rec.raw_text not in seen_raw:
                seen_raw.add(rec.raw_text)
                collected.append(rec)

    return collected, None


def _debug_scibase_attempts(student_id: str) -> dict[str, Any]:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ExamSeatDashboard/1.0)",
    }
    session = requests.Session()
    attempts_summary: list[dict[str, Any]] = []
    forms_summary: list[dict[str, Any]] = []

    try:
        direct_resp = session.get(
            SCIBASE_API_URL,
            params={"IDcard": student_id},
            timeout=SOURCE_TIMEOUT_SEC,
            headers=headers,
        )
        direct_resp.encoding = direct_resp.apparent_encoding or direct_resp.encoding or "utf-8"
        summarize("GET datatrain.php?IDcard=...", direct_resp.text, direct_resp.url)
    except Exception as exc:
        attempts_summary.append({"label": "GET datatrain.php?IDcard=...", "error": str(exc)})

    try:
        base_resp = session.get(SCIBASE_URL, timeout=SOURCE_TIMEOUT_SEC, headers=headers)
        base_resp.encoding = base_resp.apparent_encoding or base_resp.encoding
        if "รหัสนักศึกษา" not in base_resp.text:
            base_resp.encoding = "tis-620"
    except Exception as exc:
        return {"error": f"cannot open SCIBASE: {exc}", "attempts": []}

    def summarize(label: str, html: str, final_url: str = "") -> None:
        records = _parse_scibase_html(html, student_id)
        text = _clean_text(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
        attempts_summary.append(
            {
                "label": label,
                "final_url": final_url,
                "html_length": len(html),
                "contains_student_id": student_id in text,
                "contains_exam_table_hint": ("รหัสวิชาที่สอบ" in text or "วิชาที่สอบ" in text),
                "parsed_records": len(records),
                "text_sample": text[:220],
            }
        )

    summarize("GET(base)", base_resp.text, base_resp.url)

    form_attempts = _build_form_attempts(SCIBASE_URL, base_resp.text, student_id)
    for method, submit_url, payload in form_attempts:
        forms_summary.append({"method": method, "submit_url": submit_url, "payload": payload})
        try:
            if method == "post":
                resp = session.post(submit_url, data=payload, timeout=SOURCE_TIMEOUT_SEC, headers=headers)
            else:
                resp = session.get(submit_url, params=payload, timeout=SOURCE_TIMEOUT_SEC, headers=headers)
            resp.encoding = resp.apparent_encoding or resp.encoding
            if "รหัสนักศึกษา" not in resp.text:
                resp.encoding = "tis-620"
            summarize(f"FORM-{method.upper()} {submit_url} {payload}", resp.text, resp.url)
        except Exception as exc:
            attempts_summary.append({"label": f"FORM-{method.upper()} {submit_url} {payload}", "error": str(exc)})

    payload_candidates = [
        {"student_id": student_id},
        {"studentid": student_id},
        {"studentCode": student_id},
        {"studentcode": student_id},
        {"student_code": student_id},
        {"studentno": student_id},
        {"student_no": student_id},
        {"stdid": student_id},
        {"txt_student_id": student_id},
        {"txtStudentID": student_id},
        {"txt_stdid": student_id},
        {"txtStdID": student_id},
        {"student": student_id},
        {"std_id": student_id},
        {"stdcode": student_id},
        {"std_code": student_id},
        {"code_student": student_id},
        {"r_student": student_id},
        {"id": student_id},
        {"q": student_id},
        {"keyword": student_id},
        {"search": student_id},
        {"code": student_id},
    ]
    for payload in payload_candidates:
        try:
            resp = session.get(SCIBASE_URL, params=payload, timeout=SOURCE_TIMEOUT_SEC, headers=headers)
            resp.encoding = resp.apparent_encoding or resp.encoding
            if "รหัสนักศึกษา" not in resp.text:
                resp.encoding = "tis-620"
            summarize(f"GET {payload}", resp.text, resp.url)
        except Exception as exc:
            attempts_summary.append({"label": f"GET {payload}", "error": str(exc)})

    for payload in payload_candidates:
        try:
            resp = session.post(SCIBASE_URL, data=payload, timeout=SOURCE_TIMEOUT_SEC, headers=headers)
            resp.encoding = resp.apparent_encoding or resp.encoding
            if "รหัสนักศึกษา" not in resp.text:
                resp.encoding = "tis-620"
            summarize(f"POST {payload}", resp.text, resp.url)
        except Exception as exc:
            attempts_summary.append({"label": f"POST {payload}", "error": str(exc)})

    best = max((a.get("parsed_records", 0) for a in attempts_summary), default=0)
    return {
        "student_id": student_id,
        "best_parsed_records": best,
        "forms_found": forms_summary,
        "attempts": attempts_summary,
    }


def _merge_and_clean(records: list[SeatingRecord]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    for record in records:
        # ENG sometimes captures trailing part of student id as subject code.
        if record.source == "ENG":
            if record.subject_code and record.student_id and record.student_id.endswith(record.subject_code):
                record.subject_code = ""
            # If subject_name starts with a proper course code, use it as source of truth.
            m = re.match(r"^\s*(\d{8,10})\s+(.+)$", record.subject_name or "")
            if m:
                possible_code = m.group(1)
                # Ignore code fragments that look like student-id suffix.
                if not (record.student_id and record.student_id.endswith(possible_code)):
                    record.subject_code = possible_code
                    record.subject_name = m.group(2).strip()

        # Normalize room/building split for formats like 88-603-4.
        if record.room and not record.building:
            m = re.fullmatch(r"(\d{2})-(.+)", record.room.strip())
            if m:
                record.building = m.group(1)
                record.room = m.group(2)

        key = (
            record.source,
            record.subject_code,
            record.exam_date,
            record.room,
            record.seat_no,
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(asdict(record))

    return merged


@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.post("/api/search-seating")
def search_seating():
    data = request.get_json(silent=True) or {}
    student_id = _normalize_student_id(str(data.get("student_id", "")))

    if not _is_valid_student_id(student_id):
        return jsonify({"error": "student_id ต้องเป็นตัวเลข 13 หลัก"}), 400

    cached = _cached_get(student_id)
    if cached is not None:
        cached["cached"] = True
        return jsonify(cached)

    eng_records, eng_err = _query_source(ENG_URL, "ENG", student_id)
    sci_records, sci_err = _query_source(SCIBASE_URL, "SCIBASE", student_id)

    all_records = _merge_and_clean(eng_records + sci_records)
    response = {
        "student_id": student_id,
        "count": len(all_records),
        "records": all_records,
        "errors": [x for x in [eng_err, sci_err] if x],
        "cached": False,
        "sources": {
            "eng": {"url": ENG_URL, "count": len(eng_records)},
            "scibase": {"url": SCIBASE_URL, "count": len(sci_records)},
        },
    }

    _cached_set(student_id, response)
    return jsonify(response)


@app.post("/api/debug/scibase")
def debug_scibase():
    data = request.get_json(silent=True) or {}
    student_id = _normalize_student_id(str(data.get("student_id", "")))
    if not _is_valid_student_id(student_id):
        return jsonify({"error": "student_id ต้องเป็นตัวเลข 13 หลัก"}), 400
    return jsonify(_debug_scibase_attempts(student_id))


if __name__ == "__main__":
    app.run(debug=True)
