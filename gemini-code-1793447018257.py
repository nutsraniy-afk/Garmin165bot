import os
import json
from datetime import datetime, timedelta, timezone
from garminconnect import Garmin
import requests

EMAIL = os.environ.get("GARMIN_EMAIL")
PASSWORD = os.environ.get("GARMIN_PASSWORD")
FIREBASE_URL = os.environ.get("FIREBASE_URL")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELE_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELE_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
WEB_APP_URL = os.environ.get("WEB_APP_URL", "https://github.com")

vn_tz = timezone(timedelta(hours=7))
today = datetime.now(vn_tz).strftime("%Y-%m-%d")

client = Garmin(EMAIL, PASSWORD)
client.login()
raw_data = client.get_sleep_data(today)

dto = raw_data.get("dailySleepDTO", {})
total_sec = dto.get("sleepTimeSeconds") or 0

if total_sec == 0:
    print(f"Chưa có dữ liệu giấc ngủ ngày {today}.")
    exit()

fb_base = FIREBASE_URL.rstrip('/')
check_exist = requests.get(f"{fb_base}/sleep_data/history/{today}.json").json()
if check_exist and check_exist.get("notified"):
    print("Hôm nay đã phân tích và gửi thông báo rồi!")
    exit()

deep_min = round((dto.get("deepSleepSeconds") or 0) / 60)
light_min = round((dto.get("lightSleepSeconds") or 0) / 60)
rem_min = round((dto.get("remSleepSeconds") or 0) / 60)
awake_min = round((dto.get("awakeSleepSeconds") or 0) / 60)
total_hours = round(total_sec / 3600, 1)

score = dto.get("sleepScores", {}).get("overall", {}).get("value", 0)
rhr = raw_data.get("restingHeartRate", 0)
stress = round(dto.get("avgSleepStress") or 0)

prompt = f"""
Bạn là huấn luyện viên sức khỏe và chạy bộ cá nhân. Hãy phân tích dữ liệu giấc ngủ đêm qua từ đồng hồ Garmin Forerunner 165:
- Điểm giấc ngủ: {score}/100
- Tổng giờ ngủ: {total_hours} tiếng (Ngủ sâu: {deep_min} phút, REM: {rem_min} phút, Ngủ nông: {light_min} phút, Thức: {awake_min} phút)
- Nhịp tim lúc nghỉ (RHR): {rhr} bpm | Stress: {stress}/100

Trả lời ngắn gọn theo đúng cấu trúc JSON sau:
{{
  "health_status": "Đánh giá 1-2 câu về chất lượng phục hồi cơ bắp và thần kinh sáng nay.",
  "sleep_more": "Kết luận rõ: NÊN DẬY LUÔN hay NÊN NGỦ THÊM (hoặc ngủ trưa bù bao nhiêu phút).",
  "todo_today": "Lời khuyên hôm nay nên làm gì: Cường độ chạy bộ (chạy nhẹ, biến tốc hay nghỉ) và lưu ý học tập."
}}
"""

gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
gemini_payload = {
    "contents": [{"parts": [{"text": prompt}]}],
    "generationConfig": {"responseMimeType": "application/json"}
}

ai_res = requests.post(gemini_url, json=gemini_payload).json()
ai_text = ai_res["candidates"][0]["content"]["parts"][0]["text"]
ai_advice = json.loads(ai_text)

payload = {
    "date": today,
    "score": score,
    "total_hours": total_hours,
    "deep_min": deep_min,
    "light_min": light_min,
    "rem_min": rem_min,
    "awake_min": awake_min,
    "rhr": rhr,
    "stress": stress,
    "ai_health": ai_advice["health_status"],
    "ai_sleep_more": ai_advice["sleep_more"],
    "ai_todo": ai_advice["todo_today"],
    "notified": True,
    "updated_at": datetime.now(vn_tz).strftime("%H:%M %d/%m/%Y")
}

requests.put(f"{fb_base}/sleep_data/latest.json", json=payload)
requests.put(f"{fb_base}/sleep_data/history/{today}.json", json=payload)

tele_msg = (
    f"🌅 *BÁO CÁO SỨC KHỎE SÁNG NAY ({today})*\n"
    f"━━━━━━━━━━━━━━━━━━\n"
    f"🏆 *Điểm ngủ:* {score}/100 ({total_hours} tiếng)\n"
    f"❤️ *Nhịp tim nghỉ:* {rhr} bpm | ⚡ *Stress:* {stress}\n\n"
    f"🩺 *Chất lượng cơ thể:*\n{ai_advice['health_status']}\n\n"
    f"🛌 *Có nên ngủ thêm không?*\n👉 *{ai_advice['sleep_more']}*\n\n"
    f"🏃‍♂️ *Lịch trình hôm nay:*\n{ai_advice['todo_today']}"
)

requests.post(
    f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage",
    json={"chat_id": TELE_CHAT_ID, "text": tele_msg, "parse_mode": "Markdown"}
)