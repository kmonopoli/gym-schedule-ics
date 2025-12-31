#!/usr/bin/env python3
"""
Build an ICS calendar of Mt. Olympus "OPEN GYM CLOSED" blocks, based on the weekly schedule page.

Red entries are considered "closed" blocks.
The HTML currently encodes red as rgb(255, 42, 0) and also uses #ff2a00 in the explanatory text.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag

SCHEDULE_URL = "https://mtolympusgym.us/pages/weekly-schedule"
TZ = ZoneInfo("America/New_York")

# Known "red" encodings seen in your HTML dump
RED_MARKERS = {
    "rgb(255, 42, 0)",
    "rgb(255,42,0)",
    "#ff2a00",
    "#FF2A00",
}

DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]


@dataclass(frozen=True)
class ClosedBlock:
    day_name: str          # e.g., "WEDNESDAY"
    start: time
    end: time


TIME_RANGE_RE = re.compile(
    r"Training\s+(\d{1,2}:\d{2}\s*(?:am|pm))\s*-\s*(\d{1,2}:\d{2}\s*(?:am|pm))",
    re.IGNORECASE,
)


def parse_ampm(t: str) -> time:
    t = t.strip().lower().replace(" ", "")
    dt = datetime.strptime(t, "%I:%M%p")
    return dt.time().replace(second=0, microsecond=0)


def monday_of_week(d: date) -> date:
    return d - timedelta(days=d.weekday())


def normalize_day(s: str) -> str | None:
    s = s.strip().upper().rstrip(":")
    return s if s in DAYS else None


def style_has_red(style: str | None) -> bool:
    if not style:
        return False
    s = style.lower().replace(" ", "")
    # Look for any known red marker
    for marker in RED_MARKERS:
        if marker.lower().replace(" ", "") in s:
            return True
    # Also allow generic "color: red" if they ever switch
    return "color:red" in s


def extract_blocks(html: str) -> list[ClosedBlock]:
    soup = BeautifulSoup(html, "html.parser")

    # The schedule content appears inside the rich text area (rte)
    rte = soup.select_one("div.rte")
    if rte is None:
        raise RuntimeError("Could not find schedule container (div.rte). Page structure may have changed.")

    blocks: list[ClosedBlock] = []
    current_day: str | None = None

    # Iterate over paragraphs; day headers are bold/underlined text like "MONDAY:"
    for p in rte.find_all(["p", "div"], recursive=True):
        text = p.get_text(" ", strip=True)
        if not text:
            continue

        # Detect day headers
        day = normalize_day(text)
        if day:
            current_day = day
            continue

        if current_day is None:
            continue

        # Training lines: we care only when the *span that contains the text* is red
        # Many lines are like: <p><span style="color: rgb(255, 42, 0);">Training 6:00am-7:00am</span></p>
        spans = p.find_all("span")
        if not spans:
            continue

        for sp in spans:
            if not isinstance(sp, Tag):
                continue
            sp_text = sp.get_text(" ", strip=True)
            if not sp_text or "Training" not in sp_text:
                continue

            m = TIME_RANGE_RE.search(sp_text)
            if not m:
                continue

            if style_has_red(sp.get("style")):
                start_t = parse_ampm(m.group(1))
                end_t = parse_ampm(m.group(2))
                blocks.append(ClosedBlock(day_name=current_day, start=start_t, end=end_t))

    return blocks


def ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def format_dt(dt: datetime) -> str:
    # ICS local time with TZID
    return dt.strftime("%Y%m%dT%H%M%S")


def vtimezone_america_new_york() -> str:
    # Minimal VTIMEZONE for America/New_York (works well for subscriptions).
    # Many clients also work fine without VTIMEZONE, but including it helps.
    return """BEGIN:VTIMEZONE
TZID:America/New_York
X-LIC-LOCATION:America/New_York
BEGIN:DAYLIGHT
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE
"""


def build_ics(blocks: list[ClosedBlock], week_start: date) -> str:
    # Map day to date in the target week
    day_to_offset = {day: i for i, day in enumerate(DAYS)}

    now_utc = datetime.now(tz=ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")

    lines: list[str] = []
    lines.append("BEGIN:VCALENDAR")
    lines.append("VERSION:2.0")
    lines.append("PRODID:-//kmonopoli//mt-olympus-closed//EN")
    lines.append("CALSCALE:GREGORIAN")
    lines.append("METHOD:PUBLISH")
    lines.append(vtimezone_america_new_york().strip())

    for b in blocks:
        event_date = week_start + timedelta(days=day_to_offset[b.day_name])
        dt_start = datetime.combine(event_date, b.start, tzinfo=TZ)
        dt_end = datetime.combine(event_date, b.end, tzinfo=TZ)

        uid = f"{uuid.uuid5(uuid.NAMESPACE_URL, f'{event_date}-{b.start}-{b.end}')}" \
              f"@mtolympusgym.us"

        summary = f"Gym Closed (PT) [{b.day_name.title()}]"
        description = f"Mt. Olympus Open Gym unavailable (red slot). Source: {SCHEDULE_URL}"

        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{uid}")
        lines.append(f"DTSTAMP:{now_utc}")
        lines.append(f"DTSTART;TZID=America/New_York:{format_dt(dt_start)}")
        lines.append(f"DTEND;TZID=America/New_York:{format_dt(dt_end)}")
        lines.append(f"SUMMARY:{ics_escape(summary)}")
        lines.append(f"DESCRIPTION:{ics_escape(description)}")
        lines.append("STATUS:CONFIRMED")
        lines.append("TRANSP:OPAQUE")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")

    # Fold long lines to 75 octets is ideal, but most clients are forgiving.
    # If you want strict folding later, we can add it.
    return "\r\n".join(lines) + "\r\n"


def main() -> None:
    resp = requests.get(SCHEDULE_URL, timeout=30)
    resp.raise_for_status()

    blocks = extract_blocks(resp.text)

    # Put events on the current week (Mon-Sun) in America/New_York
    today = datetime.now(TZ).date()
    week_start = monday_of_week(today)

    ics = build_ics(blocks, week_start)

    out_path = "gym-closed.ics"
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write(ics)

    print(f"Wrote {out_path} with {len(blocks)} closed blocks for week starting {week_start}.")


if __name__ == "__main__":
    main()
