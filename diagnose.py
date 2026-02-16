# diagnose_thread.py
"""
Диагностика местоположения треда на форуме.
Определяет, находится ли тема в архивном разделе (Отмененные законопроекты).

ИСПОЛЬЗОВАНИЕ:
    1. Укажите URL треда в переменной THREAD_URL
    2. Запустите: python diagnose_thread.py
"""

from playwright.sync_api import sync_playwright
from typing import List, Dict, Optional
import re


# ========== НАСТРОЙКА ==========

# ← УКАЖИТЕ СВОЙ URL ЗДЕСЬ
THREAD_URL = "https://forum.majestic-rp.ru/threads/ugolovnyi-kodeks-shtata-san-andreas.2247404/"


# Ключевые слова для определения архивных/отмененных разделов
OBSOLETE_KEYWORDS = [
    'отменен',
    'отменён',
    'устарел',
    'устаревш',
    'недейств',
    'архив',
    'старые',
    'старая',
]


# ========== ФУНКЦИИ ДИАГНОСТИКИ ==========

def extract_breadcrumbs(page) -> List[Dict[str, str]]:
    """
    Извлекает навигационную цепочку (breadcrumbs) со страницы форума.
    """
    try:
        breadcrumbs_data = page.evaluate("""
            () => {
                const selectors = [
                    '.p-breadcrumbs li',
                    '.breadcrumb li',
                    '.breadcrumbs li',
                    'nav[aria-label="Breadcrumb"] li'
                ];

                let items = [];
                for (const selector of selectors) {
                    items = Array.from(document.querySelectorAll(selector));
                    if (items.length > 0) break;
                }

                return items.map(item => {
                    const link = item.querySelector('a');
                    const span = item.querySelector('span');

                    let text = '';
                    let url = '';

                    if (link) {
                        text = (link.innerText || link.textContent || '').trim();
                        url = link.getAttribute('href') || '';
                    } else if (span) {
                        text = (span.innerText || span.textContent || '').trim();
                    } else {
                        text = (item.innerText || item.textContent || '').trim();
                    }

                    return { text, url };
                }).filter(item => item.text.length > 0 && item.text !== '…');
            }
        """)

        return breadcrumbs_data

    except Exception as e:
        print(f"[Breadcrumbs] ❌ Ошибка извлечения: {e}")
        return []


def analyze_breadcrumb_path(breadcrumbs: List[Dict[str, str]]) -> Dict[str, any]:
    """
    Анализирует путь навигации на наличие архивных/отмененных разделов.
    """
    sections = [item['text'] for item in breadcrumbs]
    full_path = ' > '.join(sections)

    obsolete_section = None
    obsolete_index = None

    for i, section in enumerate(sections):
        section_lower = section.lower()
        for keyword in OBSOLETE_KEYWORDS:
            if keyword in section_lower:
                obsolete_section = section
                obsolete_index = i
                break
        if obsolete_section:
            break

    is_obsolete = obsolete_section is not None
    active_path = ' > '.join(sections[:obsolete_index]) if obsolete_index else full_path

    return {
        'full_path': full_path,
        'sections': sections,
        'is_obsolete': is_obsolete,
        'obsolete_section': obsolete_section,
        'obsolete_index': obsolete_index,
        'active_path': active_path,
        'breadcrumbs_raw': breadcrumbs
    }


def diagnose_thread_location(page) -> Dict[str, any]:
    """
    Полная диагностика местоположения треда на форуме.
    """
    breadcrumbs = extract_breadcrumbs(page)

    if not breadcrumbs:
        return {
            'breadcrumbs_found': False,
            'breadcrumbs_count': 0,
            'full_path': '',
            'sections': [],
            'is_obsolete': False,
            'obsolete_section': None,
            'recommendation': 'UNKNOWN - не удалось извлечь breadcrumbs'
        }

    analysis = analyze_breadcrumb_path(breadcrumbs)

    if analysis['is_obsolete']:
        recommendation = f"SKIP - тред находится в архивном разделе '{analysis['obsolete_section']}'"
    else:
        recommendation = "PARSE - тред находится в актуальном разделе"

    return {
        'breadcrumbs_found': True,
        'breadcrumbs_count': len(breadcrumbs),
        'full_path': analysis['full_path'],
        'sections': analysis['sections'],
        'is_obsolete': analysis['is_obsolete'],
        'obsolete_section': analysis['obsolete_section'],
        'obsolete_index': analysis['obsolete_index'],
        'active_path': analysis['active_path'],
        'breadcrumbs_raw': analysis['breadcrumbs_raw'],
        'recommendation': recommendation
    }


def print_diagnostic(diagnostic: Dict[str, any]) -> None:
    """
    Красиво выводит результаты диагностики.
    """
    print("\n" + "=" * 80)
    print("ДИАГНОСТИКА МЕСТОПОЛОЖЕНИЯ ТРЕДА")
    print("=" * 80)

    if not diagnostic['breadcrumbs_found']:
        print("❌ Breadcrumbs не найдены на странице")
        print(f"Рекомендация: {diagnostic['recommendation']}")
        return

    print(f"✓ Найдено уровней навигации: {diagnostic['breadcrumbs_count']}")
    print()

    # Полный путь
    print("📍 ПОЛНЫЙ ПУТЬ:")
    print(f"   {diagnostic['full_path']}")
    print()

    # Разделы по уровням
    print("📂 РАЗДЕЛЫ ПО УРОВНЯМ:")
    for i, section in enumerate(diagnostic['sections'], 1):
        marker = "⚠" if (diagnostic['is_obsolete'] and 
                        i > diagnostic['obsolete_index']) else "✓"
        highlight = " ← АРХИВНЫЙ РАЗДЕЛ" if (diagnostic['is_obsolete'] and 
                                             section == diagnostic['obsolete_section']) else ""
        print(f"   {marker} Уровень {i}: {section}{highlight}")
    print()

    # Статус
    print("🔍 СТАТУС:")
    if diagnostic['is_obsolete']:
        print(f"   ❌ Тред находится в АРХИВНОМ разделе")
        print(f"   📁 Архивный раздел: '{diagnostic['obsolete_section']}'")
        print(f"   📊 Позиция в пути: уровень {diagnostic['obsolete_index'] + 1}")
        print(f"   ✂ Актуальный путь: {diagnostic['active_path']}")
    else:
        print(f"   ✅ Тред находится в АКТУАЛЬНОМ разделе")
    print()

    # Рекомендация
    print("💡 РЕКОМЕНДАЦИЯ:")
    print(f"   {diagnostic['recommendation']}")
    print()

    # Детали (raw URLs)
    if diagnostic.get('breadcrumbs_raw'):
        print("🔗 ДЕТАЛИ (URLs):")
        for i, item in enumerate(diagnostic['breadcrumbs_raw'], 1):
            url_preview = item['url'][:60] + '...' if len(item['url']) > 60 else item['url']
            print(f"   {i}. {item['text']}")
            if item['url']:
                print(f"      └─ {url_preview}")

    print("=" * 80)


# ========== ГЛАВНАЯ ФУНКЦИЯ ==========

def run_diagnostic(url: str, headless: bool = False):
    """
    Запускает диагностику для указанного URL.
    """
    print(f"[Диагностика] URL: {url}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-gpu", "--disable-extensions"]
        )
        context = browser.new_context(locale="ru-RU")
        page = context.new_page()

        try:
            print("[1/3] Загрузка страницы...")
            page.goto(url, wait_until="domcontentloaded", timeout=120_000)
            page.wait_for_timeout(2000)

            # Cloudflare check
            title = page.title().lower()
            if "cloudflare" in title or "check" in title:
                print("[2/3] Обход Cloudflare...")
                try:
                    page.wait_for_load_state("networkidle", timeout=30_000)
                except:
                    pass
                page.wait_for_timeout(5000)
            else:
                print("[2/3] Страница загружена")

            # Диагностика
            print("[3/3] Анализ навигации...")
            diagnostic = diagnose_thread_location(page)

            # Вывод результатов
            print_diagnostic(diagnostic)

            # Краткий итог
            print("\n" + "─" * 80)
            print("ИТОГ:")
            if diagnostic['is_obsolete']:
                print(f"❌ АРХИВНЫЙ раздел: '{diagnostic['obsolete_section']}'")
                print("   → Парсинг НЕ РЕКОМЕНДУЕТСЯ")
            else:
                print("✅ АКТУАЛЬНЫЙ раздел")
                print("   → Можно парсить")
            print("─" * 80 + "\n")

            return diagnostic

        except Exception as e:
            print(f"\n💥 ОШИБКА: {e}\n")
            return None

        finally:
            try:
                context.close()
                browser.close()
            except:
                pass


# ========== ЗАПУСК ==========

if __name__ == "__main__":
    print("\n" + "="*80)
    print("ДИАГНОСТИКА ТРЕДА НА ФОРУМЕ")
    print("="*80)

    if not THREAD_URL or THREAD_URL == "":
        print("\n⚠️  ОШИБКА: Не указан THREAD_URL")
        print("   Откройте файл и укажите URL в переменной THREAD_URL\n")
    else:
        run_diagnostic(THREAD_URL, headless=False)