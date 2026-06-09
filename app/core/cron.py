from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status


CRON_RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]


def validate_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="无效调度时区") from exc
    return name


def parse_cron(expression: str) -> list[set[int]]:
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("Cron 表达式必须包含 5 个字段")
    return [
        _parse_field(field, minimum, maximum)
        for field, (minimum, maximum) in zip(fields, CRON_RANGES, strict=True)
    ]


def next_cron_time(expression: str, timezone_name: str, after: datetime | None = None) -> datetime:
    fields = parse_cron(expression)
    zone = ZoneInfo(timezone_name)
    reference = after or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    candidate = reference.astimezone(zone).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(60 * 24 * 366 * 5):
        if cron_matches(candidate, fields):
            return candidate.astimezone(timezone.utc).replace(tzinfo=None)
        candidate += timedelta(minutes=1)
    raise ValueError("无法在未来五年内计算下一次 Cron 执行时间")


def cron_occurrences(
    expression: str,
    timezone_name: str,
    start_at: datetime,
    end_at: datetime,
    limit: int = 500,
) -> list[datetime]:
    result = []
    cursor = start_at
    while len(result) < limit:
        occurrence = next_cron_time(expression, timezone_name, cursor)
        aware_occurrence = occurrence.replace(tzinfo=timezone.utc)
        end = end_at if end_at.tzinfo is not None else end_at.replace(tzinfo=timezone.utc)
        if aware_occurrence > end:
            break
        result.append(occurrence)
        cursor = aware_occurrence
    return result


def cron_matches(value: datetime, fields: list[set[int]]) -> bool:
    minute, hour, day, month, weekday = fields
    cron_weekday = (value.weekday() + 1) % 7
    weekday_matches = cron_weekday in weekday or (cron_weekday == 0 and 7 in weekday)
    return value.minute in minute and value.hour in hour and value.day in day and value.month in month and weekday_matches


def _parse_field(value: str, minimum: int, maximum: int) -> set[int]:
    result: set[int] = set()
    for item in value.split(","):
        base, separator, step_value = item.partition("/")
        step = int(step_value) if separator and step_value.isdigit() else 1
        if separator and (not step_value.isdigit() or step < 1):
            raise ValueError("Cron 步长无效")
        if base == "*":
            start, end = minimum, maximum
        else:
            bounds = base.split("-")
            if len(bounds) not in {1, 2} or any(not bound.isdigit() for bound in bounds):
                raise ValueError("Cron 字段无效")
            start = int(bounds[0])
            end = int(bounds[-1])
        if start < minimum or end > maximum or start > end:
            raise ValueError("Cron 字段超出范围")
        result.update(range(start, end + 1, step))
    return result
