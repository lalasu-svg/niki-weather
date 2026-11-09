import os
import logging
import requests

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request, abort

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== 1. API 憑證 =====
# 請在部署平台設定環境變數，不要寫死在程式中
LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
CWA_API_KEY = os.environ["CWA_API_KEY"]

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

TIMEZONE = ZoneInfo("Asia/Taipei")

# ===== 2. 氣象署 API =====
SHORT_API = (
    "https://opendata.cwa.gov.tw/api/v1/rest/"
    "datastore/F-C0032-001"
)

WEEKLY_API = (
    "https://opendata.cwa.gov.tw/api/v1/rest/"
    "datastore/F-D0047-091"
)

TAIWAN_CITIES = [
    "臺北市", "新北市", "桃園市",
    "臺中市", "臺南市", "高雄市",
    "基隆市", "新竹市", "嘉義市",
    "新竹縣", "苗栗縣", "彰化縣",
    "南投縣", "雲林縣", "嘉義縣",
    "屏東縣", "宜蘭縣", "花蓮縣",
    "臺東縣", "澎湖縣", "金門縣",
    "連江縣"
]


# ===== 3. 共用功能 =====

def now_tw():
    return datetime.now(TIMEZONE)


def parse_time(value):
    if not value:
        return None
    return datetime.fromisoformat(
        value.replace(" ", "T").replace("Z", "+00:00")
    ).replace(tzinfo=TIMEZONE) if (
        "+" not in value and not value.endswith("Z")
    ) else datetime.fromisoformat(
        value.replace("Z", "+00:00")
    ).astimezone(TIMEZONE)


def get_cwa_data(url, params=None):
    query = {
        "Authorization": CWA_API_KEY,
        "format": "JSON"
    }

    if params:
        query.update(params)

    response = requests.get(
        url,
        params=query,
        timeout=20
    )
    response.raise_for_status()

    data = response.json()

    if str(data.get("success", "")).lower() == "false":
        raise ValueError("氣象署 API 回報查詢失敗")

    if not data.get("records"):
        raise ValueError("氣象署未回傳預報資料")

    return data["records"]


def find_city(message):
    message = message.replace("台", "臺")

    # 先判斷完整縣市名稱
    for city in TAIWAN_CITIES:
        if city in message:
            return city

    # 常見簡稱
    aliases = {
        "臺北": "臺北市",
        "新北": "新北市",
        "桃園": "桃園市",
        "臺中": "臺中市",
        "臺南": "臺南市",
        "高雄": "高雄市",
        "基隆": "基隆市",
        "新竹": "新竹市",
        "嘉義": "嘉義市",
        "苗栗": "苗栗縣",
        "彰化": "彰化縣",
        "南投": "南投縣",
        "雲林": "雲林縣",
        "屏東": "屏東縣",
        "宜蘭": "宜蘭縣",
        "花蓮": "花蓮縣",
        "臺東": "臺東縣",
        "澎湖": "澎湖縣",
        "金門": "金門縣",
        "連江": "連江縣",
        "馬祖": "連江縣"
    }

    for keyword, city in aliases.items():
        if keyword in message:
            return city

    return None


def weather_value(item):
    # 36 小時預報的資料格式
    parameter = item.get("parameter")
    if isinstance(parameter, dict):
        return str(parameter.get("parameterName", "--"))

    # 一週預報的資料格式
    values = item.get("elementValue", [])

    if isinstance(values, list) and values:
        value = values[0]

        if isinstance(value, dict):
            for key in [
                "value", "Weather",
                "MaxTemperature", "MinTemperature",
                "Temperature", "ProbabilityOfPrecipitation"
            ]:
                if value.get(key) is not None:
                    return str(value[key])

    return "--"


def normalize_element_name(name):
    mapping = {
        "天氣現象": "Wx",
        "最高溫度": "MaxT",
        "最低溫度": "MinT",
        "12小時降雨機率": "PoP12h",
        "降雨機率": "PoP"
    }
    return mapping.get(name, name)


def extract_periods(location):
    result = {}

    for element in location.get("weatherElement", []):
        name = normalize_element_name(
            element.get("elementName", "")
        )

        for period in element.get("time", []):
            start = parse_time(period.get("startTime"))
            end = parse_time(period.get("endTime"))

            if not start:
                continue

            key = (
                start.isoformat(),
                end.isoformat() if end else ""
            )

            if key not in result:
                result[key] = {
                    "start": start,
                    "end": end
                }

            result[key][name] = weather_value(period)

    return sorted(
        result.values(),
        key=lambda x: x["start"]
    )


def choose_location(records, city):
    groups = records.get("locations", [])

    if isinstance(groups, dict):
        groups = [groups]

    # 有些資料集直接使用 location
    if not groups:
        groups = [{"location": records.get("location", [])}]

    candidates = []

    for group in groups:
        group_name = (
            group.get("locationsName", "")
            or group.get("LocationsName", "")
        )

        locations = group.get("location", [])

        if isinstance(locations, dict):
            locations = [locations]

        for loc in locations:
            name = loc.get("locationName", "")

            if name == city:
                return loc, city

            if group_name == city:
                candidates.append(loc)

    # 若資料只有鄉鎮層級，先選該縣市的一個
    # 地區作為參考，並在回覆中清楚標示。
    if candidates:
        loc = candidates[0]
        return loc, loc.get("locationName", city)

    return None, None


# ===== 4. 今天、明天天氣 =====

def get_short_weather(location_name, day_target="今天"):

    try:
        if day_target == "後天":
            return get_weekly_weather(
                location_name,
                day_target="後天"
            )

        records = get_cwa_data(
            SHORT_API,
            {"locationName": location_name}
        )

        locations = records.get("location", [])

        if not locations:
            return f"❌ 找不到{location_name}的天氣資料。"

        periods = extract_periods(locations[0])

        today = now_tw().date()

        if day_target == "明天":
            target_date = today + timedelta(days=1)
        else:
            target_date = today

        # 今天：優先選尚未結束的時段
        # 明天：優先選白天時段
        matches = [
            p for p in periods
            if p["start"].date() == target_date
        ]

        if day_target == "今天":
            active = [
                p for p in matches
                if p["end"] and p["end"] > now_tw()
            ]
            if active:
                matches = active
        else:
            daytime = [
                p for p in matches
                if 6 <= p["start"].hour < 18
            ]
            if daytime:
                matches = daytime

        if not matches:
            return get_weekly_weather(
                location_name,
                day_target=day_target
            )

        p = matches[0]

        weather = p.get("Wx", "未知")
        min_temp = p.get("MinT", "--")
        max_temp = p.get("MaxT", "--")
        rain = p.get("PoP", "--")
        comfort = p.get("CI", "")

        return (
            "🎙️ AI 氣象主播倪珍 Niki 播報\n"
            "━━━━━━━━━━━━━━\n"
            f"📅 預報日期：{target_date:%m/%d}（{day_target}）\n"
            f"📍 地區：{location_name}\n"
            f"🕒 時段：{p['start']:%H:%M} 起\n\n"
            f"☁️ 天氣：{weather}\n"
            f"🌡️ 氣溫：{min_temp}°C ～ {max_temp}°C\n"
            f"💧 降雨機率：{rain}%\n"
            f"😊 舒適度：{comfort}\n\n"
            "💡 Niki 提醒：出門前記得留意天氣變化！"
        )

    except requests.exceptions.RequestException:
        logger.exception("短期天氣 API 連線失敗")
        return "❌ 氣象資料連線失敗，請稍後再試。"

    except (ValueError, KeyError, TypeError):
        logger.exception("短期天氣資料解析失敗")
        return "❌ 氣象資料格式異常，請稍後再試。"


# ===== 5. 一週天氣及後天預報 =====

def get_weekly_weather(location_name, day_target=None):

    try:
        records = get_cwa_data(WEEKLY_API)

        location, display_name = choose_location(
            records, location_name
        )

        if not location:
            return (
                f"❌ 找不到{location_name}的一週預報資料。"
            )

        periods = extract_periods(location)
        today = now_tw().date()

        daily = {}

        for p in periods:
            date = p["start"].date()

            if date < today:
                continue

            if date not in daily:
                daily[date] = {
                    "weather": [],
                    "min": [],
                    "max": []
                }

            wx = p.get("Wx")
            if wx and wx != "--":
                daily[date]["weather"].append(wx)

            for field, dest in [
                ("MinT", "min"),
                ("MaxT", "max")
            ]:
                try:
                    daily[date][dest].append(
                        float(p[field])
                    )
                except (ValueError, TypeError, KeyError):
                    pass

        if not daily:
            return "❌ 目前沒有可用的一週預報資料。"

        # 後天單日預報
        if day_target:
            offset = {
                "今天": 0,
                "明天": 1,
                "後天": 2
            }.get(day_target, 0)

            date = today + timedelta(days=offset)
            info = daily.get(date)

            if not info:
                return f"❌ 暫時查不到{day_target}的預報。"

            return format_daily_weather(
                location_name,
                display_name,
                date,
                info,
                day_target
            )

        # 完整一週預報
        report = (
            "🎙️ AI 氣象主播倪珍 Niki\n"
            "📅 未來一週天氣展望\n"
            f"📍 地區：{location_name}\n"
        )

        if display_name != location_name:
            report += f"📌 參考地點：{display_name}\n"

        report += "━━━━━━━━━━━━━━\n"

        for date in sorted(daily.keys())[:7]:
            info = daily[date]

            wx = (
                info["weather"][0]
                if info["weather"] else "未知"
            )

            low = (
                f"{min(info['min']):g}"
                if info["min"] else "--"
            )
            high = (
                f"{max(info['max']):g}"
                if info["max"] else "--"
            )

            report += (
                f"\n📅 {date:%m/%d}\n"
                f"☁️ {wx}\n"
                f"🌡️ {low}°C ～ {high}°C\n"
            )

        report += (
            "\n━━━━━━━━━━━━━━\n"
            "💡 Niki 提醒：天氣隨時可能變化，"
            "出門前記得查看最新預報！"
        )

        return report

    except requests.exceptions.RequestException:
        logger.exception("一週天氣 API 連線失敗")
        return "❌ 一週氣象資料連線失敗，請稍後再試。"

    except (ValueError, KeyError, TypeError):
        logger.exception("一週天氣資料解析失敗")
        return "❌ 一週氣象資料格式異常，請稍後再試。"


def format_daily_weather(
    city, display_name, date, info, day_target
):
    wx = info["weather"][0] if info["weather"] else "未知"
    low = f"{min(info['min']):g}" if info["min"] else "--"
    high = f"{max(info['max']):g}" if info["max"] else "--"

    place_note = ""
    if display_name != city:
        place_note = f"📌 參考地點：{display_name}\n"

    return (
        "🎙️ AI 氣象主播倪珍 Niki 播報\n"
        "━━━━━━━━━━━━━━\n"
        f"📅 {date:%m/%d}（{day_target}）\n"
        f"📍 地區：{city}\n"
        f"{place_note}\n"
        f"☁️ 天氣：{wx}\n"
        f"🌡️ 氣溫：{low}°C ～ {high}°C\n\n"
        "💡 Niki 提醒：記得隨時留意最新天氣！"
    )


# ===== 6. LINE Webhook =====

@app.route("/callback", methods=["POST"])
def callback():

    signature = request.headers.get(
        "X-Line-Signature", ""
    )

    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)

    except InvalidSignatureError:
        abort(400)

    return "OK"


@app.route("/", methods=["GET"])
def index():
    return "AI Weather Bot Niki is Running!"


# ===== 7. LINE 訊息處理 =====

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):

    user_msg = event.message.text.strip()
    normalized = user_msg.replace("台", "臺")

    city = find_city(normalized)

    if city:

        weekly_keywords = [
            "一週", "一周",
            "7天", "七天",
            "一星期", "這週", "下週"
        ]

        if any(
            word in normalized
            for word in weekly_keywords
        ):
            reply_text = get_weekly_weather(city)

        else:
            day_target = "今天"

            if "後天" in normalized:
                day_target = "後天"
            elif "明天" in normalized:
                day_target = "明天"

            reply_text = get_short_weather(
                city, day_target
            )

    else:
        reply_text = (
            "🤖 嗨！我是 AI 氣象主播倪珍 Niki！\n\n"
            "想知道哪個縣市的天氣呢？\n"
            "只要告訴我地點，就能幫你查詢！\n\n"
            "🌤️ 你可以這樣問我：\n\n"
            "👉 今天臺北天氣如何？\n"
            "👉 明天臺中會下雨嗎？\n"
            "👉 高雄後天冷不冷？\n"
            "👉 新北一週天氣\n\n"
            "📍 支援全臺 22 縣市！"
        )

    try:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
    except Exception:
        logger.exception("LINE 回覆訊息失敗")


# ===== 8. 啟動伺服器 =====

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port
    )
