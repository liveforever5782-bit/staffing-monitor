#!/usr/bin/env python3
"""
staffing_monitor/monitor.py
事務派遣 競合モニタリングツール

使い方: python3 monitor.py <エリア>
例: python3 monitor.py 関東
    python3 monitor.py 大阪府
    python3 monitor.py 名古屋市
"""

import asyncio
import json
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote


def _median_wage(wages: list) -> int:
    """時給リストから中央値を返す（外れ値に強い）"""
    if not wages:
        return 0
    return int(statistics.median(wages))

from region_config import (
    BROAD_REGIONS, PREFECTURE_CITIES, PREF_ROMAJI, CITY_ROMAJI,
)

# ── 有効エリア一覧 ────────────────────────────────────────────────
VALID_REGIONS = set(BROAD_REGIONS.keys())
for _pref, _pd in PREFECTURE_CITIES.items():
    VALID_REGIONS.add(_pref)
    for _city in _pd["cities"]:
        VALID_REGIONS.add(_city)

# ── スタッフサービス用 都道府県URLマッピング ──────────────────────
# URL形式: https://www.staffservice.co.jp/{pref_en}/office/
STAFFSERVICE_PREF_EN = {
    "北海道":"hokkaido","青森県":"aomori","岩手県":"iwate","宮城県":"miyagi",
    "秋田県":"akita","山形県":"yamagata","福島県":"fukushima","茨城県":"ibaraki",
    "栃木県":"tochigi","群馬県":"gunma","埼玉県":"saitama","千葉県":"chiba",
    "東京都":"tokyo","神奈川県":"kanagawa","新潟県":"niigata","富山県":"toyama",
    "石川県":"ishikawa","福井県":"fukui","山梨県":"yamanashi","長野県":"nagano",
    "岐阜県":"gifu","静岡県":"shizuoka","愛知県":"aichi","三重県":"mie",
    "滋賀県":"shiga","京都府":"kyoto","大阪府":"osaka","兵庫県":"hyogo",
    "奈良県":"nara","和歌山県":"wakayama","鳥取県":"tottori","島根県":"shimane",
    "岡山県":"okayama","広島県":"hiroshima","山口県":"yamaguchi","徳島県":"tokushima",
    "香川県":"kagawa","愛媛県":"ehime","高知県":"kochi","福岡県":"fukuoka",
    "佐賀県":"saga","長崎県":"nagasaki","熊本県":"kumamoto","大分県":"oita",
    "宮崎県":"miyazaki","鹿児島県":"kagoshima","沖縄県":"okinawa",
}
# 広域エリア → 代表都道府県URL
STAFFSERVICE_BROAD = {
    "北海道":"hokkaido","東北":"miyagi","北信越":"niigata",
    "関東":"tokyo","東海":"aichi","近畿":"osaka",
    "中国":"hiroshima","四国":"ehime","九州・沖縄":"fukuoka",
}
# 市区町村レベル URL（直接指定）※ /haken/ = 派遣のみフィルター (ユーザー確認済み)
STAFFSERVICE_CITY = {
    "特別区（23区）": "https://www.staffservice.co.jp/tokyo/23ku_all/office/haken/",
    "横浜市":         "https://www.staffservice.co.jp/kanagawa/yokohamashi_all/office/haken/",
    "川崎市":         "https://www.staffservice.co.jp/kanagawa/kawasakishi_all/office/haken/",
    "相模原市":       "https://www.staffservice.co.jp/kanagawa/sagamiharashi_all/office/haken/",
    "さいたま市":     "https://www.staffservice.co.jp/saitama/saitamashi_all/office/haken/",
    "千葉市":         "https://www.staffservice.co.jp/chiba/chibashi_all/office/haken/",
    "名古屋市":       "https://www.staffservice.co.jp/aichi/nagoyashi_all/office/haken/",
    "大阪市":         "https://www.staffservice.co.jp/osaka/osakashi_all/office/haken/",
    "神戸市":         "https://www.staffservice.co.jp/hyogo/kobeshi_all/office/haken/",
    "京都市":         "https://www.staffservice.co.jp/kyoto/kyotoshi_all/office/haken/",
    "広島市":         "https://www.staffservice.co.jp/hiroshima/hiroshimashi_all/office/haken/",
    "福岡市":         "https://www.staffservice.co.jp/fukuoka/fukuokashi_all/office/haken/",
    "北九州市":       "https://www.staffservice.co.jp/fukuoka/kitakyushushi_all/office/haken/",
    "仙台市":         "https://www.staffservice.co.jp/miyagi/sendaishi_all/office/haken/",
    "札幌市":         "https://www.staffservice.co.jp/hokkaido/sapporoshi_all/office/haken/",
}

def get_staffservice_url(region: str) -> str:
    if region in STAFFSERVICE_CITY:
        return STAFFSERVICE_CITY[region]
    if region in STAFFSERVICE_PREF_EN:
        en = STAFFSERVICE_PREF_EN[region]
        return f"https://www.staffservice.co.jp/{en}/office/haken/"
    if region in STAFFSERVICE_BROAD:
        en = STAFFSERVICE_BROAD[region]
        return f"https://www.staffservice.co.jp/{en}/office/haken/"
    # 市区町村：親都道府県
    for pn, pd in PREFECTURE_CITIES.items():
        if region in pd["cities"]:
            en = STAFFSERVICE_PREF_EN.get(pn, "")
            if en:
                return f"https://www.staffservice.co.jp/{en}/office/haken/"
    return "https://www.staffservice.co.jp/office/jimu/haken/"


# ── パソナJOBサーチ 都道府県別URLコンフィグ ──────────────────────────
# place_wide_cd: パソナ独自エリアコード（JIS都道府県コードとは異なる）
# place_pref_cd: パソナ独自都道府県コード（blist/arXX の番号と対応）
PASONA_PREF_CONFIG = {
    "北海道":   {"wide_cd": 1001, "pref_cd": "01"},
    "宮城県":   {"wide_cd": 1001, "pref_cd": "04"},
    "東京都":   {"wide_cd": 1003, "pref_cd": "14"},
    "埼玉県":   {"wide_cd": 1003, "pref_cd": "17"},
    "千葉県":   {"wide_cd": 1003, "pref_cd": "16"},
    "神奈川県": {"wide_cd": 1003, "pref_cd": "15"},
    "愛知県":   {"wide_cd": 1005, "pref_cd": "21"},
    "大阪府":   {"wide_cd": 1006, "pref_cd": "25"},
    "広島県":   {"wide_cd": 1007, "pref_cd": "31"},
    "福岡県":   {"wide_cd": 1009, "pref_cd": "40"},
}
# 広域エリア → 代表都道府県（パソナ未対応エリアはここで補完）
PASONA_BROAD_PREF = {
    "北海道": "北海道",
    "東北":   "宮城県",
    "関東":   "東京都",
    "東海":   "愛知県",
    "近畿":   "大阪府",
    "中国":   "広島県",
    "九州・沖縄": "福岡県",
}
# 事務・オフィスワーク全般の job_group_cd リスト（ユーザー確認済み）
PASONA_JOB_GROUP_CDS = [133, 134, 135, 103, 104, 105, 106, 107, 115, 119, 121]


# ═══════════════════════════════════════════════════════════════════
#  共通ヘルパー：ページテキストから件数・時給・在宅率を抽出
# ═══════════════════════════════════════════════════════════════════
async def extract_metrics(page) -> dict:
    """ページの body テキストから件数・時給・在宅率を抽出"""
    text = await page.inner_text("body")
    count, avg_wage, remote_ratio = None, None, None

    # 件数：最初に出現する合理的な "N件"（求人数の現実的な上限80,000以内）
    # max()ではなく先頭の合理的な数字を使う（「200,000人登録」等を除外）
    count_matches = re.findall(r"([\d,]+)\s*件", text)
    if count_matches:
        nums = [int(m.replace(",", "")) for m in count_matches]
        reasonable = [n for n in nums if 100 <= n <= 80000]
        if reasonable:
            count = reasonable[0]   # 最初に出現する合理的な件数
        else:
            big = [n for n in nums if n >= 50]
            count = big[0] if big else (nums[0] if nums else None)

    # 時給：複数パターン対応
    wages = []
    # パターン1: 「時給 X,XXX円」「時給：X,XXX円」「【時給】X,XXX円」etc.
    for m in re.finditer(r"時給[：:】\s]*([\d,]+)円", text):
        w = int(m.group(1).replace(",", ""))
        if 900 <= w <= 5000:
            wages.append(w)
    # パターン2: 「X,XXX円/時」「X,XXX円／時」（r-staffingなど）
    if not wages:
        for m in re.finditer(r"([\d,]+)円[/／]時", text):
            w = int(m.group(1).replace(",", ""))
            if 900 <= w <= 5000:
                wages.append(w)
    # パターン3: 「¥X,XXX」「￥X,XXX」
    if not wages:
        for m in re.finditer(r"[¥￥]([\d,]+)", text):
            w = int(m.group(1).replace(",", ""))
            if 900 <= w <= 5000:
                wages.append(w)
    if wages:
        avg_wage = _median_wage(wages[:40])

    # 在宅率：求人カード固有キーワードで計算
    # 「在宅可」「テレワーク可」はナビ/フッターに出ない求人特有表記 → 精度高
    specific = len(re.findall(
        r"在宅可|在宅OK|在宅勤務可|テレワーク可|テレワークOK|リモート可|リモートOK|フルリモート|フル在宅", text))
    if specific > 0:
        remote_ratio = round(min(specific / 20 * 100, 100), 1)
    else:
        # セミ特定キーワード（「在宅勤務」「テレワーク」の複合形）
        semi = len(re.findall(r"在宅勤務|テレワーク|リモートワーク", text))
        if semi > 0:
            # サイト全体のメニュー等も含まれるため25%キャップ
            remote_ratio = round(min(semi / 20 * 100, 25.0), 1)

    return {"count": count, "avg_wage": avg_wage, "remote_ratio": remote_ratio}


# ═══════════════════════════════════════════════════════════════════
#  複数ページ時給収集ヘルパー
# ═══════════════════════════════════════════════════════════════════
def _extract_wages_from_text(text: str) -> list:
    """テキストから時給リストを抽出（900〜5000円フィルタ付き）"""
    wages = []
    # パターン1: 「時給 X,XXX円」「時給：X,XXX円」「【時給】X,XXX円」
    for m in re.finditer(r"時給[：:】\s]*([\d,]+)円", text):
        w = int(m.group(1).replace(",", ""))
        if 900 <= w <= 5000:
            wages.append(w)
    # パターン2: 「X,XXX円/時」「X,XXX円／時」（r-staffingなど）
    if not wages:
        for m in re.finditer(r"([\d,]+)円[/／]時", text):
            w = int(m.group(1).replace(",", ""))
            if 900 <= w <= 5000:
                wages.append(w)
    # パターン3: 「¥X,XXX」「￥X,XXX」
    if not wages:
        for m in re.finditer(r"[¥￥]([\d,]+)", text):
            w = int(m.group(1).replace(",", ""))
            if 900 <= w <= 5000:
                wages.append(w)
    return wages


async def _click_next_page(page) -> bool:
    """「次のページ」「次へ」ボタンをクリック。URLが変わればTrue（ページ遷移成功）"""
    prev_url = page.url
    clicked = await page.evaluate("""
        (() => {
            const TEXTS = ['次のページ', '次へ', '次ページ', '次の20件', '次の30件', '次の50件'];
            const all = [...document.querySelectorAll('a, button, [role="button"]')];
            for (const txt of TEXTS) {
                const el = all.find(e => {
                    const t = (e.textContent || '').trim();
                    return t === txt || t.startsWith(txt);
                });
                if (el && !el.getAttribute('disabled') &&
                    !(el.className || '').includes('disabled') &&
                    !(el.className || '').includes('is-disabled') &&
                    !(el.className || '').includes('inactive')) {
                    el.click();
                    return 'clicked:' + (el.textContent || '').trim().slice(0, 20);
                }
            }
            // rel="next" 属性
            const relNext = document.querySelector('a[rel="next"]');
            if (relNext) { relNext.click(); return 'clicked_rel_next'; }
            // aria-label に「次」を含む要素
            const ariaNext = document.querySelector('[aria-label*="次"]');
            if (ariaNext && !ariaNext.getAttribute('disabled')) {
                ariaNext.click(); return 'clicked_aria';
            }
            return 'not_found';
        })()
    """)
    if clicked == 'not_found':
        return False
    await asyncio.sleep(3)
    return page.url != prev_url  # URLが変わった場合のみ成功とみなす


# ═══════════════════════════════════════════════════════════════════
#  テンプスタッフ（ジョブチェキ）— クリック操作
# ═══════════════════════════════════════════════════════════════════
async def scrape_tempstaff(page, region: str) -> dict:
    result = base_result("tempstaff", "テンプスタッフ", region)
    try:
        await page.goto("https://www.tempstaff.co.jp/jbch/top",
                        timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        area_target = _get_tempstaff_area(region)  # 例: "関東"
        area_lc_value = None  # select#areaLCd の value（例: "23" = 関東）

        # ① エリア選択（select#areaLCd）- Playwright native で React/Vue イベント対応
        if area_target:
            try:
                # Playwright native select_option → React/Vue の onChange を正しく発火
                await page.locator('select#areaLCd').select_option(label=area_target)
                area_lc_value = await page.locator('select#areaLCd').input_value()
                print(f"    テンプスタッフ エリア設定(PW): {area_lc_value}:{area_target}")
                await asyncio.sleep(2)
            except Exception as _se:
                # JS フォールバック
                area_set = await page.evaluate(f"""
                    (() => {{
                        const sel = document.querySelector('select#areaLCd');
                        if (sel) {{
                            const opt = [...sel.options].find(o => o.text.trim().includes('{area_target}'));
                            if (opt) {{
                                sel.value = opt.value;
                                sel.dispatchEvent(new Event('change', {{bubbles:true}}));
                                sel.dispatchEvent(new Event('input', {{bubbles:true}}));
                                return 'set:' + opt.value + ':' + opt.text.trim();
                            }}
                        }}
                        return 'not_found';
                    }})()
                """)
                print(f"    テンプスタッフ エリア設定(JS): {area_set}")
                if area_set.startswith('set:'):
                    parts = area_set.split(':')
                    if len(parts) >= 2 and parts[1].isdigit():
                        area_lc_value = parts[1]
                await asyncio.sleep(2)

        # ② トップページの検索ボタンをクリック（エリア=関東設定済み, 職種=全部）→ 関東全件一覧へ
        top_search_result = await page.evaluate("""
            (() => {
                // 1) button要素で「検索」テキスト（子要素あっても可）
                const btns = [...document.querySelectorAll('button')];
                const btn = btns.find(b => (b.textContent||'').trim().includes('検索'));
                if (btn) { btn.click(); return 'clicked_button:' + (btn.className||'').slice(0,30); }

                // 2) input[type=submit/button] で value=検索
                const subm = [...document.querySelectorAll('input[type="submit"],input[type="button"]')];
                const inp = subm.find(b => (b.value||'').trim().includes('検索'));
                if (inp) { inp.click(); return 'clicked_input:' + (inp.value||'').slice(0,20); }

                // 3) a要素で「検索」テキスト
                const anchors = [...document.querySelectorAll('a')];
                const a = anchors.find(el => el.textContent.trim() === '検索');
                if (a) { a.click(); return 'clicked_a:' + a.href.slice(-50); }

                // 4) リーフノードで「検索」または「search」
                const all = [...document.querySelectorAll('*')];
                const leaf = all.find(b => {
                    const t = (b.textContent || '').trim();
                    return (t === 'search' || t === '検索') && !b.querySelector('*');
                });
                if (leaf) { leaf.click(); return 'clicked_leaf:' + leaf.tagName + '.' + (leaf.className||'').slice(0,30); }

                // デバッグ：要素列挙
                const dbgBtns = btns.slice(0,5).map(b => (b.textContent||'').trim().slice(0,12) + '[' + (b.className||'').slice(0,12) + ']').join(';');
                const dbgA = anchors.filter(el => el.textContent.trim().length < 10).slice(0,5).map(el => el.textContent.trim() + ':' + el.href.slice(-30)).join(';');
                return 'not_found|btns:' + dbgBtns + '|a:' + dbgA;
            })()
        """)
        print(f"    テンプスタッフ トップ検索ボタン: {top_search_result}")
        await asyncio.sleep(5)
        print(f"    テンプスタッフ 検索後URL: {page.url[:80]}")

        # ③ 新アプローチ: 全国ページ → 都道府県クリック → 事務カテゴリークリック
        jimu_clicked = False
        on_result_page = "jobList" in page.url or "search/result" in page.url

        if on_result_page:
            # エリア代表都道府県マップ（関東 → 東京都）
            area_pref_map = {
                "関東":"東京都","近畿":"大阪府","東海":"愛知県",
                "東北":"宮城県","北海道":"北海道","九州・沖縄":"福岡県",
                "中国":"広島県","四国":"愛媛県","北信越":"新潟県",
            }
            # 都道府県が直接指定された場合はそのまま使用（例: 神奈川県 → 神奈川県）
            # 広域エリア（関東など）の場合のみ代表都道府県に変換
            if region in PREFECTURE_CITIES:
                target_pref = region
            else:
                target_pref = area_pref_map.get(area_target, area_target)

            # ③-1: 全国ページから都道府県リンクを探してクリック
            pref_link = await page.evaluate(f"""
                (() => {{
                    const all = [...document.querySelectorAll('a')];
                    const p = all.find(a => a.textContent.trim() === '{target_pref}');
                    if (p && p.href) return 'found:' + p.href;
                    const prefs = all.filter(a => {{
                        const t = a.textContent.trim();
                        return (t.endsWith('都') || t.endsWith('道') || t.endsWith('府') || t.endsWith('県'))
                               && t.length <= 5;
                    }});
                    return 'not_found|' + prefs.slice(0,6).map(a => a.textContent.trim() + ':' + a.href).join(';');
                }})()
            """)
            print(f"    テンプスタッフ 都道府県リンク({target_pref}): {pref_link[:150]}")

            if pref_link.startswith('found:'):
                pref_href = pref_link[6:]
                # ③-2: pref_href から エリア×事務 URL を直接構築する
                # pref_href 例: "https://www.tempstaff.co.jp/jbch/jobList/tokyo/sk-01"
                # 目標:         "https://www.tempstaff.co.jp/jbch/jobList/tokyo/sd-51/sk-01"
                if "/sk-01" in pref_href:
                    jimu_combined_url = pref_href.replace("/sk-01", "/sd-51/sk-01")
                else:
                    jimu_combined_url = pref_href.rstrip("/") + "/sd-51/sk-01"
                print(f"    テンプスタッフ エリア×事務URL構築: {jimu_combined_url}")
                await page.goto(jimu_combined_url, timeout=30000, wait_until="domcontentloaded")
                await asyncio.sleep(4)
                jimu_clicked = True
                print(f"    テンプスタッフ {target_pref}×事務URL: {page.url[:80]}")
                on_result_page = "jobList" in page.url or "search/result" in page.url
            else:
                # 都道府県リンクが見つからなければ従来の事務フィルターアプローチ
                jimu_filter = await page.evaluate("""
                    (() => {
                        const links = [...document.querySelectorAll('a[href*="jobList"]')];
                        const jimu = links.find(a => {
                            const t = a.textContent.trim();
                            return t === '事務' || t.startsWith('事務すべて') || t.startsWith('事務（');
                        });
                        if (jimu) return 'found:' + jimu.href;
                        return 'not_found';
                    })()
                """)
                if jimu_filter.startswith('found:'):
                    await page.goto(jimu_filter[6:], timeout=30000, wait_until="domcontentloaded")
                    await asyncio.sleep(4)
                jimu_clicked = True
                on_result_page = "jobList" in page.url or "search/result" in page.url

        # ④ フォールバック：selectSyokusyu モーダルフロー
        if not on_result_page:
            print("    テンプスタッフ: モーダルフローにフォールバック")
            # トップページから再試行
            if "top" not in page.url and "jbch" not in page.url:
                await page.goto("https://www.tempstaff.co.jp/jbch/top",
                                timeout=30000, wait_until="domcontentloaded")
                await asyncio.sleep(2)
            await page.wait_for_selector("a.modal_job-type", timeout=10000)
            await page.click("a.modal_job-type", timeout=10000)
            await asyncio.sleep(3)
            print(f"    テンプスタッフ: 職種選択ページ → {page.url[:80]}")

            # 事務カテゴリを探してクリック
            for candidate in ["事務すべて", "事務・オフィス系すべて", "事務系すべて", "事務系"]:
                clicked = await page.evaluate(f"""
                    (() => {{
                        const all = [...document.querySelectorAll('li, a, button, [onclick]')];
                        const el = all.find(e => e.textContent.trim().startsWith('{candidate}'));
                        if (el) {{
                            el.click();
                            return el.tagName + ':' + el.textContent.trim().slice(0, 25);
                        }}
                        return 'not_found';
                    }})()
                """)
                print(f"    テンプスタッフ '{candidate}': {clicked}")
                if clicked != 'not_found':
                    jimu_clicked = True
                    await asyncio.sleep(3)
                    break

            # selectSyokusyu → 検索ボタン（SPAN.material-icons[text=search]）
            cur = page.url
            if "selectSyokusyu" in cur or "Syokusyu" in cur:
                sr = await page.evaluate("""
                    (() => {
                        const all = [...document.querySelectorAll('*')];
                        const leaf = all.find(b => {
                            const t = (b.textContent || '').trim();
                            return (t === '検索' || t === 'search') && !b.querySelector('*');
                        });
                        if (leaf) { leaf.click(); return 'clicked:' + leaf.tagName + '.' + (leaf.className||'').slice(0,20); }
                        return 'not_found';
                    })()
                """)
                print(f"    テンプスタッフ 検索ボタン: {sr}")
                await asyncio.sleep(5)
                print(f"    テンプスタッフ: クリック後URL → {page.url[:80]}")
                on_result_page = "jobList" in page.url or "search/result" in page.url
            else:
                on_result_page = "jobList" in page.url or "search/result" in page.url

        result["url"] = page.url
        current_url = page.url
        print(f"    テンプスタッフ 結果URL: {current_url}")
        # jobList も有効な結果URL（selectSyokusyu の検索で遷移する先）
        on_result_page = "search/result" in current_url or "jobList" in current_url
        if not on_result_page:
            print(f"    テンプスタッフ: 結果ページ未到達 (URL={current_url[:70]})")

        # ⑤ 件数取得（p.total_number セレクター → なければ extract_metrics で拾う）
        count_el = await page.query_selector("p.total_number")
        if count_el:
            text = await count_el.inner_text()
            m = re.search(r"([\d,]+)", text)
            if m:
                result["count"] = int(m.group(1).replace(",", ""))

        # ⑥ 件数・在宅率（ページ1から取得）
        metrics = await extract_metrics(page)
        if result["count"] is None:
            result["count"] = metrics["count"]
        result["remote_ratio"] = metrics["remote_ratio"]

        # 在宅率: 結果ページ到達済みで件数あり・キーワードなし → 0.0%
        if result["remote_ratio"] is None and result["count"] and on_result_page:
            result["remote_ratio"] = 0.0

        # ⑦ 時給: URLベースのページネーションで複数ページ（最大5ページ）から収集して平均
        # テンプスタッフは「もっと見る」ボタンでURL末尾に /2 /3 ... を付加する形式
        all_wages = []
        base_list_url = page.url.split("#")[0].rstrip("/")  # ハッシュを除去
        for page_no in range(1, 6):
            page_text = await page.inner_text("body")
            wages = _extract_wages_from_text(page_text)
            all_wages.extend(wages)
            print(f"    テンプスタッフ p{page_no}: 時給{len(wages)}件 (累計{len(all_wages)}件)")
            if page_no >= 5:
                break
            # 次ページURL: 末尾に /{page_no+1} を付加（例: /tokyo/sd-51/sk-01/2）
            next_url = f"{base_list_url}/{page_no + 1}"
            try:
                await page.goto(next_url, timeout=20000, wait_until="domcontentloaded")
                await asyncio.sleep(3)
                # 有効なページか確認（時給データが0件なら終了）
                check_text = await page.inner_text("body")
                check_wages = _extract_wages_from_text(check_text)
                if not check_wages:
                    print(f"    テンプスタッフ: p{page_no+1}で時給データなし → 終了")
                    break
            except Exception as _pe:
                print(f"    テンプスタッフ: p{page_no+1}へのURL遷移失敗 → 終了 ({_pe})")
                break
        if all_wages:
            result["avg_wage"] = _median_wage(all_wages)
        elif metrics["avg_wage"]:
            result["avg_wage"] = metrics["avg_wage"]  # フォールバック

        # 結果ページのデバッグ（別ファイルに保存して selectSyokusyu デバッグを上書きしない）
        _debug_result_path = Path(__file__).parent / "debug_tempstaff_result.txt"
        _result_body = await page.inner_text("body")
        with open(_debug_result_path, "w", encoding="utf-8") as _f:
            _f.write(f"URL: {page.url}\n")
            _f.write(f"Count: {result['count']}, AreaTarget: {area_target}, JimuClicked: {jimu_clicked}\n")
            _f.write(f"AvgWage: {result['avg_wage']} ({len(all_wages)}件から計算)\n\n")
            _f.write(_result_body[:3000])

    except Exception as e:
        result["error"] = str(e)[:120]
        print(f"    テンプスタッフ エラー: {e}")
    return result

def _get_tempstaff_area(region: str) -> str:
    """テンプスタッフジョブチェキで選択するエリア名を返す"""
    broad_map = {
        "北海道":"北海道","東北":"東北","北信越":"北陸・甲信越",
        "関東":"関東","東海":"東海","近畿":"近畿",
        "中国":"中国","四国":"四国","九州・沖縄":"九州・沖縄",
    }
    if region in broad_map:
        return broad_map[region]
    # 都道府県：広域名を返す
    for broad, prefs in BROAD_REGIONS.items():
        if region in prefs:
            return broad_map.get(broad, broad)
    # 市区町村：親都道府県の広域名
    for pref, pd in PREFECTURE_CITIES.items():
        if region in pd["cities"]:
            for broad, prefs in BROAD_REGIONS.items():
                if pref in prefs:
                    return broad_map.get(broad, broad)
    return ""


# ═══════════════════════════════════════════════════════════════════
#  リクルートスタッフィング
# ═══════════════════════════════════════════════════════════════════
# sd02 直接アクセス用 kinmuArea コード（ユーザー実測確認済み）
# kinmuArea=CF000 : 東京都すべて
# kinmuArea=C0000 : 関東（東京都+周辺）
# solDutyCd=A00   : オフィスワーク・事務すべて
RECRUIT_KINMU_AREA = {
    # 関東
    "関東":     "C0000",
    "東京都":   "CF000",
    "神奈川県": "CG000",
    "埼玉県":   "CD000",
    "千葉県":   "CE000",
    # 近畿
    "大阪府":   "EC000",
    # 東海
    "愛知県":   "DC000",
    # 中国
    "広島県":   "FD000",
    # 九州
    "福岡県":   "HA000",
    # 東北
    "宮城県":   "BC000",
    # 北海道
    "北海道":   "A0000",
}

async def scrape_recruit(page, region: str) -> dict:
    result = base_result("recruit_staffing", "リクルートスタッフィング", region)
    try:
        pref_id = _get_pref_id(region)
        kinmu_code = RECRUIT_KINMU_AREA.get(region)

        if kinmu_code:
            # ── sd02 直接アクセス（東京都など確認済みエリア）──────────────
            url = (f"https://www.r-staffing.co.jp/sol/op21/sd02/"
                   f"?kinmuArea={kinmu_code}&solDutyCd=A00&sort=1&pageNo=1&hyouziSuu=20&")
            result["url"] = url
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            await asyncio.sleep(4)
            print(f"    リクルート 直接URL ({kinmu_code}): {page.url[:80]}")

        else:
            # ── sd01 フォームアプローチ（kinmuArea未確認エリア）────────────
            if pref_id:
                url = f"https://www.r-staffing.co.jp/sol/op21/sd01/?prf={pref_id:02d}&job=1"
            else:
                broad_prf = {
                    "近畿":"27","東海":"23","九州・沖縄":"40",
                    "東北":"04","北海道":"01","中国":"34","四国":"38","北信越":"15",
                }
                prf = broad_prf.get(region, "")
                url = f"https://www.r-staffing.co.jp/sol/op21/sd01/?prf={prf}&job=1" if prf else \
                      "https://www.r-staffing.co.jp/sol/op21/sd01/?job=1"

            result["url"] = url
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            await asyncio.sleep(2)

            # 「検索する」ボタンをクリック
            for sel in ["button:has-text('検索する')", "input[value='検索する']",
                        "button:has-text('検索')", "a:has-text('検索する')"]:
                try:
                    await page.click(sel, timeout=4000)
                    break
                except Exception:
                    pass
            await asyncio.sleep(6)

        result["url"] = page.url

        # 件数: ページ1から取得
        result_text = await page.inner_text("body")
        count_m = re.search(r"([\d,]+)\s*件中", result_text)
        if not count_m:
            count_m = re.search(r"条件にあったお仕事\s*([\d,]+)件", result_text)
        if not count_m:
            count_m = re.search(r"([\d,]+)\s*件", result_text)
        if count_m:
            n = int(count_m.group(1).replace(",", ""))
            if 1 <= n <= 80000:
                result["count"] = n

        # 時給: URLのpageNoをループして複数ページから収集（最大5ページ）
        base_url = page.url
        all_wages = []
        for page_no in range(1, 6):
            if page_no == 1:
                page_text = result_text  # ページ1はすでに取得済み
            else:
                loop_url = re.sub(r'pageNo=\d+', f'pageNo={page_no}', base_url)
                if loop_url == base_url and "pageNo=" not in base_url:
                    # URLにpageNoパラメータがない場合はクリックで次ページへ
                    moved = await _click_next_page(page)
                    if not moved:
                        print(f"    リクルート: p{page_no}で次ページなし → 終了")
                        break
                    await asyncio.sleep(3)
                    page_text = await page.inner_text("body")
                else:
                    await page.goto(loop_url, timeout=20000, wait_until="domcontentloaded")
                    await asyncio.sleep(3)
                    page_text = await page.inner_text("body")

            wages = _extract_wages_from_text(page_text)
            # リクルートは「X,XXX円/時」形式が多いので先にチェック
            if not wages:
                for m in re.finditer(r"([\d,]+)円[/／]時", page_text):
                    w = int(m.group(1).replace(",", ""))
                    if 900 <= w <= 5000:
                        wages.append(w)
            all_wages.extend(wages)
            print(f"    リクルート p{page_no}: 時給{len(wages)}件 (累計{len(all_wages)}件)")
            if not wages:
                print(f"    リクルート: p{page_no}で時給データなし → 終了")
                break

        if all_wages:
            result["avg_wage"] = _median_wage(all_wages)

        # デバッグ保存
        wage_lines = [l.strip() for l in result_text.split("\n")
                      if any(k in l for k in ["時給", "円/時", "¥"]) and l.strip()]
        if wage_lines:
            print(f"    リクルート 時給サンプル: {wage_lines[:3]}")
        _debug_path = Path(__file__).parent / "debug_recruit.txt"
        with open(_debug_path, "w", encoding="utf-8") as _f:
            _f.write(f"URL: {base_url}\n")
            _f.write(f"AvgWage: {result['avg_wage']} ({len(all_wages)}件から計算)\n\n")
            _f.write(result_text[:5000])
        return result

    except Exception as e:
        result["error"] = str(e)[:120]
        print(f"    リクルートスタッフィング エラー: {e}")
    return result


# ═══════════════════════════════════════════════════════════════════
#  スタッフサービス（クリーンURL構造）
# ═══════════════════════════════════════════════════════════════════
async def scrape_staffservice(page, region: str) -> dict:
    result = base_result("staff_service", "スタッフサービス", region)
    try:
        url = get_staffservice_url(region)
        result["url"] = url
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # スタッフサービス独自の件数セレクターを試す
        count = None
        for sel in ["[class*='total']", "[class*='count']", "strong", ".result-count"]:
            try:
                els = await page.query_selector_all(sel)
                for el in els[:5]:
                    text = await el.inner_text()
                    m = re.search(r"([\d,]+)\s*件", text)
                    if m:
                        n = int(m.group(1).replace(",", ""))
                        if n > 50:
                            count = n
                            break
                if count:
                    break
            except Exception:
                pass

        # 件数・在宅率はページ1から取得
        metrics = await extract_metrics(page)
        result["count"]        = count or metrics["count"]
        result["remote_ratio"] = metrics["remote_ratio"]

        # 時給: 複数ページ（最大5ページ）から収集して平均
        all_wages = []
        for page_no in range(1, 6):
            page_text = await page.inner_text("body")
            wages = _extract_wages_from_text(page_text)
            all_wages.extend(wages)
            print(f"    スタッフサービス p{page_no}: 時給{len(wages)}件 (累計{len(all_wages)}件)")
            if page_no < 5:
                moved = await _click_next_page(page)
                if not moved:
                    print(f"    スタッフサービス: p{page_no}で次ページなし → 終了")
                    break
                await asyncio.sleep(3)
        if all_wages:
            result["avg_wage"] = _median_wage(all_wages)
        elif metrics["avg_wage"]:
            result["avg_wage"] = metrics["avg_wage"]  # フォールバック

        # デバッグ：時給確認用
        _ss_text = await page.inner_text("body")
        wage_lines = [l.strip() for l in _ss_text.split("\n")
                      if any(k in l for k in ["時給", "円/時", "給与", "¥"]) and l.strip()]
        print(f"    スタッフサービス 時給サンプル: {wage_lines[:5]}")
        _ss_debug = Path(__file__).parent / "debug_staffservice.txt"
        with open(_ss_debug, "w", encoding="utf-8") as _f:
            _f.write(f"URL: {page.url}\n")
            _f.write(f"Count: {result['count']}, AvgWage: {result['avg_wage']} ({len(all_wages)}件から計算)\n\n")
            _f.write(_ss_text[:5000])

    except Exception as e:
        result["error"] = str(e)[:120]
        print(f"    スタッフサービス エラー: {e}")
    return result


# ═══════════════════════════════════════════════════════════════════
#  アデコ
# ═══════════════════════════════════════════════════════════════════
async def scrape_adecco(page, region: str) -> dict:
    """
    アデコ: PO_JobListA への直接URLアクセスで都道府県＋職種フィルター
    URL: https://www.adecco.com/ja-jp/job/PO_JobListA?prefecture_city={pref}&occupation={occ}
    """
    result = base_result("adecco", "アデコ", region)
    try:
        # 広域エリア → 代表都道府県マッピング
        area_pref_map = {
            "関東": "東京都", "近畿": "大阪府", "東海": "愛知県",
            "東北": "宮城県", "北海道": "北海道", "九州・沖縄": "福岡県",
            "中国": "広島県", "四国": "愛媛県", "北信越": "新潟県",
        }
        target_pref = area_pref_map.get(region, region)

        # 直接URLアクセス（prefecture_city と occupation パラメータで絞り込み）
        occupation = quote("オフィスワーク・事務系")
        pref_encoded = quote(target_pref)
        url = (f"https://www.adecco.com/ja-jp/job/PO_JobListA"
               f"?prefecture_city={pref_encoded}&occupation={occupation}")
        result["url"] = url

        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(4)
        # URLは長いので prefecture_city と occupation のみ表示
        import urllib.parse as _up
        _qs = _up.parse_qs(_up.urlparse(page.url).query)
        _pref = _qs.get('prefecture_city', ['?'])[0]
        _occ  = _qs.get('occupation',      ['?'])[0]
        print(f"    アデコ URL: prefecture_city={_pref} / occupation={_occ}")

        # 件数・在宅率取得
        metrics = await extract_metrics(page)
        result["count"]        = metrics["count"]
        result["remote_ratio"] = metrics["remote_ratio"]

        # 時給: 複数ページ（最大5ページ）から収集して平均
        all_wages = []
        for page_no in range(1, 6):
            page_text = await page.inner_text("body")
            wages = _extract_wages_from_text(page_text)
            all_wages.extend(wages)
            print(f"    アデコ p{page_no}: 時給{len(wages)}件 (累計{len(all_wages)}件)")
            if page_no < 5:
                moved = await _click_next_page(page)
                if not moved:
                    print(f"    アデコ: p{page_no}で次ページなし → 終了")
                    break
                await asyncio.sleep(3)
        if all_wages:
            result["avg_wage"] = _median_wage(all_wages)
        elif metrics["avg_wage"]:
            result["avg_wage"] = metrics["avg_wage"]  # フォールバック

        # デバッグ保存
        _adecco_text = await page.inner_text("body")
        _adecco_debug = Path(__file__).parent / "debug_adecco.txt"
        with open(_adecco_debug, "w", encoding="utf-8") as _f:
            _f.write(f"URL: {page.url}\n")
            _f.write(f"Count: {result['count']}, AvgWage: {result['avg_wage']} ({len(all_wages)}件から計算)\n\n")
            _f.write(_adecco_text[:5000])

    except Exception as e:
        result["error"] = str(e)[:120]
        print(f"    アデコ エラー: {e}")
    return result


# ═══════════════════════════════════════════════════════════════════
#  マンパワーグループ（manpowerjobnet.com）— 直接URLアクセス
# ═══════════════════════════════════════════════════════════════════
# ユーザー確認済みURL例:
# https://www.manpowerjobnet.com/search/result/list/?JobCtgryClassCdList=201&PrfctrCdList=13
# JobCtgryClassCdList=201 : オフィス・事務
# PrfctrCdList=13        : 東京都（JIS都道府県コードをそのまま使用）
MANPOWER_JOB_CLASS = "201"  # オフィス・事務

# 広域エリア → 代表都道府県コード（JIS）
MANPOWER_BROAD_PREF = {
    "北海道": 1, "東北": 4, "北信越": 15, "関東": 13,
    "東海": 23, "近畿": 27, "中国": 34, "四国": 38, "九州・沖縄": 40,
}

async def scrape_manpower(page, region: str) -> dict:
    """
    マンパワーグループ: 直接URLアクセス方式
    URL例: /search/result/list/?JobCtgryClassCdList=201&PrfctrCdList=13
    JobCtgryClassCdList=201 = オフィス・事務（ユーザー確認済み）
    PrfctrCdList = JIS都道府県コード（例: 東京都=13, 大阪府=27）
    """
    result = base_result("manpower", "マンパワーグループ", region)
    try:
        # 都道府県コード取得
        pref_id = _get_pref_id(region)
        if not pref_id:
            # 広域エリア → 代表都道府県コードに変換
            pref_id = MANPOWER_BROAD_PREF.get(region)
            if not pref_id:
                # 市区町村 → 親都道府県
                for pn, pd in PREFECTURE_CITIES.items():
                    if region in pd["cities"]:
                        pref_id = pd["pref_id"]
                        break
            pref_id = pref_id or 13  # デフォルト: 東京都

        url = (f"https://www.manpowerjobnet.com/search/result/list/"
               f"?JobCtgryClassCdList={MANPOWER_JOB_CLASS}&PrfctrCdList={pref_id:02d}")
        result["url"] = url
        print(f"    マンパワー URL: {url}")

        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(4)
        print(f"    マンパワー 結果URL: {page.url[:100]}")

        text = await page.inner_text("body")

        # 件数: 「1～30件/2234件中」→「件中」の数字が総件数（ページ1から取得）
        total_m = re.search(r"([\d,]+)\s*件中", text)
        if total_m:
            result["count"] = int(total_m.group(1).replace(",", ""))
        else:
            count_m = re.findall(r"([\d,]+)\s*件", text)
            if count_m:
                nums = [int(m.replace(",", "")) for m in count_m]
                reasonable = [n for n in nums if 1 <= n <= 80000]
                result["count"] = reasonable[0] if reasonable else None

        # 時給: 複数ページから収集（URL の p=N パラメータ または クリック）
        base_url = page.url
        all_wages = []
        for page_no in range(1, 6):
            page_text = await page.inner_text("body") if page_no > 1 else text
            wages = _extract_wages_from_text(page_text)
            all_wages.extend(wages)
            print(f"    マンパワー p{page_no}: 時給{len(wages)}件 (累計{len(all_wages)}件)")
            if page_no < 5:
                # URLベース: &p=N を試みる
                next_url = re.sub(r'([?&])p=\d+', f'\\1p={page_no + 1}', base_url)
                if next_url == base_url:
                    # p= パラメータがなければ追加してみる
                    sep = "&" if "?" in base_url else "?"
                    next_url = base_url + f"{sep}p={page_no + 1}"
                await page.goto(next_url, timeout=20000, wait_until="domcontentloaded")
                await asyncio.sleep(3)
                # ページが実際に変わったか確認（時給データの有無で判断）
                check_text = await page.inner_text("body")
                check_wages = _extract_wages_from_text(check_text)
                if not check_wages:
                    # URLベースが失敗 → クリックを試みる（前のページに戻って）
                    await page.goto(base_url if page_no == 1 else page.url,
                                    timeout=20000, wait_until="domcontentloaded")
                    await asyncio.sleep(2)
                    moved = await _click_next_page(page)
                    if not moved:
                        print(f"    マンパワー: p{page_no}で次ページなし → 終了")
                        break
                    await asyncio.sleep(3)
        if all_wages:
            result["avg_wage"] = _median_wage(all_wages)

        # デバッグ保存
        _mp_debug = Path(__file__).parent / "debug_manpower_result.txt"
        with open(_mp_debug, "w", encoding="utf-8") as _f:
            _f.write(f"URL: {base_url}\n")
            _f.write(f"AvgWage: {result['avg_wage']} ({len(all_wages)}件から計算)\n\n")
            _f.write(text[:4000])

    except Exception as e:
        result["error"] = str(e)[:120]
        print(f"    マンパワーグループ エラー: {e}")
    return result


# ═══════════════════════════════════════════════════════════════════
#  パソナJOBサーチ — 直接URLアクセス方式
# ═══════════════════════════════════════════════════════════════════
async def scrape_pasona(page, region: str) -> dict:
    """
    パソナJOBサーチ: 直接URLアクセスで事務・オフィスワーク全般の件数・時給を取得
    URL例: https://www.pasona.co.jp/jobsearch/1003/result?place_wide_cd=1003&job_group_cd=133&...&place_pref_cd=14&keywords=
    """
    result = base_result("pasona", "パソナ", region)
    try:
        # 都道府県コンフィグを取得（広域エリア・市区町村にも対応）
        pref_name = region
        if pref_name not in PASONA_PREF_CONFIG:
            # 広域エリア → 代表都道府県
            pref_name = PASONA_BROAD_PREF.get(region)
            if not pref_name:
                # 市区町村 → 親都道府県
                for pn, pd in PREFECTURE_CITIES.items():
                    if region in pd["cities"]:
                        pref_name = pn
                        break
            if not pref_name or pref_name not in PASONA_PREF_CONFIG:
                result["error"] = f"パソナ: 未対応エリア {region}"
                return result

        cfg = PASONA_PREF_CONFIG[pref_name]
        wide_cd = cfg["wide_cd"]
        pref_cd = cfg["pref_cd"]

        # 職種コードのクエリ文字列を構築
        jg_params = "&".join(f"job_group_cd={cd}" for cd in PASONA_JOB_GROUP_CDS)
        url = (
            f"https://www.pasona.co.jp/jobsearch/{wide_cd}/result"
            f"?place_wide_cd={wide_cd}&{jg_params}"
            f"&salary_type=hour&income_ll=&income_ul=&dispatch_from__ymd="
            f"&place_pref_cd={pref_cd}&keywords="
        )
        result["url"] = url
        print(f"    パソナ URL: {url}")

        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(4)
        print(f"    パソナ 結果URL: {page.url[:100]}")

        text = await page.inner_text("body")

        # 件数抽出: 「1〜20件 / 4022件中」→「件中」の前の数字
        total_m = re.search(r"([\d,]+)\s*件中", text)
        if total_m:
            result["count"] = int(total_m.group(1).replace(",", ""))
        else:
            count_m = re.findall(r"([\d,]+)\s*件", text)
            if count_m:
                nums = [int(m.replace(",", "")) for m in count_m]
                reasonable = [n for n in nums if 1 <= n <= 80000]
                result["count"] = reasonable[0] if reasonable else None

        # 時給: 複数ページから収集（「次の20件」ボタンでページ送り）
        all_wages = []
        for page_no in range(1, 6):
            page_text = await page.inner_text("body") if page_no > 1 else text
            wages = _extract_wages_from_text(page_text)
            all_wages.extend(wages)
            print(f"    パソナ p{page_no}: 時給{len(wages)}件 (累計{len(all_wages)}件)")
            if page_no < 5:
                moved = await _click_next_page(page)
                if not moved:
                    print(f"    パソナ: p{page_no}で次ページなし → 終了")
                    break
                await asyncio.sleep(3)

        if all_wages:
            result["avg_wage"] = _median_wage(all_wages)

    except Exception as e:
        result["error"] = str(e)[:120]
        print(f"    パソナ エラー: {e}")
    return result


# ═══════════════════════════════════════════════════════════════════
#  ヘルパー関数
# ═══════════════════════════════════════════════════════════════════
def base_result(cid: str, cname: str, region: str) -> dict:
    return {
        "company_id": cid, "company_name": cname, "region": region,
        "url": "", "count": None, "avg_wage": None,
        "remote_ratio": None, "error": None,
    }

def _get_pref_id(region: str):
    if region in PREFECTURE_CITIES:
        return PREFECTURE_CITIES[region]["pref_id"]
    for pn, pd in PREFECTURE_CITIES.items():
        if region in pd["cities"]:
            return pd["pref_id"]
    return None

def _get_pref_romaji(region: str) -> str:
    if region in PREF_ROMAJI:
        return PREF_ROMAJI[region]
    broad_map = {
        "北海道":"hokkaido","東北":"miyagi","北信越":"niigata",
        "関東":"tokyo","東海":"aichi","近畿":"osaka",
        "中国":"hiroshima","四国":"ehime","九州・沖縄":"fukuoka",
    }
    if region in broad_map:
        return broad_map[region]
    for pn, pd in PREFECTURE_CITIES.items():
        if region in pd["cities"]:
            return PREF_ROMAJI.get(pn, "")
    return ""


# ═══════════════════════════════════════════════════════════════════
#  メイン実行
# ═══════════════════════════════════════════════════════════════════
async def run_monitor(region: str):
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("❌ Playwrightがインストールされていません。sh setup_mac.sh を実行してください。")
        sys.exit(1)

    print(f"\n🔍 スクレイピング開始: {region}")
    print(f"   日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("-" * 50)

    scrapers = [
        ("テンプスタッフ",          scrape_tempstaff),
        ("リクルートスタッフィング", scrape_recruit),
        ("スタッフサービス",         scrape_staffservice),
        ("アデコ",                   scrape_adecco),
        ("マンパワーグループ",       scrape_manpower),
        ("パソナ",                   scrape_pasona),
    ]

    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,   # ブラウザを画面表示（ボット検知回避）
            slow_mo=200,      # 操作を少し遅く（人間らしく）
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ]
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            extra_http_headers={
                "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        # ボット検知回避：navigator.webdriverをfalseに
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            window.chrome = {runtime: {}};
        """)

        for name, fn in scrapers:
            print(f"  [{name}] 収集中...")
            page = await context.new_page()
            try:
                r = await fn(page, region)
                results.append(r)
                icon = "✅" if r["count"] or r["avg_wage"] else "⚠️"
                print(f"    {icon} 件数:{r['count']}  時給:{r['avg_wage']}")
                if r["error"]:
                    print(f"       エラー詳細: {r['error'][:100]}")
            finally:
                await page.close()
            await asyncio.sleep(2)

        await browser.close()

    save_results(results, region)
    print_summary(results, region)

    # Excel レポートを自動更新
    try:
        from build_excel import build_report
        print("\n📊 Excelレポートを更新中...")
        build_report(region)
    except Exception as e:
        print(f"⚠️  Excel更新スキップ: {e}")

    # HTML レポートを自動更新
    try:
        from build_html import build_html
        print("🌐 HTMLレポートを更新中...")
        build_html(region)
    except Exception as e:
        print(f"⚠️  HTML更新スキップ: {e}")

    # GitHub Pages へ自動アップロード
    import subprocess
    script_dir = Path(__file__).parent
    # HEAD.lock残留対策: 5分以上前のロックファイルは自動削除
    lock_file = script_dir / ".git" / "HEAD.lock"
    if lock_file.exists():
        import time
        lock_age = time.time() - lock_file.stat().st_mtime
        if lock_age > 300:
            print(f"⚠️  HEAD.lock検出（{int(lock_age)}秒前に作成）→ 削除して続行")
            lock_file.unlink(missing_ok=True)
        else:
            print(f"⚠️  HEAD.lock検出（{int(lock_age)}秒前 ← 5分以内のため保持）")
    try:
        print("☁️  GitHubへアップロード中...")
        subprocess.run(["git", "add", "monitoring_report.html"], cwd=script_dir, check=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        subprocess.run(["git", "commit", "-m", f"update {date_str}"], cwd=script_dir, check=True)
        subprocess.run(["git", "push"], cwd=script_dir, check=True)
        print("✅ GitHubへのアップロード完了！URLが最新版に更新されました。")
    except subprocess.CalledProcessError as e:
        print(f"⚠️  GitHubアップロードスキップ: {e}")


def save_results(results: list, region: str):
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")   # 例: 2026-03-26（日次）
    safe = region.replace("/", "_").replace("・", "_")
    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)
    path = data_dir / f"{date_str}_{safe}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"scraped_at": now.isoformat(), "region": region, "results": results},
                  f, ensure_ascii=False, indent=2)
    print(f"\n✅ 保存完了: data/{path.name}")


def print_summary(results: list, region: str):
    print(f"\n{'='*44}")
    print(f"  {region} — 収集結果")
    print(f"{'='*44}")
    print(f"{'企業':<20} {'案件数':>7} {'平均時給':>9}")
    print("-" * 40)
    for r in results:
        count = str(r["count"])       if r["count"]    is not None else "取得失敗"
        wage  = f"¥{r['avg_wage']:,}" if r["avg_wage"] is not None else "取得失敗"
        print(f"{r['company_name']:<20} {count:>7} {wage:>9}")
    print(f"{'='*44}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: python3 monitor.py <エリア>")
        print("例:     python3 monitor.py 関東")
        sys.exit(0)
    region_arg = sys.argv[1]
    if region_arg not in VALID_REGIONS:
        print(f"❌ '{region_arg}' は対応エリアではありません")
        sys.exit(1)
    asyncio.run(run_monitor(region_arg))
