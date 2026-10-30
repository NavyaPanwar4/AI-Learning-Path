"""Minimal RFC 5545 (iCalendar) writer: just what the study planner needs."""
from datetime import date, datetime, timedelta
from typing import Iterable, List, Optional


def escape_text(value: str) -> str:
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def fold(line: str) -> List[str]:
    """Fold a content line to at most 75 octets per physical line (RFC 5545 3.1)."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return [line]
    parts, current, size = [], "", 0
    for char in line:
        width = len(char.encode("utf-8"))
        limit = 75 if not parts else 74          # continuation lines start with one space
        if size + width > limit:
            parts.append(current)
            current, size = "", 0
        current += char
        size += width
    parts.append(current)
    return [parts[0]] + [" " + part for part in parts[1:]]


def utc_stamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%SZ")


def event(
    uid: str,
    summary: str,
    stamp: datetime,
    start: Optional[datetime] = None,
    duration_minutes: int = 30,
    all_day: Optional[date] = None,
    description: str = "",
    alarm_minutes_before: Optional[int] = 15,
) -> List[str]:
    """Return the content lines of one VEVENT (timed, or all-day when ``all_day`` is set)."""
    lines = ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{utc_stamp(stamp)}"]
    if all_day is not None:
        lines.append(f"DTSTART;VALUE=DATE:{all_day.strftime('%Y%m%d')}")
        lines.append(f"DTEND;VALUE=DATE:{(all_day + timedelta(days=1)).strftime('%Y%m%d')}")
    else:
        lines.append(f"DTSTART:{utc_stamp(start)}")
        lines.append(f"DTEND:{utc_stamp(start + timedelta(minutes=duration_minutes))}")
    lines.append(f"SUMMARY:{escape_text(summary)}")
    if description:
        lines.append(f"DESCRIPTION:{escape_text(description)}")
    if alarm_minutes_before is not None and all_day is None:
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{escape_text(summary)}",
                  f"TRIGGER:-PT{int(alarm_minutes_before)}M", "END:VALARM"]
    lines.append("END:VEVENT")
    return lines


def calendar(events: Iterable[List[str]], name: str = "Learning Path") -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Learning Path//Study Planner//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{escape_text(name)}"]
    for lines_of_event in events:
        lines.extend(lines_of_event)
    lines.append("END:VCALENDAR")
    folded = [piece for line in lines for piece in fold(line)]
    return "\r\n".join(folded) + "\r\n"
