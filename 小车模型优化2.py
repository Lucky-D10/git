import tkinter as tk
import random
import time
import math
from datetime import datetime
import threading

# 尝试导入RPi.GPIO，如果失败则设置标志
try:
    import RPi.GPIO as GPIO
    gpio_available = True
except ImportError:
    gpio_available = False
    print("警告: RPi.GPIO不可用，将使用模拟模式")
import serial
import logging
from dataclasses import dataclass
from typing import Optional, Tuple

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('FocusRacingGame')

# 全局常量
WIDTH, HEIGHT = 1020, 530
# 优化的科技感色彩方案
RED = "#FF4444"  # 红色
BLUE = "#4488FF"  # 蓝色
GREEN = "#44CC44"  # 绿色
YELLOW = "#FFDD00"  # 黄色
DARK_BG = "#0A0A0A"  # 深色背景
LIGHT_BG = "#1A1A1A"  # 浅色背景
TRACK_COLOR = "#222222"  # 赛道颜色
BUTTON_BG = "#2A2A2A"  # 按钮背景
BUTTON_HOVER = "#3A3A3A"  # 按钮悬停
GLOW_COLOR = "#66AAFF"  # 发光效果颜色
PANEL_BG = "#16162A"  # 面板背景色（新增）
ACCENT = "#00E5FF"  # 科技感强调色（新增）
FONT_TITLE = ("Microsoft YaHei", 24, "bold")
FONT_LARGE = ("Microsoft YaHei", 32, "bold")  # 优化：从40改为32
FONT_SUBTITLE = ("Microsoft YaHei", 18, "bold")  # 新增：副标题字体
FONT_NORMAL = ("Microsoft YaHei", 16, "bold")
FONT_SMALL = ("Microsoft YaHei", 20)
FONT_VERY_SMALL = ("Microsoft YaHei", 12)
FONT_MONO = ("Consolas", 12)  # 新增：等宽字体用于数据显示

# GPIO配置
STBY = 17  # 使能
# 电机控制引脚定义
IN1 = 18  # 电机1正向
IN2 = 23  # 电机1反向
IN3 = 24  # 电机2正向
IN4 = 25  # 电机2反向

# PWM对象
pwm1 = None
pwm2 = None

if gpio_available:
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(STBY, GPIO.OUT)
        GPIO.setup(IN1, GPIO.OUT)
        GPIO.setup(IN2, GPIO.OUT)
        GPIO.setup(IN3, GPIO.OUT)
        GPIO.setup(IN4, GPIO.OUT)

        # 设置PWM
        pwm1 = GPIO.PWM(IN1, 1000)  # 1kHz频率
        pwm2 = GPIO.PWM(IN3, 1000)
        pwm1.start(0)
        pwm2.start(0)

        GPIO.output(STBY, GPIO.LOW)  # 初始状态为关闭
        print("GPIO初始化成功")
    except Exception as e:
        print(f"GPIO初始化失败: {e}")
        gpio_available = False

# 模拟EEG模块（如果没有实际模块）
class MockEEG:
    """模拟EEG模块，生成随机专注度数据"""
    def __init__(self):
        self.Attention_1 = 50
        self.Attention_2 = 50

    def f1(self):
        """模拟玩家1的专注度数据"""
        while True:
            self.Attention_1 = max(0, min(100, self.Attention_1 + random.randint(-5, 5)))
            time.sleep(0.1)

    def f2(self):
        """模拟玩家2的专注度数据"""
        while True:
            self.Attention_2 = max(0, min(100, self.Attention_2 + random.randint(-5, 5)))
            time.sleep(0.1)

# 尝试导入EEG模块，如果失败则使用模拟模块
try:
    import EEG
    logger.info("成功导入EEG模块")
except ImportError:
    logger.warning("未找到EEG模块，使用模拟数据")
    EEG = MockEEG()

# 速度配置
MAX_SPEED = 10  # 最大速度限制
SPEED_SMOOTH_FACTOR = 0.3  # 速度平滑因子，值越大变化越快

class Player:
    def __init__(self, name, color_name, color):
        self.name = f"{color_name}方玩家"
        self.color = color
        self.ready = False
        self.focus = 0  # 初始专注度设为0，防止小车自动移动
        self.focus_level = "低专注"
        self.focus_history = []
        self.speed = 0  # 初始速度设为0
        self.last_speed = 0  # 上一次的速度，用于平滑过渡
        self.max_speed = 0
        self.avg_focus = 0
        self.position = 0
        self.race_time = 0
        self.last_focus_update = 0
        self.track_length = 500  # 轨道长度，默认500米

    def reset(self):
        """重置玩家所有状态到初始状态"""
        self.ready = False
        self.focus = 0  # 重置为0
        self.focus_level = "低专注"
        self.focus_history = []
        self.speed = 0  # 重置为0
        self.last_speed = 0  # 重置为0
        self.max_speed = 0
        self.avg_focus = 0
        self.position = 0  # 重置为0，确保从起点线开始
        self.race_time = 0
        self.last_focus_update = 0

    def update_focus_level(self):
        """根据当前专注度更新专注等级"""
        if self.focus >= 70:
            self.focus_level = "高专注"
        elif self.focus >= 40:
            self.focus_level = "中专注"
        else:
            self.focus_level = "低专注"

    def update_focus(self, current_time, attention):
        """更新专注度"""
        # 每次调用都更新专注度，确保速度能及时响应
        # 使用实际的专注度数据
        new_focus = attention

        self.focus = new_focus
        self.focus_history.append(new_focus)
        # 限制历史数据长度，优化性能
        if len(self.focus_history) > 100:
            self.focus_history = self.focus_history[-100:]
        self.last_focus_update = current_time

        # 计算目标速度
        if self.focus >= 70:
            self.focus_level = "高专注"
            target_speed = 8 + (self.focus - 70) / 30 * 4
        elif self.focus >= 40:
            self.focus_level = "中专注"
            target_speed = 5 + (self.focus - 40) / 30 * 3
        else:
            self.focus_level = "低专注"
            target_speed = 3 + (self.focus - 20) / 20 * 2 if self.focus > 20 else 0

        # 速度上限保护
        target_speed = min(target_speed, MAX_SPEED)

        # 速度平滑过渡
        self.speed = self.last_speed + (target_speed - self.last_speed) * SPEED_SMOOTH_FACTOR
        self.last_speed = self.speed

        # 记录最大速度
        if self.speed > self.max_speed:
            self.max_speed = self.speed

        # 更新赛车位置 - 到达终点线后停止
        if self.position < self.track_length:
            self.position += self.speed * 0.03
            self.position = min(self.position, self.track_length)  # 允许位置达到轨道长度，确保小车到达终点线
        else:
            # 到达终点线后停止移动
            self.speed = 0

        # 记录比赛时间（如果到达终点）
        if self.position >= self.track_length and self.race_time == 0:
            self.race_time = current_time

    def calculate_avg_focus(self):
        """计算平均专注度"""
        if not self.focus_history:
            self.avg_focus = 0
        else:
            self.avg_focus = sum(self.focus_history) / len(self.focus_history)

class FocusRacingGame:
    def __init__(self, root):
        self.root = root
        self.root.title("脑控赛车竞速游戏")
        self.root.geometry("1020x510+0+0")  # 全屏尺寸，置于左上角
        self.root.resizable(False, False)
        self.root.configure(bg=DARK_BG)

        # 游戏状态
        self.state = "start"  # start, ready, countdown, racing, result

        # 玩家设置
        self.player_red = Player("玩家1", "红", RED)
        self.player_blue = Player("玩家2", "蓝", BLUE)

        # 倒计时相关
        self.countdown_value = 3
        self.countdown_id = None
        self.countdown_circle_id = None

        # 比赛计时
        self.start_time = 0
        self.racing_time = 0

        # 轨道长度选项
        self.track_length_options = {
            100: 100,
            300: 300,
            500: 500
        }
        self.selected_track_length = 500  # 默认500米

        # 缓存赛道参数
        self.track_left = 100
        self.track_right = WIDTH - 100
        self.track_length = self.track_right - self.track_left

        # 创建游戏画布
        self.canvas = tk.Canvas(self.root, width=WIDTH, height=HEIGHT, bg=DARK_BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # 初始化游戏
        self.create_start_screen()

    def select_track_length(self, length):
        """选择轨道长度"""
        self.selected_track_length = length
        
        # 更新按钮状态、光标和边框高亮
        if hasattr(self, 'track_length_buttons') and self.track_length_buttons:
            length_options = [100, 300, 500]
            for i, btn in enumerate(self.track_length_buttons):
                if length_options[i] == length:
                    btn.config(
                        bg="#224488", 
                        fg="#ffffff", 
                        activebackground="#3355AA", 
                        activeforeground="#ffffff", 
                        cursor="arrow",
                        highlightthickness=2,
                        highlightbackground=ACCENT,
                        highlightcolor=ACCENT
                    )
                else:
                    btn.config(
                        bg="#1A1A2E", 
                        fg="#666688", 
                        activebackground="#223355", 
                        activeforeground="#8888AA", 
                        cursor="hand2",
                        highlightthickness=1,
                        highlightbackground="#222244",
                        highlightcolor="#222244"
                    )

    def clear_canvas(self):
        """清除画布上的所有元素"""
        self.canvas.delete("all")

    def create_start_screen(self):
        """创建开始界面 - 左右布局（35/65比例）"""
        self.clear_canvas()
        self.state = "start"

        # 重置玩家状态
        self.player_red = Player("玩家1", "红", RED)
        self.player_blue = Player("玩家2", "蓝", BLUE)

        # 简洁背景
        self.canvas.create_rectangle(
            0, 0, WIDTH, HEIGHT,
            fill=DARK_BG,
            outline=""
        )

        # 顶部横幅 - 使用PANEL_BG
        self.canvas.create_rectangle(
            0, 0, WIDTH, 80,
            fill=PANEL_BG,
            outline=ACCENT,
            width=1
        )

        # 游戏标题
        self.canvas.create_text(
            WIDTH // 2, 40,
            text="脑控赛车竞速游戏",
            fill="white",
            font=FONT_TITLE
        )

        # 创建右分界线 - 35/65比例
        divider_x = WIDTH * 0.35
        self.canvas.create_line(
            divider_x, 80,
            divider_x, HEIGHT,
            fill=ACCENT,
            width=1
        )

        # === 左侧区域：图标（35%宽度） ===
        icon_area_width = WIDTH * 0.35

        # 计算中心位置
        center_x = icon_area_width * 0.5
        center_y = (HEIGHT + 80) // 2 - 40

        # 游戏插图背景 - 圆圈半径改为120
        circle_radius = 120
        self.canvas.create_oval(
            center_x - circle_radius, center_y - circle_radius,
            center_x + circle_radius, center_y + circle_radius,
            fill="",
            outline=ACCENT,
            width=2
        )

        # 绘制赛道 - 赛道宽度改为180
        track_y = center_y + 25
        track_width = 180
        track_height = 20
        self.canvas.create_rectangle(
            center_x - track_width // 2, track_y - track_height // 2,
            center_x + track_width // 2, track_y + track_height // 2,
            fill=TRACK_COLOR,
            outline=ACCENT,
            width=1
        )

        # 绘制两辆赛车 - 两车间距改为55
        car_y = track_y - 28

        # 增强的科技感赛车设计 - 与比赛界面风格一致
        def draw_car_model(x_pos, y, color):
            car_elements = []

            # 赛车发光效果（优化：只保留关键元素发光）
            car_elements.append(self.canvas.create_polygon(
                x_pos - 36, y + 14,      # 左后轮
                x_pos - 29, y - 14,     # 左前轮
                x_pos + 29, y - 14,     # 右前轮
                x_pos + 36, y + 14,      # 右后轮
                fill="",
                outline=ACCENT,
                width=1
            ))

            # 赛车主体 - 流线型设计
            car_elements.append(self.canvas.create_polygon(
                x_pos - 32, y + 10,      # 左后轮
                x_pos - 26, y - 15,     # 左前轮
                x_pos + 26, y - 15,     # 右前轮
                x_pos + 32, y + 10,      # 右后轮
                fill=color,
                outline=ACCENT,
                width=2
            ))

            # 车顶 - 增强设计
            car_elements.append(self.canvas.create_polygon(
                x_pos - 19, y - 15,
                x_pos - 13, y - 23,
                x_pos + 13, y - 23,
                x_pos + 19, y - 15,
                fill="#1A1A1A",
                outline=ACCENT,
                width=2
            ))

            # 车窗 - 增强设计
            car_elements.append(self.canvas.create_polygon(
                x_pos - 15, y - 10,
                x_pos - 19, y - 15,
                x_pos + 19, y - 15,
                x_pos + 15, y - 10,
                fill="#224488",
                outline=ACCENT,
                width=1
            ))

            # 车轮 - 增强设计
            wheel_radius = 8
            # 前轮
            car_elements.append(self.canvas.create_oval(
                x_pos - 23 - wheel_radius, y + 10 - wheel_radius,
                x_pos - 23 + wheel_radius, y + 10 + wheel_radius,
                fill="#111111",
                outline=ACCENT,
                width=2
            ))
            # 后轮
            car_elements.append(self.canvas.create_oval(
                x_pos + 23 - wheel_radius, y + 10 - wheel_radius,
                x_pos + 23 + wheel_radius, y + 10 + wheel_radius,
                fill="#111111",
                outline=ACCENT,
                width=2
            ))
            # 增强的轮毂设计
            car_elements.append(self.canvas.create_oval(
                x_pos - 23 - wheel_radius + 2, y + 10 - wheel_radius + 2,
                x_pos - 23 + wheel_radius - 2, y + 10 + wheel_radius - 2,
                fill=ACCENT,
                outline=color,
                width=2
            ))
            car_elements.append(self.canvas.create_oval(
                x_pos + 23 - wheel_radius + 2, y + 10 - wheel_radius + 2,
                x_pos + 23 + wheel_radius - 2, y + 10 + wheel_radius - 2,
                fill=ACCENT,
                outline=color,
                width=2
            ))
            # 轮毂中心
            car_elements.append(self.canvas.create_oval(
                x_pos - 23 - wheel_radius + 5, y + 10 - wheel_radius + 5,
                x_pos - 23 + wheel_radius - 5, y + 10 + wheel_radius - 5,
                fill=color,
                outline=ACCENT,
                width=1
            ))
            car_elements.append(self.canvas.create_oval(
                x_pos + 23 - wheel_radius + 5, y + 10 - wheel_radius + 5,
                x_pos + 23 + wheel_radius - 5, y + 10 + wheel_radius - 5,
                fill=color,
                outline=ACCENT,
                width=1
            ))

            # 增强的灯光系统
            # 前灯
            car_elements.append(self.canvas.create_oval(
                x_pos + 28, y - 6,
                x_pos + 36, y + 1,
                fill="#FFFFCC",
                outline="#FFFF66",
                width=2
            ))
            # 尾灯
            car_elements.append(self.canvas.create_oval(
                x_pos - 36, y - 3,
                x_pos - 28, y + 3,
                fill=color,
                outline="#FF4444",
                width=2
            ))

            # 装饰线条
            # 侧面线条
            car_elements.append(self.canvas.create_line(
                x_pos - 26, y + 3,
                x_pos + 26, y + 3,
                fill=ACCENT,
                width=2
            ))
            # 车头线条
            car_elements.append(self.canvas.create_line(
                x_pos - 19, y - 10,
                x_pos + 19, y - 10,
                fill=ACCENT,
                width=1
            ))

            return car_elements

        # 红色赛车 - 左侧（间距55）
        red_car_x = center_x - 55
        draw_car_model(red_car_x, car_y, RED)

        # 蓝色赛车 - 右侧（间距55）
        blue_car_x = center_x + 55
        draw_car_model(blue_car_x, car_y, BLUE)

        # === 右侧区域：文字和按钮（65%宽度） ===
        text_area_width = WIDTH * 0.65
        text_x = icon_area_width + 30
        
        # 布局容器 - 在右侧区域内居中
        container_width = text_area_width * 0.95
        container_height = HEIGHT * 0.92
        container_x = text_x + text_area_width // 2
        container_y = HEIGHT // 2
        
        # 布局参数 - 使用容器高度的百分比，优化空间分配（整体下移）
        title_pos = 0.22
        instructions_pos = 0.34
        instructions_end_pos = 0.62
        button_pos = 0.82
        version_pos = 0.92
        
        # 游戏说明标题 - 更突出，添加背景框
        title_y = container_y - container_height // 2 + container_height * title_pos
        title_bg_width = 200
        title_bg_height = 45
        self.canvas.create_rectangle(
            container_x - title_bg_width / 2, title_y - title_bg_height / 2,
            container_x + title_bg_width / 2, title_y + title_bg_height / 2,
            fill="#1A1A33", outline=YELLOW, width=2
        )
        self.canvas.create_text(
            container_x, title_y,
            text="比 赛 规 则",
            fill=YELLOW,
            font=FONT_SUBTITLE
        )

        # 游戏说明区域背景 - 在标题边框下方（整体下移）
        instructions_start_y = title_y + title_bg_height / 2 + 30
        instructions_end_y = container_y - container_height // 2 + container_height * instructions_end_pos
        self.canvas.create_rectangle(
            text_x + 10, instructions_start_y - 20,
            text_x + text_area_width - 10, instructions_end_y - 10,
            fill="#0A0A15", outline="#223355", width=1
        )

        # 游戏说明 - 在标题下方，使用固定行高（保留4条核心规则）
        instructions = [
            "1. 选择轨道长度后点击开始游戏，双人竞速",
            "2. 专注力越高，赛车速度越快",
            "3. 首先到达终点线的玩家获胜",
            "4. 比赛过程中实时显示双方专注度和速度"
        ]

        line_height = 36
        for i, text in enumerate(instructions):
            # 编号圆圈
            circle_size = 14
            circle_x = text_x + 30
            circle_y = instructions_start_y + i * line_height
            self.canvas.create_oval(
                circle_x - circle_size, circle_y - circle_size,
                circle_x + circle_size, circle_y + circle_size,
                fill=YELLOW if i < 2 else BLUE,
                outline="#ffffff",
                width=2
            )
            self.canvas.create_text(
                circle_x, circle_y,
                text=str(i + 1),
                fill="black",
                font=("Microsoft YaHei", 11, "bold")
            )
            # 文本
            self.canvas.create_text(
                text_x + 65, circle_y,
                text=text,
                anchor="w",
                fill="#CCCCDD",
                font=FONT_SMALL
            )
        
        # 开始按钮 - 优化样式和效果
        button_y = container_y - container_height // 2 + container_height * button_pos
        
        # 按钮发光效果
        glow_radius = 3
        for i in range(glow_radius, 0, -1):
            alpha = 255 // (glow_radius * 2) * i
            self.canvas.create_oval(
                container_x - 110 - i, button_y - 30 - i,
                container_x + 110 + i, button_y + 30 + i,
                fill=f"#{alpha:02x}{(255):02x}{(alpha):02x}",
                outline=""
            )
        
        # 按钮背景框
        self.canvas.create_rectangle(
            container_x - 110, button_y - 30,
            container_x + 110, button_y + 30,
            fill="#003311", outline="#00ff66", width=2
        )
        
        # 按钮边框高亮
        self.canvas.create_rectangle(
            container_x - 108, button_y - 28,
            container_x + 108, button_y + 28,
            fill="", outline="#33ff99", width=1
        )
        
        start_btn = tk.Button(
            self.root,
            text="开始游戏",
            command=self.create_ready_screen,
            bg="#00cc55",
            fg="#ffffff",
            font=("Microsoft YaHei", 18, "bold"),
            relief="flat",
            padx=70,
            pady=14,
            activebackground="#00ff77",
            activeforeground="#ffffff",
            bd=0,
            cursor="hand2",
            borderwidth=0,
            highlightthickness=0
        )
        
        self.start_btn_id = self.canvas.create_window(
            container_x, button_y,
            window=start_btn
        )

        # 版本信息 - 在开始按钮下方
        version_y = container_y - container_height // 2 + container_height * version_pos
        self.canvas.create_text(
            WIDTH // 2, version_y,
            text="版本: 3.0 | 专注力训练游戏",
            fill=ACCENT,
            font=FONT_VERY_SMALL
        )

        # 底部版权信息
        year = datetime.now().year
        self.canvas.create_text(
            WIDTH // 2, HEIGHT - 40,
            text=f"© {year} 脑控赛车竞速游戏 | 提升您的专注力",
            fill="#8888AA",
            font=FONT_VERY_SMALL
        )

    def create_ready_screen(self):
        """创建准备界面"""
        self.clear_canvas()
        self.state = "ready"

        # 背景
        self.canvas.create_rectangle(0, 0, WIDTH, HEIGHT, fill=DARK_BG, outline="")

        # 顶部标题栏
        self.canvas.create_rectangle(0, 0, WIDTH, 48, fill=PANEL_BG, outline="")
        self.canvas.create_rectangle(0, 46, WIDTH, 48, fill=ACCENT, outline="")
        self.canvas.create_text(WIDTH // 2, 24, text="玩家准备", fill="white", font=FONT_TITLE)

        # 卡片（240px高，居中于58~415区域）
        card_center_y = 238
        self.draw_player_card(WIDTH // 4 + 10, card_center_y, self.player_red)
        self.draw_player_card(3 * WIDTH // 4 - 10, card_center_y, self.player_blue)

        # 中间 VS
        self.canvas.create_text(WIDTH // 2, card_center_y, text="VS", fill=ACCENT, font=("Consolas", 16, "bold"))

        # 轨道长度选择区域 - 在开始比赛按钮上方
        track_length_y = 395
        
        # 轨道长度选择标题
        self.canvas.create_text(WIDTH // 2, track_length_y - 46, text="选择轨道长度", fill=ACCENT, font=("Microsoft YaHei", 14, "bold"))
        
        # 创建轨道长度选择按钮容器背景
        btn_container_width = 280
        btn_container_height = 55
        
        self.canvas.create_rectangle(
            WIDTH // 2 - btn_container_width / 2, track_length_y - btn_container_height / 2,
            WIDTH // 2 + btn_container_width / 2, track_length_y + btn_container_height / 2,
            fill="#0A0A15", outline="#334466", width=1
        )
        
        # 创建轨道长度选择按钮
        self.track_length_buttons = []
        length_options = [100, 300, 500]
        btn_width = 70
        btn_height = 35
        spacing = 25
        
        for i, length in enumerate(length_options):
            btn_x = WIDTH // 2 - (len(length_options) - 1) * (btn_width + spacing) / 2 + i * (btn_width + spacing)
            btn_y = track_length_y
            
            is_selected = (self.selected_track_length == length)
            
            if is_selected:
                btn_bg = "#224488"
                btn_fg = "#ffffff"
                border_color = ACCENT
                cursor_type = "arrow"
            else:
                btn_bg = "#1A1A2E"
                btn_fg = "#666688"
                border_color = "#222244"
                cursor_type = "hand2"
            
            btn = tk.Button(
                self.root,
                text=f"{length}米",
                command=lambda l=length: self.select_track_length(l),
                bg=btn_bg,
                fg=btn_fg,
                font=("Microsoft YaHei", 12, "bold"),
                width=7,
                height=1,
                relief="flat",
                bd=0,
                highlightthickness=2 if is_selected else 1,
                highlightbackground=border_color,
                highlightcolor=border_color,
                cursor=cursor_type,
                activebackground="#3355AA",
                activeforeground="#ffffff",
                borderwidth=0
            )
            
            self.track_length_buttons.append(btn)
            
            self.canvas.create_window(
                btn_x, btn_y,
                window=btn
            )

        # 底部操作区（430 到 510，80px）
        self.canvas.create_rectangle(0, 430, WIDTH, HEIGHT, fill=PANEL_BG, outline="")
        self.canvas.create_line(0, 430, WIDTH, 430, fill="#333355", width=1)

        # 提示信息
        if self.all_ready():
            self.canvas.create_text(WIDTH // 2, 435, text="✓ 双方已准备就绪", fill=GREEN, font=("Microsoft YaHei", 11))
        else:
            self.canvas.create_text(WIDTH // 2, 435, text="请双方玩家点击准备按钮", fill=YELLOW, font=("Microsoft YaHei", 11))

        # 开始比赛按钮
        ready_btn = tk.Button(
            self.root,
            text="开始比赛" if self.all_ready() else "等待玩家准备",
            command=self.start_countdown,
            bg=GREEN if self.all_ready() else "#444455",
            fg="white",
            font=("Microsoft YaHei", 12, "bold"),
            relief="flat",
            padx=35,
            pady=4,
            activebackground="#22AA22" if self.all_ready() else "#555566",
            state=tk.NORMAL if self.all_ready() else tk.DISABLED,
            cursor="hand2" if self.all_ready() else "arrow",
            bd=0
        )
        if self.all_ready():
            self.canvas.create_rectangle(
                WIDTH // 2 - 72, 452,
                WIDTH // 2 + 72, 480,
                fill="", outline=GREEN, width=1
            )
        self.ready_btn_id = self.canvas.create_window(WIDTH // 2, 466, window=ready_btn)

        # 底部信息
        self.canvas.create_text(WIDTH // 2, 498, text="专注比赛，享受游戏！", fill="#555577", font=("Microsoft YaHei", 9))

    def all_ready(self):
        """检查是否所有玩家都准备好了"""
        return self.player_red.ready and self.player_blue.ready

    def draw_player_card(self, x, y, player):
        """绘制玩家信息卡片"""
        card_w, card_h = 320, 240
        half_w, half_h = card_w // 2, card_h // 2

        # 阴影
        self.canvas.create_rectangle(x - half_w + 3, y - half_h + 3, x + half_w + 3, y + half_h + 3, fill="#050510", outline="")
        # 背景
        self.canvas.create_rectangle(x - half_w, y - half_h, x + half_w, y + half_h, fill=PANEL_BG, outline="")
        # 边框
        self.canvas.create_rectangle(x - half_w, y - half_h, x + half_w, y + half_h, fill="", outline="#333355", width=1)
        # 顶部装饰条
        self.canvas.create_rectangle(x - half_w, y - half_h, x + half_w, y - half_h + 3, fill=player.color, outline="")

        # 玩家名称
        self.canvas.create_text(x, y - half_h + 22, text=player.name, fill=player.color, font=("Microsoft YaHei", 15, "bold"))

        # 状态胶囊
        status_color = GREEN if player.ready else "#666688"
        status_text = "● 已准备" if player.ready else "○ 未准备"
        self.canvas.create_rectangle(x - 36, y - half_h + 40, x + 36, y - half_h + 56, fill="#0E0E1E", outline=status_color, width=1)
        self.canvas.create_text(x, y - half_h + 48, text=status_text, fill=status_color, font=("Microsoft YaHei", 10))

        # 赛车展示区（130px高）
        car_area_top = y - half_h + 65
        car_area_bottom = y + half_h - 65
        car_area_cy = (car_area_top + car_area_bottom) // 2

        # 展示区背景
        self.canvas.create_rectangle(x - half_w + 12, car_area_top, x + half_w - 12, car_area_bottom, fill="#0E0E1E", outline="#222244", width=1)

        # 赛车（居中，1.0倍原始大小）
        car_y = car_area_cy
        car_x = x
        s = 1.0

        self.canvas.create_polygon(car_x - 36*s, car_y + 14*s, car_x - 29*s, car_y - 14*s, car_x + 29*s, car_y - 14*s, car_x + 36*s, car_y + 14*s, fill="", outline=ACCENT, width=1)
        self.canvas.create_polygon(car_x - 32*s, car_y + 10*s, car_x - 26*s, car_y - 15*s, car_x + 26*s, car_y - 15*s, car_x + 32*s, car_y + 10*s, fill=player.color, outline=ACCENT, width=2)
        self.canvas.create_polygon(car_x - 19*s, car_y - 15*s, car_x - 13*s, car_y - 23*s, car_x + 13*s, car_y - 23*s, car_x + 19*s, car_y - 15*s, fill="#1A1A1A", outline=ACCENT, width=2)
        self.canvas.create_polygon(car_x - 15*s, car_y - 10*s, car_x - 19*s, car_y - 15*s, car_x + 19*s, car_y - 15*s, car_x + 15*s, car_y - 10*s, fill="#224488", outline=ACCENT, width=1)
        wheel_r = int(8 * s)
        for wx in [car_x - int(23*s), car_x + int(23*s)]:
            self.canvas.create_oval(wx - wheel_r, car_y + int(10*s) - wheel_r, wx + wheel_r, car_y + int(10*s) + wheel_r, fill="#111111", outline=ACCENT, width=2)
            self.canvas.create_oval(wx - wheel_r + 2, car_y + int(10*s) - wheel_r + 2, wx + wheel_r - 2, car_y + int(10*s) + wheel_r - 2, fill=ACCENT, outline=player.color, width=2)
            self.canvas.create_oval(wx - wheel_r + 5, car_y + int(10*s) - wheel_r + 5, wx + wheel_r - 5, car_y + int(10*s) + wheel_r - 5, fill=player.color, outline=ACCENT, width=1)
        self.canvas.create_oval(car_x + int(28*s), car_y - int(6*s), car_x + int(36*s), car_y + int(1*s), fill="#FFFFCC", outline="#FFFF66", width=2)
        self.canvas.create_oval(car_x - int(36*s), car_y - int(3*s), car_x - int(28*s), car_y + int(3*s), fill=player.color, outline="#FF4444", width=2)
        self.canvas.create_line(car_x - int(26*s), car_y + int(3*s), car_x + int(26*s), car_y + int(3*s), fill=ACCENT, width=2)
        self.canvas.create_line(car_x - int(19*s), car_y - int(10*s), car_x + int(19*s), car_y - int(10*s), fill=ACCENT, width=1)

        # 说明文字
        self.canvas.create_text(x, y + half_h - 48, text="专注力将影响赛车速度", fill="#666688", font=("Microsoft YaHei", 10))

        # 准备按钮
        btn_text = "准备" if not player.ready else "取消准备"
        btn_bg = player.color if not player.ready else "#333344"
        btn = tk.Button(
            self.root, text=btn_text,
            command=lambda p=player: self.toggle_player_ready(p),
            bg=btn_bg, fg="white",
            font=("Microsoft YaHei", 12),
            relief="flat", padx=20, pady=3,
            activebackground="#444455",
            cursor="hand2", bd=0
        )
        self.canvas.create_window(x, y + half_h - 22, window=btn)

    def toggle_player_ready(self, player):
        """切换玩家准备状态"""
        player.ready = not player.ready
        self.create_ready_screen()

    def start_countdown(self):
        """开始倒计时"""
        if not self.all_ready():
            return

        self.state = "countdown"
        self.countdown_value = 3
        self.draw_countdown()

    def draw_countdown(self):
        """绘制倒计时界面 - 使用ACCENT色边框和发光效果"""
        self.clear_canvas()

        # 背景
        self.canvas.create_rectangle(
            0, 0, WIDTH, HEIGHT,
            fill=DARK_BG,
            outline=""
        )

        # 标题
        self.canvas.create_text(
            WIDTH // 2, 100,
            text="比赛即将开始",
            fill=YELLOW,
            font=FONT_TITLE
        )

        # 倒计时圆圈 - 使用ACCENT色作为边框
        self.countdown_circle_id = self.canvas.create_oval(
            WIDTH // 2 - 100, HEIGHT // 2 - 100,
            WIDTH // 2 + 100, HEIGHT // 2 + 100,
            fill=PANEL_BG,
            outline=ACCENT,
            width=5
        )

        # 倒计时数字发光效果（先画一个稍大的半透明文字作为光晕）
        self.countdown_glow = self.canvas.create_text(
            WIDTH // 2, HEIGHT // 2,
            text=str(self.countdown_value),
            fill="#004455",  # 半透明ACCENT色模拟光晕
            font=("Microsoft YaHei", 80, "bold")
        )

        # 倒计时数字
        self.countdown_text = self.canvas.create_text(
            WIDTH // 2, HEIGHT // 2,
            text=str(self.countdown_value),
            fill=ACCENT,
            font=("Microsoft YaHei", 72, "bold")
        )

        # 提示文字 - 使用FONT_SUBTITLE
        self.canvas.create_text(
            WIDTH // 2, HEIGHT - 100,
            text="请保持专注...",
            fill="#AAAAAA",
            font=FONT_SUBTITLE
        )

        # 倒计时更新
        self.update_countdown()

    def update_countdown(self):
        """更新倒计时"""
        if self.countdown_value > 0:
            self.canvas.itemconfig(self.countdown_text, text=str(self.countdown_value))
            self.canvas.itemconfig(self.countdown_glow, text=str(self.countdown_value))
            self.countdown_value -= 1
            self.countdown_id = self.root.after(1000, self.update_countdown)
        else:
            # 移除倒计时圆圈
            self.canvas.delete(self.countdown_circle_id)
            self.canvas.delete(self.countdown_glow)

            # 显示"开始!"文字
            self.canvas.itemconfig(self.countdown_text, text="开始!")
            self.root.after(1000, self.start_race)

    def set_motor_speed(self, speed):
        """设置电机速度"""
        if not gpio_available:
            return

        # 将速度值（0-12）转换为PWM占空比（0-100）
        duty_cycle = min(100, int(speed * 8.33))  # 12 * 8.33 ≈ 100

        # 控制电机1（左轮）
        GPIO.output(IN2, GPIO.LOW)  # 正转
        pwm1.ChangeDutyCycle(duty_cycle)

        # 控制电机2（右轮）
        GPIO.output(IN4, GPIO.LOW)  # 正转
        pwm2.ChangeDutyCycle(duty_cycle)

    def start_race(self):
        """开始比赛"""
        self.clear_canvas()
        self.state = "racing"

        # 重置玩家
        self.player_red.reset()
        self.player_blue.reset()

        # 设置轨道长度
        self.player_red.track_length = self.selected_track_length
        self.player_blue.track_length = self.selected_track_length

        # 记录开始时间
        self.start_time = time.time()

        # 启动电机
        if gpio_available:
            GPIO.output(STBY, GPIO.HIGH)

        # 开始游戏循环
        self.update_race()

    def update_race(self):
        """更新比赛状态"""
        if self.state != "racing":
            return

        # 计算比赛用时
        self.racing_time = time.time() - self.start_time

        # 更新玩家专注力和位置
        self.player_blue.update_focus(self.racing_time, EEG.Attention_1)
        self.player_red.update_focus(self.racing_time, EEG.Attention_2)

        # 控制电机速度（使用蓝色玩家的速度）
        self.set_motor_speed(self.player_blue.speed)

        # 检查比赛是否结束
        winner = self.check_winner()
        if winner:
            self.show_result(winner)
            return

        # 绘制比赛界面
        self.draw_race_screen()

        # 继续游戏循环
        self.root.after(50, self.update_race)

    def draw_race_screen(self):
        """绘制比赛界面"""
        self.clear_canvas()

        # 简洁背景
        self.canvas.create_rectangle(
            0, 0, WIDTH, HEIGHT,
            fill=DARK_BG,
            outline=""
        )

        # === 左上角：红方信息面板 ===
        # 面板背景（与时间面板同高，统一顶部对齐）
        self.canvas.create_rectangle(
            15, 8, 210, 48,
            fill=PANEL_BG,
            outline=RED,
            width=1
        )
        # 顶部装饰条
        self.canvas.create_rectangle(
            15, 8, 210, 11,
            fill=RED,
            outline=""
        )
        # 玩家标签
        self.canvas.create_text(
            28, 22,
            text="● 红方",
            fill=RED,
            font=FONT_VERY_SMALL,
            anchor="w"
        )
        # 专注度数值（红色高亮）
        self.canvas.create_text(
            28, 38,
            text=f"专注度:",
            fill="#8888AA",
            font=FONT_VERY_SMALL,
            anchor="w"
        )
        self.canvas.create_text(
            82, 38,
            text=f"{self.player_red.focus}",
            fill=RED,
            font=("Consolas", 13, "bold"),
            anchor="w"
        )
        # 分隔符
        self.canvas.create_text(
            110, 38,
            text="|",
            fill="#444466",
            font=FONT_VERY_SMALL,
            anchor="w"
        )
        # 速度数值（ACCENT高亮）
        self.canvas.create_text(
            122, 38,
            text=f"速度:",
            fill="#8888AA",
            font=FONT_VERY_SMALL,
            anchor="w"
        )
        self.canvas.create_text(
            158, 38,
            text=f"{self.player_red.speed:.1f}",
            fill=ACCENT,
            font=("Consolas", 13, "bold"),
            anchor="w"
        )

        # 比赛时间 - 顶部中央位置
        self.canvas.create_rectangle(
            WIDTH // 2 - 90, 8,
            WIDTH // 2 + 90, 48,
            fill=PANEL_BG,
            outline=ACCENT,
            width=1
        )
        # 顶部装饰条
        self.canvas.create_rectangle(
            WIDTH // 2 - 90, 8,
            WIDTH // 2 + 90, 11,
            fill=ACCENT,
            outline=""
        )
        self.canvas.create_text(
            WIDTH // 2, 30,
            text=f"⏱ {self.racing_time:.1f}s",
            fill=ACCENT,
            font=("Consolas", 14, "bold")
        )

        # === 右上角：蓝方信息面板 ===
        self.canvas.create_rectangle(
            WIDTH - 210, 8, WIDTH - 15, 48,
            fill=PANEL_BG,
            outline=BLUE,
            width=1
        )
        # 顶部装饰条
        self.canvas.create_rectangle(
            WIDTH - 210, 8, WIDTH - 15, 11,
            fill=BLUE,
            outline=""
        )
        # 玩家标签
        self.canvas.create_text(
            WIDTH - 197, 22,
            text="● 蓝方",
            fill=BLUE,
            font=FONT_VERY_SMALL,
            anchor="w"
        )
        # 专注度数值（蓝色高亮）
        self.canvas.create_text(
            WIDTH - 197, 38,
            text=f"专注度:",
            fill="#8888AA",
            font=FONT_VERY_SMALL,
            anchor="w"
        )
        self.canvas.create_text(
            WIDTH - 143, 38,
            text=f"{self.player_blue.focus}",
            fill=BLUE,
            font=("Consolas", 13, "bold"),
            anchor="w"
        )
        # 分隔符
        self.canvas.create_text(
            WIDTH - 115, 38,
            text="|",
            fill="#444466",
            font=FONT_VERY_SMALL,
            anchor="w"
        )
        # 速度数值（ACCENT高亮）
        self.canvas.create_text(
            WIDTH - 103, 38,
            text=f"速度:",
            fill="#8888AA",
            font=FONT_VERY_SMALL,
            anchor="w"
        )
        self.canvas.create_text(
            WIDTH - 67, 38,
            text=f"{self.player_blue.speed:.1f}",
            fill=ACCENT,
            font=("Consolas", 13, "bold"),
            anchor="w"
        )

        # 绘制赛道（包含跑道线，置于小车下方）
        self.draw_track()

        # 左右两侧专注度条
        self.draw_side_focus_bars()

        # 专注度波形图区域
        self.draw_focus_chart_area()

        # 绘制赛车（放在赛道上方）
        self.draw_car(self.player_red, 135, RED)  # 向上靠一点
        self.draw_car(self.player_blue, 260, BLUE)  # 往下靠一点

        # 绘制边框
        self.canvas.create_rectangle(
            5, 5, WIDTH - 5, HEIGHT - 5,
            fill="",
            outline=ACCENT,
            width=2
        )

    def draw_track(self):
        """绘制赛道 - 优化参数"""
        # 赛道参数 - track_top=55, track_bottom=HEIGHT-210
        track_top = 55
        track_bottom = HEIGHT - 210
        track_left = 100
        track_right = WIDTH - 100
        track_height = track_bottom - track_top

        # 赛道背景 - 使用"#1E1E30"
        self.canvas.create_rectangle(
            track_left, track_top,
            track_right, track_bottom,
            fill="#1E1E30",
            outline=""
        )
        # 赛道边界 - 上边界
        self.canvas.create_rectangle(
            track_left, track_top,
            track_right, track_top + 3,
            fill=YELLOW,
            outline=ACCENT,
            width=2
        )
        # 下边界
        self.canvas.create_rectangle(
            track_left, track_bottom - 3,
            track_right, track_bottom,
            fill=YELLOW,
            outline=ACCENT,
            width=2
        )

        # 起点线
        self.canvas.create_line(
            track_left, track_top,
            track_left, track_bottom,
            fill="#FFFFFF",
            width=3
        )

        # 终点线
        self.canvas.create_line(
            track_right, track_top,
            track_right, track_bottom,
            fill="#FF4444",
            width=3
        )

        # 跑道线 - 间距从50改为60
        track_length = track_right - track_left
        for i in range(0, track_length, 60):
            # 红色小车跑道线
            self.canvas.create_rectangle(
                track_left + i, 155 - 2,
                track_left + i + 15, 155 + 2,
                fill=ACCENT,
                outline=""
            )
            # 蓝色小车跑道线
            self.canvas.create_rectangle(
                track_left + i, 280 - 2,
                track_left + i + 15, 280 + 2,
                fill=ACCENT,
                outline=""
            )

        # 赛道中间分隔线
        self.canvas.create_line(
            track_left, (track_top + track_bottom) // 2,
            track_right, (track_top + track_bottom) // 2,
            fill=ACCENT,
            width=1,
            dash=(5, 5)
        )

    def draw_side_focus_bars(self):
        """在左右两侧绘制长的专注度条"""
        # 赛道参数
        track_top = 55
        track_bottom = HEIGHT - 210
        track_height = track_bottom - track_top
        
        # 左侧红色专注度条 - 位于左侧中间位置
        left_bar_x = 35  # 左侧中间位置
        bar_width = 14
        bar_height = track_height - 30  # 稍微缩短避免穿模
        bar_top_y = track_top + 15  # 向下偏移

        # 背景条
        self.canvas.create_rectangle(
            left_bar_x, bar_top_y,
            left_bar_x + bar_width, bar_top_y + bar_height,
            fill="#1A1A2E",
            outline=RED,
            width=2
        )

        # 填充条（根据专注度）
        fill_height = int((self.player_red.focus / 100) * bar_height)
        if fill_height > 0:
            self.canvas.create_rectangle(
                left_bar_x + 1, bar_top_y + bar_height - fill_height,
                left_bar_x + bar_width - 1, bar_top_y + bar_height,
                fill=RED,
                outline=""
            )

        # 专注度数值 - 放在条的右侧，远离赛道
        self.canvas.create_text(
            left_bar_x + bar_width + 12, bar_top_y + bar_height // 2,
            text=f"{self.player_red.focus}",
            fill=RED,
            font=("Consolas", 13, "bold")
        )

        # 左侧标签 - 放在条的下方
        self.canvas.create_text(
            left_bar_x + bar_width // 2, bar_top_y + bar_height + 15,
            text="专注度",
            fill=RED,
            font=("Microsoft YaHei", 11, "bold")
        )

        # 右侧蓝色专注度条 - 位于右侧中间位置
        right_bar_x = WIDTH - 49  # 右侧中间位置

        # 背景条
        self.canvas.create_rectangle(
            right_bar_x, bar_top_y,
            right_bar_x + bar_width, bar_top_y + bar_height,
            fill="#1A1A2E",
            outline=BLUE,
            width=2
        )

        # 填充条（根据专注度）
        fill_height = int((self.player_blue.focus / 100) * bar_height)
        if fill_height > 0:
            self.canvas.create_rectangle(
                right_bar_x + 1, bar_top_y + bar_height - fill_height,
                right_bar_x + bar_width - 1, bar_top_y + bar_height,
                fill=BLUE,
                outline=""
            )

        # 专注度数值 - 放在条的左侧，远离赛道
        self.canvas.create_text(
            right_bar_x - 12, bar_top_y + bar_height // 2,
            text=f"{self.player_blue.focus}",
            fill=BLUE,
            font=("Consolas", 13, "bold")
        )

        # 右侧标签 - 放在条的下方
        self.canvas.create_text(
            right_bar_x + bar_width // 2, bar_top_y + bar_height + 15,
            text="专注度",
            fill=BLUE,
            font=("Microsoft YaHei", 11, "bold")
        )

    def draw_car(self, player, y, color):
        """绘制赛车"""
        # 检查当前状态，如果是开始界面，则绘制在固定位置
        if self.state == "start":
            # 开始界面：左右分开绘制两辆赛车，位置在圆圈里
            icon_area_width = WIDTH * 0.35
            center_x = icon_area_width * 0.5

            if color == RED:
                x_pos = center_x - 40  # 左侧红色赛车，位于圆圈内
            else:
                x_pos = center_x + 40   # 右侧蓝色赛车，位于圆圈内
        else:
            # 比赛界面：基于进度绘制
            x_pos = self.track_left + (player.position * self.track_length / self.selected_track_length)

        # 为每辆车创建唯一标识符
        car_id = f"{color}_{y}"

        # 清除之前的小车绘制
        if hasattr(self, f'car_{car_id}'):
            for item_id in getattr(self, f'car_{car_id}'):
                self.canvas.delete(item_id)
            delattr(self, f'car_{car_id}')

        # 存储当前小车的所有元素ID
        car_elements = []

        # 增强的科技感赛车设计 - 调整尺寸
        # 赛车发光效果（优化：只保留关键元素发光）
        car_elements.append(self.canvas.create_polygon(
            x_pos - 36, y + 14,      # 左后轮
            x_pos - 29, y - 14,     # 左前轮
            x_pos + 29, y - 14,     # 右前轮
            x_pos + 36, y + 14,      # 右后轮
            fill="",
            outline=ACCENT,
            width=1
        ))

        # 赛车主体 - 流线型设计
        car_elements.append(self.canvas.create_polygon(
            x_pos - 32, y + 10,      # 左后轮
            x_pos - 26, y - 15,     # 左前轮
            x_pos + 26, y - 15,     # 右前轮
            x_pos + 32, y + 10,      # 右后轮
            fill=color,
            outline=ACCENT,
            width=2
        ))

        # 车顶 - 增强设计
        car_elements.append(self.canvas.create_polygon(
            x_pos - 19, y - 15,
            x_pos - 13, y - 23,
            x_pos + 13, y - 23,
            x_pos + 19, y - 15,
            fill="#1A1A1A",
            outline=ACCENT,
            width=2
        ))

        # 车窗 - 增强设计
        car_elements.append(self.canvas.create_polygon(
            x_pos - 15, y - 10,
            x_pos - 19, y - 15,
            x_pos + 19, y - 15,
            x_pos + 15, y - 10,
            fill="#224488",
            outline=ACCENT,
            width=1
        ))

        # 车轮 - 增强设计
        wheel_radius = 8
        # 前轮
        car_elements.append(self.canvas.create_oval(
            x_pos - 23 - wheel_radius, y + 10 - wheel_radius,
            x_pos - 23 + wheel_radius, y + 10 + wheel_radius,
            fill="#111111",
            outline=ACCENT,
            width=2
        ))
        # 后轮
        car_elements.append(self.canvas.create_oval(
            x_pos + 23 - wheel_radius, y + 10 - wheel_radius,
            x_pos + 23 + wheel_radius, y + 10 + wheel_radius,
            fill="#111111",
            outline=ACCENT,
            width=2
        ))
        # 增强的轮毂设计
        car_elements.append(self.canvas.create_oval(
            x_pos - 23 - wheel_radius + 2, y + 10 - wheel_radius + 2,
            x_pos - 23 + wheel_radius - 2, y + 10 + wheel_radius - 2,
            fill=ACCENT,
            outline=color,
            width=2
        ))
        car_elements.append(self.canvas.create_oval(
            x_pos + 23 - wheel_radius + 2, y + 10 - wheel_radius + 2,
            x_pos + 23 + wheel_radius - 2, y + 10 + wheel_radius - 2,
            fill=ACCENT,
            outline=color,
            width=2
        ))
        # 轮毂中心
        car_elements.append(self.canvas.create_oval(
            x_pos - 23 - wheel_radius + 5, y + 10 - wheel_radius + 5,
            x_pos - 23 + wheel_radius - 5, y + 10 + wheel_radius - 5,
            fill=color,
            outline=ACCENT,
            width=1
        ))
        car_elements.append(self.canvas.create_oval(
            x_pos + 23 - wheel_radius + 5, y + 10 - wheel_radius + 5,
            x_pos + 23 + wheel_radius - 5, y + 10 + wheel_radius - 5,
            fill=color,
            outline=ACCENT,
            width=1
        ))

        # 增强的灯光系统
        # 前灯
        car_elements.append(self.canvas.create_oval(
            x_pos + 28, y - 6,
            x_pos + 36, y + 1,
            fill="#FFFFCC",
            outline="#FFFF66",
            width=2
        ))
        # 尾灯
        car_elements.append(self.canvas.create_oval(
            x_pos - 36, y - 3,
            x_pos - 28, y + 3,
            fill=color,
            outline="#FF4444",
            width=2
        ))

        # 装饰线条
        # 侧面线条
        car_elements.append(self.canvas.create_line(
            x_pos - 26, y + 3,
            x_pos + 26, y + 3,
            fill=ACCENT,
            width=2
        ))
        # 车头线条
        car_elements.append(self.canvas.create_line(
            x_pos - 19, y - 10,
            x_pos + 19, y - 10,
            fill=ACCENT,
            width=1
        ))


        # 存储当前小车的元素ID
        setattr(self, f'car_{car_id}', car_elements)

    def draw_focus_chart_area(self):
        """绘制专注度波形图区域 - 优化参数"""
        # 波形图区域参数 - 调整位置避免被遮挡
        chart_x, chart_y = 35, HEIGHT - 195
        chart_width, chart_height = WIDTH - 70, 165

        # 绘制波形图区域背景 - 使用PANEL_BG
        self.canvas.create_rectangle(
            chart_x, chart_y,
            chart_x + chart_width, chart_y + chart_height,
            fill=PANEL_BG,
            outline=""
        )
        # 边框
        self.canvas.create_rectangle(
            chart_x, chart_y,
            chart_x + chart_width, chart_y + chart_height,
            fill="",
            outline=ACCENT,
            width=1
        )

        # 标题
        self.canvas.create_text(
            chart_x + chart_width // 2, chart_y + 15,
            text="专注度趋势图",
            fill=ACCENT,
            font=('Microsoft YaHei', 12, 'bold')
        )

        # 绘制坐标轴
        axis_x = chart_x + 40
        axis_y = chart_y + chart_height - 25
        axis_width = chart_width - 70
        axis_height = chart_height - 50

        # 坐标原点
        self.canvas.create_line(
            axis_x, axis_y,
            axis_x + axis_width, axis_y,
            fill=ACCENT,
            arrow=tk.LAST,
            width=2
        )
        self.canvas.create_line(
            axis_x, axis_y,
            axis_x, axis_y - axis_height,
            fill=ACCENT,
            arrow=tk.LAST,
            width=2
        )

        # 时间轴刻度标签 - 使用FONT_MONO
        self.canvas.create_text(
            axis_x, axis_y + 15,
            text="0",
            fill="#8888AA",
            font=FONT_MONO
        )
        self.canvas.create_text(
            axis_x + axis_width, axis_y + 15,
            text=f"{int(self.racing_time)}秒",
            fill="#8888AA",
            font=FONT_MONO
        )

        # 专注度刻度标签 - 使用FONT_MONO
        for value in [0, 25, 50, 75, 100]:
            y_pos = axis_y - (value * axis_height) / 100
            self.canvas.create_text(
                axis_x - 10, y_pos,
                text=f"{value}",
                fill="#8888AA",
                anchor="e",
                font=FONT_MONO
            )

        # 网格线
        for value in [0, 25, 50, 75, 100]:
            y_pos = axis_y - (value * axis_height) / 100
            if value > 0:
                self.canvas.create_line(
                    axis_x, y_pos,
                    axis_x + axis_width, y_pos,
                    fill="#2A2A4A",
                    dash=(2, 2),
                    width=1
                )

        # 绘制波形图
        self.draw_waveforms(axis_x, axis_y, axis_width, axis_height)

        # 添加图例
        self.canvas.create_rectangle(
            chart_x + chart_width - 120, chart_y + 5, chart_x + chart_width - 100, chart_y + 15,
            fill=RED,
            outline=ACCENT,
            width=2
        )
        self.canvas.create_text(
            chart_x + chart_width - 90, chart_y + 10,
            text="红方",
            fill=RED,
            font=FONT_VERY_SMALL,
            anchor="w"
        )

        self.canvas.create_rectangle(
            chart_x + chart_width - 120, chart_y + 20, chart_x + chart_width - 100, chart_y + 30,
            fill=BLUE,
            outline=ACCENT,
            width=2
        )
        self.canvas.create_text(
            chart_x + chart_width - 90, chart_y + 25,
            text="蓝方",
            fill=BLUE,
            font=FONT_VERY_SMALL,
            anchor="w"
        )

        # 添加鼠标悬停事件
        self.canvas.tag_bind("waveform_area", "<Motion>", lambda e: self.on_waveform_hover(e, axis_x, axis_y, axis_width, axis_height))
        # 创建波形图区域标记
        self.canvas.create_rectangle(
            axis_x, axis_y - axis_height,
            axis_x + axis_width, axis_y,
            fill="",
            outline="",
            tags="waveform_area"
        )

    def on_waveform_hover(self, event, axis_x, axis_y, axis_width, axis_height):
        """鼠标悬停在波形图上时的处理函数"""
        # 检查鼠标是否在波形图区域内
        if not (axis_x <= event.x <= axis_x + axis_width and
                axis_y - axis_height <= event.y <= axis_y):
            return

        # 计算鼠标位置对应的时间点
        time_ratio = (event.x - axis_x) / axis_width

        # 显示红方数据
        if self.player_red.focus_history:
            index = min(int(time_ratio * len(self.player_red.focus_history)), len(self.player_red.focus_history) - 1)
            focus_value = self.player_red.focus_history[index]
            # 计算对应的Y坐标
            y_pos = axis_y - (focus_value * axis_height) / 100

            # 清除之前的悬停提示
            self.canvas.delete("hover_tooltip")

            # 绘制悬停提示
            self.canvas.create_rectangle(
                event.x + 10, event.y - 30,
                event.x + 80, event.y - 10,
                fill=PANEL_BG,
                outline=RED,
                width=1,
                tags="hover_tooltip"
            )
            self.canvas.create_text(
                event.x + 45, event.y - 20,
                text=f"红方: {focus_value}",
                fill=RED,
                font=FONT_MONO,
                tags="hover_tooltip"
            )

        # 显示蓝方数据
        if self.player_blue.focus_history:
            index = min(int(time_ratio * len(self.player_blue.focus_history)), len(self.player_blue.focus_history) - 1)
            focus_value = self.player_blue.focus_history[index]
            # 计算对应的Y坐标
            y_pos = axis_y - (focus_value * axis_height) / 100

            # 绘制悬停提示
            self.canvas.create_rectangle(
                event.x + 10, event.y - 60,
                event.x + 80, event.y - 40,
                fill=PANEL_BG,
                outline=BLUE,
                width=1,
                tags="hover_tooltip"
            )
            self.canvas.create_text(
                event.x + 45, event.y - 50,
                text=f"蓝方: {focus_value}",
                fill=BLUE,
                font=FONT_MONO,
                tags="hover_tooltip"
            )

    def draw_waveforms(self, axis_x, axis_y, axis_width, axis_height):
        """绘制专注度波形"""
        # 红色玩家波形
        if self.player_red.focus_history and len(self.player_red.focus_history) > 1:
            points = []
            for i, focus in enumerate(self.player_red.focus_history):
                x = axis_x + (i * axis_width) / (len(self.player_red.focus_history) - 1)
                y = axis_y - (focus * axis_height) / 100
                points.append(x)
                points.append(y)
            if len(points) > 2:
                # 绘制波形发光效果（优化：只保留1层）
                self.canvas.create_line(
                    *points,
                    fill="#FF4444",
                    width=5,
                    smooth=True
                )
                # 绘制主波形 - 更平滑的曲线
                self.canvas.create_line(
                    *points,
                    fill=RED,
                    width=2,
                    smooth=True,
                    capstyle=tk.ROUND,
                    joinstyle=tk.ROUND
                )
                # 绘制最后一个点 - 发光效果（优化：只保留1层）
                last_x = points[-2]
                last_y = points[-1]
                self.canvas.create_oval(
                    last_x - 7, last_y - 7,
                    last_x + 7, last_y + 7,
                    fill="",
                    outline=RED,
                    width=1
                )
                # 主点
                self.canvas.create_oval(
                    last_x - 4, last_y - 4,
                    last_x + 4, last_y + 4,
                    fill=RED,
                    outline=ACCENT,
                    width=2
                )
                # 在最新数据点上方添加小方框显示专注度数值 - 使用FONT_MONO
                last_focus = self.player_red.focus
                # 计算文本尺寸
                text_width = len(str(last_focus)) * 8
                # 绘制方框
                box_padding = 4
                self.canvas.create_rectangle(
                    last_x - text_width/2 - box_padding,
                    last_y - 20 - box_padding,
                    last_x + text_width/2 + box_padding,
                    last_y - 20 + 15 + box_padding,
                    fill=PANEL_BG,
                    outline=RED,
                    width=1
                )
                # 绘制数值 - 使用FONT_MONO
                self.canvas.create_text(
                    last_x,
                    last_y - 12,
                    text=f"{last_focus}",
                    fill=RED,
                    font=FONT_MONO
                )

        # 蓝色玩家波形
        if self.player_blue.focus_history and len(self.player_blue.focus_history) > 1:
            points = []
            for i, focus in enumerate(self.player_blue.focus_history):
                x = axis_x + (i * axis_width) / (len(self.player_blue.focus_history) - 1)
                y = axis_y - (focus * axis_height) / 100
                points.append(x)
                points.append(y)
            if len(points) > 2:
                # 绘制波形发光效果（优化：只保留1层）
                self.canvas.create_line(
                    *points,
                    fill="#4488FF",
                    width=5,
                    smooth=True
                )
                # 绘制主波形 - 更平滑的曲线
                self.canvas.create_line(
                    *points,
                    fill=BLUE,
                    width=2,
                    smooth=True,
                    capstyle=tk.ROUND,
                    joinstyle=tk.ROUND
                )
                # 绘制最后一个点 - 发光效果（优化：只保留1层）
                last_x = points[-2]
                last_y = points[-1]
                self.canvas.create_oval(
                    last_x - 7, last_y - 7,
                    last_x + 7, last_y + 7,
                    fill="",
                    outline=BLUE,
                    width=1
                )
                # 主点
                self.canvas.create_oval(
                    last_x - 4, last_y - 4,
                    last_x + 4, last_y + 4,
                    fill=BLUE,
                    outline=ACCENT,
                    width=2
                )
                # 在最新数据点上方添加小方框显示专注度数值 - 使用FONT_MONO
                last_focus = self.player_blue.focus
                # 计算文本尺寸
                text_width = len(str(last_focus)) * 8
                # 绘制方框
                box_padding = 4
                self.canvas.create_rectangle(
                    last_x - text_width/2 - box_padding,
                    last_y - 20 - box_padding,
                    last_x + text_width/2 + box_padding,
                    last_y - 20 + 15 + box_padding,
                    fill=PANEL_BG,
                    outline=BLUE,
                    width=1
                )
                # 绘制数值 - 使用FONT_MONO
                self.canvas.create_text(
                    last_x,
                    last_y - 12,
                    text=f"{last_focus}",
                    fill=BLUE,
                    font=FONT_MONO
                )

    def draw_focus_info(self, player, y):
        """绘制专注力信息"""
        # 信息板背景 - 使用PANEL_BG
        self.canvas.create_rectangle(
            20, y - 25,
            140, y + 65,
            fill=PANEL_BG,
            outline=player.color,
            width=1
        )

        # 玩家名字
        self.canvas.create_text(
            80, y - 15,
            text=f"{player.name}",
            fill=player.color,
            font=FONT_VERY_SMALL
        )

        # 专注度数值
        self.canvas.create_rectangle(
            30, y + 5,
            130, y + 20,
            fill="#222233",
            outline=""
        )
        self.canvas.create_rectangle(
            30, y + 5,
            30 + player.focus, y + 20,
            fill=player.color,
            outline=""
        )

        # 数值文本 - 使用FONT_MONO
        self.canvas.create_text(
            80, y + 12.5,
            text=f"{player.focus}",
            fill="white",
            font=FONT_MONO
        )

        # 专注度级别
        self.canvas.create_text(
            80, y + 35,
            text=player.focus_level,
            fill=YELLOW,
            font=FONT_VERY_SMALL
        )

        # 速度 - 使用FONT_MONO
        self.canvas.create_text(
            80, y + 50,
            text=f"速度: {player.speed:.1f}",
            fill="#AAAAAA",
            font=FONT_MONO
        )

    def check_winner(self):
        """检查是否有获胜者"""
        # 当任意玩家到达终点线时结束游戏
        if self.player_red.position >= self.selected_track_length and self.player_red.race_time > 0:
            return self.player_red
        if self.player_blue.position >= self.selected_track_length and self.player_blue.race_time > 0:
            return self.player_blue
        return None

    def show_result(self, winner):
        """显示结果界面"""
        # 停止电机
        if gpio_available:
            # 先将PWM占空比设为0
            pwm1.ChangeDutyCycle(0)
            pwm2.ChangeDutyCycle(0)
            # 再关闭STBY
            GPIO.output(STBY, GPIO.LOW)
        self.state = "result"

        # 计算玩家平均专注度
        self.player_red.calculate_avg_focus()
        self.player_blue.calculate_avg_focus()

        self.draw_result_screen(winner)

    def draw_result_screen(self, winner):
        """绘制结果界面 - 优化布局"""
        self.clear_canvas()

        # 顶部横幅
        self.canvas.create_rectangle(
            0, 0, WIDTH, 70,
            fill=winner.color,
            outline="",
            width=0
        )

        # 标题
        self.canvas.create_text(
            WIDTH // 2, 35,
            text="比赛结束",
            fill="white",
            font=FONT_TITLE
        )

        # 胜利者信息 - 居中显示
        info_start_y = 110
        self.canvas.create_text(
            WIDTH // 2, info_start_y,
            text=f"胜利者: {winner.name}",
            fill=winner.color,
            font=FONT_LARGE
        )
        self.canvas.create_text(
            WIDTH // 2, info_start_y + 40,
            text=f"用时: {self.racing_time:.1f}秒",
            fill="white",
            font=FONT_MONO
        )
        self.canvas.create_text(
            WIDTH // 2, info_start_y + 70,
            text=f"平均专注度: {winner.avg_focus:.1f}",
            fill=YELLOW,
            font=FONT_MONO
        )

        # === 主要内容区域 ===
        content_start_y = info_start_y + 80
        content_height = HEIGHT - content_start_y - 100

        # === 左侧区域：玩家信息 ===
        divider_x = WIDTH * 0.5
        left_width = divider_x - 30
        
        left_area_left = 15
        left_area_right = divider_x - 15
        left_area_top = content_start_y
        left_area_bottom = content_start_y + content_height

        # 统计数据区域背景
        self.canvas.create_rectangle(
            left_area_left, left_area_top,
            left_area_right, left_area_bottom,
            fill=PANEL_BG,
            outline=ACCENT,
            width=1
        )

        # 区域标题 - 水平居中
        self.canvas.create_text(
            (left_area_left + left_area_right) // 2, left_area_top + 22,
            text="玩家统计数据",
            fill=YELLOW,
            font=("Microsoft YaHei", 16, "bold")
        )

        # 玩家统计信息 - 将左侧区域分成两个相等的卡片区域
        card_height = (content_height - 50) // 2
        card_gap = 10
        
        # 玩家1卡片区域
        card1_top = left_area_top + 35
        card1_bottom = card1_top + card_height
        
        # 玩家2卡片区域
        card2_top = card1_bottom + card_gap
        card2_bottom = card2_top + card_height
        
        # 绘制玩家统计信息，传入卡片区域边界
        self.draw_player_stats_centered(self.player_red, left_area_left, left_area_right, card1_top, card1_bottom)
        self.draw_player_stats_centered(self.player_blue, left_area_left, left_area_right, card2_top, card2_bottom)

        # === 左右分界线 ===
        self.canvas.create_line(
            divider_x, content_start_y,
            divider_x, content_start_y + content_height,
            fill=ACCENT,
            width=2,
            dash=(5, 3)
        )

        # === 右侧区域：图表 ===
        self.canvas.create_text(
            divider_x + left_width * 0.5, content_start_y + 25,
            text="专注度变化趋势统计",
            fill=YELLOW,
            font=FONT_SMALL
        )

        # 创建图表
        self.draw_focus_chart(divider_x, content_start_y + content_height, content_start_y)

        # 返回按钮 - 居中显示
        home_btn = tk.Button(
            self.root,
            text="返回首页",
            command=self.create_start_screen,
            bg=ACCENT,
            fg="#0A0A0A",
            font=FONT_SMALL,
            relief="flat",
            padx=40,
            pady=10,
            activebackground="#00B8CC",
            cursor="hand2",
            highlightthickness=0,
            bd=0
        )
        self.home_btn_id = self.canvas.create_window(
            WIDTH // 2, HEIGHT - 45,
            window=home_btn
        )

    def draw_player_stats(self, player, x, y):
        """绘制玩家统计数据"""
        # 玩家标题
        self.canvas.create_text(
            x, y - 12,
            text=player.name,
            fill=player.color,
            font=FONT_VERY_SMALL
        )

        # 使用单列布局，避免文字重叠
        stats = [
            f"专注等级: {player.focus_level}",
            f"最高专注度: {max(player.focus_history) if player.focus_history else 0}",
            f"平均专注度: {player.avg_focus:.1f}",
            f"最大速度: {player.max_speed:.1f}"
        ]

        # 单列布局 - 减少行间距
        for row_index, stat in enumerate(stats):
            self.canvas.create_text(
                x, y + row_index * 19,
                text=stat,
                fill="white",
                font=FONT_MONO
            )

    def draw_player_stats_centered(self, player, area_left, area_right, area_top, area_bottom):
        """绘制玩家统计数据 - 相对于容器居中对齐"""
        area_width = area_right - area_left
        area_height = area_bottom - area_top
        
        # 区域中心
        area_center_x = area_left + area_width // 2
        area_center_y = area_top + area_height // 2
        
        # 内边距
        padding = 20
        
        # 玩家标题 - 水平居中，在区域顶部
        self.canvas.create_text(
            area_center_x, area_top + padding,
            text=player.name,
            fill=player.color,
            font=("Microsoft YaHei", 16, "bold")
        )
        
        # 统计数据区域
        data_top = area_top + padding + 30
        data_height = area_height - padding - 35
        
        # 四个数据项分成两行两列，垂直居中
        row_spacing = 30
        total_data_height = row_spacing * 2
        
        # 数据区域起始Y，使数据垂直居中
        data_start_y = data_top + (data_height - total_data_height) // 2
        
        # 两列布局，均匀分布
        col1_x = area_left + padding + 40
        col2_x = area_center_x + 20
        
        # 行1
        y1 = data_start_y
        
        # 第一列 - 专注等级
        self.canvas.create_text(
            col1_x, y1,
            text="专注等级:",
            fill="#666688",
            font=("Microsoft YaHei", 13),
            anchor="w"
        )
        level_color = GREEN if player.focus_level == "高专注" else YELLOW if player.focus_level == "中专注" else "#8888AA"
        self.canvas.create_text(
            col1_x + 85, y1,
            text=player.focus_level,
            fill=level_color,
            font=("Microsoft YaHei", 13, "bold"),
            anchor="w"
        )
        
        # 第二列 - 最高专注度
        self.canvas.create_text(
            col2_x, y1,
            text="最高专注度:",
            fill="#666688",
            font=("Microsoft YaHei", 13),
            anchor="w"
        )
        self.canvas.create_text(
            col2_x + 85, y1,
            text=f"{max(player.focus_history) if player.focus_history else 0}",
            fill=player.color,
            font=("Consolas", 13, "bold"),
            anchor="w"
        )
        
        # 行2
        y2 = data_start_y + row_spacing
        
        # 第一列 - 平均专注度
        self.canvas.create_text(
            col1_x, y2,
            text="平均专注度:",
            fill="#666688",
            font=("Microsoft YaHei", 13),
            anchor="w"
        )
        self.canvas.create_text(
            col1_x + 85, y2,
            text=f"{player.avg_focus:.1f}",
            fill=ACCENT,
            font=("Consolas", 13, "bold"),
            anchor="w"
        )
        
        # 第二列 - 最大速度
        self.canvas.create_text(
            col2_x, y2,
            text="最大速度:",
            fill="#666688",
            font=("Microsoft YaHei", 13),
            anchor="w"
        )
        self.canvas.create_text(
            col2_x + 85, y2,
            text=f"{player.max_speed:.1f}",
            fill=GREEN,
            font=("Consolas", 13, "bold"),
            anchor="w"
        )

    def draw_focus_chart(self, left_margin, bottom_margin, content_start_y):
        """在结果界面绘制专注度图表 - 使用PANEL_BG"""
        # 图表区域设置
        chart_x = left_margin + 20
        chart_y = content_start_y + 45
        chart_width = WIDTH - left_margin - 30
        chart_height = bottom_margin - chart_y - 15

        # 图表背景 - 使用PANEL_BG
        self.canvas.create_rectangle(
            chart_x, chart_y,
            chart_x + chart_width, chart_y + chart_height,
            fill=PANEL_BG,
            outline=ACCENT,
            width=1
        )

        # 坐标轴
        axis_x = chart_x + 40
        axis_y = chart_y + chart_height - 40
        axis_width = chart_width - 60
        axis_height = chart_height - 70

        # X轴
        self.canvas.create_line(
            axis_x, axis_y,
            axis_x + axis_width, axis_y,
            fill="#666666",
            arrow=tk.LAST
        )

        # Y轴
        self.canvas.create_line(
            axis_x, axis_y,
            axis_x, axis_y - axis_height,
            fill="#666666",
            arrow=tk.LAST
        )

        # 时间轴刻度 - 使用FONT_MONO
        self.canvas.create_text(
            axis_x, axis_y + 15,
            text="0",
            fill="#AAAAAA",
            font=FONT_MONO
        )
        self.canvas.create_text(
            axis_x + axis_width, axis_y + 15,
            text=f"{int(self.racing_time)}秒",
            fill="#AAAAAA",
            font=FONT_MONO
        )

        # 专注度刻度 - 使用FONT_MONO
        for value in [0, 25, 50, 75, 100]:
            y_pos = axis_y - (value * axis_height) / 100
            self.canvas.create_text(
                axis_x - 5, y_pos,
                text=f"{value}",
                fill="#AAAAAA",
                anchor="e",
                font=FONT_MONO
            )

        # 网格线
        for value in [0, 25, 50, 75, 100]:
            y_pos = axis_y - (value * axis_height) / 100
            if value > 0:
                self.canvas.create_line(
                    axis_x, y_pos,
                    axis_x + axis_width, y_pos,
                    fill="#444466",
                    dash=(2, 2)
                )

        # 图例
        self.canvas.create_text(
            chart_x + chart_width - 30, chart_y + 10,
            text="红方玩家",
            fill=RED,
            font=FONT_VERY_SMALL
        )
        self.canvas.create_rectangle(
            chart_x + chart_width - 75, chart_y + 5,
            chart_x + chart_width - 65, chart_y + 15,
            fill=RED,
            outline=""
        )

        self.canvas.create_text(
            chart_x + chart_width - 30, chart_y + 30,
            text="蓝方玩家",
            fill=BLUE,
            font=FONT_VERY_SMALL
        )
        self.canvas.create_rectangle(
            chart_x + chart_width - 75, chart_y + 25,
            chart_x + chart_width - 65, chart_y + 35,
            fill=BLUE,
            outline=""
        )

        # 绘制波形
        self.draw_waveforms(axis_x, axis_y, axis_width, axis_height)

    def update_attention_data(self, attention_1, attention_2):
        """更新两个玩家的专注度数据

        仅在比赛状态下更新专注度数据
        """
        if self.state == 'racing':
            # 确保专注度在有效范围内
            self.player_red.focus = max(0, min(99, attention_1))
            self.player_blue.focus = max(0, min(99, attention_2))

            # 添加到专注度历史记录
            self.player_red.focus_history.append(self.player_red.focus)
            self.player_blue.focus_history.append(self.player_blue.focus)

            # 更新专注度等级
            self.player_red.update_focus_level()
            self.player_blue.update_focus_level()

# 启动EEG数据采集线程
thread1 = threading.Thread(target=EEG.f1, daemon=True)
thread2 = threading.Thread(target=EEG.f2, daemon=True)
thread1.start()
thread2.start()

# 运行游戏
if __name__ == "__main__":
    try:
        root = tk.Tk()
        game = FocusRacingGame(root)
        root.mainloop()
    finally:
        # 确保在程序结束时关闭电机
        if gpio_available:
            try:
                # 停止PWM
                if pwm1:
                    pwm1.stop()
                if pwm2:
                    pwm2.stop()
                # 关闭STBY
                GPIO.output(STBY, GPIO.LOW)
                # 清理GPIO
                GPIO.cleanup()
            except Exception as e:
                logger.warning(f"GPIO清理失败: {e}")
        logger.info("系统已关闭")
