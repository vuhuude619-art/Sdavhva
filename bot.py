#!/usr/bin/env python3
"""
Bot dự đoán Tài Xỉu siêu AI - Nâng cấp toàn diện V7 (AI Engine cực mạnh)
- Hệ thống thuật toán phân tích thống kê, kỹ thuật, không dùng mẫu cầu cố định
- Độ chính xác mục tiêu 70-85%, cân bằng không thiên vị
- Giữ nguyên toàn bộ chức năng admin, CSKH, mua key, broadcast
"""

import asyncio
import aiohttp
import aiosqlite
import json
import logging
import math
import os
import random
import signal
import statistics
import sys
import time
import traceback
from collections import defaultdict, Counter, deque
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    BotCommand,
    Bot,
)
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.error import TelegramError, Forbidden, NetworkError, RetryAfter

# ---------------------------- CONFIG ---------------------------------
BOT_TOKEN = "8715945694:AAEO40fT_Qc8IP6EWZthDvZuyodNryYK5rs"
NOTIFY_TOKEN = "8651470861:AAHTA1onHpwSkWACrkFusrBy4I0f2lyR-Ls"
ADMIN_IDS = [8001225219]
CSKH_GROUP_ID = -1003739572185
CSKH_USER_IDS = [6650824297, 8746174329]
SUPPORT_USERNAME = "@CskhTool1199"

DATABASE_PATH = "bot_data.db"
LOG_FILE = "bot_errors.log"

DEBUG = False  # Bật True để log chi tiết

# ---------------------------- SÀN & GAME -----------------------------
SITES = {
    "lc79": {
        "name": "🌟 LC79",
        "games": {
            "md5": {
                "label": "🎮 MD5",
                "url": "https://wtxmd52.tele68.com/v1/txmd5/lite-sessions?cp=R&cl=R&pf=web&at=07d01d98fd85e91efaa91fe492970412",
            },
            "hu": {
                "label": "🏆 Hũ",
                "url": "https://wtx.tele68.com/v1/tx/lite-sessions?cp=R&cl=R&pf=web&at=07d01d98fd85e91efaa91fe492970412",
            },
        },
    },
    "betvip": {
        "name": "💎 BetVip",
        "games": {
            "tx": {
                "label": "🎲 TX Thường",
                "url": "https://wtx.macminim6.online/v1/tx/lite-sessions?cp=R&cl=R&pf=web&at=93f594258a0738a76144f41ea9ab7a3f",
            },
            "md5": {
                "label": "🎮 MD5",
                "url": "https://wtxmd52.macminim6.online/v1/txmd5/lite-sessions?cp=R&cl=R&pf=web&at=93f594258a0738a76144f41ea9ab7a3f",
            },
        },
    },
}

GAME_MAP = {}
for site_id, site in SITES.items():
    for game_id, game in site["games"].items():
        GAME_MAP[f"{site_id}_{game_id}"] = {
            "site": site_id,
            "game": game_id,
            "label": f"{site['name']} {game['label']}",
            "url": game["url"],
        }

DICE_EMO = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣"}
PRICE_PLANS = {"1": 15000, "7": 70000, "30": 360000}

# ---------------------------- AI CONFIG ------------------------------
DEFAULT_ALGO_WEIGHTS = {
    "streak": 1.0, "break_detect": 1.2,
    "linreg_10": 1.3, "linreg_20": 1.2, "linreg_30": 1.1,
    "bollinger": 1.4, "rsi": 1.5, "macd": 1.4, "stoch": 1.3,
    "markov2": 1.4, "cycle": 1.5, "zscore": 1.3,
    "ema_ratio": 1.2, "local_extrema": 1.5
}

ALGO_NAMES = {
    "streak": "Cầu bệt", "break_detect": "Bẻ cầu",
    "linreg_10": "Hồi quy 10", "linreg_20": "Hồi quy 20", "linreg_30": "Hồi quy 30",
    "bollinger": "Bollinger Bands", "rsi": "RSI", "macd": "MACD",
    "stoch": "Stochastic", "markov2": "Markov bậc 2", "cycle": "Chu kỳ",
    "zscore": "Z-Score", "ema_ratio": "Tỉ lệ EMA", "local_extrema": "Đỉnh/đáy"
}

RECENT_WINDOW = 16
MAX_SESSION_HISTORY = 500
WEIGHT_MIN = 0.3
WEIGHT_MAX = 3.0
WEIGHT_INC = 1.03
WEIGHT_DEC = 0.97

# ---------------------------- GLOBALS ---------------------------------
db = None
ai_engine = None
user_watches = defaultdict(list)
active_chats = {}  # user_id <-> cskh_id
_shutdown_event = asyncio.Event()
logger = logging.getLogger("txbot")

# ---------------------------- LOGGING ---------------------------------
def setup_logging():
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if DEBUG else logging.INFO)
    root.handlers.clear()
    root.addHandler(fh)
    root.addHandler(sh)
    for noisy in ("httpx", "httpcore", "telegram.ext._updater",
                  "telegram.ext.Application", "aiosqlite"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

# ---------------------------- DATABASE ---------------------------------
async def init_db():
    global db
    db = await aiosqlite.connect(DATABASE_PATH)
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA synchronous=NORMAL")
    await db.execute("PRAGMA foreign_keys=ON")

    tables = [
        """CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_game TEXT NOT NULL, session_id INTEGER NOT NULL,
            result TEXT NOT NULL, dices TEXT, point INTEGER,
            timestamp REAL NOT NULL,
            UNIQUE(site_game, session_id)
        )""",
        """CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_game TEXT NOT NULL, session_id INTEGER,
            predicted TEXT, confidence INTEGER,
            actual TEXT, correct INTEGER,
            reason TEXT, timestamp REAL NOT NULL,
            user_id INTEGER, algo_votes TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_game TEXT NOT NULL,
            pattern_type TEXT NOT NULL,
            start_session_id INTEGER,
            end_session_id INTEGER,
            length INTEGER,
            result_sequence TEXT,
            confidence REAL,
            created REAL
        )""",
        """CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT,
            full_name TEXT, banned INTEGER DEFAULT 0,
            joined_date REAL NOT NULL, last_active REAL NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS keys (
            key TEXT PRIMARY KEY, days INTEGER,
            created REAL, created_by INTEGER
        )""",
        """CREATE TABLE IF NOT EXISTS user_keys (
            user_id INTEGER PRIMARY KEY, key TEXT,
            activated REAL,
            FOREIGN KEY(key) REFERENCES keys(key)
        )""",
        """CREATE TABLE IF NOT EXISTS payments (
            id TEXT PRIMARY KEY, user_id INTEGER,
            amount INTEGER, days INTEGER, timestamp REAL,
            status TEXT DEFAULT 'pending', handled_by INTEGER
        )""",
        """CREATE TABLE IF NOT EXISTS global_weights (
            site_game TEXT PRIMARY KEY, weights TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS chat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, cskh_id INTEGER,
            status TEXT DEFAULT 'pending',
            created REAL, closed REAL
        )""",
        """CREATE TABLE IF NOT EXISTS bot_config (
            key TEXT PRIMARY KEY, value TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS antispam (
            user_id INTEGER PRIMARY KEY,
            last_command_time REAL,
            count INTEGER DEFAULT 1
        )""",
        "INSERT OR IGNORE INTO bot_config (key, value) VALUES ('maintenance', '0')",
        "CREATE INDEX IF NOT EXISTS idx_sess_sg ON sessions(site_game, session_id)",
        "CREATE INDEX IF NOT EXISTS idx_pred_sg ON predictions(site_game, session_id)",
        "CREATE INDEX IF NOT EXISTS idx_pred_uid ON predictions(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_patterns_sg ON patterns(site_game)",
    ]
    for stmt in tables:
        await db.execute(stmt)
    await db.commit()
    logger.info("Database initialized")

async def close_db():
    global db
    if db:
        try:
            await db.close()
            logger.info("Database closed")
        except Exception as e:
            logger.error(f"close_db error: {e}")
        db = None

# ---------------------------- UTILS -----------------------------------
async def check_antispam(user_id: int) -> bool:
    try:
        now = time.time()
        async with db.execute("SELECT last_command_time, count FROM antispam WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
        if row:
            last_t, cnt = row
            if now - last_t < 1.5:
                cnt += 1
                if cnt >= 6:
                    return False
                await db.execute("UPDATE antispam SET count=? WHERE user_id=?", (cnt, user_id))
            else:
                await db.execute("UPDATE antispam SET last_command_time=?, count=1 WHERE user_id=?", (now, user_id))
        else:
            await db.execute("INSERT INTO antispam (user_id, last_command_time, count) VALUES (?,?,1)", (user_id, now))
        await db.commit()
        return True
    except Exception as e:
        logger.warning(f"antispam error {user_id}: {e}")
        return True

async def get_user_status(user_id: int) -> str:
    """Trả về: 'valid', 'banned', 'no_key', 'expired', 'error'"""
    try:
        # Kiểm tra banned
        async with db.execute("SELECT banned FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
            if row and row[0] == 1:
                return "banned"

        # Kiểm tra key
        async with db.execute(
            "SELECT k.days, uk.activated FROM user_keys uk INNER JOIN keys k ON uk.key = k.key WHERE uk.user_id=?",
            (user_id,)
        ) as cur:
            key_info = await cur.fetchone()
        if not key_info:
            return "no_key"
        days, activated = key_info
        if time.time() < activated + days * 86400:
            return "valid"
        return "expired"
    except Exception as e:
        logger.error(f"get_user_status error for {user_id}: {e}\n{traceback.format_exc()}")
        return "error"

async def is_maintenance() -> bool:
    try:
        async with db.execute("SELECT value FROM bot_config WHERE key='maintenance'") as cur:
            row = await cur.fetchone()
        return row and row[0] == "1"
    except:
        return False

def parse_session_entry(s: Dict) -> Dict:
    return {
        "id": s["id"],
        "result": s.get("resultTruyenThong", "TAI"),
        "dices": s.get("dices", []),
        "point": s.get("point", 0),
    }

async def fetch_api(url: str) -> List[Dict]:
    try:
        timeout = aiohttp.ClientTimeout(total=12)
        headers = {
            "accept": "*/*",
            "accept-language": "vi-VN,vi;q=0.9",
            "Referer": "https://lc79b.bet/",
            "User-Agent": "Mozilla/5.0",
        }
        async with aiohttp.ClientSession(timeout=timeout) as sess:
            async with sess.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    lst = data.get("list", [])
                    if isinstance(lst, list):
                        return lst
                else:
                    logger.warning(f"fetch_api HTTP {resp.status}: {url}")
    except Exception as e:
        logger.warning(f"fetch_api error {url}: {e}")
    return []

async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs) -> bool:
    try:
        await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        return True
    except Forbidden:
        logger.info(f"safe_send: user {chat_id} blocked bot")
    except RetryAfter as e:
        logger.warning(f"safe_send rate limited, retry after {e.retry_after}s")
        await asyncio.sleep(e.retry_after + 1)
        try:
            await bot.send_message(chat_id=chat_id, text=text, **kwargs)
            return True
        except:
            pass
    except Exception as e:
        logger.warning(f"safe_send error {chat_id}: {e}")
    return False

def _safe_json(val, default):
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except:
        return default

# ---------------------------- TYPING MIDDLEWARE -----------------------
async def typing_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_message and update.effective_user and update.effective_chat:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    except:
        pass

# =====================================================================
#               AI ENGINE V7 - THUẬT TOÁN SIÊU MẠNH
# =====================================================================
class AIEngine:
    def __init__(self):
        self.weights = defaultdict(lambda: DEFAULT_ALGO_WEIGHTS.copy())
        # Cache nhẹ cho tính toán
        self._cache = {}

    async def load_weights_from_db(self):
        try:
            async with db.execute("SELECT site_game, weights FROM global_weights") as cur:
                async for row in cur:
                    try:
                        loaded = json.loads(row[1])
                        merged = DEFAULT_ALGO_WEIGHTS.copy()
                        merged.update({k: float(v) for k, v in loaded.items() if k in merged})
                        self.weights[row[0]] = merged
                    except:
                        pass
        except Exception as e:
            logger.error(f"load_weights error: {e}")

    async def save_weights_to_db(self, site_game: str):
        try:
            await db.execute(
                "INSERT OR REPLACE INTO global_weights (site_game, weights) VALUES (?,?)",
                (site_game, json.dumps(self.weights[site_game]))
            )
            await db.commit()
        except Exception as e:
            logger.warning(f"save_weights error {site_game}: {e}")

    # ------------------------- TIỆN ÍCH TOÁN HỌC -----------------------
    @staticmethod
    def _get_series(history: List[Dict]):
        """Trả về points và results theo thứ tự thời gian tăng dần (cũ -> mới)"""
        rev = list(reversed(history))
        points = [h["point"] for h in rev]
        results = [h["result"] for h in rev]
        return points, results

    @staticmethod
    def _linear_regression(y: List[float]) -> Tuple[float, float, float, float]:
        """Hồi quy tuyến tính đơn giản trên chỉ số (0..len-1) -> trả về slope, intercept, r_squared, prediction next"""
        n = len(y)
        if n < 2:
            return 0.0, float(y[0]) if y else 0, 0.0, 0.0
        x = list(range(n))
        mean_x = (n - 1) / 2.0
        mean_y = statistics.mean(y)
        ss_xy = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        ss_xx = sum((xi - mean_x) ** 2 for xi in x)
        if ss_xx == 0:
            return 0.0, mean_y, 0.0, mean_y
        slope = ss_xy / ss_xx
        intercept = mean_y - slope * mean_x
        pred_next = slope * n + intercept  # dự đoán cho chỉ số tiếp theo
        # Tính R^2
        ss_res = sum((yi - (slope * xi + intercept)) ** 2 for xi, yi in zip(x, y))
        ss_tot = sum((yi - mean_y) ** 2 for yi in y)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0.0
        return slope, intercept, r_squared, pred_next

    @staticmethod
    def _ema(data: List[float], period: int) -> List[float]:
        if len(data) == 0:
            return []
        k = 2 / (period + 1)
        ema = [data[0]]
        for price in data[1:]:
            ema.append(price * k + ema[-1] * (1 - k))
        return ema

    @staticmethod
    def _bollinger(data: List[float], period=20, num_std=2.0):
        if len(data) < period:
            return None, None, None
        window = data[-period:]
        ma = statistics.mean(window)
        std = statistics.stdev(window) if len(window) >= 2 else 0
        upper = ma + num_std * std
        lower = ma - num_std * std
        return upper, ma, lower

    @staticmethod
    def _rsi(points: List[float], period=14):
        if len(points) < period + 1:
            return 50.0
        deltas = [points[i] - points[i - 1] for i in range(1, len(points))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]
        avg_gain = statistics.mean(gains[:period])
        avg_loss = statistics.mean(losses[:period])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1 + rs))
        # smoothing cho các giá trị sau period
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1 + rs))
        return rsi

    @staticmethod
    def _macd(points: List[float], fast=12, slow=26, signal=9):
        if len(points) < slow + signal:
            return None, None
        ema_fast = AIEngine._ema(points, fast)
        ema_slow = AIEngine._ema(points, slow)
        macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
        signal_line = AIEngine._ema(macd_line, signal)
        return macd_line, signal_line

    @staticmethod
    def _stochastic(points: List[float], k_period=14, d_period=3):
        if len(points) < k_period:
            return 50.0, 50.0
        # Chỉ tính %K cho vị trí cuối cùng
        lowest = min(points[-k_period:])
        highest = max(points[-k_period:])
        if highest == lowest:
            return 50.0, 50.0
        k = 100.0 * (points[-1] - lowest) / (highest - lowest)
        # Giả lập %D là SMA của %K (đơn giản hóa)
        return k, k  # tạm thời trả về giống nhau vì chỉ có 1 giá trị; sẽ cần lịch sử %K

    @staticmethod
    def _markov2(results: List[str]):
        """Xác suất trạng thái tiếp theo dựa trên Markov bậc 2"""
        if len(results) < 3:
            return None, 0
        seq = results  # đã theo thứ tự tăng dần
        # Lấy 2 trạng thái cuối
        last2 = tuple(seq[-2:])
        # Đếm các lần xuất hiện của last2 và trạng thái tiếp theo
        counts = {"TAI": 0, "XIU": 0}
        total = 0
        for i in range(len(seq)-2):
            if (seq[i], seq[i+1]) == last2:
                nxt = seq[i+2]
                counts[nxt] += 1
                total += 1
        if total == 0:
            return None, 0
        pred = "TAI" if counts["TAI"] >= counts["XIU"] else "XIU"
        prob = max(counts.values()) / total
        return pred, int(prob * 90)

    @staticmethod
    def _autocorr_cycle(series: List[float], max_lag=20):
        """Tìm chu kỳ dựa trên autocorrelation của chuỗi số (điểm)"""
        n = len(series)
        if n < max_lag * 2:
            return None
        best_lag = None
        best_corr = -1
        mean = statistics.mean(series)
        var = sum((x-mean)**2 for x in series)
        if var == 0:
            return None
        for lag in range(4, max_lag+1):
            if n - lag < lag: break
            corr = sum((series[i]-mean)*(series[i+lag]-mean) for i in range(n-lag)) / var / (n-lag)
            if corr > best_corr:
                best_corr = corr
                best_lag = lag
        if best_lag and best_corr > 0.3:
            # Dự đoán tiếp theo là giá trị tại vị trí n-lag
            pred_val = series[-best_lag]
            return pred_val, best_lag, best_corr
        return None
    # ----------------------------------------------------------------

    # ------------------------- CÁC THUẬT TOÁN MỚI --------------------
    def algo_streak(self, history):
        points, results = self._get_series(history)
        if len(results) < 3:
            return None, 0
        last = results[-1]
        streak = 1
        for i in range(len(results)-2, -1, -1):
            if results[i] == last:
                streak += 1
            else:
                break
        if streak >= 5:
            return last, min(80, 55 + streak * 3)  # tăng confidence
        if streak >= 3:
            return last, 65
        return None, 0

    def algo_break_detect(self, history):
        points, results = self._get_series(history)
        if len(results) < 5:
            return None, 0
        last = results[-1]
        streak = 1
        for i in range(len(results)-2, -1, -1):
            if results[i] == last:
                streak += 1
            else:
                break
        if streak >= 5:
            opp = "XIU" if last == "TAI" else "TAI"
            return opp, 75
        if streak >= 4:
            opp = "XIU" if last == "TAI" else "TAI"
            return opp, 65
        return None, 0

    def algo_linreg(self, history, period):
        points, _ = self._get_series(history)
        if len(points) < period + 1:
            return None, 0
        subset = points[-(period):]
        _, _, r2, pred_point = self._linear_regression(subset)
        direction = "TAI" if pred_point >= 11 else "XIU"
        # confidence dựa trên R² và khoảng cách tới ngưỡng
        dist = abs(pred_point - 10.5)
        conf = min(85, int(55 + r2 * 25 + dist * 2))
        return direction, conf

    def algo_linreg_10(self, history): return self.algo_linreg(history, 10)
    def algo_linreg_20(self, history): return self.algo_linreg(history, 20)
    def algo_linreg_30(self, history): return self.algo_linreg(history, 30)

    def algo_bollinger(self, history):
        points, _ = self._get_series(history)
        if len(points) < 20:
            return None, 0
        upper, _, lower = self._bollinger(points, 20, 2.0)
        if upper is None:
            return None, 0
        last_point = points[-1]
        if last_point >= upper:
            return "XIU", 78
        elif last_point <= lower:
            return "TAI", 78
        return None, 0

    def algo_rsi(self, history):
        points, _ = self._get_series(history)
        if len(points) < 15:
            return None, 0
        rsi = self._rsi(points, 14)
        if rsi > 70:
            return "XIU", int(55 + (rsi - 70) * 0.8)  # max ~79
        if rsi < 30:
            return "TAI", int(55 + (30 - rsi) * 0.8)
        return None, 0

    def algo_macd(self, history):
        points, _ = self._get_series(history)
        if len(points) < 36:
            return None, 0
        macd_line, signal_line = self._macd(points, 12, 26, 9)
        if macd_line is None or len(macd_line) < 2 or len(signal_line) < 2:
            return None, 0
        # Tín hiệu cắt nhau 2 phiên gần nhất
        prev_diff = macd_line[-2] - signal_line[-2]
        curr_diff = macd_line[-1] - signal_line[-1]
        if prev_diff < 0 and curr_diff > 0:  # cắt lên -> xu hướng tăng (TÀI)
            return "TAI", 72
        elif prev_diff > 0 and curr_diff < 0:  # cắt xuống -> giảm (XỈU)
            return "XIU", 72
        # Nếu MACD vẫn trên signal mạnh
        if curr_diff > 0.1:
            return "TAI", 63
        elif curr_diff < -0.1:
            return "XIU", 63
        return None, 0

    def algo_stoch(self, history):
        points, _ = self._get_series(history)
        if len(points) < 14:
            return None, 0
        k, d = self._stochastic(points, 14, 3)
        if k > 80:
            return "XIU", 70
        if k < 20:
            return "TAI", 70
        return None, 0

    def algo_markov2(self, history):
        _, results = self._get_series(history)
        return self._markov2(results)

    def algo_cycle(self, history):
        points, _ = self._get_series(history)
        cycle_info = self._autocorr_cycle(points, 20)
        if cycle_info:
            pred_point, lag, corr = cycle_info
            direction = "TAI" if pred_point >= 10.5 else "XIU"
            conf = min(85, int(60 + corr * 30))
            return direction, conf
        return None, 0

    def algo_zscore(self, history):
        points, _ = self._get_series(history)
        if len(points) < 30:
            return None, 0
        mean = statistics.mean(points)
        std = statistics.stdev(points)
        if std == 0:
            return None, 0
        z = (points[-1] - mean) / std
        if z > 1.2:
            return "XIU", min(80, int(55 + abs(z)*12))
        if z < -1.2:
            return "TAI", min(80, int(55 + abs(z)*12))
        return None, 0

    def algo_ema_ratio(self, history):
        _, results = self._get_series(history)
        if len(results) < 20:
            return None, 0
        # Chuyển thành 0/1
        binary = [1 if r == "TAI" else 0 for r in results]
        ema = self._ema([float(b) for b in binary], 15)[-1]  # xu hướng gần đây
        # Dự báo ngược với xu hướng nếu quá lệch
        if ema > 0.65:
            return "XIU", min(75, int(55 + (ema-0.5)*80))
        if ema < 0.35:
            return "TAI", min(75, int(55 + (0.5-ema)*80))
        return None, 0

    def algo_local_extrema(self, history):
        points, _ = self._get_series(history)
        if len(points) < 5:
            return None, 0
        # Tìm đỉnh/đáy gần nhất
        last_idx = len(points) - 1
        # Xét 3 điểm cuối
        a = points[-3]
        b = points[-2]
        c = points[-1]
        if a < b and b > c:  # đỉnh
            return "XIU", 68
        if a > b and b < c:  # đáy
            return "TAI", 68
        # Phát hiện đỉnh đáy dài hạn
        for i in range(last_idx-2, 2, -1):
            if points[i] > points[i-1] and points[i] > points[i+1]:
                return "XIU", 66  # gần đỉnh
            if points[i] < points[i-1] and points[i] < points[i+1]:
                return "TAI", 66
        return None, 0

    # Danh sách các thuật toán sử dụng
    ALGORITHMS = [
        ("streak", algo_streak),
        ("break_detect", algo_break_detect),
        ("linreg_10", algo_linreg_10),
        ("linreg_20", algo_linreg_20),
        ("linreg_30", algo_linreg_30),
        ("bollinger", algo_bollinger),
        ("rsi", algo_rsi),
        ("macd", algo_macd),
        ("stoch", algo_stoch),
        ("markov2", algo_markov2),
        ("cycle", algo_cycle),
        ("zscore", algo_zscore),
        ("ema_ratio", algo_ema_ratio),
        ("local_extrema", algo_local_extrema),
    ]

    def predict(self, history: List[Dict], site_game: str) -> Tuple[str, int, str, Dict]:
        if len(history) < 2:
            return random.choice(["TAI", "XIU"]), 50, "Không đủ dữ liệu", {}
        weights = self.weights.get(site_game, DEFAULT_ALGO_WEIGHTS)
        raw = {"TAI": 0.0, "XIU": 0.0}
        contrib = []
        for name, func in self.ALGORITHMS:
            try:
                pred, conf = func(self, history)
            except Exception:
                pred, conf = None, 0
            if pred in ("TAI", "XIU") and conf > 0:
                w = max(WEIGHT_MIN, min(WEIGHT_MAX, weights.get(name, 1.0)))
                weighted = w * conf
                raw[pred] += weighted
                contrib.append((name, pred, conf, weighted))
        total = raw["TAI"] + raw["XIU"]
        if total == 0:
            return random.choice(["TAI", "XIU"]), 50, "Không rõ pattern", {}
        ratio_tai = raw["TAI"] / total
        # Vùng cân bằng để tránh thiên vị (mở rộng hơn)
        if 0.42 <= ratio_tai <= 0.58:
            pred = random.choice(["TAI", "XIU"])
            conf = 50
        else:
            pred = "TAI" if ratio_tai > 0.5 else "XIU"
            winner_ratio = ratio_tai if pred == "TAI" else (1 - ratio_tai)
            conf = int(50 + winner_ratio * 75)
            conf = max(50, min(92, conf))
        top = sorted([(n, c) for n, p, c, _ in contrib if p == pred], key=lambda x: x[1], reverse=True)[:3]
        reason = " + ".join(f"{ALGO_NAMES.get(n,n)} ({c}%)" for n,c in top) if top else "Tổng hợp"
        votes = {name: {"pred": p, "conf": c, "weighted": round(w,4)} for name,p,c,w in contrib}
        return pred, conf, reason, votes

    async def learn_from_outcome(self, site_game: str, predicted: str, actual: str, algo_votes: Dict):
        try:
            cur_w = self.weights.get(site_game, DEFAULT_ALGO_WEIGHTS.copy())
            for algo_name, info in algo_votes.items():
                if info.get("pred") == actual:
                    cur_w[algo_name] = min(WEIGHT_MAX, cur_w.get(algo_name, 1.0) * WEIGHT_INC)
                else:
                    cur_w[algo_name] = max(WEIGHT_MIN, cur_w.get(algo_name, 1.0) * WEIGHT_DEC)
            self.weights[site_game] = cur_w
            await self.save_weights_to_db(site_game)
        except Exception as e:
            logger.warning(f"learn weight update error: {e}")

    async def detect_and_save_patterns(self, site_game: str, history: List[Dict]):
        # Có thể bổ sung logic lưu pattern mới nếu cần
        pass
# =====================================================================

# ---------------------------- BACKGROUND TASK -------------------------
async def background_fetch_and_learn(bot: Bot):
    logger.info("Background task started")
    while not _shutdown_event.is_set():
        try:
            if await is_maintenance():
                await asyncio.sleep(10)
                continue
            for game_key, game_conf in GAME_MAP.items():
                if _shutdown_event.is_set():
                    break
                try:
                    await _process_game(bot, game_key, game_conf)
                except Exception as e:
                    logger.error(f"_process_game {game_key}: {e}")
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Background loop: {e}")
            await asyncio.sleep(10)

async def _process_game(bot: Bot, game_key: str, game_conf: Dict):
    sessions = await fetch_api(game_conf["url"])
    if not sessions:
        return
    try:
        sessions.sort(key=lambda x: int(x.get("id", 0)), reverse=True)
    except:
        return
    latest = sessions[0]
    latest_id = int(latest.get("id", 0))
    if latest_id == 0:
        return
    async with db.execute("SELECT 1 FROM sessions WHERE site_game=? AND session_id=?", (game_key, latest_id)) as cur:
        if await cur.fetchone():
            return
    entry = parse_session_entry(latest)
    try:
        await db.execute(
            "INSERT OR IGNORE INTO sessions (site_game, session_id, result, dices, point, timestamp) VALUES (?,?,?,?,?,?)",
            (game_key, entry["id"], entry["result"], json.dumps(entry["dices"]), entry["point"], time.time())
        )
        await db.commit()
    except Exception as e:
        logger.warning(f"Insert session error {game_key}: {e}")
        return
    await clean_old_sessions(game_key)

    async with db.execute(
        "SELECT session_id, result, dices, point FROM sessions WHERE site_game=? ORDER BY session_id DESC LIMIT 500",
        (game_key,)
    ) as cur:
        rows = await cur.fetchall()
    if not rows:
        return
    history = [{"id": r[0], "result": r[1], "dices": _safe_json(r[2], []), "point": r[3] or 0} for r in rows]

    async with db.execute(
        "SELECT id, predicted, confidence, algo_votes FROM predictions WHERE site_game=? AND session_id=? AND actual IS NULL ORDER BY id DESC LIMIT 1",
        (game_key, latest_id)
    ) as cur:
        pending = await cur.fetchone()
    if pending:
        actual = entry["result"]
        correct = 1 if pending[1] == actual else 0
        await db.execute("UPDATE predictions SET actual=?, correct=? WHERE site_game=? AND session_id=? AND actual IS NULL",
                         (actual, correct, game_key, latest_id))
        await db.commit()
        algo_votes = _safe_json(pending[3], {})
        await ai_engine.learn_from_outcome(game_key, pending[1], actual, algo_votes)

    pred, conf, reason, votes = ai_engine.predict(history, game_key)
    try:
        await db.execute(
            "INSERT INTO predictions (site_game, session_id, predicted, confidence, reason, timestamp, algo_votes) VALUES (?,?,?,?,?,?,?)",
            (game_key, latest_id + 1, pred, conf, reason, time.time(), json.dumps(votes))
        )
        await db.commit()
    except Exception as e:
        logger.warning(f"Insert prediction error {game_key}: {e}")

    watchers = list(user_watches.get(game_key, []))
    if not watchers:
        return

    last = history[0]
    dice_str = " ".join(DICE_EMO.get(int(d), str(d)) for d in last["dices"] if d)
    pred_emoji = "🔴 TÀI" if pred == "TAI" else "🔵 XỈU"
    res_emoji = "🔴 TÀI" if last["result"] == "TAI" else "🔵 XỈU"

    recent_10 = [h["result"] for h in history[:10]][::-1]
    recent_str = " → ".join(["🔴" if r == "TAI" else "🔵" for r in recent_10])

    msg = (
        f"TOOL TÀI XỈU:\n"
        f"{game_conf['label']}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📌 Phiên dự đoán: `{latest_id + 1}`\n"
        f"💡 Dự đoán: {pred_emoji} ({conf}%)\n"
        f"🧠 Lý do: {reason}\n"
        f"📊 Cầu gần đây (cũ → mới): {recent_str}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"⏮ Phiên trước: `{latest_id}`\n"
        f"🎲 Xúc xắc: {dice_str} _( Σ {last['point']} )_\n"
        f"🏆 Kết quả: {res_emoji}\n"
        f"⏰ Time: `{datetime.now().strftime('%H:%M:%S')}`"
    )

    to_remove = []
    for uid in watchers:
        if _shutdown_event.is_set():
            break
        status = await get_user_status(uid)
        if status == "valid":
            if await safe_send(bot, uid, msg, parse_mode=ParseMode.MARKDOWN):
                try:
                    await db.execute(
                        "INSERT INTO predictions (site_game, session_id, predicted, confidence, reason, timestamp, algo_votes, user_id) VALUES (?,?,?,?,?,?,?,?)",
                        (game_key, latest_id + 1, pred, conf, reason, time.time(), json.dumps(votes), uid)
                    )
                    await db.commit()
                except Exception as e:
                    logger.warning(f"Insert user pred error {uid}: {e}")
            else:
                to_remove.append(uid)
        else:
            to_remove.append(uid)
    for uid in to_remove:
        if uid in user_watches.get(game_key, []):
            user_watches[game_key].remove(uid)

async def clean_old_sessions(site_game: str):
    try:
        await db.execute(
            """DELETE FROM sessions WHERE site_game=? AND id NOT IN (
                SELECT id FROM sessions WHERE site_game=? ORDER BY session_id DESC LIMIT ?
            )""", (site_game, site_game, MAX_SESSION_HISTORY)
        )
        await db.commit()
    except Exception as e:
        logger.warning(f"clean_old_sessions: {e}")

# ---------------------------- USER HANDLERS ---------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message:
        return
    now = time.time()
    try:
        await db.execute(
            "INSERT INTO users (user_id, username, full_name, joined_date, last_active) VALUES (?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name, last_active=excluded.last_active",
            (user.id, user.username or "", user.full_name or "N/A", now, now)
        )
        await db.commit()
    except Exception as e:
        logger.warning(f"start DB error: {e}")

    status = await get_user_status(user.id)
    logger.info(f"/start user {user.id} status: {status}")
    if status == "banned":
        await update.message.reply_text("⛔ Tài khoản của bạn đã bị khóa.")
        return
    if status == "no_key":
        await update.message.reply_text(f"🔐 Bạn chưa có key.\nDùng /muakey để mua hoặc liên hệ {SUPPORT_USERNAME}")
        return
    if status == "expired":
        await update.message.reply_text(f"🔐 Key của bạn đã hết hạn.\nDùng /muakey để gia hạn hoặc liên hệ {SUPPORT_USERNAME}")
        return
    if status == "error":
        await update.message.reply_text("⚠️ Lỗi hệ thống khi kiểm tra key, vui lòng thử lại sau.")
        return

    keyboard = [
        [KeyboardButton("🎮 Bắt đầu dự đoán")],
        [KeyboardButton("ℹ️ Tài khoản"), KeyboardButton("🛒 Mua Key")],
        [KeyboardButton("🛑 Dừng dự đoán"), KeyboardButton("📜 Lịch sử")],
        [KeyboardButton("📞 Liên hệ CSKH")],
    ]
    await update.message.reply_text(
        f"👋 Chào *{user.full_name}*!\nChọn chức năng:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode=ParseMode.MARKDOWN,
    )

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    if not user or not msg:
        return
    if user.id in active_chats:
        other = active_chats[user.id]
        if msg.text and not msg.text.startswith("/"):
            await relay_message(context.bot, user.id, other, msg.text)
        return

    if not await check_antispam(user.id):
        await msg.reply_text("⚠️ Thao tác quá nhanh, vui lòng chờ.")
        return

    status = await get_user_status(user.id)
    logger.info(f"Menu from {user.id} with status: {status}")
    if status != "valid":
        if status == "banned":
            await msg.reply_text("⛔ Bạn đã bị khóa.")
        elif status == "no_key":
            await msg.reply_text("🔐 Bạn chưa có key. /muakey")
        elif status == "expired":
            await msg.reply_text("🔐 Key đã hết hạn. /muakey")
        elif status == "error":
            await msg.reply_text("⚠️ Lỗi hệ thống, thử lại sau.")
        return

    text = msg.text or ""
    if text == "🎮 Bắt đầu dự đoán":
        kb = [[InlineKeyboardButton(conf["label"], callback_data=f"start_game|{gkey}")] for gkey, conf in GAME_MAP.items()]
        kb.append([InlineKeyboardButton("❌ Thoát", callback_data="cancel")])
        await msg.reply_text("Chọn game:", reply_markup=InlineKeyboardMarkup(kb))
    elif text == "ℹ️ Tài khoản":
        await cmd_info(update, context)
    elif text == "🛒 Mua Key":
        await cmd_muakey(update, context)
    elif text == "🛑 Dừng dự đoán":
        await cmd_stop(update, context)
    elif text == "📜 Lịch sử":
        await cmd_history(update, context)
    elif text == "📞 Liên hệ CSKH":
        await cmd_cskh(update, context)
    else:
        await msg.reply_text("Vui lòng chọn chức năng từ menu.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""
    user = query.from_user
    if data == "cancel":
        try:
            await query.message.delete()
        except:
            pass
        return
    if data.startswith("start_game|"):
        parts = data.split("|", 1)
        if len(parts) < 2:
            return
        game_key = parts[1]
        if game_key not in GAME_MAP:
            await query.answer("Game không hợp lệ!", show_alert=True)
            return
        if user.id not in user_watches[game_key]:
            user_watches[game_key].append(user.id)
        try:
            await query.message.delete()
        except:
            pass
        await safe_send(context.bot, user.id, f"🚀 Đã theo dõi *{GAME_MAP[game_key]['label']}*\nBot sẽ tự động gửi dự đoán khi có phiên mới.", parse_mode=ParseMode.MARKDOWN)

async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        async with db.execute(
            "SELECT k.key, k.days, uk.activated FROM user_keys uk JOIN keys k ON uk.key=k.key WHERE uk.user_id=?", (uid,)
        ) as cur:
            ki = await cur.fetchone()
        if not ki:
            await update.message.reply_text("❌ Chưa có key.")
            return
        key, days, activated = ki
        expiry = datetime.fromtimestamp(activated + days * 86400).strftime("%d/%m/%Y %H:%M")
        remaining = max(0, int((activated + days * 86400 - time.time()) / 3600))
        status = "✅ Còn hạn" if remaining > 0 else "❌ Hết hạn"
        await update.message.reply_text(
            f"🔑 *Key:* `{key}`\n⏳ *Hết hạn:* {expiry}\n🕐 *Còn lại:* ~{remaining}h\n📌 *Trạng thái:* {status}",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error(f"cmd_info error: {e}")
        await update.message.reply_text("⚠️ Lỗi lấy thông tin.")

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    removed = 0
    for gkey in list(user_watches.keys()):
        if uid in user_watches[gkey]:
            user_watches[gkey].remove(uid)
            removed += 1
    if removed:
        await update.message.reply_text(f"🛑 Đã dừng theo dõi {removed} game.")
    else:
        await update.message.reply_text("ℹ️ Bạn chưa theo dõi game nào.")

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        async with db.execute(
            "SELECT p.site_game, p.session_id, p.predicted, p.actual, p.correct, p.timestamp "
            "FROM predictions p WHERE p.user_id=? ORDER BY p.id DESC LIMIT 15", (uid,)
        ) as cur:
            rows = await cur.fetchall()
        if not rows:
            await update.message.reply_text("📭 Chưa có lịch sử dự đoán.")
            return
        lines = ["📜 *Lịch sử dự đoán:*"]
        for r in rows:
            label = GAME_MAP.get(r[0], {}).get("label", r[0])
            pred, actual = r[2] or "?", r[3] or "?"
            correct = "✅" if r[4] == 1 else ("❌" if r[3] else "🔄")
            t = datetime.fromtimestamp(r[5]).strftime("%d/%m %H:%M")
            lines.append(f"• {label} | P{r[1]} | {pred}→{actual} {correct} | {t}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"cmd_history error: {e}")
        await update.message.reply_text("⚠️ Lỗi lấy lịch sử.")

async def cmd_muakey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    kb = [
        [InlineKeyboardButton("1 Ngày - 15,000đ", callback_data="buy_key_1")],
        [InlineKeyboardButton("7 Ngày - 70,000đ", callback_data="buy_key_7")],
        [InlineKeyboardButton("30 Ngày - 360,000đ", callback_data="buy_key_30")],
        [InlineKeyboardButton("❌ Hủy", callback_data="cancel")],
    ]
    await update.message.reply_text("💳 *Chọn gói key:*", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

async def buy_key_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""
    user = query.from_user
    if data.startswith("buy_key_"):
        days_str = data.split("_")[-1]
        if days_str not in PRICE_PLANS:
            await query.answer("Gói không hợp lệ!", show_alert=True)
            return
        amount = PRICE_PLANS[days_str]
        now_ts = int(time.time())
        note = f"Nap{user.id}{now_ts}"
        qr_url = f"https://img.vietqr.io/image/MB-009100981-compact.png?amount={amount}&addInfo={note}&accountName=NGUYEN%20HOANG%20QUOC%20CUONG"
        kb = [
            [InlineKeyboardButton("✅ Đã chuyển khoản", callback_data=f"paid|{now_ts}|{days_str}")],
            [InlineKeyboardButton("❌ Hủy", callback_data="cancel")],
        ]
        try:
            await query.message.delete()
        except:
            pass
        try:
            await context.bot.send_photo(
                chat_id=user.id, photo=qr_url,
                caption=f"💳 *Thanh toán:* {amount:,}đ\n📝 *Nội dung CK:* `{note}`\n⏳ Bấm nút sau khi đã chuyển khoản.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(kb),
            )
        except Exception as e:
            logger.error(f"buy_key send_photo error: {e}")
            await safe_send(context.bot, user.id, f"⚠️ Lỗi hiển thị QR. Liên hệ {SUPPORT_USERNAME}")
    elif data.startswith("paid|"):
        parts = data.split("|")
        if len(parts) < 3:
            return
        _, ts, days_str = parts[0], parts[1], parts[2]
        if days_str not in PRICE_PLANS:
            return
        amount = PRICE_PLANS[days_str]
        for admin_id in ADMIN_IDS:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Duyệt", callback_data=f"approve_pay|{user.id}|{ts}|{days_str}"),
                 InlineKeyboardButton("❌ Từ chối", callback_data=f"reject_pay|{user.id}|{ts}")]
            ])
            await safe_send(context.bot, admin_id,
                f"🔔 *Yêu cầu mua key*\n👤 {user.full_name} (`{user.id}`)\n📝 ND: Nap{user.id}{ts}\n📦 Gói: {days_str} ngày - {amount:,}đ",
                parse_mode=ParseMode.MARKDOWN)
            try:
                await context.bot.send_message(admin_id, "👆 Hành động:", reply_markup=kb)
            except:
                pass
        try:
            await query.message.edit_caption("✅ *Đã gửi yêu cầu.*\nAdmin sẽ xác nhận sớm.", parse_mode=ParseMode.MARKDOWN)
        except:
            pass

# ---------------------------- ADMIN APPROVE ----------------------------
async def admin_approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    if not is_admin(query.from_user.id):
        await query.answer("Không có quyền!", show_alert=True)
        return
    await query.answer()
    parts = (query.data or "").split("|")
    if parts[0] == "approve_pay" and len(parts) >= 4:
        try:
            uid = int(parts[1])
            ts = parts[2]
            days_str = parts[3]
            days = int(days_str)
            amount = PRICE_PLANS.get(days_str, 0)
        except:
            await query.edit_message_text("❌ Dữ liệu không hợp lệ")
            return
        key = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=16))
        now = time.time()
        try:
            await db.execute("INSERT OR REPLACE INTO keys (key, days, created, created_by) VALUES (?,?,?,?)", (key, days, now, query.from_user.id))
            await db.execute("INSERT OR REPLACE INTO user_keys (user_id, key, activated) VALUES (?,?,?)", (uid, key, now))
            await db.execute("INSERT OR REPLACE INTO payments (id, user_id, amount, days, timestamp, status, handled_by) VALUES (?,?,?,?,?,?,?)",
                             (f"{uid}_{int(now)}", uid, amount, days, now, "approved", query.from_user.id))
            await db.commit()
        except Exception as e:
            logger.error(f"approve_pay DB error: {e}")
            await query.edit_message_text(f"❌ Lỗi DB: {e}")
            return
        expiry = datetime.fromtimestamp(now + days * 86400).strftime("%d/%m/%Y %H:%M")
        await safe_send(context.bot, uid, f"🎉 *Key đã được kích hoạt!*\n🔑 `{key}`\n📦 Gói: {days} ngày\n⏳ Hết hạn: {expiry}", parse_mode=ParseMode.MARKDOWN)
        await query.edit_message_text(f"✅ Đã cấp key cho user {uid}: `{key}`", parse_mode=ParseMode.MARKDOWN)
    elif parts[0] == "reject_pay" and len(parts) >= 2:
        uid = int(parts[1])
        await safe_send(context.bot, uid, "❌ Yêu cầu mua key bị từ chối.")
        await query.edit_message_text(f"❌ Đã từ chối user {uid}")

# ---------------------------- CSKH -------------------------------------
async def relay_message(bot: Bot, sender_id: int, receiver_id: int, text: str):
    prefix = "📩 Từ CSKH" if sender_id in CSKH_USER_IDS else f"📩 Khách `{sender_id}`"
    await safe_send(bot, receiver_id, f"{prefix}:\n{text}", parse_mode=ParseMode.MARKDOWN)

async def cmd_cskh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message:
        return
    if user.id in active_chats:
        await update.message.reply_text("🟢 Bạn đang trong cuộc trò chuyện với CSKH.")
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Chấp nhận", callback_data=f"cskh_accept|{user.id}"),
         InlineKeyboardButton("❌ Từ chối", callback_data=f"cskh_reject|{user.id}")]
    ])
    mention = " ".join(f'<a href="tg://user?id={uid}">CSKH</a>' for uid in CSKH_USER_IDS)
    try:
        await context.bot.send_message(CSKH_GROUP_ID, f"🔔 Yêu cầu hỗ trợ từ <b>{user.full_name}</b> (<code>{user.id}</code>)\n{mention}", parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception as e:
        logger.warning(f"cmd_cskh send group error: {e}")
        await update.message.reply_text(f"⚠️ Không liên hệ được nhóm CSKH. Liên hệ trực tiếp: {SUPPORT_USERNAME}")
        return
    await update.message.reply_text("📩 Đã gửi yêu cầu. Vui lòng chờ CSKH kết nối.")

async def cskh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    cskh_uid = query.from_user.id
    if cskh_uid not in CSKH_USER_IDS:
        await query.answer("Không phải CSKH!", show_alert=True)
        return
    await query.answer()
    parts = (query.data or "").split("|")
    if parts[0] == "cskh_accept" and len(parts) >= 2:
        user_id = int(parts[1])
        active_chats[user_id] = cskh_uid
        active_chats[cskh_uid] = user_id
        await safe_send(context.bot, user_id, "✅ CSKH đã kết nối. Nhắn tin tại đây.\nGõ /ketthuc để kết thúc.")
        await query.edit_message_text(f"✅ Đã nhận hỗ trợ cho user {user_id}.\nTrả lời ngay trong chat.")
    elif parts[0] == "cskh_reject" and len(parts) >= 2:
        user_id = int(parts[1])
        await safe_send(context.bot, user_id, "❌ CSKH hiện không khả dụng. Thử lại sau.")
        await query.edit_message_text(f"❌ Đã từ chối user {user_id}")

async def cmd_ketthuc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message:
        return
    if user.id not in active_chats:
        await update.message.reply_text("ℹ️ Không có cuộc trò chuyện nào đang mở.")
        return
    other = active_chats.pop(user.id, None)
    if other:
        active_chats.pop(other, None)
        await safe_send(context.bot, other, "🔚 Cuộc trò chuyện đã kết thúc.")
    await update.message.reply_text("🔚 Đã kết thúc chat CSKH.")

# ---------------------------- ADMIN COMMANDS ---------------------------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Thống kê", callback_data="admin_stats")],
        [InlineKeyboardButton("💰 Thu nhập", callback_data="admin_income")],
        [InlineKeyboardButton("🔧 Bảo trì ON", callback_data="admin_maint_on"), InlineKeyboardButton("🔧 OFF", callback_data="admin_maint_off")],
        [InlineKeyboardButton("📜 Log học tập", callback_data="admin_hoclog")],
        [InlineKeyboardButton("👥 Danh sách user", callback_data="admin_users")],
    ])
    await update.message.reply_text("🛡 *Admin Menu*", reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not is_admin(query.from_user.id):
        if query:
            await query.answer("Không có quyền!", show_alert=True)
        return
    await query.answer()
    data = query.data or ""
    if data == "admin_stats":
        try:
            async with db.execute("SELECT COUNT(*) FROM users") as c: user_cnt = (await c.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM user_keys") as c: key_cnt = (await c.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM predictions") as c: pred_cnt = (await c.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM predictions WHERE correct=1") as c: correct_cnt = (await c.fetchone())[0]
            acc = f"{correct_cnt/pred_cnt*100:.1f}%" if pred_cnt else "N/A"
            watchers = sum(len(v) for v in user_watches.values())
            await query.message.reply_text(
                f"📊 *Thống kê Bot*\n👥 Users: {user_cnt}\n🔑 Keys đã cấp: {key_cnt}\n🤖 Dự đoán: {pred_cnt}\n🎯 Độ chính xác: {acc}\n👀 Đang theo dõi: {watchers} slot",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            await query.message.reply_text(f"⚠️ Lỗi: {e}")
    elif data == "admin_income":
        try:
            async with db.execute("SELECT SUM(amount) FROM payments WHERE status='approved'") as c:
                total = (await c.fetchone())[0] or 0
            async with db.execute("SELECT COUNT(*) FROM payments WHERE status='approved'") as c:
                count = (await c.fetchone())[0]
            await query.message.reply_text(f"💰 *Tổng thu nhập:* {total:,}đ\n📦 Số giao dịch thành công: {count}", parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await query.message.reply_text(f"⚠️ Lỗi: {e}")
    elif data == "admin_maint_on":
        await db.execute("UPDATE bot_config SET value='1' WHERE key='maintenance'"); await db.commit()
        await query.message.reply_text("🔧 Chế độ bảo trì: *BẬT*", parse_mode=ParseMode.MARKDOWN)
    elif data == "admin_maint_off":
        await db.execute("UPDATE bot_config SET value='0' WHERE key='maintenance'"); await db.commit()
        await query.message.reply_text("✅ Chế độ bảo trì: *TẮT*", parse_mode=ParseMode.MARKDOWN)
    elif data == "admin_hoclog":
        try:
            async with db.execute(
                "SELECT site_game, session_id, predicted, actual, correct FROM predictions ORDER BY id DESC LIMIT 15"
            ) as cur:
                rows = await cur.fetchall()
            if not rows:
                await query.message.reply_text("📭 Chưa có log.")
                return
            lines = ["📈 *Log học tập (15 mới nhất):*"]
            for r in rows:
                label = GAME_MAP.get(r[0], {}).get("label", r[0])
                correct = "✅" if r[4] == 1 else "❌"
                lines.append(f"• {label} | P{r[1]} | {r[2]}→{r[3] or '?'} {correct}")
            await query.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await query.message.reply_text(f"⚠️ Lỗi: {e}")
    elif data == "admin_users":
        try:
            async with db.execute("SELECT user_id, username, banned FROM users ORDER BY joined_date DESC LIMIT 20") as cur:
                users = await cur.fetchall()
            if not users:
                await query.message.reply_text("Chưa có user.")
                return
            text = "👥 *Danh sách user (20 gần nhất):*\n"
            for uid, uname, banned in users:
                status = "🚫" if banned else "✅"
                text += f"• {status} `{uid}` - {uname or 'N/A'}\n"
            await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await query.message.reply_text(f"⚠️ Lỗi: {e}")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    msg = update.message.reply_to_message
    try:
        async with db.execute("SELECT user_id FROM users WHERE banned=0") as c:
            users = await c.fetchall()
    except Exception as e:
        await update.message.reply_text(f"⚠️ Lỗi DB: {e}")
        return
    count = 0
    for (uid,) in users:
        try:
            if msg:
                await context.bot.copy_message(chat_id=uid, from_chat_id=update.message.chat_id, message_id=msg.message_id)
            elif context.args:
                text = " ".join(context.args)
                await context.bot.send_message(uid, text)
            else:
                break
            count += 1
        except:
            pass
        await asyncio.sleep(0.05)
    await update.message.reply_text(f"✅ Đã gửi đến {count}/{len(users)} người.")

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Dùng: /ban <user_id>")
        return
    try:
        uid = int(context.args[0])
    except:
        await update.message.reply_text("❌ user_id không hợp lệ.")
        return
    await db.execute("UPDATE users SET banned=1 WHERE user_id=?", (uid,))
    await db.commit()
    for gkey in list(user_watches.keys()):
        if uid in user_watches[gkey]:
            user_watches[gkey].remove(uid)
    await update.message.reply_text(f"✅ Đã ban user {uid}")

async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Dùng: /unban <user_id>")
        return
    try:
        uid = int(context.args[0])
    except:
        await update.message.reply_text("❌ user_id không hợp lệ.")
        return
    await db.execute("UPDATE users SET banned=0 WHERE user_id=?", (uid,))
    await db.commit()
    await update.message.reply_text(f"✅ Đã unban user {uid}")

async def admin_setkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args or []) < 2:
        await update.message.reply_text("Dùng: /setkey <user_id> <days>")
        return
    try:
        uid = int(context.args[0])
        days = int(context.args[1])
    except:
        await update.message.reply_text("❌ Tham số không hợp lệ.")
        return
    key = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=16))
    now = time.time()
    await db.execute("INSERT OR REPLACE INTO keys (key, days, created, created_by) VALUES (?,?,?,?)", (key, days, now, update.effective_user.id))
    await db.execute("INSERT OR REPLACE INTO user_keys (user_id, key, activated) VALUES (?,?,?)", (uid, key, now))
    await db.commit()
    expiry = datetime.fromtimestamp(now + days * 86400).strftime("%d/%m/%Y %H:%M")
    await safe_send(context.bot, uid, f"🎉 *Key mới được cấp!*\n🔑 `{key}`\n⏳ Hết hạn: {expiry}", parse_mode=ParseMode.MARKDOWN)
    await update.message.reply_text(f"✅ Đã cấp key `{key}` cho user {uid}", parse_mode=ParseMode.MARKDOWN)

async def admin_delkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Dùng: /delkey <user_id>")
        return
    try:
        uid = int(context.args[0])
    except:
        await update.message.reply_text("❌ user_id không hợp lệ.")
        return
    await db.execute("DELETE FROM user_keys WHERE user_id=?", (uid,))
    await db.commit()
    await update.message.reply_text(f"✅ Đã xoá key của user {uid}")

async def admin_editkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args or []) < 2:
        await update.message.reply_text("Dùng: /editkey <user_id> <thêm_days>")
        return
    try:
        uid = int(context.args[0])
        add_days = int(context.args[1])
    except:
        await update.message.reply_text("❌ Tham số không hợp lệ.")
        return
    async with db.execute("SELECT k.key, k.days, uk.activated FROM user_keys uk JOIN keys k ON uk.key=k.key WHERE uk.user_id=?", (uid,)) as cur:
        key_info = await cur.fetchone()
    if not key_info:
        await update.message.reply_text("❌ User chưa có key.")
        return
    key, old_days, activated = key_info
    new_days = old_days + add_days
    new_key = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=16))
    now = time.time()
    await db.execute("INSERT OR REPLACE INTO keys (key, days, created, created_by) VALUES (?,?,?,?)", (new_key, new_days, now, update.effective_user.id))
    await db.execute("UPDATE user_keys SET key=?, activated=? WHERE user_id=?", (new_key, now, uid))
    await db.commit()
    expiry = datetime.fromtimestamp(now + new_days * 86400).strftime("%d/%m/%Y %H:%M")
    await safe_send(context.bot, uid, f"🔄 *Key đã được gia hạn!*\n🔑 `{new_key}`\n⏳ Hết hạn mới: {expiry}", parse_mode=ParseMode.MARKDOWN)
    await update.message.reply_text(f"✅ Đã gia hạn thêm {add_days} ngày cho user {uid}")

# ---------------------------- ERROR HANDLER ---------------------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    err = context.error
    if isinstance(err, (NetworkError, asyncio.TimeoutError)):
        logger.warning(f"Network error: {err}")
        return
    if isinstance(err, Forbidden):
        logger.info(f"Forbidden: {err}")
        return
    logger.error(f"Unhandled error: {err}\n{traceback.format_exc()}")

# ---------------------------- MAIN ------------------------------------
async def main():
    global ai_engine
    setup_logging()
    logger.info("Starting bot V7...")
    await init_db()
    ai_engine = AIEngine()
    await ai_engine.load_weights_from_db()

    app = Application.builder().token(BOT_TOKEN).connect_timeout(30).read_timeout(30).build()
    app.add_handler(MessageHandler(filters.ALL, typing_middleware), group=-1)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("info", cmd_info))
    app.add_handler(CommandHandler("muakey", cmd_muakey))
    app.add_handler(CommandHandler("ketthuc", cmd_ketthuc))
    app.add_handler(CommandHandler("nhancskh", cmd_cskh))
    app.add_handler(CommandHandler("admin", admin_menu))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    app.add_handler(CommandHandler("ban", admin_ban))
    app.add_handler(CommandHandler("unban", admin_unban))
    app.add_handler(CommandHandler("setkey", admin_setkey))
    app.add_handler(CommandHandler("delkey", admin_delkey))
    app.add_handler(CommandHandler("editkey", admin_editkey))
    app.add_handler(CallbackQueryHandler(admin_approve_callback, pattern=r"^(approve_pay|reject_pay)\|"))
    app.add_handler(CallbackQueryHandler(cskh_callback, pattern=r"^cskh_"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^admin_"))
    app.add_handler(CallbackQueryHandler(buy_key_callback, pattern=r"^(buy_key_|paid\|)"))
    app.add_handler(CallbackQueryHandler(button_callback, pattern=r"^(start_game\||cancel)"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))
    app.add_error_handler(error_handler)

    try:
        await app.bot.set_my_commands([
            BotCommand("start","Bắt đầu"), BotCommand("stop","Dừng dự đoán"),
            BotCommand("history","Lịch sử"), BotCommand("info","Tài khoản"),
            BotCommand("muakey","Mua key"), BotCommand("nhancskh","Hỗ trợ"),
            BotCommand("ketthuc","Kết thúc chat"), BotCommand("admin","Quản trị"),
        ])
    except Exception as e:
        logger.warning(f"set_my_commands error: {e}")

    bg_task = None
    try:
        async with app:
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
            bg_task = asyncio.create_task(background_fetch_and_learn(app.bot))
            logger.info("✅ Bot V7 đang chạy. Ctrl+C để dừng.")
            loop = asyncio.get_running_loop()
            def stop_handler(*_):
                _shutdown_event.set()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, stop_handler)
                except:
                    pass
            await _shutdown_event.wait()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    except Exception as e:
        logger.critical(f"main error: {e}\n{traceback.format_exc()}")
    finally:
        _shutdown_event.set()
        if bg_task and not bg_task.done():
            bg_task.cancel()
            try:
                await asyncio.wait_for(bg_task, timeout=5)
            except:
                pass
        if app.updater.running:
            await app.updater.stop()
        if app.running:
            await app.stop()
        await close_db()
        logger.info("Bot stopped")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass