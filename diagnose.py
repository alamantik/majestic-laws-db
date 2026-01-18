# debug_pagenav.py
from playwright.sync_api import sync_playwright
from bot import get_thread_pages_count, _soft_scroll  # функции из твоего бота [file:4]

THREAD_URL = "https://forum.majestic-rp.ru/threads/protsessual-nyi-kodeks-shtata-san-andreas.2579857/"  # ← сюда вставь свой URL


def debug_page_nav():
    print(f"[Debug] URL: {THREAD_URL}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-gpu", "--disable-extensions"],
        )
        context = browser.new_context(locale="ru-RU")
        page = context.new_page()

        try:
            print("[Debug] goto first time...")
            page.goto(THREAD_URL, wait_until="domcontentloaded", timeout=120_000)
            page.wait_for_timeout(2000)

            title = page.title().lower()
            print(f"[Debug] title: {title}")

            # имитация обхода Cloudflare, как в основной программе [file:4]
            if "cloudflare" in title or "check" in title:
                print("[Debug] Cloudflare detected, waiting for networkidle...")
                try:
                    page.wait_for_load_state("networkidle", timeout=30_000)
                except Exception as e:
                    print("[Debug] networkidle timeout:", e)
                page.wait_for_timeout(5000)
                title = page.title().lower()
                print(f"[Debug] title after CF: {title}")

            # мягкий скролл, как у тебя
            _soft_scroll(page)

            # теперь считаем страницы ровно тем же методом
            pages_count = get_thread_pages_count(page)
            print(f"[Pages] pages_count = {pages_count}")

            # детальнее выведем .pageNav, если есть
            nav = page.query_selector(".pageNav")
            if not nav:
                print("[Pages] .pageNav NOT FOUND")
            else:
                print("[Pages] .pageNav FOUND")
                items = nav.query_selector_all("a.pageNav-page, span.pageNav-page")
                print(f"[Pages] raw items count: {len(items)}")
                for it in items:
                    txt = (it.inner_text() or "").strip()
                    print(f"[Pages] item text: {repr(txt)}")

        finally:
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    debug_page_nav()
