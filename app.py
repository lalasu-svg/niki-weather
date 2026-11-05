import os
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 我已經直接幫你把 3 組最精準的密碼和最正確的官方 API 網址牢牢鎖死在程式碼的肉體裡了！
LINE_CHANNEL_SECRET = "ece28ebb8e5846dc59fcc86946a2f81a"
LINE_CHANNEL_ACCESS_TOKEN = "jS0KXkZcs3zbeuvuqECrIEO3A+mwvl1B3XcNuyD7XfG/SIyX/6fN/tI90td0aMMWj2aYVyiiwIbpU98H8d47/VH0h7AawgKDQMVAyqhR6ZT7aFeFDyzSiFl/95Z4zEgATTncHishbFnFWF187zwpRQdB04t89/1O/w1cDnyilFU="
CWA_API_KEY = "CWA-5D1FE36C-504D-42C3-994B-9C0A2CA4185B"

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

def get_weather_report(location_name):
    # 這行已經徹底拋棄 cwa.gov.tw，換成官方 100% 正確的開放資料接口網址
    url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001"
    params = {"Authorization": CWA_API_KEY, "locationName": location_name}
    try:
        response = requests.get(url, params=params)
        data = response.json()
        
        # 終極防錯：防護氣象署陣列回傳格式
        if "records" not in data or "location" not in data["records"] or not data["records"]["location"]:
            return f"❌ 找不到『{location_name}』的氣象資料，請檢查是否有錯字（例如：臺北市、基隆市）。"
            
        location_data = data["records"]["location"][0]
        
        weather_elements = {}
        for el in location_data["weatherElement"]:
            element_name = el["elementName"]
            try:
                weather_elements[element_name] = el["time"][0]["parameter"]["parameterName"]
            except Exception:
                weather_elements[element_name] = "未知"
        
        weather_state = weather_elements.get("Wx", "未知")
        rain_chance = weather_elements.get("PoP", "0")
        min_temp = weather_elements.get("MinT", "0")
        max_temp = weather_elements.get("MaxT", "0")
        comfort = weather_elements.get("CI", "")

        try:
            rain_chance_int = int(rain_chance)
        except Exception:
            rain_chance_int = 0

        if rain_chance_int >= 70:
            ai_tip = "⛈️ 外出一定要帶傘，注意大雨！"
        elif 30 <= rain_chance_int < 70:
            ai_tip = "🌦️ 降雨機率忽高忽低，帶把折疊傘比較保險喔！"
        elif max_temp != "未知" and int(max_temp) >= 30:
            ai_tip = "☀️ 天氣炎熱，出門注意防曬並多補充水分！"
        elif min_temp != "未知" and int(min_temp) <= 15:
            ai_tip = "❄️ 氣溫偏低，記得穿上保暖外套別凍傷了！"
        else:
            ai_tip = "🍃 氣候舒適，是個適合出門的好天氣！"

        return (
            f"🎙️ AI 氣象主播倪珍Niki播報\n"
            f"📍 地區：{location_name}\n"
            f"☁️ 天氣：{weather_state} ({comfort})\n"
            f"🌡️ 氣溫：{min_temp}°C ～ {max_temp}°C\n"
            f"💧 降雨機率：{rain_chance}%\n"
            f"💡 提醒：{ai_tip}"
        )
    except Exception as e:
        return f"❌ 氣象局資料解析錯誤，原因: {str(e)}"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip().replace("台", "臺")
    
    taiwan_cities = ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", 
                     "基隆市", "新竹市", "嘉義市", "新竹縣", "苗栗縣", "彰化縣", 
                     "南投縣", "雲林縣", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣", 
                     "臺東縣", "澎湖縣", "金門縣", "連江縣"]
                     
    if user_msg in taiwan_cities:
        reply_text = get_weather_report(user_msg)
    else:
        reply_text = "🤖 嗨！我是 AI 氣象主播倪珍Niki。\n請輸入你想查詢的完整縣市名稱（例如：臺北市、高雄市），我就會為你播報今日天氣重點喔！"
        
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
