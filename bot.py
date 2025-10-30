import os
import re
import json
import time
from pathlib import Path
from datetime import datetime

os.environ["GIT_PYTHON_GIT_EXECUTABLE"] = r"C:\Program Files\Git\bin\git.exe"

import schedule
from dotenv import load_dotenv
import hashlib

load_dotenv()

GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")

SOURCES_PATH = Path("sources.json")
OUTPUT_DIR = Path("laws")  # ← ИЗМЕНЕНО: output → laws
OUTPUT_DIR.mkdir(exist_ok=True)

def _stable_dump(data: dict) -> bytes:
    # Стабильная сериализация без updatedAt
    clone = json.loads(json.dumps(data, ensure_ascii=False))
    if "updatedAt" in clone:
        clone["updatedAt_prev"] = clone.pop("updatedAt")
    return json.dumps(clone, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

# ---------- Loader (guest, no auth) ----------
def _soft_scroll(page, max_steps=60):
    last_h, same = 0, 0
    for step in range(max_steps):
        page.evaluate("window.scrollBy(0, 1600)")
        page.wait_for_timeout(400)
        h = page.evaluate("document.body.scrollHeight")
        if h == last_h:
            same += 1
        else:
            same = 0
        last_h = h
        if step % 10 == 0:
            print(f"[Loader] scroll step={step} height={h} same={same}")
        if same >= 3:
            break

def extract_visible_text(url: str) -> str:
    from playwright.sync_api import sync_playwright
    print(f"[Loader] open: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-http2",
                "--disable-renderer-backgrounding",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--window-size=1280,900"
            ],
        )
        context = browser.new_context(
            locale="ru-RU",
            viewport={"width": 1280, "height": 900}
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=120_000)

        _soft_scroll(page, max_steps=80)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
            print("[Loader] networkidle reached")
        except:
            print("[Loader] networkidle timeout")
        page.wait_for_timeout(800)

        selectors = [
            ".message-content",
            ".bbWrapper",
            ".message-userContent",
            "article.message-body",
            "article .message-content",
            ".message .bbWrapper",
            ".block-body .bbWrapper",
            ".p-body .bbWrapper"
        ]
        texts = []
        for sel in selectors:
            nodes = page.query_selector_all(sel)
            print(f"[Extract] sel={sel} nodes={len(nodes)}")
            for idx, n in enumerate(nodes):
                t = n.inner_text()
                print(f"[Extract]  -> node#{idx} len={len(t)}")
                if t and len(t) > 500:
                    texts.append((sel, idx, t))

        if not texts:
            bt = page.evaluate("document.body ? (document.body.innerText || document.body.textContent || '') : ''")
            print(f"[Extract] body.len={len(bt)}")
            if bt and len(bt) > 800:
                texts.append(("body", 0, bt))

        # retry in same session if empty
        if not texts:
            print("[Extract] retry within same session")
            page.goto(url, wait_until="domcontentloaded", timeout=120_000)
            _soft_scroll(page, max_steps=60)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except:
                pass
            page.wait_for_timeout(800)
            for sel in selectors:
                nodes = page.query_selector_all(sel)
                for idx, n in enumerate(nodes):
                    t = n.inner_text()
                    if t and len(t) > 500:
                        texts.append((sel, idx, t))
            if not texts:
                bt = page.evaluate("document.body ? (document.body.innerText || document.body.textContent || '') : ''")
                if bt and len(bt) > 800:
                    texts.append(("body", 0, bt))

        browser.close()

        if not texts:
            print("[Extract] ❌ no text candidates")
            return ""

        texts.sort(key=lambda x: len(x[2]), reverse=True)
        sel, idx, joined = texts[0]
        print(f"[Extract] ✅ pick sel={sel} node#{idx} len={len(joined)}")
        print("[Extract] preview:\n" + "\n".join(joined.splitlines()[:12]))
        return joined

# ---------- Normalization ----------
def _normalize_lines(text: str) -> list[str]:
    import re
    t = (text.replace("\u00A0", " ")
             .replace("\u200b", " ")
             .replace("\ufeff", " "))
    raw = [ln.strip() for ln in t.split("\n")]
    raw = [ln for ln in raw if ln]

    norm: list[str] = []
    rx_article_inline = re.compile(r"^(Статья\s+\d+(?:\.\d+){0,2}\.)\s*(.+)$", re.IGNORECASE)
    rx_part_inline    = re.compile(r"^(ч\.\s*\d+)\s+(.+)$", re.IGNORECASE)

    for ln in raw:
        mA = rx_article_inline.match(ln)
        if mA:
            norm.append(mA.group(1).strip())   # "Статья 5.1."
            title = mA.group(2).strip()
            if title:
                norm.append(title)
            continue
        mP = rx_part_inline.match(ln)
        if mP:
            norm.append(mP.group(1).strip())   # "ч. 1"
            rest = mP.group(2).strip()
            if rest:
                norm.append(rest)
            continue
        norm.append(ln)
    return norm

# ---------- Penalty extraction ----------
def extract_penalty(body: str) -> str | None:
    import re
    t = (body or "").replace("\u00A0", " ").replace("\u200b", " ").replace("\ufeff", " ").strip()
    if not t:
        return None

    # 1) Явное "Наказание: ..."
    m = re.search(r"Наказание:\s*([^\n\r]+)", t, flags=re.IGNORECASE)
    if m:
        frag = m.group(1).strip()
        frag = frag.split("\n")[0].strip()
        return frag.rstrip(" .")

    # 2) Частые форматы без слова "Наказание"
    #    - штраф ...
    m2 = re.search(r"\bштраф(?:\s+в\s+размере)?\s*[^\.!\n\r]+", t, flags=re.IGNORECASE)
    if m2:
        return m2.group(0).strip().rstrip(" .")

    #    - лишение свободы ...
    m3 = re.search(r"\b(лишени[ея]\s+свободы[^\.!\n\r]*)", t, flags=re.IGNORECASE)
    if m3:
        return m3.group(1).strip().rstrip(" .")

    #    - предупреждение ...
    m4 = re.search(r"\bпредупреждени[ея][^\.!\n\r]*", t, flags=re.IGNORECASE)
    if m4:
        return m4.group(0).strip().rstrip(" .")

    # 3) Более редкая формулировка: "влечёт наказание в виде ..."
    m5 = re.search(r"\bвлеч[её]т[^\.!\n\r]*наказани[ея]\s+в\s+виде\s+([^\.!\n\r]+)", t, flags=re.IGNORECASE)
    if m5:
        return m5.group(1).strip().rstrip(" .")

    return None


# ---------- Parser (uses _normalize_lines + extract_penalty) ----------
def parse_page(url: str, section: str) -> list:
    import re
    text = extract_visible_text(url)
    if not text:
        print(f"[Parser] ❌ Нет текстового содержимого для {section}")
        return []

    lines = _normalize_lines(text)
    print(f"[Parser] {section} lines(normalized)={len(lines)}")

    rx_article = re.compile(r"^Статья\s+(\d+(?:\.\d+){0,2})\.$", re.IGNORECASE)  # 5 / 5.1 / 5.1.2
    rx_part    = re.compile(r"^ч\.\s*(\d+)$", re.IGNORECASE)                     # ч. 6

    items, seen = [], set()
    current_article = None
    current_title = None
    intro_buf: list[str] = []
    collecting_intro = False
    current_part = None
    part_buf: list[str] = []

    def make_id(section_name: str, code: str) -> str:
        # "10 ч.1" -> "10 ч_1"; "10.1" -> "10_1"
        s = code
        s = re.sub(r"\s*ч\s*\.?\s*(\d+)", r" ч_\1", s, flags=re.IGNORECASE)
        s = s.replace(".", "_")
        s = re.sub(r"\s+", " ", s).strip().replace(" ", "_")
        return f"{section_name.lower()}-{s}"

    def push_item(code: str, title: str, body: str, pr=None, pen=None):
        _pen = pen if pen is not None else extract_penalty(body)
        key = f"{section}:{code}"
        if key in seen:
            return
        items.append({
            "id": make_id(section, code),
            "section": section,
            "code": code,
            "title": title,
            "text": body,
            "priority": pr,
            "penalty": _pen
        })
        seen.add(key)
        if len(items) % 25 == 0:
            print(f"[Parser] {section} progress={len(items)}")

    def flush_intro():
        nonlocal intro_buf
        if current_article and intro_buf:
            body = " ".join(intro_buf).strip()
            if body:
                push_item(current_article, current_title or f"Статья {current_article}", body)
        intro_buf = []

    def flush_part():
        nonlocal part_buf, current_part
        if current_article and current_part and part_buf:
            body = " ".join(part_buf).strip()
            if body:
                # priority можно попытаться вытянуть отдельно, если оно встречается; оставим, если уже было None
                prm = re.search(r"приоритет[:\s-]*([0-9]+)", body, re.IGNORECASE)
                pr = int(prm.group(1)) if prm else None
                code = f"{current_article} ч.{current_part}"
                push_item(code, current_title or f"Статья {current_article}", body, pr=pr, pen=None)
        part_buf, current_part = [], None

    i, N = 0, len(lines)
    while i < N:
        ln = lines[i]

        mA = rx_article.match(ln)
        if mA:
            flush_part()
            flush_intro()
            current_article = mA.group(1)   # 5 | 5.1 | 5.1.2
            current_title = None
            collecting_intro = True

            if i + 1 < N and not rx_part.match(lines[i + 1]):
                current_title = lines[i + 1].strip()
                print(f"[Parser] {section} article {current_article}: {current_title}")
                i += 2
                continue
            else:
                current_title = f"Статья {current_article}"
                print(f"[Parser] {section} article {current_article}")
                i += 1
                continue

        mP = rx_part.match(ln)
        if mP and current_article:
            if collecting_intro:
                flush_intro()
                collecting_intro = False
            flush_part()
            current_part = mP.group(1)
            part_buf = []
            print(f"[Parser] {section} part ч.{current_part} of {current_article}")
            i += 1
            continue

        if current_article:
            if collecting_intro:
                if rx_article.match(ln) or rx_part.match(ln):
                    i -= 1
                    collecting_intro = False
                else:
                    intro_buf.append(ln)
            else:
                if current_part:
                    if rx_article.match(ln) or rx_part.match(ln):
                        i -= 1
                        flush_part()
                    else:
                        part_buf.append(ln)
                else:
                    intro_buf.append(ln)

        i += 1

    flush_part()
    flush_intro()

    print(f"[Parser] {section} ✓ total={len(items)}")
    if len(items) == 0:
        head = "\n".join(lines[:30])
        tail = "\n".join(lines[-30:])
        print(f"[Parser] {section} head(30):\n{head}")
        print(f"[Parser] {section} tail(30):\n{tail}")
    return items


# ---------- Update + Git ----------
def update_server(server: str) -> bool:
    print(f"\n[Update] start: {server}")
    sources = json.loads(Path(SOURCES_PATH).read_text(encoding="utf-8"))
    s = sources.get(server)
    if not s:
        print(f"[Update] no sources for {server}")
        return False

    uk_url = s["UK"][0]
    dk_url = s["DK"][0]

    uk_items = parse_page(uk_url, "УК")
    dk_items = parse_page(dk_url, "ДК")

    items = uk_items + dk_items
    for it in items:
        it["search"] = f"{it['title'].lower()} {it['text'].lower()} {it['code']}"

    payload = {
        "server": server,
        "sourceUrls": {"UK": uk_url, "DK": dk_url},
        "items": items
    }

    out_path = OUTPUT_DIR / f"{server.lower()}.json"
    old_json = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
    old_hash = None
    if old_json:
        try:
            old_payload = json.loads(old_json)
            old_stable = _stable_dump({k: v for k, v in old_payload.items() if k != "updatedAt"})
            old_hash = _sha256(old_stable)
        except Exception:
            pass

    new_hash = _sha256(_stable_dump(payload))

    if old_hash == new_hash:
        print("[Update] no data changes — skip write/commit")
        return False

    payload["updatedAt"] = int(time.time() * 1000)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Update] saved {len(items)} → {out_path}")
    return True


def commit_and_push():
    try:
        import git
    except ImportError as e:
        print(f"[Git] skip, git not installed: {e}")
        return

    try:
        repo_path = Path.cwd()  # ВАЖНО: корень проекта, не OUTPUT_DIR!
        origin_url = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_USERNAME}/{GITHUB_REPO}.git"

        # Открыть/инициализировать репозиторий в корне
        try:
            repo = git.Repo(repo_path)
            print("[Git] repo opened")
        except git.exc.InvalidGitRepositoryError:
            repo = git.Repo.init(repo_path)
            print("[Git] repo initialized")

        # Настройка user.*
        with repo.config_writer() as cw:
            try:
                cw.get_value("user", "name")
            except Exception:
                cw.set_value("user", "name", GITHUB_USERNAME or "laws-bot")
            try:
                cw.get_value("user", "email")
            except Exception:
                cw.set_value("user", "email", f"{(GITHUB_USERNAME or 'bot')}@users.noreply.github.com")

        # Переключение на main
        try:
            current_branch = repo.active_branch.name
        except Exception:
            current_branch = None

        if current_branch is None or current_branch != "main":
            if "main" not in repo.refs:
                repo.git.checkout("-b", "main")
                print("[Git] branch main created")
            else:
                repo.git.checkout("main")
                print("[Git] checkout main")

        # Настройка remote
        if "origin" not in [r.name for r in repo.remotes]:
            repo.create_remote("origin", origin_url)
            print("[Git] origin set")
        else:
            repo.remotes.origin.set_url(origin_url)
            print("[Git] origin updated")

        # Добавляем ТОЛЬКО папку laws/ с JSON файлами
        laws_files = list(OUTPUT_DIR.glob("*.json"))
        if not laws_files:
            print("[Git] no JSON files in laws/ to commit")
            return
        
        for file in laws_files:
            repo.git.add(str(file))
            print(f"[Git] added {file}")
        
        # Проверяем изменения
        status = repo.git.status("--porcelain")
        if not status.strip():
            print("[Git] no changes to commit")
            return
        
        # Коммит
        commit_msg = f"Update laws-db: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        repo.index.commit(commit_msg)
        print(f"[Git] commit created: {commit_msg}")

        # Проверяем upstream
        try:
            repo.git.rev_parse("--symbolic-full-name", "--abbrev-ref", "main@{u}")
            has_upstream = True
        except Exception:
            has_upstream = False

        def push_now(first=False):
            if first:
                repo.git.push("--set-upstream", "origin", "main")
                print("[Git] first push with --set-upstream")
            else:
                repo.git.push("origin", "main")
                print("[Git] pushed to origin/main")

        # Push
        try:
            push_now(first=not has_upstream)
            print("[Git] ✓ Successfully pushed to GitHub")
            return
        except Exception as e:
            msg = str(e)
            print(f"[Git] push error: {msg}")

            if "Permission to " in msg or "403" in msg:
                print("[Git] ⚠ Permission denied: check GITHUB_TOKEN")
                return

            print("[Git] Push rejected, trying fetch + merge...")
            try:
                repo.git.fetch("origin", "main")
                
                try:
                    repo.git.merge("--ff-only", "origin/main")
                    print("[Git] fast-forward merge completed")
                except Exception:
                    try:
                        repo.git.merge("origin/main")
                        print("[Git] regular merge completed")
                    except Exception as e_mg:
                        if "refusing to merge unrelated histories" in str(e_mg):
                            repo.git.merge("--allow-unrelated-histories", "origin/main")
                            print("[Git] merge with --allow-unrelated-histories completed")
                        else:
                            print(f"[Git] ⚠ Merge failed: {e_mg}")
                            return

                push_now(first=False)
                print("[Git] ✓ Successfully pushed after merge")
                
            except Exception as e_all:
                print(f"[Git] ⚠ Fetch/merge failed: {e_all}")
                return

    except Exception as e:
        print(f"[Git] ⚠ Error: {e}")


def update_all() -> dict:
    """
    Обновляет все сервера из sources.json.
    Возвращает словарь вида:
    {
      "changed": ["Denver-16", "Another-1"],
      "unchanged": ["Server-X"]
    }
    """
    sources = json.loads(Path(SOURCES_PATH).read_text(encoding="utf-8"))
    changed, unchanged = [], []
    for server in sources.keys():
        try:
            ok = update_server(server)  # твоя функция уже возвращает True/False
            if ok:
                changed.append(server)
            else:
                unchanged.append(server)
        except Exception as e:
            print(f"[Update] {server} failed: {e}")
    return {"changed": changed, "unchanged": unchanged}


def run_update():
    print("\n=== Запуск обновления баз ===")
    result = update_all()
    if result["changed"]:
        print(f"[Update] changed servers: {', '.join(result['changed'])}")
        commit_and_push()
    else:
        print("[Git] skipped: no changes across servers")
    print("=== Обновление завершено ===\n")


if __name__ == "__main__":
    run_update()
    schedule.every().hour.at(":05").do(run_update)
    print("[Bot] scheduled hourly at :05")
    while True:
        schedule.run_pending()
        time.sleep(60)