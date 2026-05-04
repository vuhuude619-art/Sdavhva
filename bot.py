"""
╔══════════════════════════════════════════════════════════════╗
║         🎰  VIP PREDICTION BOT ULTRA  🎰                     ║
║         Advanced AI Prediction Engine v3.0                  ║
║         Pattern Learning + Auto Algorithm + Inline Buttons  ║
║         Multi-User Support + Ultra Fast 0.5s Updates        ║
╚══════════════════════════════════════════════════════════════╝
"""

import asyncio
import json
import logging
import math
import time
from collections import deque, Counter
from datetime import datetime
from typing import Dict

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ==================== CONFIGURATION ====================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8539748390:AAGHZzrCnyVL7ZMFvFHXvCSV0FKROPKC7R8"
MD5_API = "https://wtxmd52.tele68.com/v1/txmd5/lite-sessions?cp=R&cl=R&pf=web&at=07d01d98fd85e91efaa91fe492970412"
HU_API = "https://wtx.tele68.com/v1/tx/lite-sessions?cp=R&cl=R&pf=web&at=07d01d98fd85e91efaa91fe492970412"
CHAT_WS_URL = "wss://wchat.tele68.com/chat/?EIO=4&transport=websocket"
DATA_FILE = "pattern_data.json"

# ==================== MULTI-USER STATE ====================

USER_STATES: Dict[int, dict] = {}

def get_user_state(user_id: int) -> dict:
    """Lấy hoặc tạo state riêng cho từng user"""
    if user_id not in USER_STATES:
        USER_STATES[user_id] = {
            "predictors": {
                "md5": AdvancedPredictor("md5"),
                "hu": AdvancedPredictor("hu")
            },
            "enable": {"md5": False, "hu": False},
            "pending": {"md5": None, "hu": None},
            "tasks": {},
            "last_session_ids": {"md5": None, "hu": None},
            "win_streak": {"md5": 0, "hu": 0},
            "lose_streak": {"md5": 0, "hu": 0},
            "total_wins": {"md5": 0, "hu": 0},
            "total_games": {"md5": 0, "hu": 0},
            "session_start_time": {"md5": None, "hu": None},
            "prediction_history": [],
            "accounts": {},  # Acc hô riêng
            "shout_tasks": {},
            "shout_queues": {},
        }
    return USER_STATES[user_id]

# ==================== PATTERN DATABASE ====================

def load_pattern_data() -> dict:
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except:
        return {
            "patterns": {"md5": {}, "hu": {}},
            "algo_weights": {
                "streak": 1.0, "alternating": 1.0, "pattern6": 1.0,
                "ma10": 1.0, "freq5": 1.0, "markov2": 1.0, "markov3": 1.0,
                "entropy": 1.0, "zigzag": 1.0, "bayes": 1.0, "neural": 1.0,
            },
            "algo_correct": {k: 0 for k in ["streak","alternating","pattern6","ma10","freq5","markov2","markov3","entropy","zigzag","bayes","neural"]},
            "algo_total": {k: 0 for k in ["streak","alternating","pattern6","ma10","freq5","markov2","markov3","entropy","zigzag","bayes","neural"]},
            "version": 3,
            "last_update": "",
        }

def save_pattern_data(data: dict):
    data["last_update"] = datetime.now().isoformat()
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

PATTERN_DB = load_pattern_data()

# ==================== UTILITY FUNCTIONS ====================

def box_message(title: str, content: list, width: int = 45) -> str:
    """Tạo message dạng box đẹp"""
    lines = []
    lines.append(f"╔{'═' * (width - 2)}╗")
    lines.append(f"║ {title:^{width - 4}}║")
    lines.append(f"╠{'═' * (width - 2)}╣")
    for line in content:
        lines.append(f"║ {line:<{width - 4}}║")
    lines.append(f"╚{'═' * (width - 2)}╝")
    return "```\n" + "\n".join(lines) + "\n```"

def format_dices(dices: list) -> str:
    dice_emoji = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}
    return " ".join(dice_emoji.get(int(d), str(d)) for d in dices)

def get_game_emoji(game: str) -> str:
    return "🎲" if game == "md5" else "🎱"

def get_game_name(game: str) -> str:
    return "MD5" if game == "md5" else "HŨ"

def progress_bar(val: float, max_val: float = 100, length: int = 16) -> str:
    filled = int((val / max_val) * length)
    return "█" * filled + "░" * (length - filled)

# ==================== ADVANCED PREDICTOR ====================

class AdvancedPredictor:
    def __init__(self, game: str):
        self.game = game
        self.history = deque(maxlen=500)
        self.points = deque(maxlen=500)
        self.dices_history = deque(maxlen=500)
        self.last_votes = {}
        self.consecutive_correct = 0
        self.consecutive_wrong = 0

    def add(self, result_str: str, point: float, dices: list):
        self.history.append(result_str == "TAI")
        self.points.append(point)
        self.dices_history.append(dices)
        
        # Học pattern vào database
        h = list(self.history)
        for length in range(2, min(10, len(h))):
            if len(h) > length:
                seq = tuple(h[-(length + 1):-1])
                key = "".join("T" if x else "X" for x in seq)
                if key not in PATTERN_DB["patterns"][self.game]:
                    PATTERN_DB["patterns"][self.game][key] = {"T": 0, "X": 0}
                PATTERN_DB["patterns"][self.game][key]["T" if result_str == "TAI" else "X"] += 1

    def _streak_signal(self) -> tuple:
        if len(self.history) < 3:
            return "TAI", 0.0
        h = list(self.history)
        last = h[-1]
        streak = 1
        for i in range(len(h) - 2, -1, -1):
            if h[i] == last:
                streak += 1
            else:
                break
        if streak >= 7:
            return ("XIU" if last else "TAI"), min(45.0, streak * 6.5)
        elif streak >= 5:
            return ("XIU" if last else "TAI"), 35.0
        elif streak >= 3:
            return ("XIU" if last else "TAI"), 25.0
        elif streak == 2:
            return ("TAI" if last else "XIU"), 15.0
        return ("TAI" if last else "XIU"), 8.0

    def _alternating_signal(self) -> tuple:
        if len(self.history) < 6:
            return "TAI", 0.0
        h = list(self.history)[-10:]
        groups = []
        i = 0
        while i < len(h):
            j = i
            while j < len(h) and h[j] == h[i]:
                j += 1
            groups.append((h[i], j - i))
            i = j
        
        if len(groups) >= 3:
            last_val, last_len = groups[-1]
            prev_val, prev_len = groups[-2]
            pprev_val, pprev_len = groups[-3]
            
            # Pattern 1-1-1 hoặc 2-2-2
            if prev_len == last_len and pprev_len == prev_len and len(groups) >= 3:
                if last_val != prev_val and prev_val != pprev_val:
                    return ("TAI" if not last_val else "XIU"), 35.0
            
            # Pattern alternating
            if last_len == 1 and prev_len == 1:
                return ("TAI" if not last_val else "XIU"), 25.0
                
        return "TAI", 0.0

    def _pattern_db_signal(self, length: int = 6) -> tuple:
        if len(self.history) < length:
            return "TAI", 0.0
        h = list(self.history)
        seq = h[-length:]
        key = "".join("T" if x else "X" for x in seq)
        db = PATTERN_DB["patterns"][self.game]
        
        if key not in db:
            return "TAI", 0.0
        
        t, x = db[key]["T"], db[key]["X"]
        total = t + x
        if total < 3:
            return "TAI", 0.0
        
        if t > x:
            return "TAI", round((t / total) * 50, 1)
        elif x > t:
            return "XIU", round((x / total) * 50, 1)
        return "TAI", 0.0

    def _markov2_signal(self) -> tuple:
        if len(self.history) < 5:
            return "TAI", 0.0
        h = list(self.history)
        last2 = tuple(h[-2:])
        counts = Counter()
        for i in range(len(h) - 3):
            if tuple(h[i:i+2]) == last2:
                counts[h[i+2]] += 1
        total = sum(counts.values())
        if total < 2:
            return "TAI", 0.0
        tai_p = counts[True] / total
        xiu_p = counts[False] / total
        if tai_p > xiu_p:
            return "TAI", round(tai_p * 40, 1)
        elif xiu_p > tai_p:
            return "XIU", round(xiu_p * 40, 1)
        return "TAI", 0.0

    def _markov3_signal(self) -> tuple:
        if len(self.history) < 7:
            return "TAI", 0.0
        h = list(self.history)
        last3 = tuple(h[-3:])
        counts = Counter()
        for i in range(len(h) - 4):
            if tuple(h[i:i+3]) == last3:
                counts[h[i+3]] += 1
        total = sum(counts.values())
        if total < 2:
            return "TAI", 0.0
        tai_p = counts[True] / total
        xiu_p = counts[False] / total
        if tai_p > xiu_p:
            return "TAI", round(tai_p * 45, 1)
        elif xiu_p > tai_p:
            return "XIU", round(xiu_p * 45, 1)
        return "TAI", 0.0

    def _ma10_signal(self) -> tuple:
        if len(self.points) < 10:
            return "TAI", 0.0
        ma = sum(list(self.points)[-10:]) / 10
        diff = abs(ma - 10.5)
        confidence = min(25.0, diff * 10)
        return ("TAI" if ma > 10.5 else "XIU"), confidence

    def _freq5_signal(self) -> tuple:
        if len(self.history) < 5:
            return "TAI", 0.0
        last5 = list(self.history)[-5:]
        tai_c = sum(last5)
        xiu_c = 5 - tai_c
        if tai_c >= 4:
            return "TAI", 22.0
        elif xiu_c >= 4:
            return "XIU", 22.0
        elif tai_c == 3:
            return "XIU", 12.0
        elif xiu_c == 3:
            return "TAI", 12.0
        return "TAI", 0.0

    def _entropy_signal(self) -> tuple:
        if len(self.history) < 12:
            return "TAI", 0.0
        recent = list(self.history)[-12:]
        tai_p = sum(recent) / 12
        xiu_p = 1 - tai_p
        if tai_p == 0 or xiu_p == 0:
            entropy = 0.0
        else:
            entropy = -(tai_p * math.log2(tai_p) + xiu_p * math.log2(xiu_p))
        
        if entropy < 0.6:
            return ("TAI" if tai_p > 0.5 else "XIU"), round((1 - entropy) * 25, 1)
        elif entropy > 0.95:
            return ("XIU" if recent[-1] else "TAI"), 15.0
        return "TAI", 0.0

    def _zigzag_signal(self) -> tuple:
        if len(self.history) < 10:
            return "TAI", 0.0
        h = list(self.history)[-12:]
        flips = sum(1 for i in range(1, len(h)) if h[i] != h[i-1])
        if flips >= 8:
            return ("TAI" if not h[-1] else "XIU"), 25.0
        elif flips <= 3:
            return ("TAI" if h[-1] else "XIU"), 18.0
        return "TAI", 0.0

    def _bayes_signal(self) -> tuple:
        if len(self.history) < 20:
            return "TAI", 0.0
        h = list(self.history)[-30:]
        tai_count = sum(h)
        xiu_count = len(h) - tai_count
        prior_tai = tai_count / len(h)
        prior_xiu = xiu_count / len(h)
        
        if len(h) >= 2:
            last2 = h[-2:]
            match_tai = 0
            match_xiu = 0
            for i in range(len(h) - 2):
                if h[i] == last2[0] and h[i+1] == last2[1]:
                    if h[i+2]:
                        match_tai += 1
                    else:
                        match_xiu += 1
            total_match = match_tai + match_xiu
            if total_match > 0:
                post_tai = (prior_tai * (match_tai + 1)) / (total_match + 2)
                post_xiu = (prior_xiu * (match_xiu + 1)) / (total_match + 2)
                if post_tai > post_xiu:
                    return "TAI", round(post_tai * 38, 1)
                else:
                    return "XIU", round(post_xiu * 38, 1)
        return "TAI", 0.0

    def _neural_signal(self) -> tuple:
        if len(self.history) < 15:
            return "TAI", 0.0
        h = list(self.history)[-20:]
        weights = [0.05, 0.08, 0.1, 0.12, 0.15, 0.15, 0.15, 0.1, 0.05, 0.05]
        while len(weights) < len(h):
            weights.append(0.02)
        
        weighted_sum = 0
        for i in range(min(len(h), len(weights))):
            idx = -(i + 1)
            weighted_sum += h[idx] * weights[i]
        
        threshold = sum(weights[:min(len(h), len(weights))]) / 2
        confidence = min(28.0, abs(weighted_sum - threshold) * 60)
        
        if weighted_sum > threshold:
            return "TAI", confidence
        else:
            return "XIU", confidence

    def predict(self) -> dict:
        w = PATTERN_DB["algo_weights"]
        signals = {
            "streak": self._streak_signal(),
            "alternating": self._alternating_signal(),
            "pattern6": self._pattern_db_signal(6),
            "markov2": self._markov2_signal(),
            "markov3": self._markov3_signal(),
            "ma10": self._ma10_signal(),
            "freq5": self._freq5_signal(),
            "entropy": self._entropy_signal(),
            "zigzag": self._zigzag_signal(),
            "bayes": self._bayes_signal(),
            "neural": self._neural_signal(),
        }
        
        scores = {"TAI": 0.0, "XIU": 0.0}
        detail = {}
        
        # Adaptive boosting: tăng weight cho algo đang đúng liên tục
        boost = 1.0
        if self.consecutive_correct >= 3:
            boost = 1.5
        elif self.consecutive_wrong >= 3:
            boost = 0.7
        
        for name, (pred, conf) in signals.items():
            weight = w.get(name, 1.0) * boost
            wconf = conf * weight
            scores[pred] += wconf
            detail[name] = {"pred": pred, "conf": round(conf, 1), "w": round(weight, 2)}
        
        total = scores["TAI"] + scores["XIU"]
        if total == 0:
            result, conf = "TAI", 50.0
        elif scores["TAI"] >= scores["XIU"]:
            result = "TAI"
            conf = round((scores["TAI"] / total) * 100, 1)
        else:
            result = "XIU"
            conf = round((scores["XIU"] / total) * 100, 1)
        
        self.last_votes = {name: (pred, conf) for name, (pred, conf) in signals.items()}
        
        # Confidence tier
        if conf >= 85:
            tier = "🔥 SIÊU MẠNH"
        elif conf >= 75:
            tier = "⚡ RẤT MẠNH"
        elif conf >= 65:
            tier = "✅ KHÁ"
        elif conf >= 55:
            tier = "📊 TRUNG BÌNH"
        else:
            tier = "⚠️ YẾU"
        
        return {
            "result": result,
            "confidence": conf,
            "tier": tier,
            "detail": detail,
            "scores": {k: round(v, 1) for k, v in scores.items()}
        }

    def record_actual(self, actual_str: str):
        for algo, (voted, _) in self.last_votes.items():
            PATTERN_DB["algo_total"][algo] = PATTERN_DB["algo_total"].get(algo, 0) + 1
            if voted == actual_str:
                PATTERN_DB["algo_correct"][algo] = PATTERN_DB["algo_correct"].get(algo, 0) + 1

# ==================== AUTO WEIGHT UPDATE ====================

def recalculate_weights():
    weights = PATTERN_DB["algo_weights"]
    correct = PATTERN_DB["algo_correct"]
    total = PATTERN_DB["algo_total"]
    
    for algo in weights.keys():
        n = total.get(algo, 0)
        if n < 10:
            continue
        acc = correct.get(algo, 0) / n
        # Công thức cải tiến: dùng sigmoid-based
        x = (acc - 0.5) * 10
        weights[algo] = round(2.5 / (1 + math.exp(-x)), 3)
    
    save_pattern_data(PATTERN_DB)

async def auto_weight_update_loop():
    while True:
        await asyncio.sleep(30)
        recalculate_weights()
        logger.debug("Weights updated")

# ==================== API FUNCTIONS ====================

async def fetch_sessions(game_type: str):
    url = MD5_API if game_type == "md5" else HU_API
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                return await resp.json()
    except Exception as e:
        logger.error(f"Fetch error [{game_type}]: {e}")
        return None

# ==================== PREDICTION LOGIC ====================

async def process_new_session(user_id: int, game: str, session_data: dict, bot):
    state = get_user_state(user_id)
    rid = session_data["id"]
    result = session_data["resultTruyenThong"]
    point = session_data["point"]
    dices = session_data["dices"]
    
    # Record actual result
    state["predictors"][game].record_actual(result)
    state["predictors"][game].add(result, point, dices)
    
    pending = state["pending"][game]
    correct = None
    
    if pending and pending["session_id"] == rid:
        correct = (pending["predicted"] == result)
        state["prediction_history"].append({
            "game": game,
            "session_id": rid,
            "result": result,
            "predicted": pending["predicted"],
            "confidence": pending["confidence"],
            "correct": correct,
            "timestamp": datetime.now().isoformat(),
        })
        
        state["total_games"][game] += 1
        if correct:
            state["total_wins"][game] += 1
            state["win_streak"][game] += 1
            state["lose_streak"][game] = 0
            state["predictors"][game].consecutive_correct += 1
            state["predictors"][game].consecutive_wrong = 0
        else:
            state["win_streak"][game] = 0
            state["lose_streak"][game] += 1
            state["predictors"][game].consecutive_correct = 0
            state["predictors"][game].consecutive_wrong += 1
        
        # Gửi kết quả
        pred_emoji = "🟢" if pending["predicted"] == "TAI" else "🔴"
        result_emoji = "🟢" if result == "TAI" else "🔴"
        ok_emoji = "✅" if correct else "❌"
        
        wr = (state["total_wins"][game] / state["total_games"][game] * 100) if state["total_games"][game] > 0 else 0
        
        content = [
            f"{get_game_emoji(game)} Phiên: {rid}",
            f"🎲 Xúc xắc: {format_dices(dices)}",
            f"📊 Điểm: {point}",
            f"🏆 Kết quả: {result_emoji} {result}",
            f"🤖 Dự đoán: {pred_emoji} {pending['predicted']}",
            f"📈 Độ tin cậy: {pending['confidence']}%",
            f"{ok_emoji} {'ĐÚNG!' if correct else 'SAI!'}",
            f"🏅 Win rate: {wr:.1f}%",
            f"🔥 Streak: {state['win_streak'][game]}W / {state['lose_streak'][game]}L",
        ]
        
        msg = box_message("KẾT QUẢ", content, 40)
        
        if state["enable"][game]:
            await bot.send_message(chat_id=user_id, text=msg, parse_mode=ParseMode.MARKDOWN)
    
    # Tạo dự đoán mới
    new_pred = state["predictors"][game].predict()
    state["pending"][game] = {
        "session_id": rid + 1,
        "predicted": new_pred["result"],
        "confidence": new_pred["confidence"],
        "tier": new_pred["tier"],
    }
    
    if state["enable"][game]:
        conf_bar = progress_bar(new_pred["confidence"])
        pred_emoji = "🟢" if new_pred["result"] == "TAI" else "🔴"
        
        content = [
            f"{get_game_emoji(game)} Game: {get_game_name(game)}",
            f"🔮 DỰ ĐOÁN PHIÊN {rid + 1}",
            f"{pred_emoji} Kết quả: {new_pred['result']}",
            f"📊 {new_pred['tier']}",
            f"📈 [{conf_bar}] {new_pred['confidence']}%",
        ]
        
        pred_msg = box_message("DỰ ĐOÁN MỚI", content, 40)
        await bot.send_message(chat_id=user_id, text=pred_msg, parse_mode=ParseMode.MARKDOWN)

async def prediction_loop(user_id: int, game: str, bot):
    state = get_user_state(user_id)
    
    while state["enable"].get(game, False):
        try:
            data = await fetch_sessions(game)
            if data and "list" in data and data["list"]:
                latest = data["list"][0]
                if latest["id"] != state["last_session_ids"][game]:
                    await process_new_session(user_id, game, latest, bot)
                    state["last_session_ids"][game] = latest["id"]
        except Exception as e:
            logger.error(f"Loop error [user={user_id}, game={game}]: {e}")
        
        await asyncio.sleep(0.5)  # 0.5 giây cập nhật 1 lần

# ==================== COMMAND HANDLERS ====================

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.args:
        keyboard = [
            [InlineKeyboardButton("🎲 MD5", callback_data="start_md5"),
             InlineKeyboardButton("🎱 HŨ", callback_data="start_hu")],
            [InlineKeyboardButton("📊 Thống kê", callback_data="stats"),
             InlineKeyboardButton("📋 Lịch sử", callback_data="his")],
            [InlineKeyboardButton("🧠 Thuật toán", callback_data="algo"),
             InlineKeyboardButton("📚 Học máy", callback_data="hoc")],
            [InlineKeyboardButton("⏹ Dừng tất cả", callback_data="stop_all")],
        ]
        
        content = [
            "🎰 VIP ",
            "VI-AI-PI × PỜ RAI VẾT",
            "",
            "Chọn game để bắt đầu:",
        ]
        msg = box_message("CHÀO MỪNG", content, 42)
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    game = context.args[0].lower()
    if game in ["md5", "hu"]:
        await start_prediction(update, context, game)
    else:
        content = ["Dùng /start md5 hoặc /start hu"]
        msg = box_message("LỖI", content, 35)
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def start_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE, game: str):
    user_id = update.effective_user.id
    state = get_user_state(user_id)
    
    if state["enable"][game]:
        content = [f"{get_game_emoji(game)} {get_game_name(game)} đã đang chạy!"]
        msg = box_message("CẢNH BÁO", content, 40)
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return
    
    state["enable"][game] = True
    state["session_start_time"][game] = datetime.now()
    state["win_streak"][game] = 0
    state["lose_streak"][game] = 0
    
    data = await fetch_sessions(game)
    if not data or "list" not in data or not data["list"]:
        content = ["Không thể tải dữ liệu từ server"]
        msg = box_message("LỖI", content, 40)
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        state["enable"][game] = False
        return
    
    latest = data["list"][0]
    state["last_session_ids"][game] = latest["id"]
    state["predictors"][game].add(latest["resultTruyenThong"], latest["point"], latest["dices"])
    
    new_pred = state["predictors"][game].predict()
    state["pending"][game] = {
        "session_id": latest["id"] + 1,
        "predicted": new_pred["result"],
        "confidence": new_pred["confidence"],
        "tier": new_pred["tier"],
    }
    
    total_patterns = sum(e["T"] + e["X"] for e in PATTERN_DB["patterns"][game].values())
    conf_bar = progress_bar(new_pred["confidence"])
    pred_emoji = "🟢" if new_pred["result"] == "TAI" else "🔴"
    
    content = [
        f"📍 Phiên gần nhất: {latest['id']}",
        f"🎲 Xúc xắc: {format_dices(latest['dices'])}",
        f"📊 Kết quả: {latest['resultTruyenThong']}",
        f"🔢 Điểm: {latest['point']}",
        "",
        f"🔮 DỰ ĐOÁN PHIÊN {latest['id'] + 1}",
        f"{pred_emoji} Kết quả: {new_pred['result']}",
        f"📊 {new_pred['tier']}",
        f"📈 [{conf_bar}] {new_pred['confidence']}%",
        "",
        f"🧠 Patterns: {total_patterns}",
    ]
    
    msg = box_message(f"BẮT ĐẦU {get_game_name(game)}", content, 42)
    
    if update.message:
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    
    task = asyncio.create_task(prediction_loop(user_id, game, context.bot))
    state["tasks"][game] = task

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_user_state(user_id)
    
    game = context.args[0].lower() if context.args else None
    targets = [game] if game in ["md5", "hu"] else ["md5", "hu"]
    stopped = []
    
    for g in targets:
        if g in state["tasks"] and state["enable"][g]:
            state["enable"][g] = False
            state["tasks"][g].cancel()
            del state["tasks"][g]
            stopped.append(get_game_name(g))
    
    if stopped:
        save_pattern_data(PATTERN_DB)
        content = [f"Đã dừng: {', '.join(stopped)}"]
        msg = box_message("DỪNG", content, 40)
    else:
        content = ["Không có dự đoán đang chạy"]
        msg = box_message("THÔNG BÁO", content, 40)
    
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_user_state(user_id)
    
    content = []
    for game in ["md5", "hu"]:
        g = state["total_games"][game]
        w = state["total_wins"][game]
        wr = f"{w/g*100:.1f}%" if g > 0 else "N/A"
        pat = sum(e["T"] + e["X"] for e in PATTERN_DB["patterns"][game].values())
        
        content.append(f"{get_game_emoji(game)} {get_game_name(game)}")
        content.append(f"  Win: {w}/{g} ({wr})")
        content.append(f"  Streak: {state['win_streak'][game]}W/{state['lose_streak'][game]}L")
        content.append(f"  Patterns: {pat}")
        content.append("")
    
    total_p = sum(sum(e["T"] + e["X"] for e in PATTERN_DB["patterns"][g].values()) for g in ["md5", "hu"])
    content.append(f"🧠 Tổng patterns: {total_p}")
    content.append(f"⚙️ Auto-weight: ON")
    
    msg = box_message("THỐNG KÊ", content, 42)
    
    if update.message:
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def algo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    w = PATTERN_DB["algo_weights"]
    c = PATTERN_DB["algo_correct"]
    t = PATTERN_DB["algo_total"]
    
    algo_names = {
        "streak": "Streak Analyzer",
        "alternating": "Alternating Wave",
        "pattern6": "Pattern-6 DB",
        "markov2": "Markov Chain-2",
        "markov3": "Markov Chain-3",
        "ma10": "Moving Avg MA-10",
        "freq5": "Frequency-5",
        "entropy": "Entropy Analyzer",
        "zigzag": "Zigzag Detector",
        "bayes": "Bayesian Inf.",
        "neural": "Neural Pattern",
    }
    
    content = []
    for k, name in algo_names.items():
        wt = w.get(k, 1.0)
        acc = (c.get(k, 0) / t.get(k, 1) * 100) if t.get(k, 0) >= 5 else -1
        acc_str = f"{acc:.1f}%" if acc >= 0 else "N/A"
        content.append(f"{name:<20} W:{wt:.2f} A:{acc_str}")
    
    msg = box_message("THUẬT TOÁN & TRỌNG SỐ", content, 48)
    
    if update.message:
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def hoc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_p = sum(sum(e["T"] + e["X"] for e in PATTERN_DB["patterns"][g].values()) for g in ["md5", "hu"])
    
    content = [
        "📚 CÁC KỸ THUẬT AI ĐÃ TRIỂN KHAI:",
        " ",
        "① Streak Analysis - Phân tích cầu",
        "② Pattern Database - Pattern 2-9",
        "③ Markov Chain (bậc 2 & 3)",
        "④ Bayesian Inference",
        "⑤ Neural-like Pattern",
        "⑥ Auto Weight Update (30s)",
        " ",
        f"💾 Patterns đã học: {total_p}",
        f"🔄 Last update: {PATTERN_DB.get('last_update','N/A')[:16]}",
    ]
    
    msg = box_message("HỆ THỐNG HỌC MÁY", content, 48)
    
    if update.message:
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def his_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_user_state(user_id)
    
    if not state["prediction_history"]:
        content = ["Chưa có lịch sử dự đoán"]
        msg = box_message("LỊCH SỬ", content, 40)
        if update.message:
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        elif update.callback_query:
            await update.callback_query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return
    
    recent = state["prediction_history"][-15:]
    
    content = []
    for h in recent:
        mark = "✅" if h["correct"] else "❌"
        g_name = get_game_name(h["game"])
        conf = f"{h.get('confidence', 0):.0f}%"
        content.append(f"{h['session_id']:>5} {g_name} {h['result']} {mark} {conf}")
    
    correct_c = sum(1 for h in recent if h["correct"])
    content.append(f"\n✅ Đúng: {correct_c}/15 ({correct_c/15*100:.0f}%)")
    
    msg = box_message("LỊCH SỬ (15 gần nhất)", content, 48)
    
    if update.message:
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global PATTERN_DB
    PATTERN_DB = {
        "patterns": {"md5": {}, "hu": {}},
        "algo_weights": {k: 1.0 for k in ["streak","alternating","pattern6","ma10","freq5","markov2","markov3","entropy","zigzag","bayes","neural"]},
        "algo_correct": {k: 0 for k in ["streak","alternating","pattern6","ma10","freq5","markov2","markov3","entropy","zigzag","bayes","neural"]},
        "algo_total": {k: 0 for k in ["streak","alternating","pattern6","ma10","freq5","markov2","markov3","entropy","zigzag","bayes","neural"]},
        "version": 3,
        "last_update": "",
    }
    save_pattern_data(PATTERN_DB)
    
    content = ["Đã reset toàn bộ dữ liệu học", "Tất cả weights về 1.0"]
    msg = box_message("RESET", content, 42)
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_user_state(user_id)
    
    if not state["accounts"]:
        content = ["Chưa có account nào", "Dùng /themacc để thêm"]
        msg = box_message("DANH SÁCH ACC", content, 42)
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return
    
    content = []
    for name, info in state["accounts"].items():
        content.append(f"💠 {name}")
        content.append(f"   User: @{info['username']}")
        content.append(f"   Biệt danh: {info['bietdanh']}")
        content.append("")
    
    msg = box_message("DANH SÁCH ACC", content, 42)
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def themacc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_user_state(user_id)
    
    if len(context.args) < 4:
        content = [
            "Cách dùng:",
            "/themacc tenacc username bietdanh token"
        ]
        msg = box_message("HƯỚNG DẪN", content, 48)
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return
    
    tenacc, username, bietdanh, token = context.args[0], context.args[1], context.args[2], context.args[3]
    state["accounts"][tenacc] = {
        "username": username,
        "bietdanh": bietdanh,
        "token": token
    }
    
    content = [
        f"✅ ĐÃ THÊM ACC",
        f"Tên: {tenacc}",
        f"Biệt danh: {bietdanh}",
    ]
    msg = box_message("THÊM ACC", content, 42)
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎲 MD5", callback_data="start_md5"),
         InlineKeyboardButton("🎱 HŨ", callback_data="start_hu")],
        [InlineKeyboardButton("⏹ Dừng tất cả", callback_data="stop_all")],
        [InlineKeyboardButton("📊 Thống kê", callback_data="stats"),
         InlineKeyboardButton("📋 Lịch sử", callback_data="his")],
        [InlineKeyboardButton("🧠 Thuật toán", callback_data="algo"),
         InlineKeyboardButton("📚 Học máy", callback_data="hoc")],
    ]
    
    content = [
        "AI PỜ RAI VẾT  "
        "",
        "🎮 LỆNH:",
        "/start md5 - Bắt đầu MD5",
        "/start hu - Bắt đầu HŨ",
        "/stop - Dừng tất cả",
        "/stop md5 - Dừng MD5",
        "/stats - Thống kê",
        "/his - Lịch sử",
        "/algo - Thuật toán",
        "/hoc - Học máy",
        "/reset - Reset DB",
        "",
        "👤 ACC HÔ:",
        "/themacc - Thêm acc",
        "/list - Danh sách acc",
    ]
    
    msg = box_message("TRỢ GIÚP", content, 42)
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

# ==================== BUTTON CALLBACK ====================

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "start_md5":
        await start_prediction_from_callback(query, context, "md5")
    elif data == "start_hu":
        await start_prediction_from_callback(query, context, "hu")
    elif data == "stop_all":
        user_id = update.effective_user.id
        state = get_user_state(user_id)
        
        for g in ["md5", "hu"]:
            if g in state["tasks"] and state["enable"][g]:
                state["enable"][g] = False
                state["tasks"][g].cancel()
                del state["tasks"][g]
        
        save_pattern_data(PATTERN_DB)
        content = ["Đã dừng tất cả dự đoán"]
        msg = box_message("DỪNG", content, 40)
        await query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    
    elif data == "stats":
        await stats_cmd(update, context)
    elif data == "his":
        await his_cmd(update, context)
    elif data == "algo":
        await algo_cmd(update, context)
    elif data == "hoc":
        await hoc_cmd(update, context)

async def start_prediction_from_callback(query, context, game: str):
    user_id = query.from_user.id
    state = get_user_state(user_id)
    
    if state["enable"][game]:
        content = [f"{get_game_emoji(game)} {get_game_name(game)} đã đang chạy!"]
        msg = box_message("CẢNH BÁO", content, 40)
        await query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return
    
    state["enable"][game] = True
    state["session_start_time"][game] = datetime.now()
    state["win_streak"][game] = 0
    state["lose_streak"][game] = 0
    
    data = await fetch_sessions(game)
    if not data or "list" not in data or not data["list"]:
        content = ["Không thể tải dữ liệu"]
        msg = box_message("LỖI", content, 40)
        await query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        state["enable"][game] = False
        return
    
    latest = data["list"][0]
    state["last_session_ids"][game] = latest["id"]
    state["predictors"][game].add(latest["resultTruyenThong"], latest["point"], latest["dices"])
    
    new_pred = state["predictors"][game].predict()
    state["pending"][game] = {
        "session_id": latest["id"] + 1,
        "predicted": new_pred["result"],
        "confidence": new_pred["confidence"],
        "tier": new_pred["tier"],
    }
    
    total_patterns = sum(e["T"] + e["X"] for e in PATTERN_DB["patterns"][game].values())
    conf_bar = progress_bar(new_pred["confidence"])
    pred_emoji = "🟢" if new_pred["result"] == "TAI" else "🔴"
    
    content = [
        f"📍 Phiên gần nhất: {latest['id']}",
        f"🎲 Xúc xắc:{format_dices(latest['dices'])}",
        f"📊 Kết quả: {latest['resultTruyenThong']}",
        f"🔢 Điểm: {latest['point']}",
        "",
        f" 🔮 DỰ ĐOÁN PHIÊN {latest['id'] + 1}",
        f"{pred_emoji} Kết quả: {new_pred['result']}",
        f"📊 {new_pred['tier']}",
        f"📈 [{conf_bar}] {new_pred['confidence']}%",
        "",
        f"🧠 Patterns: {total_patterns}",
    ]
    
    msg = box_message(f"BẮT ĐẦU {get_game_name(game)}", content, 42)
    await query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    
    task = asyncio.create_task(prediction_loop(user_id, game, context.bot))
    state["tasks"][game] = task

# ==================== MAIN ====================

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("algo", algo_cmd))
    app.add_handler(CommandHandler("hoc", hoc_cmd))
    app.add_handler(CommandHandler("his", his_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("themacc", themacc_cmd))
    
    # Callback handler
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Post init
    async def post_init(app):
        asyncio.create_task(auto_weight_update_loop())
        logger.info("🚀 Multi-User Bot Started! 0.5s update interval!")
    
    app.post_init = post_init
    
    logger.info("╔════════════════════════════════════════════╗")
    logger.info("║   🎰  VIP PREDICTION BOT ULTRA v3.0      ║")
    logger.info("║   Multi-User | 0.5s Updates | 11 Algo    ║")
    logger.info("╚════════════════════════════════════════════╝")
    
    app.run_polling()

if __name__ == "__main__":
    main()