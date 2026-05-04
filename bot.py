"""
╔══════════════════════════════════════════════════════════════╗
║         🎰  VIP PREDICTION BOT ULTRA  🎰                     ║
║         Advanced AI Prediction Engine v4.0                  ║
║         Deep Learning + Ensemble + Auto Evolution           ║
║         Multi-User Support + Ultra Fast 0.5s Updates        ║
╚══════════════════════════════════════════════════════════════╝
"""

import asyncio
import json
import logging
import math
import time
from collections import deque, Counter, defaultdict
from datetime import datetime
from typing import Dict, List, Tuple

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
                "md5": UltraPredictor("md5"),
                "hu": UltraPredictor("hu")
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
            "accounts": {},
            "shout_tasks": {},
            "shout_queues": {},
        }
    return USER_STATES[user_id]

# ==================== PATTERN DATABASE ====================

def load_pattern_data() -> dict:
    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
            # Đảm bảo có đủ key mới
            if "deep_patterns" not in data:
                data["deep_patterns"] = {"md5": {}, "hu": {}}
            if "time_patterns" not in data:
                data["time_patterns"] = {"md5": {}, "hu": {}}
            if "point_ranges" not in data:
                data["point_ranges"] = {"md5": {"TAI": [], "XIU": []}, "hu": {"TAI": [], "XIU": []}}
            return data
    except:
        return {
            "patterns": {"md5": {}, "hu": {}},
            "deep_patterns": {"md5": {}, "hu": {}},
            "time_patterns": {"md5": {}, "hu": {}},
            "point_ranges": {"md5": {"TAI": [], "XIU": []}, "hu": {"TAI": [], "XIU": []}},
            "algo_weights": {
                "streak": 1.0, "alternating": 1.0, "pattern6": 1.0,
                "ma10": 1.0, "freq5": 1.0, "markov2": 1.0, "markov3": 1.0,
                "entropy": 1.0, "zigzag": 1.0, "bayes": 1.0, "neural": 1.0,
                "deep_pattern": 1.0, "time_cycle": 1.0, "point_trend": 1.0,
                "chaos_theory": 1.0, "fourier": 1.0, "lstm_simple": 1.0,
                "ensemble_boost": 1.0, "reinforcement": 1.0,
            },
            "algo_correct": {k: 0 for k in [
                "streak","alternating","pattern6","ma10","freq5",
                "markov2","markov3","entropy","zigzag","bayes","neural",
                "deep_pattern","time_cycle","point_trend","chaos_theory",
                "fourier","lstm_simple","ensemble_boost","reinforcement"
            ]},
            "algo_total": {k: 0 for k in [
                "streak","alternating","pattern6","ma10","freq5",
                "markov2","markov3","entropy","zigzag","bayes","neural",
                "deep_pattern","time_cycle","point_trend","chaos_theory",
                "fourier","lstm_simple","ensemble_boost","reinforcement"
            ]},
            "global_stats": {"total_predictions": 0, "total_correct": 0},
            "version": 4,
            "last_update": "",
        }

def save_pattern_data(data: dict):
    data["last_update"] = datetime.now().isoformat()
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

PATTERN_DB = load_pattern_data()

# ==================== UTILITY FUNCTIONS ====================

def box_message(title: str, content: list, width: int = 48) -> str:
    """Tạo message dạng box đẹp"""
    lines = []
    lines.append(f"╔{'═' * (width - 2)}╗")
    lines.append(f"║ {title:^{width - 4}}║")
    lines.append(f"╠{'═' * (width - 2)}╣")
    for line in content:
        clean_line = str(line)[:width - 6]
        lines.append(f"║ {clean_line:<{width - 4}}║")
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

# ==================== ULTRA PREDICTOR ====================

class UltraPredictor:
    def __init__(self, game: str):
        self.game = game
        self.history = deque(maxlen=1000)
        self.points = deque(maxlen=1000)
        self.dices_history = deque(maxlen=1000)
        self.timestamps = deque(maxlen=1000)
        self.last_votes = {}
        self.consecutive_correct = 0
        self.consecutive_wrong = 0
        self.learning_rate = 0.01
        self.confidence_history = []
        self.actual_results = []
        
    def add(self, result_str: str, point: float, dices: list):
        is_tai = result_str == "TAI"
        self.history.append(is_tai)
        self.points.append(point)
        self.dices_history.append(dices)
        self.timestamps.append(time.time())
        
        # Lưu point ranges để phân tích xu hướng điểm
        PATTERN_DB["point_ranges"][self.game][result_str].append(point)
        if len(PATTERN_DB["point_ranges"][self.game][result_str]) > 1000:
            PATTERN_DB["point_ranges"][self.game][result_str].pop(0)
        
        # Học pattern vào database (cả pattern cơ bản và sâu)
        self._learn_patterns(is_tai)
        
    def _learn_patterns(self, is_tai: bool):
        h = list(self.history)
        result_str = "T" if is_tai else "X"
        
        # Pattern cơ bản (2-9)
        for length in range(2, min(10, len(h))):
            if len(h) > length:
                seq = tuple(h[-(length + 1):-1])
                key = "".join("T" if x else "X" for x in seq)
                if key not in PATTERN_DB["patterns"][self.game]:
                    PATTERN_DB["patterns"][self.game][key] = {"T": 0, "X": 0}
                PATTERN_DB["patterns"][self.game][key][result_str] += 1
        
        # Deep pattern (10-15) cho phân tích dài hạn
        for length in range(10, min(16, len(h))):
            if len(h) > length:
                seq = tuple(h[-(length + 1):-1])
                key = "".join("T" if x else "X" for x in seq)
                if key not in PATTERN_DB["deep_patterns"][self.game]:
                    PATTERN_DB["deep_patterns"][self.game][key] = {"T": 0, "X": 0}
                PATTERN_DB["deep_patterns"][self.game][key][result_str] += 1
        
        # Time pattern (phân tích theo khung giờ)
        current_hour = datetime.now().hour
        time_key = f"h{current_hour}"
        if time_key not in PATTERN_DB["time_patterns"][self.game]:
            PATTERN_DB["time_patterns"][self.game][time_key] = {"T": 0, "X": 0}
        PATTERN_DB["time_patterns"][self.game][time_key][result_str] += 1

    def _streak_signal(self) -> Tuple[str, float]:
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
        
        # Phân tích streak với xác suất đảo chiều
        if streak >= 8:
            reverse_prob = min(0.95, 0.5 + (streak - 7) * 0.1)
            return ("XIU" if last else "TAI"), reverse_prob * 100
        elif streak >= 6:
            return ("XIU" if last else "TAI"), 75.0
        elif streak >= 4:
            return ("XIU" if last else "TAI"), 60.0
        elif streak >= 3:
            # Có thể tiếp tục hoặc đảo
            continue_prob = 0.45 + streak * 0.05
            return ("TAI" if last else "XIU"), continue_prob * 100
        elif streak == 2:
            return ("TAI" if last else "XIU"), 52.0
        return ("TAI" if last else "XIU"), 48.0

    def _alternating_signal(self) -> Tuple[str, float]:
        if len(self.history) < 6:
            return "TAI", 0.0
        h = list(self.history)[-15:]
        
        # Phân tích sóng nâng cao
        flips = sum(1 for i in range(1, len(h)) if h[i] != h[i-1])
        flip_ratio = flips / (len(h) - 1)
        
        # Phát hiện pattern sóng
        groups = []
        i = 0
        while i < len(h):
            j = i
            while j < len(h) and h[j] == h[i]:
                j += 1
            groups.append((h[i], j - i))
            i = j
        
        if len(groups) >= 3:
            # Pattern đối xứng
            if len(groups) >= 4:
                last_4 = groups[-4:]
                if last_4[0][1] == last_4[2][1] and last_4[1][1] == last_4[3][1]:
                    return ("TAI" if not groups[-1][0] else "XIU"), 70.0
            
            # Sóng 1-1-1
            if len(groups) >= 5:
                last_5 = groups[-5:]
                if all(g[1] == 1 for g in last_5):
                    # Kiểm tra xem có phải là sóng hoàn hảo không
                    if all(last_5[i][0] != last_5[i+1][0] for i in range(4)):
                        return ("TAI" if not groups[-1][0] else "XIU"), 65.0
        
        # Dựa vào flip ratio
        if flip_ratio > 0.7:
            return ("TAI" if not h[-1] else "XIU"), 55.0
        elif flip_ratio < 0.3:
            return ("TAI" if h[-1] else "XIU"), 60.0
        
        return "TAI", 0.0

    def _pattern_db_signal(self, length: int = 6) -> Tuple[str, float]:
        if len(self.history) < length:
            return "TAI", 0.0
        h = list(self.history)
        
        # Tìm pattern gần nhất trong database
        best_conf = 0.0
        best_pred = "TAI"
        
        for l in range(4, min(length + 1, len(h))):
            seq = h[-l:]
            key = "".join("T" if x else "X" for x in seq)
            db = PATTERN_DB["patterns"][self.game]
            
            if key in db:
                t, x = db[key]["T"], db[key]["X"]
                total = t + x
                if total >= 5:
                    if t > x:
                        conf = (t / total) * 100
                        if conf > best_conf:
                            best_conf = conf
                            best_pred = "TAI"
                    elif x > t:
                        conf = (x / total) * 100
                        if conf > best_conf:
                            best_conf = conf
                            best_pred = "XIU"
        
        return best_pred, best_conf

    def _deep_pattern_signal(self) -> Tuple[str, float]:
        """Phân tích pattern dài hạn (10-15 phiên)"""
        if len(self.history) < 12:
            return "TAI", 0.0
        h = list(self.history)
        
        for length in [12, 10, 8]:
            if len(h) > length:
                seq = h[-length:]
                key = "".join("T" if x else "X" for x in seq)
                db = PATTERN_DB["deep_patterns"][self.game]
                
                if key in db:
                    t, x = db[key]["T"], db[key]["X"]
                    total = t + x
                    if total >= 3:
                        if t > x:
                            return "TAI", min(70, (t/total) * 100)
                        elif x > t:
                            return "XIU", min(70, (x/total) * 100)
        
        return "TAI", 0.0

    def _time_cycle_signal(self) -> Tuple[str, float]:
        """Phân tích pattern theo thời gian trong ngày"""
        current_hour = datetime.now().hour
        time_key = f"h{current_hour}"
        db = PATTERN_DB["time_patterns"][self.game]
        
        if time_key in db:
            t, x = db[time_key]["T"], db[time_key]["X"]
            total = t + x
            if total >= 10:
                if t > x:
                    return "TAI", min(60, (t/total) * 100)
                else:
                    return "XIU", min(60, (x/total) * 100)
        
        return "TAI", 0.0

    def _markov2_signal(self) -> Tuple[str, float]:
        if len(self.history) < 5:
            return "TAI", 0.0
        h = list(self.history)
        last2 = tuple(h[-2:])
        counts = Counter()
        for i in range(len(h) - 3):
            if tuple(h[i:i+2]) == last2:
                counts[h[i+2]] += 1
        total = sum(counts.values())
        if total < 3:
            return "TAI", 0.0
        tai_p = counts[True] / total
        xiu_p = counts[False] / total
        if tai_p > xiu_p:
            return "TAI", round(tai_p * 100, 1)
        elif xiu_p > tai_p:
            return "XIU", round(xiu_p * 100, 1)
        return "TAI", 0.0

    def _markov3_signal(self) -> Tuple[str, float]:
        if len(self.history) < 7:
            return "TAI", 0.0
        h = list(self.history)
        last3 = tuple(h[-3:])
        counts = Counter()
        for i in range(len(h) - 4):
            if tuple(h[i:i+3]) == last3:
                counts[h[i+3]] += 1
        total = sum(counts.values())
        if total < 3:
            return "TAI", 0.0
        tai_p = counts[True] / total
        xiu_p = counts[False] / total
        if tai_p > xiu_p:
            return "TAI", round(tai_p * 100, 1)
        elif xiu_p > tai_p:
            return "XIU", round(xiu_p * 100, 1)
        return "TAI", 0.0

    def _point_trend_signal(self) -> Tuple[str, float]:
        """Phân tích xu hướng điểm số"""
        if len(self.points) < 5:
            return "TAI", 0.0
        
        recent_points = list(self.points)[-10:]
        avg = sum(recent_points) / len(recent_points)
        
        # Tính trend (tăng hay giảm)
        if len(recent_points) >= 6:
            first_half = sum(recent_points[:len(recent_points)//2]) / (len(recent_points)//2)
            second_half = sum(recent_points[len(recent_points)//2:]) / (len(recent_points) - len(recent_points)//2)
            trend = second_half - first_half
        else:
            trend = 0
        
        # Phân tích
        confidence = 50.0
        if avg > 10.8:
            confidence += 15
            pred = "TAI"
        elif avg < 10.2:
            confidence += 15
            pred = "XIU"
        else:
            pred = "TAI"
        
        # Điều chỉnh theo trend
        if trend > 0.3:
            pred = "TAI"
            confidence += 10
        elif trend < -0.3:
            pred = "XIU"
            confidence += 10
        
        return pred, min(confidence, 75)

    def _chaos_theory_signal(self) -> Tuple[str, float]:
        """Áp dụng lý thuyết hỗn loạn để dự đoán"""
        if len(self.history) < 20:
            return "TAI", 0.0
        
        h = list(self.history)
        
        # Tính Lyapunov exponent đơn giản
        changes = []
        for i in range(1, min(20, len(h))):
            if h[i] != h[i-1]:
                changes.append(1)
            else:
                changes.append(0)
        
        # Tỷ lệ thay đổi
        change_rate = sum(changes) / len(changes) if changes else 0
        
        # Nếu tỷ lệ thay đổi cao -> hệ thống hỗn loạn -> khó dự đoán
        # Nếu thấp -> có pattern ổn định
        if change_rate > 0.6:
            # Hỗn loạn cao -> ngược với xu hướng gần đây
            recent_trend = sum(h[-5:]) / 5
            if recent_trend > 0.6:
                return "XIU", 55.0
            elif recent_trend < 0.4:
                return "TAI", 55.0
        
        # Phân tích fractal đơn giản
        segments = []
        for i in range(0, len(h) - 5, 3):
            segments.append(sum(h[i:i+5]) / 5)
        
        if len(segments) >= 2:
            if all(s > 0.5 for s in segments):
                return "TAI", 60.0
            elif all(s < 0.5 for s in segments):
                return "XIU", 60.0
        
        return "TAI", 0.0

    def _fourier_signal(self) -> Tuple[str, float]:
        """Phân tích Fourier đơn giản để tìm chu kỳ"""
        if len(self.history) < 16:
            return "TAI", 0.0
        
        h = list(self.history)[-32:]
        n = len(h)
        
        # Tìm chu kỳ 2, 3, 4, 5, 6, 8
        best_cycle = None
        best_match = 0
        
        for cycle in [2, 3, 4, 5, 6, 8]:
            if cycle * 2 <= n:
                match = 0
                for i in range(n - cycle):
                    if h[i] == h[i + cycle]:
                        match += 1
                match_ratio = match / (n - cycle)
                if match_ratio > best_match:
                    best_match = match_ratio
                    best_cycle = cycle
        
        if best_cycle and best_match > 0.6:
            # Dự đoán dựa trên chu kỳ tìm được
            next_pos = len(h) - best_cycle
            if next_pos >= 0:
                return ("TAI" if h[next_pos] else "XIU"), best_match * 100
        
        return "TAI", 0.0

    def _lstm_simple_signal(self) -> Tuple[str, float]:
        """Mô phỏng LSTM đơn giản với cổng quên và cổng nhớ"""
        if len(self.history) < 10:
            return "TAI", 0.0
        
        h = list(self.history)[-20:]
        
        # Forget gate: quên pattern cũ nếu không còn phù hợp
        # Input gate: học pattern mới
        # Output gate: dự đoán
        
        # Tính trọng số cho các vị trí (gần đây quan trọng hơn)
        weights = [0.02 * i for i in range(1, len(h) + 1)]
        total_weight = sum(weights)
        
        weighted_tai = sum(w * (1 if v else 0) for w, v in zip(weights, h))
        weighted_xiu = sum(w * (0 if v else 1) for w, v in zip(weights, h))
        
        tai_score = weighted_tai / total_weight
        xiu_score = weighted_xiu / total_weight
        
        # Bias correction cho mẫu nhỏ
        bias = len(h) / 20  # Càng nhiều dữ liệu càng tự tin
        
        if tai_score > xiu_score:
            return "TAI", min(70, tai_score * 100 * bias)
        else:
            return "XIU", min(70, xiu_score * 100 * bias)

    def _ensemble_boost_signal(self) -> Tuple[str, float]:
        """Ensemble boosting: học từ sai lầm trước đó"""
        if len(self.actual_results) < 5:
            return "TAI", 0.0
        
        # Phân tích pattern của các lần sai
        wrong_patterns = []
        for i in range(1, len(self.actual_results)):
            if self.actual_results[i]["correct"] == False:
                wrong_patterns.append({
                    "prev_result": self.actual_results[i-1]["actual"],
                    "predicted": self.actual_results[i]["predicted"],
                    "actual": self.actual_results[i]["actual"],
                })
        
        if not wrong_patterns:
            return "TAI", 0.0
        
        # Đếm pattern sai phổ biến
        last_actual = self.actual_results[-1]["actual"] if self.actual_results else None
        
        if last_actual:
            relevant = [w for w in wrong_patterns if w["prev_result"] == last_actual]
            if relevant:
                counter = Counter(w["actual"] for w in relevant)
                most_common = counter.most_common(1)[0]
                return most_common[0], min(65, (most_common[1] / len(relevant)) * 100)
        
        return "TAI", 0.0

    def _reinforcement_signal(self) -> Tuple[str, float]:
        """Reinforcement Learning: học từ reward/punishment"""
        if len(self.history) < 10:
            return "TAI", 0.0
        
        h = list(self.history)
        
        # State: 3 phiên gần nhất
        state = tuple(h[-3:])
        
        # Tính Q-value đơn giản cho mỗi action (TAI, XIU)
        q_values = {"TAI": 0, "XIU": 0}
        
        # Tìm các state tương tự trong quá khứ
        for i in range(len(h) - 4):
            if tuple(h[i:i+3]) == state:
                # Reward: +1 nếu action dẫn đến đúng
                next_result = h[i+3]
                if next_result:
                    q_values["TAI"] += 1
                else:
                    q_values["XIU"] += 1
        
        total_q = q_values["TAI"] + q_values["XIU"]
        if total_q > 0:
            if q_values["TAI"] > q_values["XIU"]:
                return "TAI", (q_values["TAI"] / total_q) * 100
            else:
                return "XIU", (q_values["XIU"] / total_q) * 100
        
        return "TAI", 0.0

    def _ma10_signal(self) -> Tuple[str, float]:
        if len(self.points) < 10:
            return "TAI", 0.0
        ma = sum(list(self.points)[-10:]) / 10
        diff = abs(ma - 10.5)
        confidence = min(70.0, diff * 15)
        return ("TAI" if ma > 10.5 else "XIU"), confidence

    def _freq5_signal(self) -> Tuple[str, float]:
        if len(self.history) < 5:
            return "TAI", 0.0
        last5 = list(self.history)[-5:]
        tai_c = sum(last5)
        xiu_c = 5 - tai_c
        
        if tai_c >= 4:
            return "TAI", 75.0
        elif xiu_c >= 4:
            return "XIU", 75.0
        elif tai_c == 3:
            return "XIU", 58.0
        elif xiu_c == 3:
            return "TAI", 58.0
        return "TAI", 50.0

    def _entropy_signal(self) -> Tuple[str, float]:
        if len(self.history) < 12:
            return "TAI", 0.0
        recent = list(self.history)[-12:]
        tai_p = sum(recent) / 12
        xiu_p = 1 - tai_p
        
        if tai_p == 0 or xiu_p == 0:
            entropy = 0.0
        else:
            entropy = -(tai_p * math.log2(tai_p) + xiu_p * math.log2(xiu_p))
        
        if entropy < 0.5:
            return ("TAI" if tai_p > 0.5 else "XIU"), round((1 - entropy) * 100, 1)
        elif entropy > 0.95:
            return ("XIU" if recent[-1] else "TAI"), 60.0
        return "TAI", 50.0

    def _zigzag_signal(self) -> Tuple[str, float]:
        if len(self.history) < 10:
            return "TAI", 0.0
        h = list(self.history)[-12:]
        flips = sum(1 for i in range(1, len(h)) if h[i] != h[i-1])
        flip_ratio = flips / (len(h) - 1)
        
        if flip_ratio > 0.7:
            return ("TAI" if not h[-1] else "XIU"), 65.0
        elif flip_ratio < 0.3:
            return ("TAI" if h[-1] else "XIU"), 60.0
        return "TAI", 0.0

    def _bayes_signal(self) -> Tuple[str, float]:
        if len(self.history) < 20:
            return "TAI", 0.0
        h = list(self.history)[-40:]
        tai_count = sum(h)
        xiu_count = len(h) - tai_count
        prior_tai = (tai_count + 1) / (len(h) + 2)
        prior_xiu = (xiu_count + 1) / (len(h) + 2)
        
        if len(h) >= 3:
            last3 = tuple(h[-3:])
            match_tai = 0
            match_xiu = 0
            for i in range(len(h) - 3):
                if tuple(h[i:i+3]) == last3:
                    if h[i+3]:
                        match_tai += 1
                    else:
                        match_xiu += 1
            total_match = match_tai + match_xiu
            if total_match > 0:
                post_tai = (prior_tai * (match_tai + 1)) / (total_match + 2)
                post_xiu = (prior_xiu * (match_xiu + 1)) / (total_match + 2)
                if post_tai > post_xiu:
                    return "TAI", round(post_tai * 100, 1)
                else:
                    return "XIU", round(post_xiu * 100, 1)
        return "TAI", 50.0

    def _neural_signal(self) -> Tuple[str, float]:
        if len(self.history) < 15:
            return "TAI", 0.0
        h = list(self.history)[-25:]
        
        # Neural network đơn giản với 2 lớp ẩn
        # Lớp 1: Trọng số theo vị trí
        layer1_weights = []
        for i in range(len(h)):
            # Hàm sigmoid cho trọng số vị trí
            x = (i - len(h)/2) / (len(h)/4)
            w = 1 / (1 + math.exp(-x))
            layer1_weights.append(w)
        
        # Lớp 2: Trọng số cho kết quả gần đây
        layer2_boost = 1.5 if len(h) >= 3 and h[-1] == h[-2] == h[-3] else 1.0
        
        # Tính weighted sum
        weighted_sum = sum(h[i] * layer1_weights[i] * layer2_boost for i in range(len(h)))
        total_weight = sum(layer1_weights) * layer2_boost
        
        if total_weight > 0:
            score = weighted_sum / total_weight
            if score > 0.5:
                return "TAI", min(75, score * 100)
            else:
                return "XIU", min(75, (1 - score) * 100)
        
        return "TAI", 50.0

    def predict(self) -> dict:
        """Tổng hợp tất cả thuật toán với ensemble voting"""
        w = PATTERN_DB["algo_weights"]
        
        # Thu thập tín hiệu từ tất cả thuật toán
        signals = {
            "streak": self._streak_signal(),
            "alternating": self._alternating_signal(),
            "pattern6": self._pattern_db_signal(6),
            "deep_pattern": self._deep_pattern_signal(),
            "time_cycle": self._time_cycle_signal(),
            "markov2": self._markov2_signal(),
            "markov3": self._markov3_signal(),
            "point_trend": self._point_trend_signal(),
            "chaos_theory": self._chaos_theory_signal(),
            "fourier": self._fourier_signal(),
            "lstm_simple": self._lstm_simple_signal(),
            "ma10": self._ma10_signal(),
            "freq5": self._freq5_signal(),
            "entropy": self._entropy_signal(),
            "zigzag": self._zigzag_signal(),
            "bayes": self._bayes_signal(),
            "neural": self._neural_signal(),
            "ensemble_boost": self._ensemble_boost_signal(),
            "reinforcement": self._reinforcement_signal(),
        }
        
        # Ensemble với weighted voting
        scores = {"TAI": 0.0, "XIU": 0.0}
        total_weight = 0
        detail = {}
        
        # Adaptive boosting dựa trên streak
        if self.consecutive_correct >= 5:
            boost = 2.0
        elif self.consecutive_correct >= 3:
            boost = 1.5
        elif self.consecutive_wrong >= 5:
            boost = 0.3
        elif self.consecutive_wrong >= 3:
            boost = 0.5
        else:
            boost = 1.0
        
        for name, (pred, conf) in signals.items():
            if conf > 0:
                weight = w.get(name, 1.0) * boost
                # Confidence càng cao, trọng số càng lớn
                adjusted_conf = conf * weight * (1 + conf / 200)
                scores[pred] += adjusted_conf
                total_weight += weight
                detail[name] = {
                    "pred": pred,
                    "conf": round(conf, 1),
                    "w": round(weight, 2)
                }
        
        # Chuẩn hóa
        if scores["TAI"] + scores["XIU"] > 0:
            total = scores["TAI"] + scores["XIU"]
            if scores["TAI"] >= scores["XIU"]:
                result = "TAI"
                confidence = round((scores["TAI"] / total) * 100, 1)
            else:
                result = "XIU"
                confidence = round((scores["XIU"] / total) * 100, 1)
        else:
            result = "TAI"
            confidence = 50.0
        
        # Giới hạn confidence
        confidence = max(50.0, min(99.0, confidence))
        
        self.last_votes = {name: (info["pred"], info["conf"]) for name, info in detail.items()}
        self.confidence_history.append(confidence)
        
        # Confidence tier
        if confidence >= 80:
            tier = "🔥 RẤT CAO"
        elif confidence >= 70:
            tier = "⚡ CAO"
        elif confidence >= 60:
            tier = "✅ KHÁ"
        elif confidence >= 55:
            tier = "📊 TRUNG BÌNH"
        else:
            tier = "⚠️ THẤP"
        
        return {
            "result": result,
            "confidence": confidence,
            "tier": tier,
            "detail": detail,
            "scores": {k: round(v, 1) for k, v in scores.items()}
        }

    def record_actual(self, actual_str: str):
        """Ghi nhận kết quả thực tế và cập nhật học"""
        for algo, (voted, _) in self.last_votes.items():
            PATTERN_DB["algo_total"][algo] = PATTERN_DB["algo_total"].get(algo, 0) + 1
            if voted == actual_str:
                PATTERN_DB["algo_correct"][algo] = PATTERN_DB["algo_correct"].get(algo, 0) + 1
        
        # Cập nhật global stats
        PATTERN_DB["global_stats"]["total_predictions"] += 1
        if len(self.actual_results) > 0 and self.actual_results[-1].get("predicted") == actual_str:
            PATTERN_DB["global_stats"]["total_correct"] += 1
        
        # Lưu actual result để ensemble boost học
        if self.confidence_history:
            self.actual_results.append({
                "actual": actual_str,
                "predicted": self.last_votes.get("pattern6", ("TAI", 0))[0],
                "correct": self.last_votes.get("pattern6", ("TAI", 0))[0] == actual_str,
                "confidence": self.confidence_history[-1] if self.confidence_history else 50
            })
            if len(self.actual_results) > 100:
                self.actual_results.pop(0)

# ==================== AUTO WEIGHT UPDATE ====================

def recalculate_weights():
    """Cập nhật trọng số dựa trên hiệu suất thực tế"""
    weights = PATTERN_DB["algo_weights"]
    correct = PATTERN_DB["algo_correct"]
    total = PATTERN_DB["algo_total"]
    
    for algo in weights.keys():
        n = total.get(algo, 0)
        if n < 10:
            continue
        
        acc = correct.get(algo, 0) / n
        
        # Công thức sigmoid cải tiến với learning rate
        x = (acc - 0.5) * 12
        
        # Adaptive learning rate: thuật toán có nhiều mẫu -> learning rate nhỏ hơn
        lr = 0.5 / (1 + math.log10(n))
        weights[algo] = round(weights[algo] * (1 - lr) + (2.5 / (1 + math.exp(-x))) * lr, 3)
    
    save_pattern_data(PATTERN_DB)

async def auto_weight_update_loop():
    while True:
        await asyncio.sleep(15)  # Cập nhật mỗi 15 giây
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
    
    predictor = state["predictors"][game]
    
    # Ghi nhận kết quả thực tế
    predictor.record_actual(result)
    predictor.add(result, point, dices)
    
    pending = state["pending"][game]
    correct = None
    
    if pending and pending["session_id"] == rid:
        correct = (pending["predicted"] == result)
        
        # Lưu vào history
        state["prediction_history"].append({
            "game": game,
            "session_id": rid,
            "result": result,
            "predicted": pending["predicted"],
            "confidence": pending["confidence"],
            "correct": correct,
            "timestamp": datetime.now().isoformat(),
        })
        
        # Giới hạn history
        if len(state["prediction_history"]) > 200:
            state["prediction_history"] = state["prediction_history"][-200:]
        
        # Cập nhật stats
        state["total_games"][game] += 1
        if correct:
            state["total_wins"][game] += 1
            state["win_streak"][game] += 1
            state["lose_streak"][game] = 0
            predictor.consecutive_correct += 1
            predictor.consecutive_wrong = 0
        else:
            state["win_streak"][game] = 0
            state["lose_streak"][game] += 1
            predictor.consecutive_correct = 0
            predictor.consecutive_wrong += 1
        
        # Gửi kết quả nếu đang enable
        if state["enable"][game]:
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
                f"🔥 Streak: {state['win_streak'][game]}W/{state['lose_streak'][game]}L",
            ]
            
            msg = box_message("KẾT QUẢ", content, 45)
            await bot.send_message(chat_id=user_id, text=msg, parse_mode=ParseMode.MARKDOWN)
    
    # Tạo dự đoán mới
    new_pred = predictor.predict()
    state["pending"][game] = {
        "session_id": rid + 1,
        "predicted": new_pred["result"],
        "confidence": new_pred["confidence"],
        "tier": new_pred["tier"],
    }
    
    # Gửi dự đoán mới nếu đang enable
    if state["enable"][game]:
        conf_bar = progress_bar(new_pred["confidence"])
        pred_emoji = "🟢" if new_pred["result"] == "TAI" else "🔴"
        
        # Stats thuật toán
        correct_algos = sum(1 for v in new_pred["detail"].values() if v["pred"] == new_pred["result"])
        total_algos = len(new_pred["detail"])
        
        content = [
            f"{get_game_emoji(game)} Game: {get_game_name(game)}",
            f"🔮 DỰ ĐOÁN PHIÊN {rid + 1}",
            f"{pred_emoji} Kết quả: {new_pred['result']}",
            f"📊 {new_pred['tier']}",
            f"📈 [{conf_bar}] {new_pred['confidence']}%",
            f"🧠 {correct_algos}/{total_algos} thuật toán đồng thuận",
        ]
        
        pred_msg = box_message("DỰ ĐOÁN MỚI", content, 45)
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
        
        await asyncio.sleep(0.5)

# ==================== COMMAND HANDLERS ====================

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.args:
        keyboard = [
            [InlineKeyboardButton("🎲 Bắt đầu MD5", callback_data="start_md5"),
             InlineKeyboardButton("🎱 Bắt đầu HŨ", callback_data="start_hu")],
            [InlineKeyboardButton("⏹ Dừng tất cả", callback_data="stop_all")],
            [InlineKeyboardButton("📊 Thống kê", callback_data="stats"),
             InlineKeyboardButton("📋 Lịch sử", callback_data="his")],
            [InlineKeyboardButton("🧠 Thuật toán", callback_data="algo"),
             InlineKeyboardButton("📚 Học máy", callback_data="hoc")],
        ]
        
        content = [
            "Bot Lẩu Cua 79 pờ re i um ",
            "",
            "Chọn game để bắt đầu:",
        ]
        msg = box_message("CHÀO MỪNG", content, 48)
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    game = context.args[0].lower()
    if game in ["md5", "hu"]:
        await start_prediction(update, context, game)
    else:
        content = ["Dùng /start md5 hoặc /start hu"]
        msg = box_message("LỖI", content, 40)
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def start_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE, game: str):
    user_id = update.effective_user.id
    state = get_user_state(user_id)
    
    if state["enable"][game]:
        content = [f"{get_game_emoji(game)} {get_game_name(game)} đã đang chạy!"]
        msg = box_message("CẢNH BÁO", content, 45)
        if update.message:
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        elif update.callback_query:
            await update.callback_query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return
    
    state["enable"][game] = True
    state["session_start_time"][game] = datetime.now()
    state["win_streak"][game] = 0
    state["lose_streak"][game] = 0
    
    data = await fetch_sessions(game)
    if not data or "list" not in data or not data["list"]:
        content = ["Không thể tải dữ liệu từ server"]
        msg = box_message("LỖI", content, 45)
        if update.message:
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        elif update.callback_query:
            await update.callback_query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        state["enable"][game] = False
        return
    
    latest = data["list"][0]
    state["last_session_ids"][game] = latest["id"]
    predictor = state["predictors"][game]
    predictor.add(latest["resultTruyenThong"], latest["point"], latest["dices"])
    
    new_pred = predictor.predict()
    state["pending"][game] = {
        "session_id": latest["id"] + 1,
        "predicted": new_pred["result"],
        "confidence": new_pred["confidence"],
        "tier": new_pred["tier"],
    }
    
    total_patterns = sum(e["T"] + e["X"] for e in PATTERN_DB["patterns"][game].values())
    deep_patterns = sum(e["T"] + e["X"] for e in PATTERN_DB["deep_patterns"][game].values())
    conf_bar = progress_bar(new_pred["confidence"])
    pred_emoji = "🟢" if new_pred["result"] == "TAI" else "🔴"
    
    correct_algos = sum(1 for v in new_pred["detail"].values() if v["pred"] == new_pred["result"])
    total_algos = len(new_pred["detail"])
    
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
        f"🧠 {correct_algos}/{total_algos} thuật toán đồng thuận",
        "",
        f"💾 Patterns: {total_patterns}",
        f"🔬 Deep patterns: {deep_patterns}",
        f"⚙️ 19 thuật toán AI",
    ]
    
    msg = box_message(f"BẮT ĐẦU {get_game_name(game)}", content, 48)
    
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
        msg = box_message("DỪNG", content, 45)
    else:
        content = ["Không có dự đoán đang chạy"]
        msg = box_message("THÔNG BÁO", content, 45)
    
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
        deep = sum(e["T"] + e["X"] for e in PATTERN_DB["deep_patterns"][game].values())
        
        content.append(f"{get_game_emoji(game)} {get_game_name(game)}")
        content.append(f"  Win: {w}/{g} ({wr})")
        content.append(f"  Streak: {state['win_streak'][game]}W/{state['lose_streak'][game]}L")
        content.append(f"  Patterns: {pat}")
        content.append(f"  Deep: {deep}")
        content.append("")
    
    total_p = sum(sum(e["T"] + e["X"] for e in PATTERN_DB["patterns"][g].values()) for g in ["md5", "hu"])
    total_d = sum(sum(e["T"] + e["X"] for e in PATTERN_DB["deep_patterns"][g].values()) for g in ["md5", "hu"])
    global_stats = PATTERN_DB.get("global_stats", {})
    global_wr = f"{global_stats.get('total_correct',0)/global_stats.get('total_predictions',1)*100:.1f}%" if global_stats.get('total_predictions',0) > 0 else "N/A"
    
    content.append(f"🌍 Toàn cầu:")
    content.append(f"  Predictions: {global_stats.get('total_predictions',0)}")
    content.append(f"  Win rate: {global_wr}")
    content.append(f"🧠 Tổng patterns: {total_p}")
    content.append(f"🔬 Tổng deep: {total_d}")
    content.append(f"⚙️ 19 thuật toán AI")
    
    msg = box_message("THỐNG KÊ", content, 48)
    
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
        "pattern6": "Pattern Database",
        "deep_pattern": "Deep Pattern (10-15)",
        "time_cycle": "Time Cycle (Hour)",
        "markov2": "Markov Chain-2",
        "markov3": "Markov Chain-3",
        "point_trend": "Point Trend Analysis",
        "chaos_theory": "Chaos Theory",
        "fourier": "Fourier Cycle",
        "lstm_simple": "LSTM Simple",
        "ma10": "Moving Avg MA-10",
        "freq5": "Frequency-5",
        "entropy": "Entropy Analyzer",
        "zigzag": "Zigzag Detector",
        "bayes": "Bayesian Inference",
        "neural": "Neural Network",
        "ensemble_boost": "Ensemble Boosting",
        "reinforcement": "Reinforcement Learning",
    }
    
    content = ["Tên Algo           │ Wt  │ Acc"]
    content.append("─" * 35)
    
    for k, name in algo_names.items():
        wt = w.get(k, 1.0)
        acc = (c.get(k, 0) / t.get(k, 1) * 100) if t.get(k, 0) >= 5 else -1
        acc_str = f"{acc:.1f}%" if acc >= 0 else "N/A"
        content.append(f"{name:<20}│{wt:.2f} │{acc_str}")
    
    msg = box_message("19 THUẬT TOÁN & TRỌNG SỐ", content, 50)
    
    if update.message:
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def hoc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_p = sum(sum(e["T"] + e["X"] for e in PATTERN_DB["patterns"][g].values()) for g in ["md5", "hu"])
    total_d = sum(sum(e["T"] + e["X"] for e in PATTERN_DB["deep_patterns"][g].values()) for g in ["md5", "hu"])
    total_t = sum(sum(e["T"] + e["X"] for e in PATTERN_DB["time_patterns"][g].values()) for g in ["md5", "hu"])
    
    content = [
        "📚 HỆ THỐNG HỌC MÁY NÂNG CAO",
        "",
        f"💾 Patterns: {total_p}",
        f"🔬 Deep: {total_d}",
        f"🕐 Time: {total_t}",
        f"🔄 Cập nhật: {PATTERN_DB.get('last_update','N/A')[:16]}",
    ]
    
    msg = box_message("HỆ THỐNG HỌC MÁY", content, 50)
    
    if update.message:
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def his_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_user_state(user_id)
    
    if not state["prediction_history"]:
        content = ["Chưa có lịch sử dự đoán"]
        msg = box_message("LỊCH SỬ", content, 45)
        if update.message:
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        elif update.callback_query:
            await update.callback_query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return
    
    recent = state["prediction_history"][-15:]
    
    content = ["Phiên    │Game│KQ  │Dự │Conf│Đ/S"]
    content.append("─" * 35)
    
    for h in recent:
        mark = "✅" if h["correct"] else "❌"
        g_name = get_game_name(h["game"])
        conf = f"{h.get('confidence', 0):.0f}%"
        sid = str(h["session_id"])[-7:]
        content.append(f"{sid:<9}│{g_name:<4}│{h['result']:<4}│{h['predicted']:<3}│{conf:<4}│{mark}")
    
    correct_c = sum(1 for h in recent if h["correct"])
    wr = correct_c / len(recent) * 100
    content.append("─" * 35)
    content.append(f"✅ Đúng: {correct_c}/{len(recent)} ({wr:.0f}%)")
    
    if wr >= 70:
        content.append("🔥 Hiệu suất RẤT TỐT!")
    elif wr >= 50:
        content.append("✅ Hiệu suất KHÁ!")
    else:
        content.append("⚠️ Cần thêm dữ liệu học!")
    
    msg = box_message("LỊCH SỬ (15 gần nhất)", content, 48)
    
    if update.message:
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global PATTERN_DB
    PATTERN_DB = {
        "patterns": {"md5": {}, "hu": {}},
        "deep_patterns": {"md5": {}, "hu": {}},
        "time_patterns": {"md5": {}, "hu": {}},
        "point_ranges": {"md5": {"TAI": [], "XIU": []}, "hu": {"TAI": [], "XIU": []}},
        "algo_weights": {k: 1.0 for k in [
            "streak","alternating","pattern6","ma10","freq5",
            "markov2","markov3","entropy","zigzag","bayes","neural",
            "deep_pattern","time_cycle","point_trend","chaos_theory",
            "fourier","lstm_simple","ensemble_boost","reinforcement"
        ]},
        "algo_correct": {k: 0 for k in [
            "streak","alternating","pattern6","ma10","freq5",
            "markov2","markov3","entropy","zigzag","bayes","neural",
            "deep_pattern","time_cycle","point_trend","chaos_theory",
            "fourier","lstm_simple","ensemble_boost","reinforcement"
        ]},
        "algo_total": {k: 0 for k in [
            "streak","alternating","pattern6","ma10","freq5",
            "markov2","markov3","entropy","zigzag","bayes","neural",
            "deep_pattern","time_cycle","point_trend","chaos_theory",
            "fourier","lstm_simple","ensemble_boost","reinforcement"
        ]},
        "global_stats": {"total_predictions": 0, "total_correct": 0},
        "version": 4,
        "last_update": "",
    }
    save_pattern_data(PATTERN_DB)
    
    content = ["Đã reset toàn bộ dữ liệu học", "Tất cả weights về 1.0", "19 thuật toán sẵn sàng học lại"]
    msg = box_message("RESET", content, 48)
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
        "HOÀNG ĐẾ LC TOOL"
        "",
        "🎮 LỆNH:",
        "/start md5 - Bắt đầu MD5",
        "/start hu - Bắt đầu HŨ",
        "/stop - Dừng tất cả",
        "/stop md5/hu - Dừng game cụ thể",
        "/stats - Thống kê",
        "/his - Lịch sử",
        "/algo - Thuật toán",
        "/hoc - Học máy",
        "/reset - Reset DB",
        "",
    ]
    
    msg = box_message("TRỢ GIÚP", content, 48)
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

# ==================== BUTTON CALLBACK ====================

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "start_md5":
        await start_prediction(update, context, "md5")
    elif data == "start_hu":
        await start_prediction(update, context, "hu")
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
        msg = box_message("DỪNG", content, 45)
        await query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    
    elif data == "stats":
        await stats_cmd(update, context)
    elif data == "his":
        await his_cmd(update, context)
    elif data == "algo":
        await algo_cmd(update, context)
    elif data == "hoc":
        await hoc_cmd(update, context)

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
    
    # Callback handler
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Post init
    async def post_init(app):
        asyncio.create_task(auto_weight_update_loop())
        logger.info("🚀 Ultra Bot v4.0 Started! 19 Algo | 0.5s Updates | Multi-User!")
    
    app.post_init = post_init
    
    logger.info("╔════════════════════════════════════════════╗")
    logger.info("║   🎰  VIP PREDICTION BOT ULTRA v4.0      ║")
    logger.info("║   19 Algorithms | Deep Learning | 0.5s   ║")
    logger.info("╚════════════════════════════════════════════╝")
    
    app.run_polling()

if __name__ == "__main__":
    main()