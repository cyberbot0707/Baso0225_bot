import os
from datetime import datetime, date, timedelta
import requests
from icalendar import Calendar
import recurring_ical_events
import pytz

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
GROUP_NAME = "БАСО-02-25"
MSK_TZ = pytz.timezone("Europe/Moscow")

# Координаты Москвы (район пр-та Вернадского)
MOSCOW_LAT = 55.67
MOSCOW_LON = 37.48


def get_academic_week(target_date: date) -> int:
    """Считает номер учебной недели РТУ МИРЭА"""
    year = target_date.year if target_date.month >= 9 else target_date.year - 1
    sep_1 = date(year, 9, 1)
    start_monday = sep_1 - timedelta(days=sep_1.weekday())
    if sep_1.weekday() == 6:
        start_monday += timedelta(days=7)
    target_monday = target_date - timedelta(days=target_date.weekday())
    return ((target_monday - start_monday).days // 7) + 1


def detect_campus(location: str) -> str:
    loc = location.upper()
    if "ДИСТАНЦ" in loc or "ОНЛАЙН" in loc or "LMS" in loc:
        return "💻 Дистанционно (Онлайн)"
    if loc.startswith("МП"):
        return f"📍 {location} (М. Пироговская, 1с5)"
    if loc.startswith("СГ"):
        return f"📍 {location} (Соколиная Гора, 22)"
    if loc.startswith("С-") or loc.startswith("С "):
        return f"📍 {location} (Стромынка, 20)"
    if loc.startswith(("К-", "Л-")):
        return f"📍 {location} (Вернадского, 86)"
    if loc.startswith(("А-", "Б-", "В-", "Г-", "Д-", "И-")):
        return f"📍 {location} (Вернадского, 78)"
    return f"📍 Ауд.: {location}" if location else "📍 Аудитория не указана"


def format_type_badge(summary: str) -> str:
    if summary.startswith("ЛК"):
        return "🟢 " + summary
    if summary.startswith("ПР"):
        return "🔵 " + summary
    if summary.startswith("ЛР"):
        return "🟣 " + summary
    return "📚 " + summary


def decode_weather_code(wmo_code: int) -> tuple[str, bool]:
    """Переводит код погоды WMO в текст с эмодзи и флагом осадков"""
    if wmo_code == 0:
        return "☀️ Ясно", False
    if wmo_code in (1, 2):
        return "🌤 Малооблачно", False
    if wmo_code == 3:
        return "☁️ Пасмурно", False
    if wmo_code in (45, 48):
        return "🌫 Туман", False
    if wmo_code in (51, 53, 55, 56, 57):
        return "🌦 Морось", True
    if wmo_code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "🌧 Дождь", True
    if wmo_code in (71, 73, 75, 77, 85, 86):
        return "❄️ Снег", True
    if wmo_code in (95, 96, 99):
        return "⛈ Гроза", True
    return "🌥 Облачно", False


def fetch_hourly_weather(target_date: date) -> dict:
    """Получает почасовой прогноз погоды в Москве на конкретную дату"""
    date_str = target_date.strftime("%Y-%m-%d")
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={MOSCOW_LAT}&longitude={MOSCOW_LON}"
        f"&hourly=temperature_2m,apparent_temperature,precipitation_probability,weathercode"
        f"&timezone=Europe%2FMoscow&start_date={date_str}&end_date={date_str}"
    )
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json().get("hourly", {})
        weather_by_hour = {}
        for i, time_iso in enumerate(data.get("time", [])):
            hour = int(time_iso.split("T")[1].split(":")[0])
            weather_by_hour[hour] = {
                "temp": round(data["temperature_2m"][i]),
                "feels": round(data["apparent_temperature"][i]),
                "prob": data["precipitation_probability"][i],
                "code": data["weathercode"][i]
            }
        return weather_by_hour
    except Exception as e:
        print(f"Ошибка получения погоды: {e}")
        return {}


def format_weather_line(weather_dict: dict, hour: int) -> tuple[str, bool]:
    """Форматирует строку погоды для конкретного часа"""
    w = weather_dict.get(hour)
    if not w:
        return "н/д", False
    desc, is_rainy = decode_weather_code(w["code"])
    temp_sign = "+" if w["temp"] > 0 else ""
    feels_sign = "+" if w["feels"] > 0 else ""
    rain_info = f", осадки {w['prob']}%" if w["prob"] >= 30 else ""
    need_umbrella = is_rainy or w["prob"] >= 45
    return f"{temp_sign}{w['temp']}°C (ощущ. {feels_sign}{w['feels']}°C), {desc}{rain_info}", need_umbrella


def fetch_calendar() -> Calendar:
    search_url = f"https://schedule-of.mirea.ru/schedule/api/search?match={GROUP_NAME}"
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(search_url, headers=headers, timeout=15)
    data = resp.json()
    ical_link = data["data"][0]["iCalLink"]
    ical_resp = requests.get(ical_link, headers=headers, timeout=15)
    return Calendar.from_ical(ical_resp.content)


def get_day_lessons(cal: Calendar, target_date: date):
    events = recurring_ical_events.of(cal).at(target_date)
    lessons = [e for e in events if isinstance(e.get("DTSTART").dt, datetime)]
    lessons.sort(key=lambda e: e.get("DTSTART").dt)
    return lessons


def build_telegram_message(cal: Calendar, target_date: date) -> str:
    weekdays = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    day_name = weekdays[target_date.weekday()]
    date_str = target_date.strftime("%d.%m.%Y")
    week_num = get_academic_week(target_date)
    lessons = get_day_lessons(cal, target_date)
    weather = fetch_hourly_weather(target_date)

    header = (
        f"🌙 <b>Расписание {GROUP_NAME} на завтра</b>\n"
        f"📅 <b>{day_name}, {date_str}</b> <i>({week_num}-я неделя)</i>\n\n"
    )

    if not lessons:
        msg = header + "🎉 <b>Завтра пар нет! Можно выспаться и отдохнуть.</b>\n"
        if weather:
            day_w, _ = format_weather_line(weather, 14)
            msg += f"\n🌡 <b>Погода днем (14:00):</b> {day_w}"
        return msg

    text = header
    prev_end = None

    for idx, lesson in enumerate(lessons, 1):
        start_dt = lesson.get("DTSTART").dt.astimezone(MSK_TZ)
        end_dt = lesson.get("DTEND").dt.astimezone(MSK_TZ)

        if prev_end:
            gap_minutes = int((start_dt - prev_end).total_seconds() // 60)
            if gap_minutes > 30:
                hours, mins = divmod(gap_minutes, 60)
                gap_str = f"{hours} ч. {mins} мин." if hours else f"{mins} мин."
                text += f"☕ <i>Окно между парами: {gap_str}</i>\n\n"

        prev_end = end_dt
        time_str = f"{start_dt.strftime('%H:%M')} – {end_dt.strftime('%H:%M')}"
        summary = format_type_badge(str(lesson.get("SUMMARY", "Предмет")).strip())
        location = detect_campus(str(lesson.get("LOCATION", "")).strip())
        teacher = str(lesson.get("DESCRIPTION", "")).strip().replace("\n", ", ")

        text += f"<b>{idx}. 🕒 {time_str}</b>\n"
        text += f"<b>{summary}</b>\n"
        text += f"<code>{location}</code>\n"
        if teacher:
            text += f"👤 {teacher}\n"
        text += "\n"

    first_start_dt = lessons[0].get("DTSTART").dt.astimezone(MSK_TZ)
    last_end_dt = lessons[-1].get("DTEND").dt.astimezone(MSK_TZ)
    text += f"🏁 <i>Пары заканчиваются в <b>{last_end_dt.strftime('%H:%M')}</b></i>\n"

    # Добавляем блок погоды на утро (за 1 час до первой пары) и после окончания пар
    if weather:
        morning_hour = max(6, first_start_dt.hour - 1)
        evening_hour = min(23, last_end_dt.hour)

        m_str, m_umb = format_weather_line(weather, morning_hour)
        e_str, e_umb = format_weather_line(weather, evening_hour)

        text += (
            f"\n🌡 <b>Погода в Москве на завтра:</b>\n"
            f"🌅 <b>Перед парами ({morning_hour:02d}:00):</b> {m_str}\n"
            f"🌇 <b>После пар ({evening_hour:02d}:00):</b> {e_str}\n"
        )
        if m_umb or e_umb:
            text += "☂️ <i>Совет: возможны осадки, захвати зонт!</i>"

    return text


def generate_website(cal: Calendar, start_date: date):
    """Генерирует красивый сайт index.html на 7 дней вперед для GitHub Pages"""
    weekdays = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    cards_html = ""

    for i in range(7):
        d = start_date + timedelta(days=i)
        day_name = weekdays[d.weekday()]
        date_str = d.strftime("%d.%m")
        week_num = get_academic_week(d)
        lessons = get_day_lessons(cal, d)

        badge = "Сегодня" if i == 0 else ("Завтра" if i == 1 else f"{week_num} нед.")
        cards_html += f'<div class="day-card"><div class="day-header"><span>{day_name}, {date_str}</span><span class="badge">{badge}</span></div>'

        # Для Сегодня и Завтра добавляем плашку погоды прямо на сайт
        if i in (0, 1) and lessons:
            w = fetch_hourly_weather(d)
            if w:
                m_hour = max(6, lessons[0].get("DTSTART").dt.astimezone(MSK_TZ).hour - 1)
                e_hour = min(23, lessons[-1].get("DTEND").dt.astimezone(MSK_TZ).hour)
                m_str, _ = format_weather_line(w, m_hour)
                e_str, _ = format_weather_line(w, e_hour)
                cards_html += f'''
                <div class="weather-box">
                    <div>🌅 <b>Утром ({m_hour:02d}:00):</b> {m_str}</div>
                    <div>🌇 <b>После пар ({e_hour:02d}:00):</b> {e_str}</div>
                </div>'''

        if not lessons:
            cards_html += '<div class="no-lessons">🎉 Выходной / Пар нет</div>'
        else:
            for lesson in lessons:
                start_dt = lesson.get("DTSTART").dt.astimezone(MSK_TZ).strftime('%H:%M')
                end_dt = lesson.get("DTEND").dt.astimezone(MSK_TZ).strftime('%H:%M')
                summary = str(lesson.get("SUMMARY", "Предмет")).strip()
                loc = detect_campus(str(lesson.get("LOCATION", "")).strip())
                teacher = str(lesson.get("DESCRIPTION", "")).strip().replace("\n", ", ")
                cards_html += f'''
                <div class="lesson">
                    <div class="time">{start_dt} – {end_dt}</div>
                    <div class="title">{summary}</div>
                    <div class="meta">{loc}</div>
                    {f'<div class="teacher">👤 {teacher}</div>' if teacher else ''}
                </div>'''
        cards_html += '</div>'

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Расписание {GROUP_NAME}</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 16px; }}
        h1 {{ font-size: 22px; text-align: center; margin-bottom: 20px; color: #38bdf8; }}
        .day-card {{ background: #1e293b; border-radius: 14px; padding: 14px; margin-bottom: 16px; box-shadow: 0 4px 12px rgba(0,0,0,0.25); }}
        .day-header {{ display: flex; justify-content: space-between; font-weight: 700; font-size: 17px; border-bottom: 1px solid #334155; padding-bottom: 8px; margin-bottom: 10px; }}
        .badge {{ background: #0284c7; color: white; padding: 2px 10px; border-radius: 12px; font-size: 13px; }}
        .weather-box {{ background: #0f172a; border-left: 3px solid #38bdf8; padding: 8px 10px; border-radius: 6px; font-size: 12.5px; color: #cbd5e1; margin-bottom: 10px; line-height: 1.5; }}
        .lesson {{ padding: 10px 0; border-bottom: 1px dashed #334155; }}
        .lesson:last-child {{ border-bottom: none; }}
        .time {{ color: #38bdf8; font-weight: 600; font-size: 14px; }}
        .title {{ font-weight: 600; font-size: 15px; margin: 4px 0; }}
        .meta, .teacher {{ font-size: 13px; color: #94a3b8; margin-top: 2px; }}
        .no-lessons {{ color: #64748b; padding: 8px 0; font-style: italic; }}
    </style>
</head>
<body>
    <h1>🎓 Расписание {GROUP_NAME}</h1>
    {cards_html}
</body>
</html>"""
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)


def main():
    cal = fetch_calendar()
    now_msk = datetime.now(MSK_TZ).date()
    tomorrow_msk = now_msk + timedelta(days=1)

    generate_website(cal, now_msk)

    msg_text = build_telegram_message(cal, tomorrow_msk)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": msg_text,
        "parse_mode": "HTML"
    }
    requests.post(url, json=payload, timeout=15)
    print("Расписание с прогнозом погоды успешно отправлено и сайт обновлен!")


if __name__ == "__main__":
    main()