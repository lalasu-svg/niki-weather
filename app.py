import os
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# LINE 憑證與氣象署授權碼
LINE_CHANNEL_SECRET = "ece28ebb8e5846dc59fcc86946a2f81a"
LINE_CHANNEL_ACCESS_TOKEN = "jS0KXkZcs3zbeuvuqECrIEO3A+mwvl1B3XcNuyD7XfG/SIyX/6fN/tI90td0aMMWj2aYVyiiwIbpU98H8d47/VH0h7AawgKDQMVAyqhR6ZT7aFeFDyzSiFl/95Z4zEgATTncHishbFnFWF187zwpRQdB04t89/1O/w1cDnyilFU="
CWA_API_KEY = "CWA-5D1FE36C-504D-42C3-994B-9C0A2CA4185B"

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

TAIWAN_CITIES = [
    "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", 
    "基隆市", "新竹市", "嘉義市", "新竹縣", "苗栗縣", "彰化縣", 
    "南投縣", "雲林縣", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣", 
    "臺東縣", "澎湖縣", "金門縣", "連江縣"
]

# 1. 今明 36 小時預報
def get_short_weather(location_name, day_target="今天"):
    url = "https://cwa.gov.tw"
    params = {"Authorization": CWA_API_KEY, "locationName": location_name}
    try:
        response = requests.get(url, params=params)
        data = response.json()
        if "records" not in data or "location" not in data["records"] or not data["records"]["location"]:
            return f"❌ 找不到『{location_name}』的氣象資料。"
            
        location_data = data["records"]["location"][0]
        
        time_index = 0
        if day_target == "明天":
            time_index = 1
        elif day_target == "後天":
            time_index = 2
            
        weather_elements = {}
        for el in location_data["weatherElement"]:
            element_name = el["elementName"]
            try:
                weather_elements[element_name] = el["time"][time_index]["parameter"]["parameterName"]
            except Exception:
                weather_elements[element_name] = "未知"
        
        weather_state = weather_elements.get("Wx", "未知")
        rain_chance = weather_elements.get("PoP", "0")
        min_temp = weather_elements.get("MinT", "0")
        max_temp = weather_elements.get("MaxT", "0")
        comfort = weather_elements.get("CI", "")

        return (
            f"🎙️ AI 氣象主播倪珍Niki播報\n"
            f"📅 預報時間：{day_target}\n"
            f"📍 地區：{location_name}\n"
            f"☁️ 天氣：{weather_state} ({comfort})\n"
            f"🌡️ 氣溫：{min_temp}°C ～ {max_temp}°C\n"
            f"💧 降雨機率：{rain_chance}%\n"
            f"💡 提醒：祝您出門有副好心情！"
        )
    except Exception as e:
        return f"❌ 氣象局資料解析錯誤，原因: {str(e)}"

# 2. 全新一週天氣預報
def get_weekly_weather(location_name):
    # 精準修正：改為官方標準一週天氣預報正確接口，徹底拋棄舊網址
    url = "https://cwa.gov.tw"
    params = {"Authorization": CWA_API_KEY, "locationName": location_name}
    try:
        response = requests.get(url, params=params)
        data = response.json()
        if "records" not in data or "locations" not in data["records"] or not data["records"]["locations"]:
            return f"❌ 找不到『{location_name}』的一週氣象資料。"
            
        location_data = data["records"]["locations"]["location"][0]
        
        daily_reports = {}
        for el in location_data["weatherElement"]:
            element_name = el["elementName"]
            if element_name in ["Wx", "MinT", "MaxT"]:
                for t in el["time"]:
                    start_time = t["startTime"]
                    # 格式化時間戳記
                    date_str = start_time.split(" ")[0].split("-")[1] + "/" + start_time.split(" ")[0].split("-")[2]
                    
                    # 抓取白天時段預報
                    if "12:00:00" in start_time or "06:00:00" in start_time:
                        if date_str not in daily_reports:
                            daily_reports[date_str] = {}
                        
                        if element_name == "Wx":
                            daily_reports[date_str]["Wx"] = t["elementValue"][0]["value"]
                        elif element_name == "MinT":
                            daily_reports[date_str]["MinT"] = t["elementValue"][0]["value"]
                        elif element_name == "MaxT":
                            daily_reports[date_str]["MaxT"] = t["elementValue"][0]["value"]

        report_text = f"🎙️ AI 氣象主播倪珍Niki ➔ 一週天氣展望\n📍 地區：{location_name}\n"
        report_text += "====================\n"
        
        count = 0
        for date, info in sorted(daily_reports.items()):
            if count >= 7:
                break
            wx = info.get("Wx", "未知")
            mint = info.get("MinT", "--")
            maxt = info.get("MaxT", "--")
            report_text += f"📅 {date} ➔ {wx} ({mint}°C~{maxt}°C)\n"
            count += 1
            
        report_text += "====================\n💡 提醒：氣候多變，記得隨時留意最新氣象喔！"
        return report_text
    except Exception as e:
        return f"❌ 一週氣象資料解析錯誤，原因: {str(e)}"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@app.route("/", methods=['GET'])
def index():
    return "Hello, Complete Weather Bot is Running!"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip().replace("台", "臺")
    
    matched_city = None
    for city in TAIWAN_CITIES:
        if city in user_msg or city.replace("市", "").replace("縣", "") in user_msg:
            matched_city = city
            break
            
    if matched_city:
        if "一週" in user_msg or "一周" in user_msg or "7天" in user_msg or "七天" in user_msg:
            reply_text = get_weekly_weather(matched_city)
        else:
            day_target = "今天"
            if "明天" in user_msg:
                day_target = "明天"
            elif "後天" in user_msg:
                day_target = "後天"
            reply_text = get_short_weather(matched_city, day_target)
    else:
        reply_text = (
            f"🤖 嗨！我是 AI 氣象主播倪珍Niki。\n\n"
            f"只要句子裡有【縣市名稱】我就能偵測到喔！\n\n"
            f"💡 範例：\n"
            f"👉「我想知道明天台北市會下雨嗎」\n"
            f"👉「幫我查台中一週天氣」\n"
            f"👉「高雄後天冷不冷」"
        )
        
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
