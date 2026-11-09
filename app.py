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

# 台灣 22 縣市清單，用來進行關鍵字模糊比對
TAIWAN_CITIES = [
    "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", 
    "基隆市", "新竹市", "嘉義市", "新竹縣", "苗栗縣", "彰化縣", 
    "南投縣", "雲林縣", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣", 
    "臺東縣", "澎湖縣", "金門縣", "連江縣"
]

# 功能 1：原本的今明 36 小時預報（支援今天、明天、後天）
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

# 功能 2：全新解鎖的一週天氣預報（未來 7 天）
def get_weekly_weather(location_name):
    # 使用氣象署官方標準一週天氣預報接口 (F-D0047-091)
    url = "https://cwa.gov.tw"
    params = {"Authorization": CWA_API_KEY, "locationName": location_name}
    try:
        response = requests.get(url, params=params)
        data = response.json()
        if "records" not in data or "locations" not in data["records"] or not data["records"]["locations"]:
            return f"❌ 找不到『{location_name}』的一週氣象資料。"
            
        location_data = data["records"]["locations"][0]["location"][0]
        
        # 用來整理每天白天的預報
        daily_reports = {}
        
        for el in location_data["weatherElement"]:
            element_name = el["elementName"]
            # 我們抓取：天氣現象(Wx)、最低溫(MinT)、最高溫(MaxT)
            if element_name in ["Wx", "MinT", "MaxT"]:
                for t in el["time"]:
                    # 抓取日期 (例如 2026-11-10)
                    start_time = t["startTime"]
                    date_str = start_time.split(" ")[0].split("-")[1] + "/" + start_time.split(" ")[0].split("-")[2]
                    
                    # 由於一週預報每 12 小時一筆，我們主要抓白天的資料作為代表
                    if "12:00:00" in start_time or "06:00:00" in start_time:
                        if date_str not in daily_reports:
                            daily_reports[date_str] = {}
                        
                        if element_name == "Wx":
                            daily_reports[date_str]["Wx"] = t["elementValue"][0]["value"]
                        elif element_name == "MinT":
                            daily_reports[date_str]["MinT"] = t["elementValue"][0]["value"]
                        elif element_name == "MaxT":
                            daily_reports[date_str]["MaxT"] = t["elementValue"][0]["value"]

        # 組合出一週天氣的精美純文字報表
        report_text = f"🎙️ AI 氣象主播倪珍Niki ➔ 一週天氣展望\n📍 地區：{location_name}\n"
        report_text += "====================\n"
        
        # 取前 7 天的資料印出
        count = 0
        for date, info in sorted(daily_reports.items()):
            if count >= 7:
                break
            wx = info.get("Wx", "未知")
            mint = info.get("MinT", "--")
            maxt = info.get("MaxT", "--")
            report_text += f"📅 {date} ➔ {wx} ({mint}°C~{maxt}°C)\n"
            count += 1
            
        report_text += "====================\n💡 提醒：春季/秋季氣候多變，記得隨時留意最新氣象喔！"
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
    # 統一將使用者訊息中不規範的「台」置換為官方規格的「臺」
    user_msg = event.message.text.strip().replace("台", "臺")
    
    # 步驟一：檢查使用者輸入的句子裡，有沒有包含任何一個台灣縣市（模糊比對）
    matched_city = None
    for city in TAIWAN_CITIES:
        if city in user_msg or city.replace("市", "").replace("縣", "") in user_msg:
            matched_city = city
            break
            
    # 步驟二：如果有點選到縣市關鍵字，開始拆解時間需求
    if matched_city:
        if "一週" in user_msg or "一周" in user_msg or "7天" in user_msg or "七天" in user_msg:
            # 觸發功能 2：一週天氣
            reply_text = get_weekly_weather(matched_city)
        else:
            # 觸發功能 1：短天期預報
            day_target = "今天"
            if "明天" in user_msg:
                day_target = "明天"
            elif "後天" in user_msg:
                day_target = "後天"
            reply_text = get_short_weather(matched_city, day_target)
    else:
        # 如果使用者輸入的句子完全沒提到任何縣市
        reply_text = (
            f"🤖 嗨！我是 AI 氣象主播倪珍Niki。\n\n"
            f"不論你怎麼輸入，只要句子裡有【縣市名稱】我就能偵測到喔！\n\n"
            f"💡 範例你可以這樣輸入：\n"
            f"👉「我想知道明天台北市會下雨嗎」\n"
            f"👉「幫我查台中一週天氣」\n"
            f"👉「高雄後天冷不冷」"
        )
        
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
