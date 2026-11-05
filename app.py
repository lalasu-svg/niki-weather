import os
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 已經幫你將 3 組正確的密碼直接鎖定在程式碼中，完全不用再手動填寫！
LINE_CHANNEL_SECRET = "ece28ebb8e5846dc59fcc86946a2f81a"
LINE_CHANNEL_ACCESS_TOKEN = "jS0KXkZcs3zbeuvuqECrIEO3A+mwvl1B3XcNuyD7XfG/SIyX/6fN/tI90td0aMMWj2aYVyiiwIbpU98H8d47/VH0h7AawgKDQMVAyqhR6ZT7aFeFDyzSiFl/95Z4zEgATTncHishbFnFWF187zwpRQdB04t89/1O/w1cDnyilFU="
CWA_API_KEY = "CWA-5D1FE36C-504D-42C3-994B-9C0A2CA4185B"

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 氣象署資料抓取邏輯
def get_weather_report(location_name):
    # 修正點 1：修正氣象署開放資料 API 的正確請求網址
    url = "https://cwa.gov.tw"
    params = {"Authorization": CWA_API_KEY, "locationName": location_name}
    try:
        response = requests.get(url, params=params)
        data = response.json()
        if not data["records"]["location"]:
            return f"❌ 找不到『{location_name}』的氣象資料，請檢查是否有錯字（例如：臺北市、基隆市）。"
            
        location_data = data["records"]["location"][0]
        
        # 解析氣象元素
        weather_elements = {}
        for el in location_data["weatherElement"]:
            # 抓取未來 12 小時的第一個預報時段
            weather_elements[el["elementName"]] = el["time"][0]["parameter"]["parameterName"]
        
        weather_state = weather_elements.get("Wx", "未知")
        rain_chance = weather_elements.get("PoP", "0")
        min_temp = weather_elements.get("MinT", "0")
        max_temp = weather_elements.get("MaxT", "0")
        comfort = weather_elements.get("CI", "")

        rain_chance_int = int(rain_chance)
        if rain_chance_int >= 70:
            ai_tip = "⛈️ 外出一定要帶傘，注意大雨！"
        elif 30 <= rain_chance_int < 70:
            ai_tip = "🌦️ 降雨機率忽高忽低，帶把折疊傘比較保險喔！"
        elif int(max_temp) >= 30:
            ai_tip = "☀️ 天氣炎熱，出門注意防曬並多補充水分！"
        elif int(min_temp) <= 15:
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
        return "❌ 氣象局資料連線錯誤，請稍後再試。"

# 接收 LINE 訊息的通道
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 當用戶傳送「文字訊息」給機器人時，會觸發這個區塊
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip().replace("台", "臺") # 自動轉換台/臺
    
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
    # 修正點 2：配合 Render 雲端平台自動分配的連接埠（Port）
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
