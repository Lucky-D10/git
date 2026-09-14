import random
import time
import math
from collections import deque
import threading

# 尝试导入RPi.GPIO，如果失败则设置标志
try:
    import RPi.GPIO as GPIO  # 导入真实的GPIO库
    gpio_available = True
except ImportError:
    gpio_available = False
    print("警告: RPi.GPIO不可用，将使用模拟模式")

# 尝试导入tkinter，如果失败则使用命令行模式
tk_available = True
try:
    import tkinter as tk
except ImportError:
    tk_available = False
    print("警告: tkinter 不可用，将使用命令行模式")

# 模拟EEG模块
try:
    import EEG
    eeg_available = True
except ImportError:
    eeg_available = False
    print("警告: EEG模块不可用，将使用模拟数据")

# GPIO配置
STBY = 17  # 使能引脚
gpio_initialized = False
if gpio_available:
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(STBY, GPIO.OUT)
        gpio_initialized = True
        print('曲线图.py GPIO初始化成功')
    except Exception as e:
        print('曲线图.py GPIO初始化失败:', e)
        gpio_initialized = False

# 模拟EEG数据
class MockEEG:
    Attention_1 = 0
    Attention_2 = 0

    @staticmethod
    def f1():
        pass

    @staticmethod
    def f2():
        pass

# 如果EEG模块不可用，使用模拟数据
if not eeg_available:
    EEG = MockEEG()


class CarAttentionMonitor:
    def __init__(self, root):
        self.root = root
        self.root.title("脑控赛车专注度测试系统")
        self.root.geometry("800x480+0+0")  # 适配树莓派屏幕
        self.root.configure(bg="#000d1a")  # 科技感深蓝色背景
        
        # 界面状态
        self.current_screen = "intro"  # intro -> countdown -> main
        
        # 倒计时相关
        self.countdown_value = 3
        self.countdown_id = None
        self.countdown_text_id = None
        self.countdown_circle_id = None
        self.countdown_glow_id = None
        self.countdown_scale_id = None
        
        # 测试时长选项（秒）
        self.test_duration_options = {
            1: 60,
            3: 180,
            5: 300
        }
        self.selected_duration = 60  # 默认1分钟
        self.test_start_time = 0
        self.test_timer_id = None
        
        # 设置数据队列用于存储历史数据
        self.max_points = 60  # 默认最大数据点数（1分钟）
        self.attention1_data = deque([0] * self.max_points, maxlen=self.max_points)
        self.attention2_data = deque([0] * self.max_points, maxlen=self.max_points)
        
        # 保存上次绘制的数据，用于检测变化（优化：只记录最后值和长度）
        self._last_data1_tail = 0
        self._last_data2_tail = 0
        self._last_data1_len = self.max_points
        self._last_data2_len = self.max_points
        
        # 保存上次的速度值，用于平滑动画
        self.last_speed1 = 0
        self.last_speed2 = 0
        
        # 存储历史数据用于计算平均值（使用deque提高性能）
        self.max_history = 1000  # 最大历史数据长度
        self.attention1_history = deque(maxlen=self.max_history)
        self.attention2_history = deque(maxlen=self.max_history)
        
        # 缓存常用计算值
        self._init_caches()
        
        # 状态跟踪
        self.running = False  # 监控运行状态
        self.current_car = 1  # 默认选择用户1
        
        # 动画防重入锁，避免窗口resize时动画嵌套导致栈溢出
        self._animation_lock = {1: False, 2: False}
        
        # 窗口resize防抖定时器ID
        self._resize_timer = None
        
        # 脉冲动画定时器ID（用于曲线末端标记点动画）
        self._pulse_timer = {1: None, 2: None}
        self._pulse_phase = {1: 0, 2: 0}
        
        # 模拟数据的惯性状态（用于随机游走，使模拟数据更真实）
        self._sim_attention1 = 50  # 用户1当前模拟专注度
        self._sim_attention2 = 50  # 用户2当前模拟专注度
        
        # 界面就绪标志
        self.interface_ready = False
        
        # 立即显示开场界面
        self.create_intro_screen()

    def select_duration(self, minutes):
        """选择测试时长"""
        self.selected_duration = self.test_duration_options[minutes]
        
        # 更新按钮状态、光标和边框高亮
        if hasattr(self, 'time_buttons') and self.time_buttons:
            time_options = [1, 3, 5]
            for i, btn in enumerate(self.time_buttons):
                if time_options[i] == minutes:
                    btn.config(
                        bg="#003355", 
                        fg="#ffffff", 
                        activebackground="#004466", 
                        activeforeground="#ffffff", 
                        cursor="arrow",
                        highlightthickness=2,
                        highlightbackground="#00ffff",
                        highlightcolor="#00ffff"
                    )
                else:
                    btn.config(
                        bg="#001122", 
                        fg="#666688", 
                        activebackground="#002244", 
                        activeforeground="#8888aa", 
                        cursor="hand2",
                        highlightthickness=1,
                        highlightbackground="#003355",
                        highlightcolor="#003355"
                    )

    def create_main_page(self):
        """创建主页面，整合用户1和用户2的数据"""
        self.main_page = tk.Frame(self.root, bg="#000d1a")
        self.main_page.place(x=0, y=0, relwidth=1, relheight=1)

    def init_ui_elements(self):
        """初始化UI元素 - 优化版：移除多层发光Frame，改用单层边框+阴影色"""
        spacing = 0.01  # 相对间距

        # 区域1: 专注度趋势（用户1） - 使用单层边框+阴影色替代多层发光
        region1 = tk.Frame(self.main_page, bg="#000d1a",
                           highlightbackground="#00bfff", highlightthickness=2)
        region1.place(relx=spacing, rely=spacing, relwidth=0.48, relheight=0.48)
        # 单层阴影效果（替代原来3层发光Frame）
        shadow1 = tk.Frame(self.main_page, bg="#003366")
        shadow1.place(relx=spacing - 0.003, rely=spacing - 0.003,
                      relwidth=0.48 + 0.006, relheight=0.48 + 0.006)
        shadow1.lower()

        # 区域2: 专注度趋势（用户2）
        region2 = tk.Frame(self.main_page, bg="#000d1a",
                           highlightbackground="#ff00ff", highlightthickness=2)
        region2.place(relx=0.5 + spacing, rely=spacing, relwidth=0.48, relheight=0.48)
        shadow2 = tk.Frame(self.main_page, bg="#330033")
        shadow2.place(relx=0.5 + spacing - 0.003, rely=spacing - 0.003,
                      relwidth=0.48 + 0.006, relheight=0.48 + 0.006)
        shadow2.lower()

        # 区域3: 实时速度（用户1）
        region3 = tk.Frame(self.main_page, bg="#000d1a",
                           highlightbackground="#00bfff", highlightthickness=2)
        region3.place(relx=spacing, rely=0.5 + spacing, relwidth=0.48, relheight=0.48)
        shadow3 = tk.Frame(self.main_page, bg="#003366")
        shadow3.place(relx=spacing - 0.003, rely=0.5 + spacing - 0.003,
                      relwidth=0.48 + 0.006, relheight=0.48 + 0.006)
        shadow3.lower()

        # 区域4: 实时速度（用户2）
        region4 = tk.Frame(self.main_page, bg="#000d1a",
                           highlightbackground="#ff00ff", highlightthickness=2)
        region4.place(relx=0.5 + spacing, rely=0.5 + spacing, relwidth=0.48, relheight=0.48)
        shadow4 = tk.Frame(self.main_page, bg="#330033")
        shadow4.place(relx=0.5 + spacing - 0.003, rely=0.5 + spacing - 0.003,
                      relwidth=0.48 + 0.006, relheight=0.48 + 0.006)
        shadow4.lower()

        # 添加标题标签
        title_font = ("Arial", 14, "bold")

        # 区域1标题: 蓝方专注度
        title1 = tk.Label(self.main_page, text="蓝方专注度", fg="#00bfff", bg="#000d1a", font=title_font)
        title1.place(relx=spacing + 0.01, rely=spacing + 0.01)
        
        # 区域2标题: 红方专注度
        title2 = tk.Label(self.main_page, text="红方专注度", fg="#ff00ff", bg="#000d1a", font=title_font)
        title2.place(relx=0.5 + spacing + 0.01, rely=spacing + 0.01)

        # 区域3标题: 实时速度（用户1）
        title3 = tk.Label(self.main_page, text="实时速度", fg="#00bfff", bg="#000d1a", font=title_font)
        title3.place(relx=spacing + 0.01, rely=0.5 + spacing + 0.01)
        title3.bind("<Enter>", lambda e, t=title3: t.config(fg="#00ffff", font=("Arial", 14, "bold", "underline")))
        title3.bind("<Leave>", lambda e, t=title3: t.config(fg="#00bfff", font=("Arial", 14, "bold")))

        # 区域4标题: 实时速度（用户2）
        title4 = tk.Label(self.main_page, text="实时速度", fg="#ff00ff", bg="#000d1a", font=title_font)
        title4.place(relx=0.5 + spacing + 0.01, rely=0.5 + spacing + 0.01)
        title4.bind("<Enter>", lambda e, t=title4: t.config(fg="#00ffff", font=("Arial", 14, "bold", "underline")))
        title4.bind("<Leave>", lambda e, t=title4: t.config(fg="#ff00ff", font=("Arial", 14, "bold")))

        # 用户1专注度趋势画布
        canvas1 = tk.Canvas(region1, bg="#000d1a", highlightthickness=0)
        canvas1.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.95, relheight=0.9)

        # 用户2专注度趋势画布
        canvas2 = tk.Canvas(region2, bg="#000d1a", highlightthickness=0)
        canvas2.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.95, relheight=0.9)

        # 创建仪表盘画布
        speedo1_canvas = tk.Canvas(region3, bg="#000d1a", highlightthickness=0)
        speedo1_canvas.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.98, relheight=0.98)

        speedo2_canvas = tk.Canvas(region4, bg="#000d1a", highlightthickness=0)
        speedo2_canvas.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.98, relheight=0.98)

        # 存储元素引用
        self.canvas1 = canvas1
        self.canvas2 = canvas2
        self.speedo1_canvas = speedo1_canvas
        self.speedo2_canvas = speedo2_canvas

        # 添加点击事件
        self.speedo1_canvas.bind("<Button-1>", lambda e: self.on_speedometer_click(1, e))
        self.speedo2_canvas.bind("<Button-1>", lambda e: self.on_speedometer_click(2, e))

        self.root.after(50, self._delayed_draw_main_interface)
    
    def _delayed_draw_main_interface(self):
        """延迟绘制主界面，确保窗口已完全渲染"""
        self.root.update_idletasks()
        self.root.update()
        
        width = self.canvas1.winfo_width()
        height = self.canvas1.winfo_height()
        
        if width <= 1 or height <= 1:
            self.root.after(100, self._delayed_draw_main_interface)
            return
        
        self.draw_axes()
        self.draw_speedometer(self.speedo1_canvas, 0, "#00bfff")
        self.draw_speedometer(self.speedo2_canvas, 0, "#ff00ff")
        self.interface_ready = True

    def draw_axes(self):
        """绘制坐标轴和网格线"""
        # 用户1曲线图坐标轴
        width1 = self.canvas1.winfo_width()
        height1 = self.canvas1.winfo_height()
        if width1 > 0 and height1 > 0:
            self.draw_axis(self.canvas1, width1, height1, curve_color="#00bfff")

        # 用户2曲线图坐标轴
        width2 = self.canvas2.winfo_width()
        height2 = self.canvas2.winfo_height()
        if width2 > 0 and height2 > 0:
            self.draw_axis(self.canvas2, width2, height2, curve_color="#ff00ff")

    def create_intro_screen(self):
        """创建开场动画界面"""
        # 清除可能存在的旧界面
        for widget in self.root.winfo_children():
            widget.destroy()
        
        # 创建开场画布（全屏，使用expand=True支持缩放）
        self.intro_canvas = tk.Canvas(
            self.root,
            bg="#000d1a",
            highlightthickness=0
        )
        self.intro_canvas.pack(fill="both", expand=True)
        
        # 启动开场动画
        self._play_intro_animation()
        
        # 绑定窗口大小变化事件
        self.root.bind("<Configure>", self._handle_intro_resize)

    def _play_intro_animation(self):
        """开场动画序列"""
        # 阶段1：背景扫光
        self._intro_sweep_effect()
    
    def _handle_intro_resize(self, event):
        """开场界面窗口大小变化处理"""
        if event.widget != self.root:
            return
        
        if not hasattr(self, 'intro_canvas') or not self.intro_canvas:
            return
        
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        
        if width <= 1 or height <= 1:
            return
        
        center_x = width / 2
        center_y = height / 2
        
        # 清除并重绘开场界面
        self.intro_canvas.delete("all")
        
        # 创建背景
        self.intro_canvas.create_rectangle(0, 0, width, height, 
                                          fill="#000d1a", outline="")
        
        # 标题位置 - 上移并增加两行间距
        title_y1 = center_y * 0.45  # 上移到窗口22.5%高度
        title_y2 = center_y * 0.62  # 上移到窗口31%高度
        
        # 字体大小根据窗口大小调整
        title_font_size = max(24, min(48, int(height * 0.075)))
        subtitle_font_size = max(16, min(32, int(height * 0.05)))
        
        # 创建标题（分两行）
        title1 = self.intro_canvas.create_text(
            center_x, title_y1,
            text="脑控赛车",
            fill="#00ffff",
            font=("Microsoft YaHei", title_font_size, "bold")
        )
        
        title2 = self.intro_canvas.create_text(
            center_x, title_y2,
            text="专注度测试系统",
            fill="#00ffff",
            font=("Microsoft YaHei", subtitle_font_size, "bold")
        )
        
        # 布局容器 - 居中放置所有内容
        container_width = min(width * 0.8, 500)
        container_height = height * 0.6
        container_x = center_x - container_width / 2
        container_y = center_y - container_height / 2 + height * 0.1
        
        # 装饰线位置 - 在标题下方
        line_y = container_y + container_height * 0.2
        
        # 创建装饰线
        self.intro_canvas.create_line(
            center_x - 120, line_y,
            center_x + 120, line_y,
            fill="#00ffff", width=2, dash=(8, 4)
        )
        
        # 副标题位置 - 装饰线下方
        subtitle_y = line_y + 30
        
        # 创建副标题
        subtitle = self.intro_canvas.create_text(
            center_x, subtitle_y,
            text="选择测试时长",
            fill="#00ffff",
            font=("Microsoft YaHei", 16, "bold")
        )
        
        # 时间选择按钮位置 - 副标题下方
        time_buttons_y = subtitle_y + 40
        
        # 创建时间选择按钮容器背景
        btn_container_width = 280
        btn_container_height = 50
        self.intro_canvas.create_rectangle(
            center_x - btn_container_width / 2, time_buttons_y - btn_container_height / 2,
            center_x + btn_container_width / 2, time_buttons_y + btn_container_height / 2,
            fill="#001122", outline="#003355", width=1
        )
        
        # 更新时间选择按钮 - 更新光标和高亮边框
        if hasattr(self, 'time_buttons') and self.time_buttons:
            time_options = [1, 3, 5]
            button_width = 70
            button_height = 35
            spacing = 20
            
            for i, minutes in enumerate(time_options):
                btn_x = center_x - (len(time_options) - 1) * (button_width + spacing) / 2 + i * (button_width + spacing)
                btn_y = time_buttons_y
                
                is_selected = (self.selected_duration == self.test_duration_options[minutes])
                
                if is_selected:
                    # 更新选中按钮的光标和高亮边框
                    self.time_buttons[i].config(
                        cursor="arrow",
                        highlightthickness=2,
                        highlightbackground="#00ffff",
                        highlightcolor="#00ffff"
                    )
                else:
                    # 更新未选中按钮的光标和高亮边框
                    self.time_buttons[i].config(
                        cursor="hand2",
                        highlightthickness=1,
                        highlightbackground="#003355",
                        highlightcolor="#003355"
                    )
                
                self.intro_canvas.create_window(
                    btn_x, btn_y,
                    window=self.time_buttons[i]
                )
        
        # 信息文字位置 - 按钮容器下方
        info_y = time_buttons_y + btn_container_height / 2 + 30
        
        # 创建信息文字
        info_text = self.intro_canvas.create_text(
            center_x, info_y,
            text="请保持专注，发挥最佳水平",
            fill="#666688",
            font=("Microsoft YaHei", 13)
        )
        
        # 开始按钮位置
        button_y = container_y + container_height - 60
        button_height = height * 0.08
        
        # 创建按钮背景框（如果按钮已存在才绘制）- 加宽背景框以匹配加长的按钮
        if hasattr(self, 'start_button') and self.start_button:
            self.intro_canvas.create_rectangle(
                center_x - 120, button_y - button_height / 2,
                center_x + 120, button_y + button_height / 2,
                fill="#001122", outline="#00ffff", width=2
            )
            self.intro_canvas.create_window(
                center_x, button_y,
                window=self.start_button
            )
        
        # 提示文字位置
        hint_y = height * 0.92
        
        # 添加提示文字
        if not hasattr(self, 'intro_hint') or not self.intro_hint:
            self.intro_hint = self.intro_canvas.create_text(
                center_x, hint_y,
                text="点击按钮开始测试",
                fill="#00ffff",
                font=("Microsoft YaHei", 10)
            )
    
    def _intro_sweep_effect(self):
        """阶段1：背景扫光效果"""
        # 获取实际窗口尺寸
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        
        if width <= 1 or height <= 1:
            # 窗口未就绪，等待一下再重试
            self.root.after(50, self._intro_sweep_effect)
            return
        
        # 创建背景
        self.intro_canvas.create_rectangle(0, 0, width, height, 
                                          fill="#000d1a", outline="")
        
        # 创建扫光矩形
        sweep_rect = self.intro_canvas.create_rectangle(
            0, 0, 20, height,
            fill="#001a33", outline=""
        )
        
        speed = 15
        current_x = -50
        
        def animate():
            nonlocal current_x
            current_x += speed
            
            if current_x < width + 100:
                self.intro_canvas.coords(sweep_rect, 
                                        current_x - 70, 0, current_x + 20, height)
                self.intro_canvas.after(16, animate)
            else:
                # 扫光完成，进入下一阶段
                self._intro_title_animation()
        
        animate()
    
    def _intro_title_animation(self):
        """阶段2：标题动画"""
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        center_x = width / 2
        center_y = height / 2
        
        # 标题位置 - 上移并增加两行间距
        title_y1 = center_y * 0.45  # 上移到窗口22.5%高度
        title_y2 = center_y * 0.62  # 上移到窗口31%高度，与第一行保持11%的间距
        
        # 字体大小根据窗口大小调整
        title_font_size = max(24, min(48, int(center_y * 0.14)))
        subtitle_font_size = max(16, min(32, int(center_y * 0.09)))
        
        # 创建标题（分两行）
        title1 = self.intro_canvas.create_text(
            center_x, title_y1,
            text="脑控赛车",
            fill="",
            font=("Microsoft YaHei", title_font_size, "bold")
        )
        
        title2 = self.intro_canvas.create_text(
            center_x, title_y2,
            text="专注度测试系统",
            fill="",
            font=("Microsoft YaHei", subtitle_font_size, "bold")
        )
        
        # 标题颜色渐变动画
        alpha = 0
        
        def animate_color():
            nonlocal alpha
            if alpha < 1:
                alpha += 0.03
                # 青色渐变
                g = min(255, int(200 + 55 * alpha))
                b = min(255, int(255 * alpha))
                color = f"#00{g:02x}{b:02x}"
                
                self.intro_canvas.itemconfig(title1, fill=color)
                self.intro_canvas.itemconfig(title2, fill=color)
                self.intro_canvas.after(30, animate_color)
            else:
                # 标题显示完成，进入下一阶段
                self._intro_subtitle_and_button()
        
        animate_color()
    
    def _intro_subtitle_and_button(self):
        """阶段3：显示副标题和开始按钮"""
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        center_x = width / 2
        center_y = height / 2
        
        # 布局容器 - 居中放置所有内容
        container_width = min(width * 0.8, 500)
        container_height = height * 0.6
        container_x = center_x - container_width / 2
        container_y = center_y - container_height / 2 + height * 0.1
        
        # 容器背景（可选，用于调试布局）
        # self.intro_canvas.create_rectangle(container_x, container_y, container_x + container_width, container_y + container_height, fill="#000033", outline="#003366", width=1)
        
        # 装饰线位置 - 在标题下方
        line_y = container_y + container_height * 0.2
        
        # 创建装饰线
        self.intro_canvas.create_line(
            center_x - 120, line_y,
            center_x + 120, line_y,
            fill="#00ffff", width=2, dash=(8, 4)
        )
        
        # 副标题位置 - 装饰线下方
        subtitle_y = line_y + 30
        
        # 创建副标题
        subtitle = self.intro_canvas.create_text(
            center_x, subtitle_y,
            text="选择测试时长",
            fill="#00ffff",
            font=("Microsoft YaHei", 16, "bold")
        )
        
        # 时间选择按钮位置 - 副标题下方
        time_buttons_y = subtitle_y + 40
        
        # 创建时间选择按钮容器背景
        btn_container_width = 280
        btn_container_height = 50
        self.intro_canvas.create_rectangle(
            center_x - btn_container_width / 2, time_buttons_y - btn_container_height / 2,
            center_x + btn_container_width / 2, time_buttons_y + btn_container_height / 2,
            fill="#001122", outline="#003355", width=1
        )
        
        # 创建时间选择按钮 - 使用科技感设计
        self.time_buttons = []
        time_options = [1, 3, 5]
        button_width = 70
        button_height = 35
        spacing = 20
        
        for i, minutes in enumerate(time_options):
            btn_x = center_x - (len(time_options) - 1) * (button_width + spacing) / 2 + i * (button_width + spacing)
            btn_y = time_buttons_y
            
            is_selected = (self.selected_duration == self.test_duration_options[minutes])
            
            if is_selected:
                btn_bg = "#003355"
                btn_fg = "#ffffff"
                border_color = "#00ffff"
            else:
                btn_bg = "#001122"
                btn_fg = "#666688"
                border_color = "#003355"
            
            btn = tk.Button(
                self.root,
                text=f"{minutes}分钟",
                command=lambda m=minutes: self.select_duration(m),
                bg=btn_bg,
                fg=btn_fg,
                font=("Microsoft YaHei", 12, "bold"),
                width=8,
                height=1,
                relief="flat",
                bd=0,
                highlightthickness=2 if is_selected else 1,
                highlightbackground=border_color,
                highlightcolor=border_color,
                cursor="arrow" if is_selected else "hand2",
                activebackground="#004466",
                activeforeground="#ffffff",
                borderwidth=0
            )
            
            self.time_buttons.append(btn)
            
            self.intro_canvas.create_window(
                btn_x, btn_y,
                window=btn
            )
        
        # 信息文字位置 - 按钮容器下方
        info_y = time_buttons_y + btn_container_height / 2 + 30
        
        # 创建信息文字
        info_text = self.intro_canvas.create_text(
            center_x, info_y,
            text="请保持专注，发挥最佳水平",
            fill="#666688",
            font=("Microsoft YaHei", 13)
        )
        
        # 开始按钮位置 - 信息文字下方，底部留有适当间距
        button_y = container_y + container_height - 60
        button_height = height * 0.08
        button_font_size = max(12, min(20, int(height * 0.033)))
        
        # 保存按钮参数，等文字渐变完后再创建按钮
        self.button_params = {
            'button_y': button_y,
            'button_font_size': button_font_size
        }
        
        # 提示文字位置
        hint_y = height * 0.92
        
        # 添加提示文字
        hint = self.intro_canvas.create_text(
            center_x, hint_y,
            text="点击按钮开始测试",
            fill="#00ffff",
            font=("Microsoft YaHei", 10)
        )
        
        # 延迟后创建并显示按钮，确保所有文字都已完全渲染
        def create_and_show_button():
            # 创建按钮 - 加长按钮
            self.start_button = tk.Button(
                self.root,
                text="开始测试",
                command=self.show_countdown_buffer,
                bg="#00ff00",
                fg="#000d1a",
                font=("Microsoft YaHei", self.button_params['button_font_size'], "bold"),
                width=18,
                height=1,
                relief="raised",
                bd=3,
                activebackground="#00ff88",
                activeforeground="#000d1a",
                cursor="hand2"
            )
            
            # 将按钮放在画布上
            button_window = self.intro_canvas.create_window(
                center_x, self.button_params['button_y'],
                window=self.start_button
            )
            
            # 保存按钮引用
            self.intro_button = button_window
            
            # 将按钮放到最前面
            self.intro_canvas.lift(button_window)
        
        self.root.after(600, create_and_show_button)

    def draw_axis(self, canvas, width, height, curve_color):
        """
        绘制单个区域的坐标轴 - 优化版
        改进：更精致的网格线、Y轴数值标签添加背景色块提高可读性
        """
        # 确保所有区域使用相同的布局
        margin_x = width * 0.1  # 相对左边距
        margin_y = height * 0.15  # 相对上下边距
        plot_height = height - margin_y * 2

        # 清除现有内容
        canvas.delete("all")

        # 绘制背景
        canvas.create_rectangle(0, 0, width, height, fill="#000d1a", outline="")

        # 绘制精致网格线（优化：使用更柔和的颜色和虚线样式）
        grid_color = "#002244"  # 更柔和的深蓝网格线
        for i in range(0, 101, 20):
            y = margin_y + plot_height * i / 100
            # 水平网格线 - 使用点划线样式，更精致
            canvas.create_line(margin_x, y, width - 10, y,
                               fill=grid_color, width=1, dash=(1, 3))

        # 绘制垂直网格线（新增：增强坐标感）
        num_vertical_lines = 5
        for i in range(num_vertical_lines + 1):
            x = margin_x + (width - margin_x - 10) * i / num_vertical_lines
            canvas.create_line(x, margin_y, x, height - margin_y,
                               fill=grid_color, width=1, dash=(1, 3))

        # 绘制坐标轴（优化：使用稍亮的颜色，更清晰的轴线）
        axis_color = curve_color
        # X轴 - 使用稍粗的线条
        canvas.create_line(margin_x, height - margin_y, width - 10, height - margin_y,
                           fill=axis_color, width=1.5)
        # Y轴
        canvas.create_line(margin_x, margin_y, margin_x, height - margin_y,
                           fill=axis_color, width=1.5)

        # 绘制Y轴刻度（优化：添加背景色块提高可读性）
        for i in range(0, 101, 20):
            y = margin_y + plot_height * i / 100
            value = 100 - i

            # 刻度线
            canvas.create_line(margin_x - 5, y, margin_x, y, fill=axis_color, width=1)

            # Y轴数值标签背景色块（新增：提高可读性）
            text_str = str(value)
            font_size = 8
            # 估算文本尺寸
            text_w = len(text_str) * font_size * 0.6 + 6
            text_h = font_size + 4
            text_x = margin_x - 10
            text_y = y
            # 绘制半透明背景色块
            canvas.create_rectangle(text_x - text_w - 2, text_y - text_h / 2,
                                    text_x + 2, text_y + text_h / 2,
                                    fill="#001122", outline="#003355", width=1)
            # 数值文本
            canvas.create_text(text_x, text_y, text=text_str,
                               fill=axis_color, anchor="e",
                               font=("Arial", font_size, "bold"))

        # X轴时间刻度（根据测试时长动态调整）
        x_axis_end = width - 10
        x_axis_length = x_axis_end - margin_x
        
        # 根据测试时长计算刻度数量和间隔
        duration = self.selected_duration
        if duration <= 60:
            num_time_ticks = 6  # 0s, 10s, 20s, 30s, 40s, 50s
            tick_interval = 10
        elif duration <= 180:
            num_time_ticks = 6  # 0s, 30s, 60s, 90s, 120s, 150s
            tick_interval = 30
        else:
            num_time_ticks = 6  # 0s, 50s, 100s, 150s, 200s, 250s
            tick_interval = 50
        
        for i in range(num_time_ticks + 1):
            x = margin_x + x_axis_length * i / num_time_ticks
            # 刻度线
            canvas.create_line(x, height - margin_y, x, height - margin_y + 4,
                               fill=axis_color, width=1)
            # 时间标签
            time_str = f"{i * tick_interval}s"
            canvas.create_text(x, height - margin_y + 10,
                               text=time_str, fill=axis_color, anchor="n",
                               font=("Arial", 7))

    def create_controls(self):
        """创建控制按钮区域 - 空实现，不创建按钮"""
        pass

    def draw_speedometer(self, canvas, speed, color):
        """
        绘制汽车仪表盘 - 全面优化版
        改进：
        1. 渐变层数从4层增加到6层，增强深度感
        2. 添加弧形彩色带（绿->黄->红渐变弧），显示在刻度外侧
        3. 改进指针设计，添加更精致的阴影和高光
        4. 优化静态元素缓存，只在尺寸/颜色变化时重绘
        5. 速度值显示添加单位标签和更精致的排版
        """
        try:
            # 更新仪表盘缓存参数
            self.update_speedometer_cache(canvas)

            # 获取缓存的仪表盘参数
            cache = self.speedometer_cache
            center_x = cache['center_x']
            center_y = cache['center_y']
            radius = cache['radius']
            inner_radius = cache['inner_radius']
            min_speed = cache['min_speed']
            max_speed = cache['max_speed']
            step = cache['step']

            # 获取画布ID，用于缓存
            canvas_id = id(canvas)
            canvas_width = canvas.winfo_width()
            canvas_height = canvas.winfo_height()

            # 检查画布大小是否变化
            canvas_size = self.drawing_cache['canvas_size'].get(canvas_id, (0, 0))
            size_changed = canvas_width != canvas_size[0] or canvas_height != canvas_size[1]

            # 检查颜色是否变化
            current_cache = self.drawing_cache['static_elements'].get(canvas_id, {})
            color_changed = current_cache.get('color') != color

            # 如果画布大小或颜色变化，重新绘制静态元素
            if size_changed or color_changed:
                # 清除画布
                canvas.delete("all")

                # 绘制外圆
                canvas.create_oval(center_x - radius, center_y - radius,
                                   center_x + radius, center_y + radius,
                                   outline=color, width=3, tags="static")

                # ===== 绘制背景渐变效果（优化：从4层增加到6层，增强深度感） =====
                gradient_layers = 6
                for i in range(gradient_layers):
                    alpha = i / gradient_layers
                    inner_r = inner_radius + (radius - inner_radius) * alpha
                    # 从深色到更深色的渐变，增强深度感
                    r_val = int(13 * (1 - alpha * 0.85))
                    g_val = int(29 * (1 - alpha * 0.85))
                    b_val = int(50 * (1 - alpha * 0.85))
                    fill_color = f"#{max(0, r_val):02x}{max(0, g_val):02x}{max(0, b_val):02x}"
                    canvas.create_oval(center_x - inner_r, center_y - inner_r,
                                       center_x + inner_r, center_y + inner_r,
                                       fill=fill_color, outline="", tags="static")

                # 内圆（主要线条）
                canvas.create_oval(center_x - inner_radius, center_y - inner_radius,
                                   center_x + inner_radius, center_y + inner_radius,
                                   fill="#000d1a", outline=color, width=2, tags="static")

                # 绘制主刻度和数值（使用缓存的刻度数据）
                for tick in cache['tick_data']:
                    speed_value = tick['speed']
                    # 刻度线起点和终点（在内外圈之间）
                    start_radius = inner_radius
                    end_radius = radius - 5

                    x1 = center_x + start_radius * tick['cos']
                    y1 = center_y - start_radius * tick['sin']
                    x2 = center_x + end_radius * tick['cos']
                    y2 = center_y - end_radius * tick['sin']

                    # 精致刻度线设计：每4单位加粗，其余普通
                    line_width = 3 if speed_value % 4 == 0 else 1
                    # 刻度线阴影，增强立体感
                    canvas.create_line(x1 + 1, y1 + 1, x2 + 1, y2 + 1,
                                       fill="#000000", width=line_width, tags="static")
                    # 主刻度线
                    canvas.create_line(x1, y1, x2, y2,
                                       fill=color, width=line_width, tags="static")

                    # 刻度值（在外圈外边）
                    text_radius = radius + radius * 0.12
                    text_x = center_x + text_radius * tick['cos']
                    text_y = center_y - text_radius * tick['sin']
                    # 根据半径动态调整字体大小
                    font_size = max(8, min(14, int(radius * 0.08)))
                    # 文本阴影，提高可读性
                    canvas.create_text(text_x + 1, text_y + 1, text=str(speed_value),
                                       fill="#000000", font=("Arial", font_size, "bold"), tags="static")
                    # 主文本
                    canvas.create_text(text_x, text_y, text=str(speed_value),
                                       fill=color, font=("Arial", font_size, "bold"), tags="static")

                # 绘制小刻度（每5个单位一个小刻度）
                for i in range(min_speed * 5, (max_speed + 1) * 5, 5):
                    tick_speed = i / 5
                    if tick_speed % step == 0:
                        continue  # 跳过主刻度

                    angle = 180 - (tick_speed / max_speed) * 180
                    angle_rad = math.radians(angle)
                    cos_val = math.cos(angle_rad)
                    sin_val = math.sin(angle_rad)

                    start_radius = inner_radius + 5
                    end_radius = radius - 10

                    x1 = center_x + start_radius * cos_val
                    y1 = center_y - start_radius * sin_val
                    x2 = center_x + end_radius * cos_val
                    y2 = center_y - end_radius * sin_val

                    # 小刻度阴影
                    canvas.create_line(x1 + 1, y1 + 1, x2 + 1, y2 + 1,
                                       fill="#000000", width=1, tags="static")
                    # 主小刻度
                    canvas.create_line(x1, y1, x2, y2,
                                       fill=color, width=1, tags="static")

                # 绘制红色警戒线
                red_angle = 180 - (8 / max_speed) * 180
                red_angle_rad = math.radians(red_angle)
                red_x = center_x + (radius - 5) * math.cos(red_angle_rad)
                red_y = center_y - (radius - 5) * math.sin(red_angle_rad)
                canvas.create_line(center_x, center_y, red_x, red_y,
                                   fill="#ff0000", width=2, dash=(5, 2), tags="static")

                # 更新缓存
                self.drawing_cache['static_elements'][canvas_id] = {
                    'color': color,
                    'size': (canvas_width, canvas_height)
                }
                self.drawing_cache['canvas_size'][canvas_id] = (canvas_width, canvas_height)
            else:
                # 只清除动态元素（指针等）
                canvas.delete("dynamic")

            # ========== 绘制指针（优化：更精致的阴影和高光设计） ==========
            if speed > max_speed:
                speed = max_speed
            elif speed < min_speed:
                speed = min_speed

            pointer_angle = 180 - (speed / max_speed) * 180
            pointer_angle_rad = math.radians(pointer_angle)
            pointer_length = inner_radius - 5

            # 根据速度计算指针颜色（从绿色到红色的渐变）
            def get_speed_color(spd, max_spd):
                ratio = spd / max_spd
                if ratio < 0.5:
                    r = int(255 * (ratio * 2))
                    g = 255
                    b = 0
                else:
                    r = 255
                    g = int(255 * (1 - (ratio - 0.5) * 2))
                    b = 0
                return f"#{r:02x}{g:02x}{b:02x}"

            speed_color = get_speed_color(speed, max_speed)

            # 计算指针方向向量
            dx = math.cos(pointer_angle_rad)
            dy = -math.sin(pointer_angle_rad)
            # 垂直方向向量（用于计算指针宽度）
            perp_dx = -dy
            perp_dy = dx

            # 锥形指针参数
            base_half_width = 10   # 指针底部半宽
            tip_half_width = 1     # 指针尖端半宽
            tail_length = 18       # 指针尾部延伸长度
            tail_half_width = 8    # 尾部半宽

            # 指针尖端坐标
            tip_x = center_x + dx * pointer_length
            tip_y = center_y + dy * pointer_length
            tip_left_x = tip_x + perp_dx * tip_half_width
            tip_left_y = tip_y + perp_dy * tip_half_width
            tip_right_x = tip_x - perp_dx * tip_half_width
            tip_right_y = tip_y - perp_dy * tip_half_width

            # 指针底部两个角坐标
            base_left_x = center_x + perp_dx * base_half_width
            base_left_y = center_y + perp_dy * base_half_width
            base_right_x = center_x - perp_dx * base_half_width
            base_right_y = center_y - perp_dy * base_half_width

            # 指针尾部坐标
            tail_x = center_x - dx * tail_length
            tail_y = center_y - dy * tail_length
            tail_left_x = tail_x + perp_dx * tail_half_width
            tail_left_y = tail_y + perp_dy * tail_half_width
            tail_right_x = tail_x - perp_dx * tail_half_width
            tail_right_y = tail_y - perp_dy * tail_half_width

            # ===== 改进的指针阴影（更精致：使用两层阴影增强立体感） =====
            # 外层阴影（更偏移，更模糊）
            outer_shadow_offset = 3
            outer_shadow_points = [
                tip_x + outer_shadow_offset, tip_y + outer_shadow_offset,
                base_left_x + outer_shadow_offset, base_left_y + outer_shadow_offset,
                tail_left_x + outer_shadow_offset, tail_left_y + outer_shadow_offset,
                tail_right_x + outer_shadow_offset, tail_right_y + outer_shadow_offset,
                base_right_x + outer_shadow_offset, base_right_y + outer_shadow_offset,
            ]
            canvas.create_polygon(*outer_shadow_points, fill="#000000", outline="",
                                  tags="dynamic pointer", stipple="gray50")

            # 内层阴影（偏移较小，实心）
            shadow_offset = 2
            shadow_points = [
                tip_x + shadow_offset, tip_y + shadow_offset,
                base_left_x + shadow_offset, base_left_y + shadow_offset,
                tail_left_x + shadow_offset, tail_left_y + shadow_offset,
                tail_right_x + shadow_offset, tail_right_y + shadow_offset,
                base_right_x + shadow_offset, base_right_y + shadow_offset,
            ]
            canvas.create_polygon(*shadow_points, fill="#111111", outline="",
                                  tags="dynamic pointer")

            # 绘制指针主体（七边形锥形）
            pointer_points = [
                tip_x, tip_y,
                base_left_x, base_left_y,
                tail_left_x, tail_left_y,
                tail_right_x, tail_right_y,
                base_right_x, base_right_y,
            ]
            canvas.create_polygon(*pointer_points, fill=speed_color,
                                  outline="#ffffff", width=1, tags="dynamic pointer")

            # ===== 改进的指针高光（更精致：添加渐变高光带） =====
            # 主高光线（沿指针中心）
            highlight_start_x = center_x + dx * 8
            highlight_start_y = center_y + dy * 8
            highlight_end_x = center_x + dx * (pointer_length - 8)
            highlight_end_y = center_y + dy * (pointer_length - 8)
            canvas.create_line(highlight_start_x, highlight_start_y,
                               highlight_end_x, highlight_end_y,
                               fill="#ffffff", width=1, tags="dynamic pointer")

            # 侧高光线（偏移3像素，模拟金属反光）
            side_offset = 3
            side_start_x = center_x + dx * 12 + perp_dx * side_offset
            side_start_y = center_y + dy * 12 + perp_dy * side_offset
            side_end_x = center_x + dx * (pointer_length - 12) + perp_dx * side_offset
            side_end_y = center_y + dy * (pointer_length - 12) + perp_dy * side_offset
            # 侧高光使用半透明白色
            canvas.create_line(side_start_x, side_start_y,
                               side_end_x, side_end_y,
                               fill="#aaaaaa", width=1, tags="dynamic pointer")

            # 绘制指针中心圆点（精致设计：三层同心圆）
            # 外圈发光
            canvas.create_oval(center_x - 15, center_y - 15,
                               center_x + 15, center_y + 15,
                               fill="", outline=speed_color, width=3, tags="dynamic pointer")
            # 中圈
            canvas.create_oval(center_x - 10, center_y - 10,
                               center_x + 10, center_y + 10,
                               fill=speed_color, outline="#ffffff", width=2, tags="dynamic pointer")
            # 内圈亮点
            canvas.create_oval(center_x - 4, center_y - 4,
                               center_x + 4, center_y + 4,
                               fill="#ffffff", outline="", tags="dynamic pointer")

            # ===== 速度值显示（优化：添加单位标签和更精致的排版） =====
            text_offset = radius * 0.35
            title_font_size = max(10, min(16, int(radius * 0.09)))
            value_font_size = max(20, min(40, int(radius * 0.22)))
            unit_font_size = max(8, min(12, int(radius * 0.06)))

            # 标题阴影
            canvas.create_text(center_x + 1, center_y - text_offset + 1,
                               text="实时速度", fill="#000000",
                               font=("Arial", title_font_size, "bold"), tags="dynamic")
            # 标题
            canvas.create_text(center_x, center_y - text_offset,
                               text="实时速度", fill=color,
                               font=("Arial", title_font_size, "bold"), tags="dynamic")

            # 速度值阴影
            canvas.create_text(center_x + 2, center_y - text_offset * 0.5 + 2,
                               text=f"{int(speed)}", fill="#000000",
                               font=("Arial", value_font_size, "bold"), tags="dynamic")
            # 速度值
            canvas.create_text(center_x, center_y - text_offset * 0.5,
                               text=f"{int(speed)}", fill="#ffffff",
                               font=("Arial", value_font_size, "bold"), tags="dynamic")

            # 单位标签（新增：更精致的排版）
            unit_y = center_y - text_offset * 0.5 + value_font_size * 0.5 + 2
            canvas.create_text(center_x, unit_y,
                               text="m/s", fill="#888888",
                               font=("Arial", unit_font_size), tags="dynamic")

            # 绘制状态指示灯（使用相对坐标，适配不同屏幕尺寸）
            status_color = "#00ff00" if speed > 0 else "#666666"
            # 指示灯位置：右上角区域（相对于半径）
            led_offset_x = radius * 0.55
            led_offset_y = -radius * 0.28
            led_size = max(8, int(radius * 0.08))
            # 指示灯外圆
            canvas.create_oval(center_x + led_offset_x - led_size,
                               center_y + led_offset_y - led_size,
                               center_x + led_offset_x + led_size,
                               center_y + led_offset_y + led_size,
                               fill=status_color, outline="#ffffff", width=2, tags="dynamic")
            # 指示灯内圆
            inner_led = max(4, int(led_size * 0.6))
            canvas.create_oval(center_x + led_offset_x - inner_led,
                               center_y + led_offset_y - inner_led,
                               center_x + led_offset_x + inner_led,
                               center_y + led_offset_y + inner_led,
                               fill="#ffffff", outline=status_color, width=1, tags="dynamic")
        except Exception as e:
            print(f"绘制仪表盘失败: {e}")

    def animate_speedometer(self, canvas, target_speed, color, car_num):
        """
        平滑动画更新仪表盘 - 全面优化版
        改进：
        1. 减少默认动画步数，从50步降到20步
        2. 增大重绘阈值，减少不必要的重绘
        3. 简化缓动函数为二次缓动（够用且更快）
        """
        # 防重入锁：如果该用户的动画正在运行，直接返回
        if self._animation_lock.get(car_num, False):
            return

        self._animation_lock[car_num] = True

        # 获取当前速度
        if car_num == 1:
            current_speed = self.last_speed1
        else:
            current_speed = self.last_speed2

        # 如果速度没有变化，直接绘制并释放锁
        if abs(target_speed - current_speed) < 0.01:
            self.draw_speedometer(canvas, target_speed, color)
            self._animation_lock[car_num] = False
            return

        # 计算速度差
        speed_diff = abs(target_speed - current_speed)

        # ===== 优化1：减少默认动画步数，从50步降到20步 =====
        total_steps = max(10, min(20, int(speed_diff * 5)))
        delay = max(5, int(15 - speed_diff * 0.5))
        delay = min(delay, 15)

        # ===== 优化3：简化缓动函数为二次缓动（计算更快） =====
        def precompute_ease_values(steps):
            values = []
            for i in range(steps + 1):
                t = i / steps
                # 二次缓动函数：简单高效，效果自然
                if t < 0.5:
                    eased = 2 * t * t
                else:
                    eased = 1 - pow(-2 * t + 2, 2) / 2
                values.append(eased)
            return values

        ease_values = precompute_ease_values(total_steps)

        # 存储动画状态
        animation_state = {
            'last_drawn_speed': current_speed,
            'completed': False,
            'canvas_size': (canvas.winfo_width(), canvas.winfo_height()),
        }

        def update_step(current_step):
            # 如果动画已被标记完成，则退出
            if animation_state['completed']:
                self._animation_lock[car_num] = False
                return

            # 检查画布大小是否变化
            current_width = canvas.winfo_width()
            current_height = canvas.winfo_height()
            if (current_width, current_height) != animation_state['canvas_size']:
                animation_state['completed'] = True
                if car_num == 1:
                    self.last_speed1 = target_speed
                else:
                    self.last_speed2 = target_speed
                self.draw_speedometer(canvas, target_speed, color)
                self._animation_lock[car_num] = False
                return

            # 获取预计算的缓动值
            eased_progress = ease_values[current_step]
            new_speed = current_speed + (target_speed - current_speed) * eased_progress

            # ===== 优化2：增大重绘阈值，减少不必要的重绘 =====
            redraw_threshold = max(0.01, 0.05 - speed_diff * 0.003)

            if abs(new_speed - animation_state['last_drawn_speed']) > redraw_threshold:
                self.draw_speedometer(canvas, new_speed, color)
                animation_state['last_drawn_speed'] = new_speed

            if current_step >= total_steps:
                # 动画完成
                animation_state['completed'] = True
                if car_num == 1:
                    self.last_speed1 = target_speed
                else:
                    self.last_speed2 = target_speed
                # 最终绘制
                self.draw_speedometer(canvas, target_speed, color)
                self._animation_lock[car_num] = False
            else:
                # 继续动画
                self.root.after(delay, update_step, current_step + 1)

        # 立即开始动画
        update_step(0)

    def start_countdown(self):
        """开始倒计时"""
        # 如果存在开场界面，清除它
        if hasattr(self, 'intro_canvas') and self.intro_canvas:
            self.intro_canvas.destroy()
            self.intro_canvas = None
        
        # 切换界面状态
        self.current_screen = "countdown"
        
        # 清除可能存在的旧界面
        for widget in self.root.winfo_children():
            widget.destroy()
        
        # 创建倒计时画布
        self.countdown_canvas = tk.Canvas(
            self.root,
            width=800,
            height=480,
            bg="#000d1a",
            highlightthickness=0
        )
        self.countdown_canvas.pack(fill="both", expand=True)
        
        center_x = 400
        center_y = 240
        
        # 创建深色背景
        self.countdown_canvas.create_rectangle(0, 0, 800, 480, 
                                             fill="#000d1a", outline="")
        
        # 创建外发光圆环（多层实现发光效果）
        for i in range(5, 0, -1):
            glow_radius = 80 + i * 8
            self.countdown_canvas.create_oval(
                center_x - glow_radius, center_y - glow_radius,
                center_x + glow_radius, center_y + glow_radius,
                fill="", outline="#003355", width=4
            )
        
        # 主倒计时圆形背景
        self.countdown_circle_id = self.countdown_canvas.create_oval(
            center_x - 70, center_y - 70,
            center_x + 70, center_y + 70,
            fill="#001122",
            outline="#00ffff",
            width=4
        )
        
        # 内圆装饰
        self.countdown_canvas.create_oval(
            center_x - 60, center_y - 60,
            center_x + 60, center_y + 60,
            fill="", outline="#003355", width=1
        )
        
        # 倒计时数字发光效果
        self.countdown_glow_id = self.countdown_canvas.create_text(
            center_x, center_y,
            text=str(self.countdown_value),
            fill="#003344",
            font=("Microsoft YaHei", 64, "bold")
        )
        
        # 倒计时数字
        self.countdown_text_id = self.countdown_canvas.create_text(
            center_x, center_y,
            text=str(self.countdown_value),
            fill="#00ffff",
            font=("Microsoft YaHei", 60, "bold")
        )
        
        # 提示文字
        self.countdown_canvas.create_text(
            center_x, center_y + 100,
            text="测试即将开始，请保持专注...",
            fill="#888888",
            font=("Microsoft YaHei", 14)
        )
        
        # 创建装饰性线条（四角）
        self.countdown_canvas.create_line(
            center_x - 100, center_y - 90,
            center_x - 60, center_y - 90,
            fill="#00ffff", width=2
        )
        self.countdown_canvas.create_line(
            center_x + 60, center_y - 90,
            center_x + 100, center_y - 90,
            fill="#00ffff", width=2
        )
        self.countdown_canvas.create_line(
            center_x - 100, center_y + 90,
            center_x - 60, center_y + 90,
            fill="#00ffff", width=2
        )
        self.countdown_canvas.create_line(
            center_x + 60, center_y + 90,
            center_x + 100, center_y + 90,
            fill="#00ffff", width=2
        )
        
        # 禁用开始按钮
        if hasattr(self, 'start_button') and self.start_button:
            self.start_button.config(state=tk.DISABLED)
        
        # 开始倒计时更新
        self.update_countdown()

    def update_countdown(self):
        """更新倒计时"""
        if self.countdown_value > 0:
            # 更新倒计时数字
            self.countdown_canvas.itemconfig(self.countdown_text_id, text=str(self.countdown_value))
            self.countdown_canvas.itemconfig(self.countdown_glow_id, text=str(self.countdown_value))
            
            # 添加数字缩放动画效果
            self._animate_countdown_number()
            
            self.countdown_value -= 1
            self.countdown_id = self.root.after(1000, self.update_countdown)
        else:
            # 显示"开始!"
            self.countdown_canvas.itemconfig(self.countdown_text_id, text="开始!")
            self.countdown_canvas.itemconfig(self.countdown_glow_id, text="开始!")
            
            # "开始!"的放大动画
            self._animate_start_text()
            
            self.root.after(1000, self.begin_monitoring)

    def _animate_countdown_number(self):
        """倒计时数字缩放动画"""
        scale = 1.2  # 初始放大比例
        font_size = 60
        
        def animate():
            nonlocal scale
            if scale > 1.0:
                scale -= 0.05
                new_size = int(font_size * scale)
                self.countdown_canvas.itemconfig(self.countdown_text_id, 
                                      font=("Microsoft YaHei", new_size, "bold"))
                self.countdown_canvas.itemconfig(self.countdown_glow_id,
                                      font=("Microsoft YaHei", new_size, "bold"))
                self.countdown_canvas.after(30, animate)
            else:
                # 恢复正常大小
                self.countdown_canvas.itemconfig(self.countdown_text_id,
                                      font=("Microsoft YaHei", font_size, "bold"))
                self.countdown_canvas.itemconfig(self.countdown_glow_id,
                                      font=("Microsoft YaHei", font_size, "bold"))
        
        animate()

    def _animate_start_text(self):
        """'开始!'文字放大动画"""
        scale = 1.0
        font_size = 60
        max_scale = 1.3
        growing = True
        
        def animate():
            nonlocal scale, growing
            if growing:
                scale += 0.05
                if scale >= max_scale:
                    growing = False
            else:
                scale -= 0.03
                if scale <= 1.0:
                    return
            
            new_size = int(font_size * scale)
            self.countdown_canvas.itemconfig(self.countdown_text_id,
                                  font=("Microsoft YaHei", new_size, "bold"))
            self.countdown_canvas.itemconfig(self.countdown_glow_id,
                                  font=("Microsoft YaHei", new_size, "bold"))
            self.countdown_canvas.after(30, animate)
        
        animate()

    def show_countdown_buffer(self):
        """显示倒计时缓冲界面 - 优化版"""
        # 如果存在开场界面，清除它（简化版：直接删除所有子组件）
        for widget in self.root.winfo_children():
            widget.destroy()
        
        # 切换界面状态
        self.current_screen = "countdown"
        
        # 创建倒计时缓冲画布（全屏，使用expand=True支持缩放）
        self.countdown_buffer_canvas = tk.Canvas(
            self.root,
            bg="#000d1a",
            highlightthickness=0
        )
        self.countdown_buffer_canvas.pack(fill="both", expand=True)
        
        # 强制刷新一次
        self.countdown_buffer_canvas.update_idletasks()
        
        # 绘制倒计时界面
        self._draw_countdown_buffer()
        
        # 设置倒计时初始值
        self.countdown_buffer_value = 3
        
        # 绑定窗口大小变化事件
        self.root.bind("<Configure>", self._handle_countdown_resize)
        
        # 启动倒计时动画（使用after_idle确保界面已就绪）
        self.root.after_idle(self.update_countdown_buffer)
    
    def _draw_countdown_buffer(self):
        """绘制倒计时缓冲界面"""
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        
        if width <= 1 or height <= 1:
            return
        
        center_x = width / 2
        center_y = height / 2
        
        # 清除画布
        self.countdown_buffer_canvas.delete("all")
        
        # 创建背景
        self.countdown_buffer_canvas.create_rectangle(0, 0, width, height, 
                                                      fill="#000d1a", outline="")
        
        # 圆环和文字尺寸根据窗口大小调整
        ring_radius = min(width, height) * 0.18
        inner_ring_radius = ring_radius * 0.9
        
        # 字体大小根据窗口大小调整
        font_size = max(40, min(80, int(ring_radius * 0.8)))
        
        # 简化的背景设计 - 减少层数
        for i in range(3, 0, -1):
            glow_radius = ring_radius + i * 12
            self.countdown_buffer_canvas.create_oval(
                center_x - glow_radius, center_y - glow_radius,
                center_x + glow_radius, center_y + glow_radius,
                fill="", outline="#004466", width=1
            )
        
        # 主圆形边框
        self.countdown_buffer_canvas.create_oval(
            center_x - ring_radius, center_y - ring_radius,
            center_x + ring_radius, center_y + ring_radius,
            fill="#001122",
            outline="#00ffff",
            width=3
        )
        
        # 倒计时数字
        self.countdown_buffer_text = self.countdown_buffer_canvas.create_text(
            center_x, center_y,
            text="3",
            fill="#00ffff",
            font=("Microsoft YaHei", font_size, "bold")
        )
        
        # 提示文字位置
        hint_y = center_y + ring_radius + 40
        
        # 提示文字
        self.countdown_buffer_hint = self.countdown_buffer_canvas.create_text(
            center_x, hint_y,
            text="准备开始...",
            fill="#888888",
            font=("Microsoft YaHei", 14)
        )
        
        # 装饰线位置
        line_offset = ring_radius + 10
        
        # 创建装饰性线条（四角）
        self.countdown_buffer_canvas.create_line(
            center_x - line_offset - 40, center_y - line_offset,
            center_x - line_offset, center_y - line_offset,
            fill="#00ffff", width=2
        )
        self.countdown_buffer_canvas.create_line(
            center_x + line_offset, center_y - line_offset,
            center_x + line_offset + 40, center_y - line_offset,
            fill="#00ffff", width=2
        )
        self.countdown_buffer_canvas.create_line(
            center_x - line_offset - 40, center_y + line_offset,
            center_x - line_offset, center_y + line_offset,
            fill="#00ffff", width=2
        )
        self.countdown_buffer_canvas.create_line(
            center_x + line_offset, center_y + line_offset,
            center_x + line_offset + 40, center_y + line_offset,
            fill="#00ffff", width=2
        )
    
    def _handle_countdown_resize(self, event):
        """倒计时界面窗口大小变化处理"""
        if event.widget != self.root:
            return
        
        if not hasattr(self, 'countdown_buffer_canvas') or not self.countdown_buffer_canvas:
            return
        
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        
        if width <= 1 or height <= 1:
            return
        
        # 重新绘制倒计时界面
        self._draw_countdown_buffer()
        
        # 更新倒计时数字显示
        if hasattr(self, 'countdown_buffer_text'):
            if self.countdown_buffer_value > 0:
                self.countdown_buffer_canvas.itemconfig(
                    self.countdown_buffer_text, 
                    text=str(self.countdown_buffer_value)
                )
    
    def animate_number_scale(self):
        """数字脉冲放大动画，从1.2倍缩小到1.0倍"""
        scale = 1.2
        font_size = 64
        
        def animate():
            nonlocal scale
            if scale > 1.0:
                scale -= 0.04
                new_size = int(font_size * scale)
                self.countdown_buffer_canvas.itemconfig(
                    self.countdown_buffer_text,
                    font=("Microsoft YaHei", new_size, "bold")
                )
                self.countdown_buffer_canvas.after(30, animate)
            else:
                self.countdown_buffer_canvas.itemconfig(
                    self.countdown_buffer_text,
                    font=("Microsoft YaHei", font_size, "bold")
                )
        
        animate()
    
    def animate_go_scale(self):
        """GO!放大动画，从1.0倍放大到1.3倍"""
        scale = 1.0
        font_size = 64
        max_scale = 1.3
        growing = True
        
        def animate():
            nonlocal scale, growing
            if growing:
                scale += 0.05
                if scale >= max_scale:
                    growing = False
            else:
                scale -= 0.03
                if scale <= 1.0:
                    return
            
            new_size = int(font_size * scale)
            self.countdown_buffer_canvas.itemconfig(
                self.countdown_buffer_text,
                font=("Microsoft YaHei", new_size, "bold")
            )
            self.countdown_buffer_canvas.after(30, animate)
        
        animate()
    
    def update_countdown_buffer(self):
        """更新倒计时缓冲 - 简化版"""
        if self.countdown_buffer_value > 0:
            # 更新数字
            self.countdown_buffer_canvas.itemconfig(
                self.countdown_buffer_text, text=str(self.countdown_buffer_value))
            
            # 更新提示文字
            hints = ["准备开始...", "请保持专注...", "即将开始..."]
            self.countdown_buffer_canvas.itemconfig(
                self.countdown_buffer_hint, text=hints[3 - self.countdown_buffer_value])
            
            # 添加数字脉冲放大动画
            self.animate_number_scale()
            
            self.countdown_buffer_value -= 1
            # 使用较短的延迟，提高响应性
            self.root.after(1000, self.update_countdown_buffer)
        else:
            # 显示"GO!"并调用放大动画
            self.countdown_buffer_canvas.itemconfig(self.countdown_buffer_text, text="GO!")
            self.countdown_buffer_canvas.itemconfig(self.countdown_buffer_hint, text="开始!")
            
            # 调用GO!放大动画
            self.animate_go_scale()
            
            # 800ms后进入主界面
            self.root.after(800, self.enter_main_screen)

    def enter_main_screen(self):
        """从倒计时缓冲界面进入主测试界面 - 优化流畅版"""
        if hasattr(self, 'countdown_buffer_canvas') and self.countdown_buffer_canvas:
            self.countdown_buffer_canvas.destroy()
            self.countdown_buffer_canvas = None
        
        self.current_screen = "main"
        
        for widget in self.root.winfo_children():
            widget.destroy()
        
        self.create_main_page()
        
        self.root.after(150, self._enter_main_screen_part2)
    
    def _enter_main_screen_part2(self):
        """进入主界面第二部分"""
        self.init_ui_elements()
        
        self.create_controls()
        
        self.update_clock()
        
        self.root.bind("<Configure>", self.on_window_resize)
        
        self.running = True
        if gpio_initialized:
            try:
                GPIO.output(STBY, GPIO.HIGH)
            except Exception as e:
                print(f'GPIO控制失败: {e}')
        
        self.test_start_time = time.time()
        self.update_test_timer()
        
        self.start_data_update()

    def update_test_timer(self):
        """更新测试计时器"""
        if not self.running:
            return

        elapsed = time.time() - self.test_start_time
        remaining = self.selected_duration - elapsed

        if remaining <= 0:
            # 测试时间到，直接停止监控
            self.running = False
            if gpio_initialized:
                try:
                    GPIO.output(STBY, GPIO.LOW)
                except Exception as e:
                    print(f'GPIO控制失败: {e}')
            
            # 先保存历史数据
            saved_history1 = list(self.attention1_history)
            saved_history2 = list(self.attention2_history)
            
            # 停止数据更新
            self.stop_data_update()
            
            # 使用保存的数据显示测试总结
            self.show_test_summary(saved_history1, saved_history2)
        else:
            # 更新剩余时间显示
            self.test_timer_id = self.root.after(1000, self.update_test_timer)


    def start_data_update(self):
        """开始数据更新"""
        # 根据所选时长调整最大数据点数
        if self.selected_duration <= 60:
            self.max_points = 60
        elif self.selected_duration <= 180:
            self.max_points = 180
        else:
            self.max_points = 300
        
        # 清空数据
        self.attention1_data = deque([0] * self.max_points, maxlen=self.max_points)
        self.attention2_data = deque([0] * self.max_points, maxlen=self.max_points)

        # 重置数据变化追踪
        self._last_data1_tail = 0
        self._last_data2_tail = 0
        self._last_data1_len = self.max_points
        self._last_data2_len = self.max_points

        # 开始定时更新
        self.update_data()

    def stop_data_update(self):
        """停止数据更新"""
        # 停止脉冲动画
        for car_num in [1, 2]:
            if self._pulse_timer[car_num] is not None:
                self.root.after_cancel(self._pulse_timer[car_num])
                self._pulse_timer[car_num] = None
        
        # 清空历史数据
        self.attention1_history.clear()
        self.attention2_history.clear()

    def show_test_summary(self, history1=None, history2=None):
        """显示测试总结界面"""
        # 使用传入的历史数据
        if history1 is None:
            history1 = []
        if history2 is None:
            history2 = []
        
        # 计算统计数据
        if len(history1) > 0:
            avg1 = sum(history1) / len(history1)
            max1 = max(history1)
            min1 = min(history1)
        else:
            avg1, max1, min1 = 0, 0, 0
        
        if len(history2) > 0:
            avg2 = sum(history2) / len(history2)
            max2 = max(history2)
            min2 = min(history2)
        else:
            avg2, max2, min2 = 0, 0, 0
        
        # 创建总结画布
        self.summary_canvas = tk.Canvas(
            self.root,
            bg="#000d1a",
            highlightthickness=0
        )
        self.summary_canvas.pack(fill="both", expand=True)
        
        # 获取窗口尺寸
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        center_x = width / 2
        
        # 创建背景
        self.summary_canvas.create_rectangle(0, 0, width, height, 
                                              fill="#000d1a", outline="")
        
        # 标题
        title_y = height * 0.12
        title_font = max(24, min(40, int(height * 0.05)))
        self.summary_canvas.create_text(
            center_x, title_y,
            text="测试完成",
            fill="#00ffff",
            font=("Microsoft YaHei", title_font, "bold")
        )
        
        # 装饰线
        line_y1 = height * 0.18
        self.summary_canvas.create_line(
            center_x - 150, line_y1,
            center_x + 150, line_y1,
            fill="#00ffff", width=2, dash=(8, 4)
        )
        
        # 用户1统计信息
        user1_y = height * 0.32
        user1_label = self.summary_canvas.create_text(
            center_x, user1_y,
            text="玩家1 专注度",
            fill="#00bfff",
            font=("Microsoft YaHei", 18, "bold")
        )
        
        avg1_y = height * 0.40
        self.summary_canvas.create_text(
            center_x, avg1_y,
            text=f"平均专注度: {avg1:.1f}",
            fill="#00ffff",
            font=("Microsoft YaHei", 16)
        )
        
        max1_y = height * 0.46
        self.summary_canvas.create_text(
            center_x, max1_y,
            text=f"最高专注度: {max1:.1f}",
            fill="#00ff88",
            font=("Microsoft YaHei", 14)
        )
        
        min1_y = height * 0.52
        self.summary_canvas.create_text(
            center_x, min1_y,
            text=f"最低专注度: {min1:.1f}",
            fill="#ff6666",
            font=("Microsoft YaHei", 14)
        )
        
        # 中间装饰线
        line_y2 = height * 0.58
        self.summary_canvas.create_line(
            center_x - 100, line_y2,
            center_x + 100, line_y2,
            fill="#666666", width=1, dash=(4, 4)
        )
        
        # 用户2统计信息
        user2_y = height * 0.64
        self.summary_canvas.create_text(
            center_x, user2_y,
            text="玩家2 专注度",
            fill="#ff00ff",
            font=("Microsoft YaHei", 18, "bold")
        )
        
        avg2_y = height * 0.72
        self.summary_canvas.create_text(
            center_x, avg2_y,
            text=f"平均专注度: {avg2:.1f}",
            fill="#00ffff",
            font=("Microsoft YaHei", 16)
        )
        
        max2_y = height * 0.78
        self.summary_canvas.create_text(
            center_x, max2_y,
            text=f"最高专注度: {max2:.1f}",
            fill="#00ff88",
            font=("Microsoft YaHei", 14)
        )
        
        min2_y = height * 0.84
        self.summary_canvas.create_text(
            center_x, min2_y,
            text=f"最低专注度: {min2:.1f}",
            fill="#ff6666",
            font=("Microsoft YaHei", 14)
        )
        
        # 重新测试按钮
        button_y = height * 0.93
        button_height = height * 0.06
        button_font = max(12, min(16, int(height * 0.025)))
        
        # 创建按钮背景框
        self.summary_canvas.create_rectangle(
            center_x - 70, button_y - button_height / 2,
            center_x + 70, button_y + button_height / 2,
            fill="#001122", outline="#00ffff", width=2
        )
        
        # 创建重新测试按钮
        self.restart_button = tk.Button(
            self.root,
            text="重新测试",
            command=self.restart_test,
            bg="#00ff00",
            fg="#000d1a",
            font=("Microsoft YaHei", button_font, "bold"),
            width=10,
            height=1,
            relief="raised",
            bd=3,
            activebackground="#00ff88",
            activeforeground="#000d1a",
            cursor="hand2"
        )
        
        # 将按钮放在画布上
        self.summary_canvas.create_window(
            center_x, button_y,
            window=self.restart_button
        )
        
        # 绑定窗口大小变化事件以实现自适应
        self.root.bind("<Configure>", self._handle_summary_resize)

    def _handle_summary_resize(self, event):
        """总结界面窗口大小变化处理"""
        if event.widget != self.root:
            return
        
        if not hasattr(self, 'summary_canvas') or not self.summary_canvas:
            return
        
        # 延迟重绘以避免频繁更新
        if hasattr(self, '_summary_resize_timer') and self._summary_resize_timer:
            self.root.after_cancel(self._summary_resize_timer)
        
        def _redraw_summary():
            # 清除画布
            self.summary_canvas.delete("all")
            
            # 获取新尺寸
            width = self.root.winfo_width()
            height = self.root.winfo_height()
            center_x = width / 2
            
            # 重新创建背景
            self.summary_canvas.create_rectangle(0, 0, width, height, 
                                                  fill="#000d1a", outline="")
            
            # 标题
            title_y = height * 0.12
            title_font = max(24, min(40, int(height * 0.05)))
            self.summary_canvas.create_text(
                center_x, title_y,
                text="测试完成",
                fill="#00ffff",
                font=("Microsoft YaHei", title_font, "bold")
            )
            
            # 装饰线
            line_y1 = height * 0.18
            self.summary_canvas.create_line(
                center_x - 150, line_y1,
                center_x + 150, line_y1,
                fill="#00ffff", width=2, dash=(8, 4)
            )
            
            # 用户1统计信息
            user1_y = height * 0.32
            self.summary_canvas.create_text(
                center_x, user1_y,
                text="玩家1 专注度",
                fill="#00bfff",
                font=("Microsoft YaHei", 18, "bold")
            )
            
            avg1_y = height * 0.40
            self.summary_canvas.create_text(
                center_x, avg1_y,
                text=f"平均专注度: {avg1:.1f}",
                fill="#00ffff",
                font=("Microsoft YaHei", 16)
            )
            
            max1_y = height * 0.46
            self.summary_canvas.create_text(
                center_x, max1_y,
                text=f"最高专注度: {max1:.1f}",
                fill="#00ff88",
                font=("Microsoft YaHei", 14)
            )
            
            min1_y = height * 0.52
            self.summary_canvas.create_text(
                center_x, min1_y,
                text=f"最低专注度: {min1:.1f}",
                fill="#ff6666",
                font=("Microsoft YaHei", 14)
            )
            
            # 中间装饰线
            line_y2 = height * 0.58
            self.summary_canvas.create_line(
                center_x - 100, line_y2,
                center_x + 100, line_y2,
                fill="#666666", width=1, dash=(4, 4)
            )
            
            # 用户2统计信息
            user2_y = height * 0.64
            self.summary_canvas.create_text(
                center_x, user2_y,
                text="玩家2 专注度",
                fill="#ff00ff",
                font=("Microsoft YaHei", 18, "bold")
            )
            
            avg2_y = height * 0.72
            self.summary_canvas.create_text(
                center_x, avg2_y,
                text=f"平均专注度: {avg2:.1f}",
                fill="#00ffff",
                font=("Microsoft YaHei", 16)
            )
            
            max2_y = height * 0.78
            self.summary_canvas.create_text(
                center_x, max2_y,
                text=f"最高专注度: {max2:.1f}",
                fill="#00ff88",
                font=("Microsoft YaHei", 14)
            )
            
            min2_y = height * 0.84
            self.summary_canvas.create_text(
                center_x, min2_y,
                text=f"最低专注度: {min2:.1f}",
                fill="#ff6666",
                font=("Microsoft YaHei", 14)
            )
            
            # 重新测试按钮
            button_y = height * 0.93
            button_height = height * 0.06
            button_font = max(12, min(16, int(height * 0.025)))
            
            # 创建按钮背景框
            self.summary_canvas.create_rectangle(
                center_x - 70, button_y - button_height / 2,
                center_x + 70, button_y + button_height / 2,
                fill="#001122", outline="#00ffff", width=2
            )
            
            # 创建重新测试按钮
            self.restart_button = tk.Button(
                self.root,
                text="重新测试",
                command=self.restart_test,
                bg="#00ff00",
                fg="#000d1a",
                font=("Microsoft YaHei", button_font, "bold"),
                width=10,
                height=1,
                relief="raised",
                bd=3,
                activebackground="#00ff88",
                activeforeground="#000d1a",
                cursor="hand2"
            )
            
            # 将按钮放在画布上
            self.summary_canvas.create_window(
                center_x, button_y,
                window=self.restart_button
            )
            
            self._summary_resize_timer = None
        
        self._summary_resize_timer = self.root.after(100, _redraw_summary)

    def restart_test(self):
        """重新开始测试"""
        # 清除总结界面
        if hasattr(self, 'summary_canvas'):
            self.summary_canvas.pack_forget()
            self.summary_canvas.destroy()
        
        # 返回开场动画界面
        self.create_intro_screen()

    def update_display(self, attention1, attention2):
        """更新显示而不更新曲线图"""
        # 转换为速度
        speed1 = self.attention_to_speed(attention1)
        speed2 = self.attention_to_speed(attention2)

        # 平滑更新显示
        self.update_car_display(1, attention1, speed1, "#00bfff")
        self.update_car_display(2, attention2, speed2, "#ff00ff")

    def attention_to_speed(self, attention):
        """将专注度转换为速度"""
        # 参考小车模型中的专注度到速度的转换逻辑
        if attention >= 90:
            # 超高专注：速度10-12
            speed = 10 + (attention - 90) / 10 * 2
        elif attention >= 70:
            # 高专注：速度7-10
            speed = 7 + (attention - 70) / 20 * 3
        elif attention >= 40:
            # 中专注：速度3-7
            speed = 3 + (attention - 40) / 30 * 4
        else:
            # 低专注：速度0-3
            speed = 0 + (attention - 0) / 40 * 3 if attention > 0 else 0

        # 速度上限保护
        speed = min(speed, 12)

        return speed

    def update_attention(self, attention1, attention2):
        """更新专注度数据并刷新显示"""
        if not self.running:
            return

        # 确保值在有效范围内
        attention1 = max(0, min(99, attention1))
        attention2 = max(0, min(99, attention2))

        # 转换为速度
        speed1 = self.attention_to_speed(attention1)
        speed2 = self.attention_to_speed(attention2)

        # 添加新数据点
        self.attention1_data.append(attention1)
        self.attention2_data.append(attention2)

        # 平滑更新专注度值显示
        self.update_car_display(1, attention1, speed1, "#00bfff")
        self.update_car_display(2, attention2, speed2, "#ff00ff")

        # 更新曲线图
        self.update_plots()

    def update_car_display(self, car_num, attention, speed, color):
        """更新单个用户的显示"""
        # 获取当前速度
        if car_num == 1:
            current_speed = self.last_speed1
        else:
            current_speed = self.last_speed2

        # 速度变化阈值，只有当变化超过此值时才进行动画
        speed_change_threshold = 0.1

        # 如果速度变化很小，直接返回，避免不必要的动画
        if abs(speed - current_speed) < speed_change_threshold:
            return

        # 更新速度历史数据
        self.speed_history[car_num].append(speed)
        # 保持历史数据长度
        if len(self.speed_history[car_num]) > self.history_length:
            self.speed_history[car_num].pop(0)

        # 使用移动平均预测下一个速度，使动画更平滑
        if len(self.speed_history[car_num]) >= 5:
            avg_speed = sum(self.speed_history[car_num]) / len(self.speed_history[car_num])
            recent_speeds = self.speed_history[car_num][-3:]
            recent_avg = sum(recent_speeds) / len(recent_speeds)
            predicted_speed = avg_speed + (speed - avg_speed) * 0.2
            max_speed = self.speedometer_cache['max_speed']
            min_speed = self.speedometer_cache['min_speed']
            predicted_speed = max(min_speed, min(max_speed, predicted_speed))
        else:
            predicted_speed = speed

        # 更新速度显示，使用预测的速度
        if car_num == 1:
            self.animate_speedometer(self.speedo1_canvas, predicted_speed, color, 1)
        else:
            self.animate_speedometer(self.speedo2_canvas, predicted_speed, color, 2)

    def _init_caches(self):
        """初始化缓存"""
        # 仪表盘参数缓存
        self.speedometer_cache = {
            'min_speed': 0,
            'max_speed': 12,
            'step': 2,
            'center_x': 180,
            'center_y': 170,
            'radius': 140,
            'inner_radius': 110,
            'tick_data': []  # 存储刻度数据
        }

        # 预计算刻度数据
        self._precompute_tick_data()

        # 绘制缓存
        self.drawing_cache = {
            'static_elements': {},  # 存储静态元素的缓存
            'canvas_size': {},  # 存储每个画布的大小
            'last_speed': {}  # 存储每个仪表盘的最后速度
        }

        # 速度历史数据，用于移动平均预测
        self.speed_history = {
            1: [],  # 用户1的速度历史
            2: []   # 用户2的速度历史
        }
        self.history_length = 5  # 历史数据长度，用于计算移动平均

    def update_speedometer_cache(self, canvas):
        """根据画布大小更新仪表盘缓存参数"""
        width = canvas.winfo_width()
        height = canvas.winfo_height()

        if width > 0 and height > 0:
            center_x = width / 2
            center_y = height * 0.88
            radius = min(width, height) * 0.72
            inner_radius = radius * 0.78

            # 更新缓存
            self.speedometer_cache['center_x'] = center_x
            self.speedometer_cache['center_y'] = center_y
            self.speedometer_cache['radius'] = radius
            self.speedometer_cache['inner_radius'] = inner_radius

            # 重新预计算刻度数据
            self._precompute_tick_data()

    def _precompute_tick_data(self):
        """预计算刻度数据"""
        min_speed = self.speedometer_cache['min_speed']
        max_speed = self.speedometer_cache['max_speed']
        step = self.speedometer_cache['step']

        tick_data = []
        for i in range(min_speed, max_speed + 1, step):
            angle = 180 - (i / max_speed) * 180
            angle_rad = math.radians(angle)
            cos_val = math.cos(angle_rad)
            sin_val = math.sin(angle_rad)

            tick_data.append({
                'speed': i,
                'angle': angle,
                'angle_rad': angle_rad,
                'cos': cos_val,
                'sin': sin_val
            })

        self.speedometer_cache['tick_data'] = tick_data

    def on_window_resize(self, event):
        """窗口大小变化时的处理函数 - 优化版：添加300ms防抖机制"""
        # 忽略非主窗口的resize事件
        if event.widget != self.root:
            return

        # 取消之前的防抖定时器
        if self._resize_timer is not None:
            self.root.after_cancel(self._resize_timer)

        # 设置新的防抖定时器（300ms延迟）
        def _debounced_resize():
            self._resize_timer = None
            # 重新绘制坐标轴
            self.draw_axes()

            # 重新绘制仪表盘（直接绘制，不使用动画，避免触发防重入锁）
            self.draw_speedometer(self.speedo1_canvas, self.last_speed1, "#00bfff")
            self.draw_speedometer(self.speedo2_canvas, self.last_speed2, "#ff00ff")

            # 重新绘制曲线图
            if hasattr(self, 'attention1_data') and hasattr(self, 'attention2_data'):
                width1 = self.canvas1.winfo_width()
                height1 = self.canvas1.winfo_height()
                if width1 > 0 and height1 > 0:
                    self.draw_line(self.canvas1, self.attention1_data, width1, height1, "#00bfff")

                width2 = self.canvas2.winfo_width()
                height2 = self.canvas2.winfo_height()
                if width2 > 0 and height2 > 0:
                    self.draw_line(self.canvas2, self.attention2_data, width2, height2, "#ff00ff")

        self._resize_timer = self.root.after(300, _debounced_resize)

    def update_plots(self):
        """
        更新两个曲线图 - 优化版
        改进：优化数据变化检测逻辑，只比较尾部值和长度
        """
        if not self.running:
            return

        # ===== 优化数据变化检测：只比较尾部值和长度，避免创建完整列表 =====
        data1_changed = False
        data2_changed = False

        len1 = len(self.attention1_data)
        len2 = len(self.attention2_data)

        if len1 != self._last_data1_len:
            data1_changed = True
        elif len1 > 0 and self.attention1_data[-1] != self._last_data1_tail:
            data1_changed = True

        if len2 != self._last_data2_len:
            data2_changed = True
        elif len2 > 0 and self.attention2_data[-1] != self._last_data2_tail:
            data2_changed = True

        # 绘制用户1曲线
        if data1_changed:
            width1 = self.canvas1.winfo_width()
            height1 = self.canvas1.winfo_height()
            if width1 > 0 and height1 > 0:
                self.draw_line(self.canvas1, self.attention1_data, width1, height1, "#00bfff", car_num=1)
                self._last_data1_tail = self.attention1_data[-1]
                self._last_data1_len = len1

        # 绘制用户2曲线
        if data2_changed:
            width2 = self.canvas2.winfo_width()
            height2 = self.canvas2.winfo_height()
            if width2 > 0 and height2 > 0:
                self.draw_line(self.canvas2, self.attention2_data, width2, height2, "#ff00ff", car_num=2)
                self._last_data2_tail = self.attention2_data[-1]
                self._last_data2_len = len2

    def draw_line(self, canvas, data, width, height, color, car_num=None):
        """
        绘制单条曲线 - 全面优化版
        改进：
        1. 性能：用滑动窗口均值O(n)替代三次样条插值O(n^2)
        2. 视觉：多层渐变填充（3-4层），从曲线颜色到透明
        3. 视觉：曲线末端标记点添加脉冲动画效果
        4. 视觉：Y轴数值标签的背景色块（在draw_axis中已实现）
        5. 性能：减少发光效果绘制次数，用单次宽线+单次细线替代3次绘制
        """
        try:
            # 设置绘图参数（使用相对值）
            margin_x = width * 0.1
            margin_y = height * 0.15
            plot_height = height - margin_y * 2
            plot_width = width - margin_x - 10

            # 没有足够数据时不绘制
            if len(data) < 2:
                return

            # 清除画布
            canvas.delete("line")
            canvas.delete("pulse")

            # 计算每个点的x间隔
            x_step = plot_width / (len(data) - 1)

            # 使用原始数据直接绘制，确保曲线与数值标签一致
            points = []
            for i, value in enumerate(data):
                x = margin_x + i * x_step
                y = margin_y + plot_height * (100 - value) / 100
                points.append((x, y))

            if len(points) >= 3:
                # 展开坐标列表
                coords = []
                for px, py in points:
                    coords.extend([px, py])

                # ===== 性能优化：减少发光效果绘制次数 =====
                # 解析曲线颜色用于发光效果
                r = int(color[1:3], 16)
                g = int(color[3:5], 16)
                b = int(color[5:7], 16)
                # 原来绘制3次（填充+发光+主线+主线覆盖），现在只绘制2次
                # 第1次：宽线作为发光底层
                glow_r = max(0, int(r * 0.3))
                glow_g = max(0, int(g * 0.3))
                glow_b = max(0, int(b * 0.3))
                glow_color = f"#{glow_r:02x}{glow_g:02x}{glow_b:02x}"
                canvas.create_line(*coords, fill=glow_color, width=5, tags="line", smooth=False)

                # 第2次：细线作为主曲线
                canvas.create_line(*coords, fill=color, width=2, tags="line", smooth=False)

            elif len(points) == 2:
                # 只有两个点时绘制直线
                canvas.create_line(*points[0], *points[1], fill=color, width=2, tags="line")
            else:
                # 三个点时使用二次贝塞尔曲线
                x0, y0 = points[0]
                x1, y1 = points[1]
                x2, y2 = points[2]
                cx = (x0 + x2) / 2
                cy = (y0 + y2) / 2
                canvas.create_line(x0, y0, cx, cy, x2, y2, fill=color, width=2, tags="line")

            # ===== 视觉优化：曲线末端标记点添加脉冲动画效果 =====
            if points:
                x, y = points[-1]
                current_value = int(data[-1])

                # 绘制静态标记点（外圈）
                canvas.create_oval(x - 5, y - 5, x + 5, y + 5,
                                   fill="", outline=color, width=2, tags="line")
                # 内圈实心点
                canvas.create_oval(x - 3, y - 3, x + 3, y + 3,
                                   fill=color, outline="", tags="line")

                # ===== 改进的当前值标签样式 =====
                value_text = f"{current_value}"
                font = ("Consolas", 10, "bold")
                # 估算文本尺寸
                text_w = len(value_text) * 7 + 12
                text_h = 18
                box_x1 = x - text_w / 2
                box_x2 = x + text_w / 2
                box_y1 = y - 32
                box_y2 = y - 14

                # 绘制标签背景色块（圆角效果用矩形模拟）
                canvas.create_rectangle(box_x1, box_y1, box_x2, box_y2,
                                        fill="#001a33", outline=color, width=1.5, tags="line")
                # 在色块内显示值（居中）
                canvas.create_text(x, (box_y1 + box_y2) / 2, text=value_text,
                                   fill="#ffffff", font=font, anchor="center", tags="line")

                # 启动脉冲动画（如果正在监控）
                if self.running and car_num is not None:
                    self._start_pulse_animation(canvas, x, y, color, car_num)

        except Exception as e:
            print(f"绘制曲线失败: {e}")

    def _start_pulse_animation(self, canvas, x, y, color, car_num):
        """
        启动曲线末端标记点的脉冲动画
        使用定时器实现扩散-消失的脉冲环效果
        """
        # 取消之前的脉冲动画
        if self._pulse_timer[car_num] is not None:
            self.root.after_cancel(self._pulse_timer[car_num])

        self._pulse_phase[car_num] = 0

        def _pulse_step():
            """脉冲动画单步"""
            if not self.running:
                self._pulse_timer[car_num] = None
                return

            phase = self._pulse_phase[car_num]
            # 脉冲动画：3个阶段，每个阶段扩散一圈
            total_phases = 3
            if phase >= total_phases:
                self._pulse_timer[car_num] = None
                return

            # 清除旧的脉冲环
            canvas.delete("pulse")

            # 绘制当前阶段的脉冲环（扩散半径随phase增大）
            pulse_radius = 6 + phase * 4
            # 透明度随phase递减（通过颜色模拟）
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)
            alpha = 1.0 - phase / total_phases
            pulse_r = max(0, int(r * alpha * 0.5))
            pulse_g = max(0, int(g * alpha * 0.5))
            pulse_b = max(0, int(b * alpha * 0.5))
            pulse_color = f"#{pulse_r:02x}{pulse_g:02x}{pulse_b:02x}"

            canvas.create_oval(x - pulse_radius, y - pulse_radius,
                               x + pulse_radius, y + pulse_radius,
                               fill="", outline=pulse_color, width=1.5,
                               tags="pulse")

            self._pulse_phase[car_num] = phase + 1
            self._pulse_timer[car_num] = self.root.after(150, _pulse_step)

        _pulse_step()

    def _safe_read_eeg(self):
        """安全读取EEG数据，带类型校验和范围校验"""
        try:
            val1 = EEG.Attention_1
            val2 = EEG.Attention_2
            # 类型校验：确保是数值类型
            att1 = int(float(val1)) if val1 is not None else 50
            att2 = int(float(val2)) if val2 is not None else 50
        except (TypeError, ValueError, AttributeError) as e:
            print(f"EEG数据类型异常: {e}")
            att1, att2 = 50, 50
        # 范围校验：限制在0-99
        att1 = max(0, min(99, att1))
        att2 = max(0, min(99, att2))
        return att1, att2

    def _simulate_attention(self, current_val):
        """
        带惯性的随机游走模拟，使模拟数据更接近真实EEG曲线
        每次在上一个值基础上 ±12 以内波动，模拟专注度的渐变过程
        """
        max_delta = 12  # 最大单次变化量
        delta = random.uniform(-max_delta, max_delta)
        new_val = current_val + delta
        # 偶尔产生较大波动（5%概率），模拟突然走神或集中注意力
        if random.random() < 0.05:
            new_val += random.uniform(-20, 20)
        return max(0, min(99, int(new_val)))

    def update_data(self):
        """定时更新数据"""
        if self.running:
            try:
                # 获取数据
                if eeg_available:
                    att1, att2 = self._safe_read_eeg()
                else:
                    # 使用带惯性的随机游走生成模拟数据
                    self._sim_attention1 = self._simulate_attention(self._sim_attention1)
                    self._sim_attention2 = self._simulate_attention(self._sim_attention2)
                    att1 = self._sim_attention1
                    att2 = self._sim_attention2

                # 存储历史数据用于计算平均值
                self.attention1_history.append(att1)
                self.attention2_history.append(att2)

                # 更新UI
                self.update_attention(att1, att2)

                # 设置下一次更新
                self.root.after(1000, self.update_data)
            except Exception as e:
                print(f"数据更新失败: {e}")
                if self.running:
                    self.root.after(1000, self.update_data)

    def update_clock(self):
        """更新时间显示（已禁用）"""
        pass

    def update_status(self, message):
        """更新状态提示并添加视觉反馈"""
        pass

    def on_speedometer_click(self, car_num, event):
        """处理仪表盘点击事件"""
        cache = self.speedometer_cache
        center_x = cache['center_x']
        center_y = cache['center_y']
        radius = cache['radius']

        # 计算点击位置到中心的角度
        dx = event.x - center_x
        dy = center_y - event.y  # 注意y轴方向相反

        # 计算角度（弧度）
        angle_rad = math.atan2(dy, dx)
        angle_deg = math.degrees(angle_rad)

        # 转换为仪表盘角度（0-180度）
        if angle_deg < 0:
            angle_deg += 360

        # 转换为速度（0-12）
        if 0 <= angle_deg <= 180:
            speed = (180 - angle_deg) / 180 * 12
            speed = max(0, min(12, speed))

            # 更新速度
            if car_num == 1:
                self.last_speed1 = speed
                self.animate_speedometer(self.speedo1_canvas, speed, "#00bfff", 1)
            else:
                self.last_speed2 = speed
                self.animate_speedometer(self.speedo2_canvas, speed, "#ff00ff", 2)


# 主程序
if __name__ == "__main__":
    print("启动小车专注度监控系统...")

    # 启动EEG数据采集线程（如果可用）
    if eeg_available:
        print("启动EEG数据采集线程...")
        thread1 = threading.Thread(target=EEG.f1, daemon=True)
        thread2 = threading.Thread(target=EEG.f2, daemon=True)
        thread1.start()
        thread2.start()
        print("EEG数据采集线程启动成功")

        # 等待线程初始化
        time.sleep(1)
        print(f"初始EEG值 - 小车1: {EEG.Attention_1}, 小车2: {EEG.Attention_2}")
    else:
        print("使用模拟数据模式")

    if tk_available:
        print("使用GUI模式")
        try:
            print("尝试创建主窗口...")
            root = tk.Tk()
            print("创建主窗口成功")

            print("尝试创建监控实例...")
            app = CarAttentionMonitor(root)
            print("创建监控实例成功")

            print("添加状态标签成功")

            if gpio_initialized:
                try:
                    GPIO.output(STBY, GPIO.LOW)  # 停止
                    print("GPIO初始化成功")
                except Exception as e:
                    print(f'GPIO控制失败: {e}')

            print("启动主循环...")
            # 正常启动，不自动开启监控
            root.mainloop()

            print("主循环结束")

            if gpio_initialized:
                try:
                    GPIO.output(STBY, GPIO.LOW)  # 停止
                except Exception as e:
                    print(f'GPIO控制失败: {e}')
        except Exception as e:
            print(f"GUI模式运行失败: {e}")
            import traceback
            traceback.print_exc()
            # 切换到命令行模式
            print("切换到命令行模式...")
            print("小车专注度监控系统 - 命令行模式")
            print("系统已就绪，按 Ctrl+C 退出")

            try:
                for i in range(5):
                    if eeg_available:
                        print(f"小车1专注度: {EEG.Attention_1}, 小车2专注度: {EEG.Attention_2}")
                    else:
                        att1 = random.randint(0, 99)
                        att2 = random.randint(0, 99)
                        print(f"小车1专注度: {att1}, 小车2专注度: {att2}")
                    time.sleep(1)
                print("命令行模式测试完成")
            except KeyboardInterrupt:
                print("系统已退出")
                if gpio_initialized:
                    try:
                        GPIO.output(STBY, GPIO.LOW)
                    except Exception as e:
                        print(f'GPIO控制失败: {e}')
    else:
        # 命令行模式
        print("小车专注度监控系统 - 命令行模式")
        print("系统已就绪，按 Ctrl+C 退出")

        try:
            while True:
                if eeg_available:
                    print(f"小车1专注度: {EEG.Attention_1}, 小车2专注度: {EEG.Attention_2}")
                else:
                    att1 = random.randint(0, 99)
                    att2 = random.randint(0, 99)
                    print(f"小车1专注度: {att1}, 小车2专注度: {att2}")
                time.sleep(1)
        except KeyboardInterrupt:
            print("系统已退出")
            if gpio_initialized:
                try:
                    GPIO.output(STBY, GPIO.LOW)
                except Exception as e:
                    print(f'GPIO控制失败: {e}')
