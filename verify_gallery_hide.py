import sys
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1400, "height": 900})
    pg.goto("http://127.0.0.1:5173/galleries", wait_until="networkidle")
    pg.wait_for_timeout(1000)
    try:
        pg.click("text=登录", timeout=3000)
    except Exception:
        pass
    pg.wait_for_timeout(600)
    try:
        pg.fill('input[type="text"]', 'root', timeout=3000)
        pg.fill('input[type="password"]', '<初始密码>', timeout=3000)
        pg.click('button:has-text("登录")', timeout=3000)
    except Exception as e:
        print("login err:", e)
    pg.wait_for_timeout(1500)

    pg.wait_for_selector(".gallery-card", timeout=5000)
    pg.wait_for_timeout(800)
    # open first gallery
    title0 = pg.query_selector(".gallery-card .gallery-title, .gallery-card").inner_text()
    pg.query_selector(".gallery-card").click()
    pg.wait_for_timeout(2500)
    print("detail url:", pg.url)

    hide_btn = pg.query_selector("button.bar-action[title*='隐藏'], button.bar-action[title*='显示']")
    print("hide btn found:", hide_btn is not None, "title:", hide_btn.get_attribute("title") if hide_btn else None)
    if hide_btn:
        hide_btn.click()
        pg.wait_for_timeout(1500)
        print("after click class:", hide_btn.get_attribute("class"))
        print("after click title:", hide_btn.get_attribute("title"))
    # go back to list
    pg.goto("http://127.0.0.1:5173/galleries", wait_until="networkidle")
    pg.wait_for_timeout(1500)
    print("back to list, cards:", len(pg.query_selector_all(".gallery-card")))
    b.close()
