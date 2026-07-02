"""
Проверка непрерывности разделов в кодексах (laws/*.json).

Раздел = первая цифра кода статьи (1.1 → 1, 12.4 → 12).
При обходе статей по порядку каждый новый раздел должен быть на +1 от предыдущего.
Пример ошибки: ...5.6 → 12.4 (пропущены разделы 6–11).

Запуск: python check_codex_gaps.py
Вывод: только серверы/кодексы с разрывами. Если всё OK — одна строка.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

LAWS_DIR = Path(__file__).resolve().parent / "laws"

CODEX_NAMES = {
    "UK": "Уголовный кодекс",
    "AK": "Административный кодекс",
    "DK": "Дорожный кодекс",
    "PK": "Процессуальный кодекс",
    "UAK": "Уголовно-административный",
}

_SECTION_NUM_RE = re.compile(r"^(\d+)")
_SERVER_NUM_RE = re.compile(r"-(\d+)$")
_CODEX_ORDER = {"UK": 0, "AK": 1, "DK": 2, "PK": 3, "UAK": 4}


def server_number(server: str) -> int:
    """Номер сервера из имени файла: 'new york-1' -> 1, 'memphis-19' -> 19."""
    m = _SERVER_NUM_RE.search(server.lower())
    return int(m.group(1)) if m else 9999


def section_number(code: str) -> Optional[int]:
    """Первая цифра кода: '5.6 ч.1' → 5, '12.4' → 12."""
    if not code:
        return None
    clean = code.strip().lower()
    clean = re.sub(r"\s*ч\.\d+", "", clean)
    m = _SECTION_NUM_RE.match(clean)
    return int(m.group(1)) if m else None


def section_sequence(codes: List[str]) -> List[int]:
    """Уникальные разделы в порядке появления (1,1,1,2,2,3 → [1,2,3])."""
    seq: List[int] = []
    prev: Optional[int] = None
    for code in codes:
        num = section_number(code)
        if num is None:
            continue
        if num != prev:
            seq.append(num)
            prev = num
    return seq


def find_gaps(seq: List[int]) -> List[Tuple[int, int]]:
    """Пары (было, стало) где шаг не +1."""
    gaps: List[Tuple[int, int]] = []
    for i in range(1, len(seq)):
        if seq[i] != seq[i - 1] + 1:
            gaps.append((seq[i - 1], seq[i]))
    return gaps


def check_codex(articles: list) -> Tuple[List[Tuple[int, int]], List[str]]:
    codes = [a.get("code", "") for a in articles if isinstance(a, dict)]
    seq = section_sequence(codes)
    return find_gaps(seq), codes


def format_gap(prev: int, nxt: int) -> str:
    missing = list(range(prev + 1, nxt))
    if len(missing) <= 6:
        miss = ", ".join(str(x) for x in missing)
        return f"раздел {prev} -> {nxt} (пропущены: {miss})"
    return f"раздел {prev} -> {nxt} (пропущены: {prev + 1}-{nxt - 1})"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if not LAWS_DIR.is_dir():
        print(f"Папка не найдена: {LAWS_DIR}", file=sys.stderr)
        return 2

    failures: List[Tuple[int, int, str]] = []

    for path in LAWS_DIR.glob("*.json"):
        server = path.stem
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            failures.append((server_number(server), 99, f"{server} | (файл) | не удалось прочитать: {e}"))
            continue

        data = payload.get("data") or {}
        if not isinstance(data, dict):
            continue

        for codex_key in ("UK", "AK", "DK", "PK", "UAK"):
            block = data.get(codex_key)
            if not block or not isinstance(block, dict):
                continue
            articles = block.get("articles")
            if not articles:
                continue

            gaps, codes = check_codex(articles)
            if not gaps:
                continue

            codex_name = CODEX_NAMES.get(codex_key, codex_key)
            gap_text = "; ".join(format_gap(a, b) for a, b in gaps)
            # контекст: коды статей на границе первого разрыва
            seq = section_sequence(codes)
            first_prev, first_next = gaps[0]
            boundary_codes = []
            for code in codes:
                s = section_number(code)
                if s in (first_prev, first_next):
                    boundary_codes.append(code)
            boundary_hint = ""
            if boundary_codes:
                boundary_hint = f" | у границы: {' -> '.join(boundary_codes[:4])}"
                if len(boundary_codes) > 4:
                    boundary_hint += " …"

            failures.append((
                server_number(server),
                _CODEX_ORDER.get(codex_key, 99),
                f"{server} | {codex_key} ({codex_name}) | {gap_text}{boundary_hint}",
            ))

    failures.sort(key=lambda x: (x[0], x[1]))

    if failures:
        print("Разрывы в цепочке разделов:\n")
        for _, _, line in failures:
            print(line)
        print(f"\nИтого: {len(failures)} проблем(ы)")
        return 1

    print("OK — разрывов разделов в кодексах не найдено")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
