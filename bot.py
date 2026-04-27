import asyncio
import aiohttp
import random
from collections import deque
from datetime import datetime
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = "8778249747:AAFnLZeDZYuRXVyjJrdQqIndezMe7-kHGs0"

API_URLS = {
    "md5": "https://wtxmd52.tele68.com/v1/txmd5/lite-sessions?cp=R&cl=R&pf=web&at=07d01d98fd85e91efaa91fe492970412",
    "hu":  "https://wtx.tele68.com/v1/tx/lite-sessions?cp=R&cl=R&pf=web&at=07d01d98fd85e91efaa91fe492970412",
}

REQ_HEADERS = {
    "accept": "*/*",
    "accept-language": "vi-VN,vi;q=0.9",
    "Referer": "https://lc79b.bet/",
}

GAME_LABEL = {"md5": "🎮 *LC MD5*", "hu": "🏆 *LC Hũ*"}
DICE_EMO = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣"}

ALGO_NAME_VN = {
    "streak":       "Cầu bệt",
    "break_detect": "Phát hiện gãy cầu",
    "pingpong":     "Cầu 1-1 ping pong",
    "pairs":        "Cầu 2-2 / 3-3",
    "zigzag":       "Cầu zigzag",
    "freq20":       "Tần suất 20 phiên",
    "freq50":       "Tần suất 50 phiên",
    "point_trend":  "Xu hướng điểm số",
    "pattern6":     "Pattern 6 phiên lịch sử",
    "trend":        "Xu hướng tổng thể",
    "dice_avg":     "Trung bình xúc xắc",
    "momentum":     "Đà tăng / giảm điểm",
}


def default_weights():
    return {
        "streak":       1.5,
        "break_detect": 1.8,
        "pingpong":     1.2,
        "pairs":        1.1,
        "zigzag":       0.8,
        "freq20":       1.0,
        "freq50":       0.9,
        "point_trend":  0.7,
        "pattern6":     1.3,
        "trend":        0.9,
        "dice_avg":     0.6,
        "momentum":     1.0,
    }


def make_game():
    return {
        "running":  False,
        "task":     None,
        "history":  deque(maxlen=100),
        "preds":    deque(maxlen=500),
        "last_id":  None,
        "chat_id":  None,
        "weights":  default_weights(),
        "correct":  0,
        "wrong":    0,
        "pending":  None,
    }


STATE = {"md5": make_game(), "hu": make_game()}


def _streak_info(h):
    if not h:
        return None, 0
    last = h[0]["result"]
    streak = 1
    for i in range(1, len(h)):
        if h[i]["result"] == last:
            streak += 1
        else:
            break
    return last, streak


def algo_streak(h):
    last, s = _streak_info(h)
    if s < 2:
        return None, 0
    if s <= 3:
        return last, 52
    return last, 56


def algo_break_detect(h):
    last, s = _streak_info(h)
    if s >= 5:
        opp = "TAI" if last == "XIU" else "XIU"
        return opp, min(82, 60 + (s - 5) * 5)
    return None, 0


def algo_pingpong(h):
    if len(h) < 4:
        return None, 0
    r = [h[i]["result"] for i in range(min(6, len(h)))]
    if all(r[i] != r[i + 1] for i in range(min(5, len(r) - 1))):
        return ("TAI" if r[0] == "XIU" else "XIU"), 68
    if len(r) >= 4 and all(r[i] != r[i + 1] for i in range(3)):
        return ("TAI" if r[0] == "XIU" else "XIU"), 60
    return None, 0


def algo_pairs(h):
    if len(h) < 6:
        return None, 0
    r = [h[i]["result"] for i in range(min(8, len(h)))]
    if len(r) >= 4 and r[0] == r[1] and r[2] == r[3] and r[0] != r[2]:
        return r[0], 62
    if len(r) >= 6 and r[0] == r[1] == r[2] and r[3] == r[4] == r[5] and r[0] != r[3]:
        return r[0], 66
    return None, 0


def algo_zigzag(h):
    if len(h) < 6:
        return None, 0
    r = [h[i]["result"] for i in range(6)]
    changes = [r[i] != r[i + 1] for i in range(5)]
    score = sum(1 for i in range(4) if changes[i] != changes[i + 1])
    if score >= 3:
        pred = r[0] if not changes[0] else ("TAI" if r[0] == "XIU" else "XIU")
        return pred, 57
    return None, 0


def algo_freq20(h):
    n = min(20, len(h))
    if n < 5:
        return None, 0
    tai = sum(1 for i in range(n) if h[i]["result"] == "TAI")
    r = tai / n
    if r > 0.68:
        return "XIU", int(r * 65)
    if r < 0.32:
        return "TAI", int((1 - r) * 65)
    return None, 0


def algo_freq50(h):
    n = min(50, len(h))
    if n < 15:
        return None, 0
    tai = sum(1 for i in range(n) if h[i]["result"] == "TAI")
    r = tai / n
    if r > 0.65:
        return "XIU", int(r * 60)
    if r < 0.35:
        return "TAI", int((1 - r) * 60)
    return None, 0


def algo_point_trend(h):
    if len(h) < 5:
        return None, 0
    avg = sum(h[i]["point"] for i in range(5)) / 5
    if avg > 12.5:
        return "TAI", 56
    if avg < 8.5:
        return "XIU", 56
    return None, 0


def algo_pattern6(h):
    n = len(h)
    if n < 14:
        return None, 0
    pattern = tuple(h[i]["result"] for i in range(6))
    tai_c = xiu_c = 0
    for i in range(6, n - 6):
        win = tuple(h[j]["result"] for j in range(i, i + 6))
        if win == pattern:
            after = h[i - 1]["result"]
            if after == "TAI":
                tai_c += 1
            else:
                xiu_c += 1
    total = tai_c + xiu_c
    if total < 2:
        return None, 0
    if tai_c >= xiu_c:
        return "TAI", min(73, int((tai_c / total) * 75))
    return "XIU", min(73, int((xiu_c / total) * 75))


def algo_trend(h):
    if len(h) < 10:
        return None, 0
    r_tai = sum(1 for i in range(5) if h[i]["result"] == "TAI")
    o_tai = sum(1 for i in range(5, 10) if h[i]["result"] == "TAI")
    diff = r_tai - o_tai
    if diff >= 3:
        return "TAI", 60
    if diff <= -3:
        return "XIU", 60
    return None, 0


def algo_dice_avg(h):
    if len(h) < 8:
        return None, 0
    all_dice = []
    for i in range(min(15, len(h))):
        all_dice.extend(h[i].get("dices", []))
    if not all_dice:
        return None, 0
    avg = sum(all_dice) / len(all_dice)
    if avg > 3.8:
        return "TAI", 54
    if avg < 3.2:
        return "XIU", 54
    return None, 0


def algo_momentum(h):
    if len(h) < 3:
        return None, 0
    p0, p1, p2 = h[0]["point"], h[1]["point"], h[2]["point"]
    if p0 > p1 > p2:
        return "TAI", 55
    if p0 < p1 < p2:
        return "XIU", 55
    return None, 0


ALGOS = {
    "streak":       algo_streak,
    "break_detect": algo_break_detect,
    "pingpong":     algo_pingpong,
    "pairs":        algo_pairs,
    "zigzag":       algo_zigzag,
    "freq20":       algo_freq20,
    "freq50":       algo_freq50,
    "point_trend":  algo_point_trend,
    "pattern6":     algo_pattern6,
    "trend":        algo_trend,
    "dice_avg":     algo_dice_avg,
    "momentum":     algo_momentum,
}


def predict(history, weights):
    if len(history) < 2:
        tai = sum(1 for i in range(len(history)) if history[i]["result"] == "TAI")
        return ("TAI" if tai * 2 >= len(history) else "XIU"), 50

    votes = {"TAI": 0.0, "XIU": 0.0}
    for name, fn in ALGOS.items():
        w = weights.get(name, 1.0)
        pred, conf = fn(history)
        if pred and conf > 0:
            votes[pred] += w * conf

    total = votes["TAI"] + votes["XIU"]
    if total == 0:
        tai = sum(1 for i in range(min(10, len(history))) if history[i]["result"] == "TAI")
        return ("TAI" if tai >= 5 else "XIU"), 50

    tai_r = votes["TAI"] / total
    if tai_r >= 0.5:
        return "TAI", min(95, int(tai_r * 100))
    return "XIU", min(95, int((1 - tai_r) * 100))


async def fetch_api(game_type):
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(
                API_URLS[game_type],
                headers=REQ_HEADERS,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    return data.get("list", [])
    except Exception:
        pass
    return []


def build_msg(game_type, next_id, pred, conf, latest, match=None):
    st = STATE[game_type]
    now = datetime.now().strftime("%H:%M:%S")

    p_emo = "🔴" if pred == "TAI" else "🔵"
    p_txt = "TÀI" if pred == "TAI" else "XỈU"
    r_emo = "🔴" if latest["result"] == "TAI" else "🔵"
    r_txt = "TÀI" if latest["result"] == "TAI" else "XỈU"

    dice_str = " ".join(DICE_EMO.get(d, str(d)) for d in latest.get("dices", []))
    stars = "⭐" * max(1, conf // 20)

    total = st["correct"] + st["wrong"]
    acc_line = ""
    if total > 0:
        acc = int(st["correct"] / total * 100)
        acc_line = f"📈 *Tỉ lệ:* `{st['correct']}/{total}` _({acc}%)_\n"

    match_line = ""
    if match == "correct":
        match_line = "\n✅ *Khớp dự đoán!* 🎉"
    elif match == "wrong":
        match_line = "\n❌ *Lệch dự đoán!* 📉"

    return (
        f"{GAME_LABEL[game_type]}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📌 *Phiên dự đoán:* `{next_id}`\n"
        f"💡 *Dự đoán:* {p_emo} *{p_txt}*\n"
        f"📊 *Tin cậy:* `{conf}%` {stars}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"⏮ *Phiên trước:* `{latest['id']}`\n"
        f"🎲 *Xúc xắc:* {dice_str} _( Σ {latest['point']} )_\n"
        f"🏆 *Kết quả:* {r_emo} *{r_txt}*"
        f"{match_line}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"{acc_line}"
        f"⏰ *Time:* `{now}`"
    )


def parse_entry(s):
    return {
        "id":     s["id"],
        "result": s["resultTruyenThong"],
        "dices":  s.get("dices", []),
        "point":  s.get("point", 0),
    }


async def prediction_loop(bot, game_type):
    st = STATE[game_type]
    try:
        sessions = await fetch_api(game_type)
        if sessions:
            for s in reversed(sessions):
                st["history"].appendleft(parse_entry(s))

            latest = sessions[0]
            st["last_id"] = latest["id"]
            pred, conf = predict(st["history"], st["weights"])
            st["pending"] = {"id": latest["id"] + 1, "pred": pred}

            msg = build_msg(game_type, latest["id"] + 1, pred, conf, st["history"][0])
            await bot.send_message(chat_id=st["chat_id"], text=msg, parse_mode=ParseMode.MARKDOWN)

        while st["running"]:
            await asyncio.sleep(5)

            sessions = await fetch_api(game_type)
            if not sessions:
                continue

            latest_id = sessions[0]["id"]
            if latest_id == st["last_id"]:
                continue

            entry = parse_entry(sessions[0])
            st["history"].appendleft(entry)

            match = None
            if st["pending"] and st["pending"]["id"] == latest_id:
                correct = entry["result"] == st["pending"]["pred"]
                if correct:
                    st["correct"] += 1
                    match = "correct"
                else:
                    st["wrong"] += 1
                    match = "wrong"
                st["preds"].appendleft({
                    "id":      latest_id,
                    "pred":    st["pending"]["pred"],
                    "actual":  entry["result"],
                    "correct": correct,
                })

            st["last_id"] = latest_id
            pred, conf = predict(st["history"], st["weights"])
            st["pending"] = {"id": latest_id + 1, "pred": pred}

            msg = build_msg(game_type, latest_id + 1, pred, conf, entry, match)
            await bot.send_message(chat_id=st["chat_id"], text=msg, parse_mode=ParseMode.MARKDOWN)

    except asyncio.CancelledError:
        pass
    except Exception:
        pass


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args or args[0].lower() not in ("md5", "hu"):
        await update.message.reply_text(
            "⚠️ *Cú pháp:* `/start md5` hoặc `/start hu`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    game = args[0].lower()
    st = STATE[game]

    if st["running"]:
        await update.message.reply_text(
            f"⚡ {GAME_LABEL[game]} *đang chạy rồi!*",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    st["running"] = True
    st["chat_id"] = update.effective_chat.id
    st["last_id"] = None
    st["pending"] = None
    st["correct"] = 0
    st["wrong"]   = 0
    st["weights"] = default_weights()
    st["history"].clear()
    st["preds"].clear()

    await update.message.reply_text(
        f"🚀 {GAME_LABEL[game]}\n*Bắt đầu dự đoán tự động...*\n_Đang tải dữ liệu lịch sử..._",
        parse_mode=ParseMode.MARKDOWN,
    )
    st["task"] = asyncio.create_task(prediction_loop(ctx.bot, game))


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    stopped = []
    for game, st in STATE.items():
        if st["running"] and st["chat_id"] == chat_id:
            st["running"] = False
            if st["task"]:
                st["task"].cancel()
                st["task"] = None
            stopped.append(game)

    if not stopped:
        await update.message.reply_text(
            "⚠️ *Không có bot nào đang chạy.*",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    lines = ["🛑 *Đã dừng dự đoán*\n"]
    for game in stopped:
        st = STATE[game]
        total = st["correct"] + st["wrong"]
        acc = int(st["correct"] / total * 100) if total > 0 else 0
        lines.append(
            f"{GAME_LABEL[game]}\n"
            f"✅ *Đúng:* `{st['correct']}`  ❌ *Sai:* `{st['wrong']}`\n"
            f"📊 *Tỉ lệ:* `{acc}%`"
        )

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_hoc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    results = []
    for game, st in STATE.items():
        preds = list(st["preds"])
        if len(preds) < 5:
            continue

        recent = preds[: min(30, len(preds))]
        acc = sum(1 for p in recent if p["correct"]) / len(recent)
        w = st["weights"]

        if acc < 0.45:
            for k in w:
                w[k] = max(0.3, min(3.0, w[k] + random.uniform(-0.15, 0.25)))
        elif acc < 0.55:
            for k in w:
                w[k] = max(0.3, min(3.0, w[k] + random.uniform(-0.08, 0.15)))
        else:
            for k in w:
                w[k] = max(0.3, min(3.0, w[k] * random.uniform(0.97, 1.07)))

        top3 = sorted(w.items(), key=lambda x: x[1], reverse=True)[:3]
        top_str = "\n".join(
            f"  • _{ALGO_NAME_VN.get(k, k)}_ → `{v:.2f}`" for k, v in top3
        )

        results.append(
            f"{GAME_LABEL[game]}\n"
            f"📚 *Chính xác gần đây:* `{int(acc * 100)}%`\n"
            f"🔧 *Thuật toán mạnh nhất:*\n{top_str}"
        )

    if not results:
        await update.message.reply_text(
            "⚠️ *Chưa đủ dữ liệu để học.*\nChạy thêm nhiều phiên để tích lũy!",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text(
        "🧠 *Đã học tập & nâng cấp thuật toán!*\n\n" + "\n\n".join(results),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_his(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lines = []
    for game, st in STATE.items():
        preds = list(st["preds"])
        if not preds:
            continue
        lines.append(f"{GAME_LABEL[game]}")
        lines.append("`Phiên      Dự Đoán  KQ      Kết`")
        lines.append("`" + "─" * 34 + "`")
        for p in preds[:20]:
            pd = "TÀI " if p["pred"]   == "TAI" else "XỈU "
            ac = "TÀI " if p["actual"] == "TAI" else "XỈU "
            rs = "✅" if p["correct"] else "❌"
            lines.append(f"`{str(p['id']):<10} {pd:<9}{ac:<8}` {rs}")
        lines.append("")

    if not lines:
        await update.message.reply_text(
            "⚠️ *Chưa có lịch sử dự đoán.*",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop",  cmd_stop))
    app.add_handler(CommandHandler("hoc",   cmd_hoc))
    app.add_handler(CommandHandler("his",   cmd_his))
    print("✅ Bot đang chạy...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
