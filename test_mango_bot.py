import re
import math
import json
import traceback
import html as html_lib
from datetime import datetime

from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

# =========================
# الإعدادات
# =========================
BOT_TOKEN = "8658680521:AAFq4BPpVh0SJeMfr3lBLfO7l7apWLHbIPM"

HEADLESS = True
WAIT_MS = 3000
NAV_TIMEOUT = 60000

MANGO_TR_HOSTS = (
    "https://shop.mango.com/tr/",
    "http://shop.mango.com/tr/",
)

ALLOWED_USERS = {
    127859316,   # Reem
    806135538,   # Dno
    763153242,   # farooha
    781782960,   # Summer
    78539704,    # ZU
    736810149,   # Rose
    7734083418,  # eman
    8126651104,  # Marwan
}

ADMIN_ID = 8126651104
LOG_CHANNEL_ID = -1003737274733
MAX_RETRIES = 2

user_request_counter = {}

# =========================
# أدوات عامة
# =========================
def clean_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def is_supported_mango_tr_url(text: str) -> bool:
    text = (text or "").strip()
    return text.startswith(MANGO_TR_HOSTS) and "shop.mango.com" in text


def extract_ref(url: str):
    m = re.search(r"_(\d{8})", url)
    if m:
        return m.group(1)

    m = re.search(r"(\d{8})", url)
    if m:
        return m.group(1)

    return None


def parse_tl_number(s: str) -> float:
    s = s.replace("TL", "").replace("₺", "").strip()
    s = s.replace(".", "").replace(",", ".")
    return float(s)


def parse_iqd_number(s: str) -> int:
    s = s.replace("IQD", "").replace("د.ع", "").strip()
    s = s.replace(",", "")
    if "." in s:
        s = s.split(".")[0]
    return int(float(s))


def convert_try_to_iqd(price_try: float) -> int:
    return round((price_try / 4300) * 140000)


def round_up_to_500(value: float) -> int:
    return int(math.ceil(value / 500.0) * 500)


def interpolate(x, x1, y1, x2, y2):
    if x2 == x1:
        return y1
    return y1 + ((x - x1) * (y2 - y1) / (x2 - x1))


def progressive_load(diff_iqd: int) -> int:
    if diff_iqd <= 0:
        return 0

    if diff_iqd < 5000:
        return 0
    elif diff_iqd < 7000:
        return 1000
    elif diff_iqd < 9000:
        return 2000
    elif diff_iqd < 11000:
        return 3000
    elif diff_iqd == 11000:
        return 3500
    elif diff_iqd < 15000:
        return 4000
    elif diff_iqd == 15000:
        return 4500
    elif diff_iqd == 16000:
        return 5500
    elif diff_iqd == 17000:
        return 6000
    elif diff_iqd == 18000:
        return 7000
    elif diff_iqd == 19000:
        return 8000
    else:
        return round_up_to_500(diff_iqd * 0.40)

def calculate_system_load(diff_iqd: int, turkey_discount: bool, iraq_discount: bool) -> int:
    if diff_iqd <= 0:
        return 0

    if turkey_discount and not iraq_discount:
        load = round_up_to_500(diff_iqd * 0.30)

        if load > 11000:
            load = 11000

        return load

    return progressive_load(diff_iqd)



def clean_final_price_and_adjust_load(converted_iqd: int, system_load: int):
    final_price = converted_iqd + system_load

    remainder = final_price % 1000

    if remainder <= 500:
        target = (final_price // 1000) * 1000 + 500
    else:
        target = (final_price // 1000 + 1) * 1000

    difference = target - final_price

    system_load += difference
    final_price = target

    return system_load, final_price


def format_try(price_try: float) -> str:
    return f"{price_try:,.2f} ليرة".replace(",", "X").replace(".", ",").replace("X", ".")


def format_iqd(value: int) -> str:
    return f"{value:,} دينار"


def slugify_en(text: str) -> str:
    text = (text or "").lower().strip()
    replacements = {
        "ä": "a", "ö": "o", "ü": "u", "ı": "i", "ş": "s", "ğ": "g", "ç": "c",
        "&": " and ",
        "/": " ",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)

    text = re.sub(r"[^a-z0-9\s-]", " ", text)
    text = re.sub(r"\s+", "-", text).strip("-")
    text = re.sub(r"-+", "-", text)
    return text


# =========================
# أدوات اللوق للقناة
# =========================
def get_time_now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def increase_user_count(user_id: int):
    if user_id not in user_request_counter:
        user_request_counter[user_id] = 0
    user_request_counter[user_id] += 1
    return user_request_counter[user_id]


async def send_to_log_channel(bot, text: str):
    try:
        await bot.send_message(chat_id=LOG_CHANNEL_ID, text=text)
    except:
        pass


async def log_request(bot, user_id: int, user_name: str, url: str):
    count = increase_user_count(user_id)
    time_now = get_time_now()

    msg = (
        "طلب جديد 🔔\n\n"
        f"👤 الموظف: {user_name}\n"
        f"🆔 ID: {user_id}\n"
        f"📊 عدد طلباته: {count}\n"
        f"⏱ الوقت: {time_now}\n\n"
        f"🔗 الرابط:\n{url}"
    )

    await send_to_log_channel(bot, msg)


async def log_result(bot, user_id: int, user_name: str, result: str):
    time_now = get_time_now()

    msg = (
        "نتيجة الطلب ✅\n\n"
        f"👤 الموظف: {user_name}\n"
        f"🆔 ID: {user_id}\n"
        f"⏱ الوقت: {time_now}\n\n"
        f"{result}"
    )

    await send_to_log_channel(bot, msg)


async def log_error(bot, user_id: int, user_name: str, url: str, err: str, trace: str):
    time_now = get_time_now()

    msg = (
        "خطأ ❌\n\n"
        f"👤 الموظف: {user_name}\n"
        f"🆔 ID: {user_id}\n"
        f"⏱ الوقت: {time_now}\n\n"
        f"🔗 الرابط:\n{url}\n\n"
        f"الخطأ:\n{err}\n\n"
        f"{trace}"
    )

    await send_to_log_channel(bot, msg)


# =========================
# تنبيه الأدمن
# =========================
async def notify_admin(context, error_text: str, user_text: str):
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"⚠️ خطأ في البوت:\n\n{error_text}\n\nالرابط:\n{user_text}"
        )
    except:
        pass


# =========================
# قبول الكوكيز
# =========================
async def accept_cookies(page):
    possible_texts = [
        "Accept",
        "Accept all",
        "Allow all cookies",
        "Agree",
        "I agree",
        "قبول",
        "موافق",
        "السماح",
        "قبول الكل",
        "Tamam",
        "Kabul et",
        "Tümünü kabul et",
        "YALNIZCA GEREKLİ ÇEREZLER",
        "ONLY NECESSARY COOKIES",
    ]

    selectors = [
        "button",
        "[role='button']",
        "button span",
        "[id*='cookie'] button",
        "[class*='cookie'] button",
    ]

    for _ in range(4):
        for sel in selectors:
            try:
                loc = page.locator(sel)
                count = await loc.count()
                for i in range(min(count, 40)):
                    el = loc.nth(i)
                    txt = clean_spaces(await el.inner_text(timeout=600))
                    if any(t.lower() in txt.lower() for t in possible_texts):
                        try:
                            await el.click(timeout=1200)
                            await page.wait_for_timeout(700)
                            return
                        except:
                            pass
            except:
                pass


# =========================
# اختيار Irak
# =========================
async def select_irak_country_if_needed(page):
    try:
        await page.wait_for_timeout(1500)

        inputs = page.locator("input")
        count = await inputs.count()

        for i in range(min(count, 10)):
            try:
                el = inputs.nth(i)
                await el.click(timeout=1000)
                await el.fill("Irak", timeout=1200)
                await page.wait_for_timeout(800)
                await page.keyboard.press("ArrowDown")
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(800)
                break
            except:
                pass

        buttons = page.locator("button, [role='button']")
        bcount = await buttons.count()

        for i in range(min(bcount, 30)):
            try:
                txt = clean_spaces(await buttons.nth(i).inner_text()).lower()
                if "accept" in txt:
                    await buttons.nth(i).click(timeout=1200)
                    await page.wait_for_timeout(1500)
                    return
            except:
                pass
    except:
        pass


# =========================
# تحليل أسعار تركيا
# =========================
def parse_turkey_price_block(body_text: str):
    body_text = clean_spaces(body_text)

    prices = re.findall(r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*(?:TL|₺)", body_text, flags=re.I)
    values = []

    for p in prices:
        try:
            values.append(parse_tl_number(p))
        except:
            pass

    if not values:
        return None, False

    unique_values = sorted(set(values))
    current = min(unique_values)
    has_discount = len(unique_values) >= 2 and max(unique_values) > min(unique_values)

    return current, has_discount


# =========================
# تحليل أسعار العراق - HTML أقوى
# =========================
def extract_iqd_values(text: str):
    prices = re.findall(r'IQD\s*([\d,]+(?:\.\d{2})?)', text, flags=re.I)
    values = []

    for p in prices:
        try:
            values.append(parse_iqd_number(p))
        except:
            pass

    return values


def parse_iraq_price_from_html(page_html: str, body_text: str, product_name: str):
    html_text = html_lib.unescape(page_html).replace("\\/", "/")
    body_text = clean_spaces(body_text)
    product_name = clean_spaces(product_name or "")

    current = None

    # 1) اقرأ السعر الرئيسي من Current price أولاً
    m = re.search(
        r'Current price[^I]{0,80}IQD\s*([\d,]+(?:\.\d{2})?)',
        body_text,
        flags=re.I
    )
    if m:
        current = parse_iqd_number(m.group(1))
    else:
        # 2) fallback من HTML
        m = re.search(
            r'Current price[^I]{0,120}IQD\s*([\d,]+(?:\.\d{2})?)',
            html_text,
            flags=re.I
        )
        if m:
            current = parse_iqd_number(m.group(1))

    # 3) fallback من قرب اسم المنتج
    if current is None and product_name:
        idx = body_text.find(product_name)
        if idx != -1:
            nearby = body_text[idx: idx + 700]
            vals = extract_iqd_values(nearby)
            if vals:
                current = vals[0]

    # 4) fallback عام
    if current is None:
        vals = extract_iqd_values(body_text)
        if vals:
            current = vals[0]

    if current is None:
        return None, False

    # التخفيض:
    # نعم فقط إذا وجد Old price أو سعران داخل بلوك السعر الرئيسي نفسه
    has_discount = False

    m_current = re.search(r'Current price', body_text, flags=re.I)
    if m_current:
        nearby = body_text[max(0, m_current.start() - 120): m_current.end() + 220]

        if re.search(r'Old price', nearby, flags=re.I):
            nearby_vals = extract_iqd_values(nearby)
            unique_vals = sorted(set(nearby_vals))
            if len(unique_vals) >= 2 and max(unique_vals) > min(unique_vals):
                has_discount = True

    if not has_discount:
        html_block_match = re.search(
            r'(Old price.{0,120}?IQD\s*[\d,]+(?:\.\d{2})?.{0,120}?Current price.{0,120}?IQD\s*[\d,]+(?:\.\d{2})?)',
            html_text,
            flags=re.I | re.S
        )
        if html_block_match:
            block = html_block_match.group(1)
            block_vals = extract_iqd_values(block)
            unique_vals = sorted(set(block_vals))
            if len(unique_vals) >= 2 and max(unique_vals) > min(unique_vals):
                has_discount = True

    return current, has_discount


# =========================
# رابط العراق
# =========================
def extract_iraq_url_from_html(page_html: str, ref_code: str):
    html_text = html_lib.unescape(page_html).replace("\\/", "/")

    patterns = [
        rf'https://shop\.mango\.com/iq/en/p/[^"\']*_{ref_code}',
        rf'/iq/en/p/[^"\']*_{ref_code}',
    ]

    for pattern in patterns:
        m = re.search(pattern, html_text, flags=re.I)
        if m:
            url = m.group(0)
            if url.startswith("/"):
                url = "https://shop.mango.com" + url
            url = url.split("&amp;")[0].split('"')[0].split("'")[0]
            return url

    return None


def build_iraq_url_guesses(ref_code: str, product_name: str):
    en_slug = slugify_en(product_name)

    guesses = [
        f"https://shop.mango.com/iq/en/p/women/coats/coats/{en_slug}_{ref_code}",
        f"https://shop.mango.com/iq/en/p/women/jeans/flare/{en_slug}_{ref_code}",
        f"https://shop.mango.com/iq/en/p/women/dresses-and-jumpsuits/dresses/{en_slug}_{ref_code}",
        f"https://shop.mango.com/iq/en/p/women/shirts/shirts/{en_slug}_{ref_code}",
        f"https://shop.mango.com/iq/en/p/women/t-shirts/t-shirts/{en_slug}_{ref_code}",
        f"https://shop.mango.com/iq/en/p/women/trousers/trousers/{en_slug}_{ref_code}",
        f"https://shop.mango.com/iq/en/p/women/skirts/skirts/{en_slug}_{ref_code}",
        f"https://shop.mango.com/iq/en/p/women/jackets-and-blazers/jackets/{en_slug}_{ref_code}",
        f"https://shop.mango.com/iq/en/p/women/cardigans-and-sweaters/sweaters/{en_slug}_{ref_code}",
        f"https://shop.mango.com/iq/en/p/women/bags/shoulder/{en_slug}_{ref_code}",
        f"https://shop.mango.com/iq/en/p/women/{en_slug}_{ref_code}",
    ]

    out = []
    seen = set()
    for g in guesses:
        if g not in seen:
            out.append(g)
            seen.add(g)

    return out


async def url_looks_like_product(page, url: str, ref_code: str):
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        await page.wait_for_timeout(2000)
        await select_irak_country_if_needed(page)
        await accept_cookies(page)
        await page.wait_for_timeout(1200)

        body = await page.locator("body").inner_text()
        body_low = body.lower()

        if "doesn't exist" in body_low or "we're sorry" in body_low:
            return False

        if ref_code not in page.url and ref_code not in body:
            return False

        has_iqd = "IQD" in body

        try:
            has_h1 = await page.locator("h1").count() > 0
        except:
            has_h1 = False

        return has_iqd or has_h1
    except:
        return False


# =========================
# سحب تركيا
# =========================
async def scrape_turkey(page, turkey_url: str):
    await page.goto(turkey_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
    await page.wait_for_timeout(WAIT_MS)
    await accept_cookies(page)
    await page.wait_for_timeout(1200)

    try:
        await page.wait_for_selector("h1", timeout=12000)
    except:
        pass

    body_text = await page.locator("body").inner_text()
    page_html = await page.content()

    name = "غير معروف"
    try:
        h1 = page.locator("h1").first
        if await h1.count() > 0:
            name = clean_spaces(await h1.inner_text())
    except:
        pass

    ref_code = extract_ref(turkey_url)
    current_try, turkey_discount = parse_turkey_price_block(body_text)

    return {
        "ref_code": ref_code or "غير معروف",
        "name": name,
        "turkey_url": page.url,
        "turkey_price_try": current_try,
        "turkey_discount": turkey_discount,
        "body_text": body_text,
        "page_html": page_html,
    }


# =========================
# سحب العراق
# =========================
async def scrape_iraq(page, iraq_url: str):
    await page.goto(iraq_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
    await page.wait_for_timeout(WAIT_MS)

    await select_irak_country_if_needed(page)
    await accept_cookies(page)
    await page.wait_for_timeout(1200)

    try:
        await page.wait_for_selector("h1", timeout=12000)
    except:
        pass

    body_text = await page.locator("body").inner_text()
    page_html = await page.content()

    product_name = ""
    try:
        h1 = page.locator("h1").first
        if await h1.count() > 0:
            product_name = clean_spaces(await h1.inner_text())
    except:
        pass

    current_iqd, iraq_discount = parse_iraq_price_from_html(page_html, body_text, product_name)

    return {
        "iraq_url": page.url,
        "iraq_price_iqd": current_iqd,
        "iraq_discount": iraq_discount,
        "body_text": body_text,
    }


# =========================
# الرسالة النهائية
# =========================
def build_result_message(data: dict) -> str:
    ref_code = data.get("ref_code", "غير معروف")
    name = data.get("name", "غير معروف")

    turkey_url = data.get("turkey_url", "غير معروف")
    turkey_price_try = data.get("turkey_price_try")
    converted_iqd = data.get("converted_iqd")
    turkey_discount = data.get("turkey_discount", False)

    iraq_url = data.get("iraq_url", "غير معروف")
    iraq_price_iqd = data.get("iraq_price_iqd")
    iraq_discount = data.get("iraq_discount", False)

    diff_iqd = data.get("diff_iqd")
    system_load = data.get("system_load")
    final_price = data.get("final_price")

    turkey_price_text = format_try(turkey_price_try) if turkey_price_try is not None else "لم أستطع تأكيد سعر تركيا"
    converted_text = format_iqd(converted_iqd) if converted_iqd is not None else "لم أستطع التحويل"
    iraq_price_text = format_iqd(iraq_price_iqd) if iraq_price_iqd is not None else "لم أستطع تأكيد سعر العراق"
    diff_text = format_iqd(diff_iqd) if diff_iqd is not None else "غير محسوب"
    load_text = format_iqd(system_load) if system_load is not None else "غير محسوب"
    final_text = format_iqd(final_price) if final_price is not None else "غير محسوب"

    return (
        f"كود القطعة: {ref_code}\n"
        f"اسم القطعة: {name}\n\n"
        f"رابط تركيا: {turkey_url}\n"
        f"سعر تركيا: {turkey_price_text}\n"
        f"السعر المحول للعراقي: {converted_text}\n"
        f"تخفيض تركيا: {'نعم' if turkey_discount else 'لا'}\n\n"
        f"رابط العراق: {iraq_url}\n"
        f"سعر العراق: {iraq_price_text}\n"
        f"تخفيض العراق: {'نعم' if iraq_discount else 'لا'}\n\n"
        f"الفرق: {diff_text}\n"
        f"سعر التحميل في السستم: {load_text}\n"
        f"السعر النهائي: {final_text}"
    )


# =========================
# التحليل الكامل
# =========================
async def analyze_mango_product(turkey_url: str):
    ref_code = extract_ref(turkey_url)
    if not ref_code:
        raise ValueError("فشل تحليل كود القطعة من الرابط")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        tr_context = await browser.new_context(
            locale="tr-TR",
            timezone_id="Europe/Istanbul",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            extra_http_headers={
                "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Upgrade-Insecure-Requests": "1",
            },
            viewport={"width": 1366, "height": 900},
        )
        tr_page = await tr_context.new_page()
        tr_data = await scrape_turkey(tr_page, turkey_url)
        await tr_context.close()

        iq_context = await browser.new_context(
            locale="en-IQ",
            timezone_id="Asia/Baghdad",
            geolocation={"longitude": 44.3661, "latitude": 33.3152},
            permissions=["geolocation"],
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            extra_http_headers={
                "Accept-Language": "en-IQ,en;q=0.9,ar-IQ;q=0.8",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Upgrade-Insecure-Requests": "1",
            },
            viewport={"width": 1366, "height": 900},
        )
        iq_page = await iq_context.new_page()

        iraq_url = extract_iraq_url_from_html(tr_data["page_html"], ref_code)

        if not iraq_url:
            guesses = build_iraq_url_guesses(ref_code, tr_data["name"])
            iraq_url = None

            for guess in guesses:
                ok = await url_looks_like_product(iq_page, guess, ref_code)
                if ok:
                    iraq_url = guess
                    break

        if not iraq_url:
            await iq_context.close()
            await browser.close()
            raise ValueError("لم أستطع إيجاد رابط العراق لهذه القطعة.")

        iq_data = await scrape_iraq(iq_page, iraq_url)
        await iq_context.close()
        await browser.close()

    turkey_price_try = tr_data.get("turkey_price_try")
    iraq_price_iqd = iq_data.get("iraq_price_iqd")

    converted_iqd = None
    diff_iqd = None
    system_load = None
    final_price = None

    if turkey_price_try is not None:
        converted_iqd = convert_try_to_iqd(turkey_price_try)

    if converted_iqd is not None and iraq_price_iqd is not None:
        diff_iqd = iraq_price_iqd - converted_iqd

        system_load = calculate_system_load(
            diff_iqd=diff_iqd,
            turkey_discount=tr_data.get("turkey_discount", False),
            iraq_discount=iq_data.get("iraq_discount", False),
        )

        system_load, final_price = clean_final_price_and_adjust_load(
            converted_iqd,
            system_load
        )

    return {
        "ref_code": tr_data["ref_code"],
        "name": tr_data["name"],
        "turkey_url": tr_data["turkey_url"],
        "turkey_price_try": turkey_price_try,
        "converted_iqd": converted_iqd,
        "turkey_discount": tr_data["turkey_discount"],
        "iraq_url": iq_data["iraq_url"],
        "iraq_price_iqd": iraq_price_iqd,
        "iraq_discount": iq_data["iraq_discount"],
        "diff_iqd": diff_iqd,
        "system_load": system_load,
        "final_price": final_price,
    }


# =========================
# إعادة المحاولة
# =========================
async def analyze_with_retry(turkey_url: str):
    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            return await analyze_mango_product(turkey_url)
        except Exception as e:
            last_error = e

    raise last_error


# =========================
# تيليجرام
# =========================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message

    if not user or not message:
        return

    if user.id not in ALLOWED_USERS:
        await message.reply_text("عذرًا، هذا البوت خاص.")
        return

    text = clean_spaces(message.text or "")
    user_name = user.full_name or "بدون اسم"

    if not is_supported_mango_tr_url(text):
        await message.reply_text("هذا الرابط غير مدعوم")
        return

    await log_request(context.bot, user.id, user_name, text)

    wait_msg = await message.reply_text("جاري فحص القطعة...")

    try:
        data = await analyze_with_retry(text)
        msg = build_result_message(data)
        await wait_msg.edit_text(msg)
        await log_result(context.bot, user.id, user_name, msg)
    except Exception as e:
        err = str(e).strip() or "Unknown error"

        await wait_msg.edit_text(f"حدث خطأ أثناء الفحص:\n{err}")

        await notify_admin(context, err, text)
        await log_error(context.bot, user.id, user_name, text, err, traceback.format_exc(limit=5))

        print("\n=== ERROR ===")
        traceback.print_exc()


app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Bot is running...")
import asyncio

async def main():
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())