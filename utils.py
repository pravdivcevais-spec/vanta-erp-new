import re
import string
from datetime import datetime, date

from config import ACTIVE_MASTER_STATUSES


# ---------------------------------------------------------------------------
# Форматирование
# ---------------------------------------------------------------------------

def format_dt(value) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime("%d.%m.%Y %H:%M")


def format_short_date(value) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime("%d.%m.%Y")


# ---------------------------------------------------------------------------
# Имена сотрудников
# ---------------------------------------------------------------------------

def full_name(row: dict) -> str:
    first_name = (row.get("first_name") or "").strip()
    last_name = (row.get("last_name") or "").strip()
    name = f"{last_name} {first_name}".strip()
    return name or "—"


def latest_assignment_name(row: dict) -> str:
    first_name = (row.get("assigned_first_name") or row.get("first_name") or "").strip()
    last_name = (row.get("assigned_last_name") or row.get("last_name") or "").strip()
    name = f"{last_name} {first_name}".strip()
    return name or "—"


# ---------------------------------------------------------------------------
# Велосипеды
# ---------------------------------------------------------------------------

def filter_bikes(bikes: list[dict], search: str, fields: tuple[str, ...]) -> list[dict]:
    if not search:
        return bikes
    needle = search.strip().lower()
    result = []
    for bike in bikes:
        haystack = " ".join(str(bike.get(field) or "") for field in fields).lower()
        if needle in haystack:
            result.append(bike)
    return result


def bike_history_for_darkstore(bike_id: int, darkstore_id: int, incoming_requests: list[dict]) -> list[dict]:
    rows = [
        row for row in incoming_requests
        if row.get("bike_id") == bike_id and row.get("darkstore_id") == darkstore_id
    ]
    return sorted(rows, key=lambda row: row.get("created_at") or datetime.min, reverse=True)


def bike_logs_for_bike(bike_id: int, bike_logs: list[dict]) -> list[dict]:
    return [row for row in bike_logs if row.get("bike_id") == bike_id]


# ---------------------------------------------------------------------------
# Сортировка заявок выездных мастеров
# ---------------------------------------------------------------------------

def field_master_status_rank(status: str) -> int:
    order = {
        "назначена": 0,
        "в работе": 1,
        "отложена": 2,
        "ожидает запчасти": 2,
        "замена вело": 3,
        "завершена": 4,
    }
    return order.get((status or "").strip().lower(), 9)


def sort_field_master_repairs(rows: list[dict]) -> list[dict]:
    return sorted(
        rows,
        key=lambda row: (
            field_master_status_rank(row.get("status")),
            row.get("darkstore_direction") or "",
            row.get("darkstore_name") or "",
            row.get("updated_at") or datetime.min,
        ),
    )


# ---------------------------------------------------------------------------
# Запчасти
# ---------------------------------------------------------------------------

def suggested_spare_parts_for_repair(repair: dict, spare_catalog: list[dict]) -> list[dict]:
    problem = f"{repair.get('problem') or ''} {repair.get('comment') or ''}".lower()
    suggestions = []
    keyword_map = {
        "торм": ("тормоз", "колод"),
        "цеп": ("цеп",),
        "кам": ("камер",),
        "аккум": ("акб", "аккум"),
        "мотор": ("мотор",),
    }
    for part in spare_catalog:
        haystack = f"{part.get('name') or ''} {part.get('article') or ''} {part.get('description') or ''}".lower()
        matched = False
        for _, keywords in keyword_map.items():
            if any(keyword in problem for keyword in keywords) and any(keyword in haystack for keyword in keywords):
                matched = True
                break
        if matched:
            suggestions.append(part)
    if not suggestions and spare_catalog:
        suggestions = spare_catalog[:3]
    return suggestions[:5]


def aggregate_stock_by_part(stock_rows: list[dict]) -> list[dict]:
    aggregated: dict[int, dict] = {}
    for row in stock_rows:
        catalog_id = row.get("spare_part_catalog_id")
        if catalog_id is None:
            continue
        item = aggregated.setdefault(
            int(catalog_id),
            {
                "spare_part_catalog_id": int(catalog_id),
                "spare_name": row.get("spare_name") or "Запчасть",
                "article": row.get("article") or "",
                "quantity": 0,
                "stock_rows": [],
            },
        )
        item["quantity"] += int(row.get("quantity") or 0)
        item["stock_rows"].append(row)
    return sorted(
        aggregated.values(),
        key=lambda item: ((item.get("spare_name") or "").lower(), item["spare_part_catalog_id"]),
    )


# ---------------------------------------------------------------------------
# Прочее
# ---------------------------------------------------------------------------

def count_by(rows: list[dict], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        value = row.get(key) or "—"
        result[value] = result.get(value, 0) + 1
    return result


def build_yandex_maps_link(route_points: list[dict]) -> str:
    if not route_points:
        return ""
    base = "https://yandex.ru/maps/?rtext="
    points = "~".join(f"{point['lat']},{point['lon']}" for point in route_points)
    return f"{base}{points}&rtt=auto"


# ---------------------------------------------------------------------------
# Нормализация идентификаторов велосипедов
# ---------------------------------------------------------------------------

LATIN_TO_CYRILLIC_GOV_MAP = str.maketrans(
    {
        "A": "А", "B": "В", "C": "С", "E": "Е",
        "H": "Н", "K": "К", "M": "М", "O": "О",
        "P": "Р", "T": "Т", "X": "Х", "Y": "У",
    }
)


def normalize_gov_number(value: str) -> str:
    cleaned = (value or "").strip().upper().replace(" ", "")
    return cleaned.translate(LATIN_TO_CYRILLIC_GOV_MAP)


def normalize_iot_device_id(value: str) -> str:
    return (value or "").strip().upper().replace(" ", "")


def validate_gov_format(gov_number: str) -> None:
    if gov_number and not re.fullmatch(r"[А-ЯЁ0-9]+", gov_number):
        raise ValueError("В госномере должны быть только заглавные русские буквы и цифры.")


def validate_iot_format(iot_device_id: str) -> None:
    if iot_device_id and not re.fullmatch(r"25-\d{4}", iot_device_id):
        raise ValueError("IoT должен быть в формате 25-1234.")
