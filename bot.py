import asyncio
import aiohttp
from collections import Counter
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

BOT_TOKEN = "8778249747:AAFnLZeDZYuRXVyjJrdQqIndezMe7-kHGs0"

APIS = {
    "md5": "https://wtxmd52.tele68.com/v1/txmd5/lite-sessions?cp=R&cl=R&pf=web&at=07d01d98fd85e91efaa91fe492970412",
    "hu":  "https://wtx.tele68.com/v1/tx/lite-sessions?cp=R&cl=R&pf=web&at=07d01d98fd85e91efaa91fe492970412",
}

HEADERS = {
    "accept": "*/*",
    "accept-language": "vi-VN,vi;q=0.9,fr-FR;q=0.8,fr;q=0.7,en-US;q=0.6,en;q=0.5",
    "Referer": "https://lc79b.bet/",
}

DICE_EMOJI = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"]

active_chats = {}
history_data = {"md5": [], "hu": []}
pred_history = {"md5": [], "hu": []}
last_session_id = {"md5": None, "hu": None}
pending_prediction = {"md5": None, "hu": None}
correct_count = {"md5": 0, "hu": 0}
wrong_count = {"md5": 0, "hu": 0}
algo_version = {"md5": 0, "hu": 0}
weights = {
    "md5": {"bridge": 0.40, "trend": 0.20, "pattern": 0.20, "freq": 0.20},
    "hu":  {"bridge": 0.40, "trend": 0.20, "pattern": 0.20, "freq": 0.20},
}


def _opposite(r):
    return "XIU" if r == "TAI" else "TAI"


def analyze_bridge(results):
    if len(results) < 2:
        return "unknown", 0

    streak = 1
    for i in range(1, len(results)):
        if results[i] == results[0]:
            streak += 1
        else:
            break

    if streak >= 2:
        return "bet_long" if streak >= 4 else "bet", streak

    alt_len = 1
    for i in range(1, min(10, len(results))):
        expected = results[0] if i % 2 == 0 else _opposite(results[0])
        if results[i] == expected:
            alt_len += 1
        else:
            break

    if alt_len >= 4:
        return "one_one", alt_len

    if len(results) >= 4:
        pair_ok = all(results[i] == results[i ^ 1] for i in range(min(8, len(results) - 1)))
        if pair_ok:
            return "two_two", len(results)

    zigzag = True
    for i in range(min(8, len(results) - 1)):
        if results[i] == results[i + 1]:
            zigzag = False
            break
    if zigzag and alt_len < 4:
        return "zigzag", 0

    return "mixed", 0


def break_probability(bridge_type, streak):
    if bridge_type == "bet_long":
        return min(0.80, 0.50 + (streak - 4) * 0.08)
    if bridge_type == "bet" and streak == 3:
        return 0.45
    if bridge_type == "one_one" and streak >= 6:
        return 0.50 + (streak - 6) * 0.06
    return 0.0


def bridge_vote(results):
    bridge_type, streak = analyze_bridge(results)
    bp = break_probability(bridge_type, streak)

    if bridge_type in ("bet", "bet_long"):
        if bp >= 0.55:
            return _opposite(results[0]), bp, f"🔴 Cầu bệt {streak} — khả năng gãy {bp:.0%}"
        return results[0], 0.55 + streak * 0.03, f"🟢 Cầu bệt {streak} — theo cầu"

    if bridge_type == "one_one":
        nxt = _opposite(results[0])
        if bp >= 0.50:
            return results[0], bp, f"🔴 Cầu 1‑1 dài {streak} — lệch nhịp"
        return nxt, 0.60, f"🟢 Cầu 1‑1 — đảo chiều"

    if bridge_type == "two_two":
        if len(results) >= 2 and results[0] == results[1]:
            return _opposite(results[0]), 0.58, "🟡 Cầu 2‑2 — chuyển cặp"
        return results[0], 0.55, "🟡 Cầu 2‑2 — theo hiện tại"

    if bridge_type == "zigzag":
        return _opposite(results[0]), 0.52, "🔵 Cầu zigzag — đảo chiều"

    return None, 0.0, "⚪ Cầu hỗn hợp"


def freq_vote(results, window=20):
    sample = results[:window]
    if not sample:
        return None, 0.0, ""
    tai = sample.count("TAI")
    total = len(sample)
    tai_r = tai / total
    xiu_r = 1 - tai_r

    if tai_r > 0.62:
        return "XIU", min(0.65, 0.50 + (tai_r - 0.50)), f"📊 Tần số {window}p — TAI {tai_r:.0%} → bù XIU"
    if xiu_r > 0.62:
        return "TAI", min(0.65, 0.50 + (xiu_r - 0.50)), f"📊 Tần số {window}p — XIU {xiu_r:.0%} → bù TAI"
    if tai_r > xiu_r:
        return "TAI", tai_r, f"📊 Tần số {window}p — TAI dẫn {tai_r:.0%}"
    return "XIU", xiu_r, f"📊 Tần số {window}p — XIU dẫn {xiu_r:.0%}"


def pattern_vote(results, pattern_len=6):
    if len(results) < pattern_len * 2 + 1:
        return None, 0.0, ""

    target = tuple(results[:pattern_len])
    matches = []

    for i in range(pattern_len, len(results) - 1):
        window = tuple(results[i: i + pattern_len])
        if window == target:
            matches.append(results[i - 1])

    if not matches:
        return None, 0.0, ""

    c = Counter(matches)
    best, cnt = c.most_common(1)[0]
    conf = cnt / len(matches)
    if conf < 0.55:
        return None, 0.0, ""
    return best, conf, f"🔁 Pattern {pattern_len}p — {len(matches)} mẫu khớp ({conf:.0%})"


def trend_vote(results, window=10):
    sample = results[:window]
    if len(sample) < window:
        return None, 0.0, ""
    tai = sample.count("TAI")
    if tai >= 7:
        score = 0.55 + (tai - 7) * 0.05
        return "TAI", min(score, 0.70), f"📈 Xu hướng {window}p — TAI mạnh ({tai}/{window})"
    if tai <= 3:
        score = 0.55 + (3 - tai) * 0.05
        return "XIU", min(score, 0.70), f"📉 Xu hướng {window}p — XIU mạnh ({window-tai}/{window})"
    return None, 0.0, ""


def point_hint(sessions):
    if len(sessions) < 5:
        return None, 0.0
    points = [s["point"] for s in sessions[:15]]
    tai_p = sum(1 for p in points if p >= 11)
    xiu_p = sum(1 for p in points if p <= 10)
    total = len(points)
    if tai_p / total > 0.65:
        return "TAI", 0.55
    if xiu_p / total > 0.65:
        return "XIU", 0.55
    return None, 0.0


def predict(game_type):
    sessions = history_data[game_type]
    if len(sessions) < 4:
        return "TAI", 0.50, "⚪ Chưa đủ dữ liệu"

    results = [s["resultTruyenThong"] for s in sessions]
    w = weights[game_type]
    votes = {"TAI": 0.0, "XIU": 0.0}
    signals = []

    r_bridge, c_bridge, s_bridge = bridge_vote(results)
    if r_bridge:
        votes[r_bridge] += w["bridge"] * c_bridge * 10
        signals.append(s_bridge)

    r_freq, c_freq, s_freq = freq_vote(results, 20)
    if r_freq:
        votes[r_freq] += w["freq"] * c_freq * 10
        signals.append(s_freq)

    r_freq50, c_freq50, _ = freq_vote(results, 50)
    if r_freq50:
        votes[r_freq50] += w["freq"] * c_freq50 * 4

    r_pat, c_pat, s_pat = pattern_vote(results, 6)
    if r_pat:
        votes[r_pat] += w["pattern"] * c_pat * 10
        signals.append(s_pat)

    r_trend, c_trend, s_trend = trend_vote(results, 10)
    if r_trend:
        votes[r_trend] += w["trend"] * c_trend * 10
        signals.append(s_trend)

    r_pt, c_pt = point_hint(sessions)
    if r_pt:
        votes[r_pt] += 0.5 * c_pt * 10

    total = votes["TAI"] + votes["XIU"]
    if total == 0:
        pred = "TAI"
        conf = 0.50
    elif votes["TAI"] >= votes["XIU"]:
        pred = "TAI"
        conf = votes["TAI"] / total
    else:
        pred = "XIU"
        conf = votes["XIU"] / total

    conf = min(0.95, max(0.50, conf))
    detail = " · ".join(signals[:3]) if signals else "⚪ Phân tích tổng hợp"
    return pred, conf, detail


def conf_label(conf):
    if conf >= 0.80:
        return f"🔥 *{conf:.0%}* — Rất cao"
    if conf >= 0.68:
        return f"⚡ *{conf:.0%}* — Cao"
    if conf >= 0.58:
        return f"🟡 *{conf:.0%}* — Trung bình"
    return f"⚪ *{conf:.0%}* — Thấp"


def game_label(game_type):
    return "🎮 *LC MD5*" if game_type == "md5" else "🏆 *LC HŨ*"


async def fetch_sessions(game_type):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                APIS[game_type],
                headers=HEADERS,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("list", [])
    except Exception:
        pass
    return []


def update_history(game_type, sessions):
    existing_ids = {s["id"] for s in history_data[game_type]}
    for s in reversed(sessions):
        if s["id"] not in existing_ids:
            history_data[game_type].insert(0, s)
            existing_ids.add(s["id"])
    history_data[game_type] = sorted(
        history_data[game_type], key=lambda x: x["id"], reverse=True
    )[:100]


async def polling_loop(app, game_type):
    while True:
        try:
            sessions = await fetch_sessions(game_type)
            if not sessions:
                await asyncio.sleep(5)
                continue

            update_history(game_type, sessions)
            latest_id = sessions[0]["id"]

            if last_session_id[game_type] is None:
                last_session_id[game_type] = latest_id
                await asyncio.sleep(5)
                continue

            if latest_id == last_session_id[game_type]:
                await asyncio.sleep(5)
                continue

            last_session_id[game_type] = latest_id
            new_session = sessions[0]

            match_str = ""
            if pending_prediction[game_type] is not None:
                pred_res, pred_conf = pending_prediction[game_type]
                actual = new_session["resultTruyenThong"]
                correct = pred_res == actual
                if correct:
                    correct_count[game_type] += 1
                else:
                    wrong_count[game_type] += 1
                pred_history[game_type].append(
                    {
                        "session_id": latest_id,
                        "actual": actual,
                        "predicted": pred_res,
                        "correct": correct,
                        "time": datetime.now().strftime("%H:%M:%S"),
                    }
                )
                match_str = "✅ *Khớp*" if correct else "❌ *Lệch*"

            pred, conf, detail = predict(game_type)
            pending_prediction[game_type] = (pred, conf)

            pred_str = "🔴 *TÀI*" if pred == "TAI" else "🔵 *XỈU*"
            time_str = datetime.now().strftime("%H:%M:%S %d/%m")

            msg = (
                f"{game_label(game_type)}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 *Phiên:* `#{latest_id}`\n"
                f"💡 *Dự đoán:* {pred_str}\n"
                f"📊 *Tin cậy:* {conf_label(conf)}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
            )

            dices = new_session["dices"]
            dice_str = " ".join(DICE_EMOJI[d - 1] for d in dices)
            res_icon = "🔴 *TÀI*" if new_session["resultTruyenThong"] == "TAI" else "🔵 *XỈU*"
            msg += (
                f"📌 *Phiên trước:* `#{latest_id}`\n"
                f"🎲 *Xúc xắc:* {dice_str}  _{new_session['point']} điểm_\n"
                f"📋 *Kết quả:* {res_icon}\n"
            )
            if match_str:
                msg += f"🎯 *Đối chiếu:* {match_str}\n"

            msg += (
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔍 _{detail}_\n"
                f"⏰ _{time_str}_"
            )

            chats_for_type = [
                cid for cid, info in list(active_chats.items())
                if info.get("type") == game_type
            ]
            for chat_id in chats_for_type:
                try:
                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=msg,
                        parse_mode=ParseMode.MARKDOWN,
                    )
                except Exception:
                    pass

        except Exception:
            pass

        await asyncio.sleep(5)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args

    if not args or args[0].lower() not in ("md5", "hu"):
        await update.message.reply_text(
            "📌 *Cách dùng:*\n`/start md5` — Dự đoán LC MD5\n`/start hu` — Dự đoán LC Hũ",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    gt = args[0].lower()
    active_chats[chat_id] = {"type": gt}

    msg = (
        f"✅ {game_label(gt)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🚀 *Đã bắt đầu dự đoán tự động*\n"
        f"🔄 _Cập nhật mỗi khi có phiên mới_\n"
        f"📡 _Đang chờ phiên tiếp theo..._\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ /stop — dừng · /hoc — nâng cấp · /his — lịch sử"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if chat_id not in active_chats:
        await update.message.reply_text(
            "⚠️ _Bạn chưa bắt đầu dự đoán._", parse_mode=ParseMode.MARKDOWN
        )
        return

    gt = active_chats.pop(chat_id)["type"]
    correct = correct_count[gt]
    wrong = wrong_count[gt]
    total = correct + wrong
    acc = correct / total if total > 0 else 0

    msg = (
        f"🛑 {game_label(gt)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"✋ *Đã dừng dự đoán*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ *Đoán đúng:* `{correct}`\n"
        f"❌ *Sai:* `{wrong}`\n"
        f"🎯 *Tỷ lệ:* `{acc:.1%}`"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def cmd_hoc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if chat_id not in active_chats:
        await update.message.reply_text(
            "⚠️ _Vui lòng /start trước._", parse_mode=ParseMode.MARKDOWN
        )
        return

    gt = active_chats[chat_id]["type"]
    algo_version[gt] += 1
    v = algo_version[gt]
    w = weights[gt]

    correct = correct_count[gt]
    wrong = wrong_count[gt]
    total = correct + wrong
    upgrades = []

    if total >= 10:
        acc = correct / total
        if acc < 0.50:
            w["bridge"] = min(0.55, w["bridge"] + 0.05)
            w["pattern"] = min(0.30, w["pattern"] + 0.05)
            w["freq"] = max(0.10, w["freq"] - 0.05)
            w["trend"] = max(0.10, w["trend"] - 0.05)
            upgrades.append("Tăng trọng số cầu & pattern, giảm tần số")
        elif acc < 0.60:
            w["trend"] = min(0.30, w["trend"] + 0.03)
            w["pattern"] = min(0.30, w["pattern"] + 0.03)
            upgrades.append("Tăng nhẹ xu hướng & pattern")
        else:
            w["freq"] = min(0.30, w["freq"] + 0.03)
            upgrades.append("Tỷ lệ tốt — tăng nhẹ trọng số tần số")
    else:
        upgrades.append("Chưa đủ dữ liệu — giữ trọng số mặc định")

    upgrades.append(f"Phát hiện cầu gãy nhạy hơn (v{v})")
    upgrades.append(f"Pattern matching mở rộng {min(8, 6 + v)} phiên")

    detail_str = "\n".join(f"  • _{u}_" for u in upgrades)

    msg = (
        f"🧠 {game_label(gt)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ *Đã học tập — Nâng cấp v{v}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ *Thuật toán nâng cấp:*\n{detail_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Trọng số mới:*\n"
        f"  🔗 Cầu: `{w['bridge']:.0%}`\n"
        f"  📈 Xu hướng: `{w['trend']:.0%}`\n"
        f"  🔁 Pattern: `{w['pattern']:.0%}`\n"
        f"  📊 Tần số: `{w['freq']:.0%}`"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def cmd_his(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if chat_id not in active_chats:
        await update.message.reply_text(
            "⚠️ _Vui lòng /start trước._", parse_mode=ParseMode.MARKDOWN
        )
        return

    gt = active_chats[chat_id]["type"]
    hist = pred_history[gt]

    if not hist:
        await update.message.reply_text(
            "📭 _Chưa có lịch sử dự đoán._", parse_mode=ParseMode.MARKDOWN
        )
        return

    rows = []
    for entry in hist[-20:]:
        icon = "✅" if entry["correct"] else "❌"
        act = "🔴TÀI" if entry["actual"] == "TAI" else "🔵XỈU"
        prd = "🔴TÀI" if entry["predicted"] == "TAI" else "🔵XỈU"
        rows.append(f"`#{entry['session_id']}` │ {act} │ {prd} {icon}")

    correct = correct_count[gt]
    wrong = wrong_count[gt]
    total = correct + wrong
    acc = correct / total if total > 0 else 0

    history_str = "\n".join(rows)
    msg = (
        f"📜 {game_label(gt)} — *Lịch sử dự đoán*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"`Phiên        │ Kết quả │ Dự đoán`\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{history_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ *Đúng:* `{correct}` · ❌ *Sai:* `{wrong}` · 🎯 `{acc:.1%}`"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def post_init(application: Application):
    asyncio.create_task(polling_loop(application, "md5"))
    asyncio.create_task(polling_loop(application, "hu"))


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("hoc", cmd_hoc))
    app.add_handler(CommandHandler("his", cmd_his))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()