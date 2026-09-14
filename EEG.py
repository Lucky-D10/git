import RPi.GPIO as GPIO
import serial
import threading
import time
import logging
from queue import Queue

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('EEGSystem')

# PWM波
pwm_pin_1 = 2             #PWMA  2
pwm_pin_2 = 11            #PWMB  11
AIN1=4
AIN2=3
BIN1=10
BIN2=9
STBY=17  # 定义STBY引脚

# 初始化GPIO
try:
    GPIO.setmode(GPIO.BCM)   #定义树莓派gpio引脚以BCM方式编号
    GPIO.setup(pwm_pin_1,GPIO.OUT)  #使能gpio口为输出
    pwm_1 = GPIO.PWM(pwm_pin_1,10000)   #定义pwm输出频率
    GPIO.setup(pwm_pin_2,GPIO.OUT)  
    pwm_2 = GPIO.PWM(pwm_pin_2,10000)   
    pwm_1.start(100) # 启动PWM，初始占空比为0
    pwm_2.start(100)
    GPIO.setup(AIN1,GPIO.OUT)
    GPIO.setup(AIN2,GPIO.OUT)
    GPIO.setup(BIN1,GPIO.OUT)
    GPIO.setup(BIN2,GPIO.OUT)
    GPIO.setup(STBY,GPIO.OUT)  # 初始化STBY引脚
    GPIO.output(STBY, GPIO.LOW)  # 初始状态为关闭
    logger.info("GPIO初始化完成")
except Exception as e:
    logger.error(f"GPIO初始化失败: {e}")

# 串口初始化
ser_1 = None
ser_2 = None

# 专注度数据
Attention_1 = 0
Attention_2 = 0

# 线程安全队列
data_queue_1 = Queue()
data_queue_2 = Queue()

# 全局运行状态标志
running = True

# 专注度阈值配置
LOW_FOCUS_THRESHOLD = 40
MEDIUM_FOCUS_THRESHOLD = 70
HIGH_FOCUS_THRESHOLD = 90

def load_usart():
    """初始化串口连接"""
    global ser_1, ser_2
    success = False
    try:
        # 尝试连接第一个设备
        try:
            ser_1 = serial.Serial('/dev/ttyUSB0', 57600, timeout=1)
            logger.info('成功连接设备1: /dev/ttyUSB0')
            success = True
        except Exception as e:
            logger.warning(f'连接设备1失败: {e}')
            ser_1 = None
        
        # 尝试连接第二个设备
        try:
            ser_2 = serial.Serial('/dev/ttyUSB1', 57600, timeout=1)
            logger.info('成功连接设备2: /dev/ttyUSB1')
            success = True
        except Exception as e:
            logger.warning(f'连接设备2失败: {e}')
            ser_2 = None
        
        if success:
            logger.info('串口加载完成')
        else:
            logger.warning('未连接到任何设备')
        
        return success
    except Exception as e:
        logger.error(f'串口加载失败: {e}')
        try:
            if ser_1 is not None:
                ser_1.close()
            if ser_2 is not None:
                ser_2.close()
        except Exception as i:
            logger.error(f'关闭串口失败: {i}')
        return False

def read_data(ser, queue, device_id):
    """读取单个设备的EEG数据"""
    buffer = bytearray()
    while running:
        try:
            if ser is not None and ser.is_open:
                if ser.in_waiting:
                    buffer.extend(ser.read(ser.in_waiting))
                    while len(buffer) >= 36:
                        header_index = buffer.find(b'\xaa\xaa\x20\x02')
                        if header_index == -1 or header_index + 35 >= len(buffer):
                            break
                        try:
                            # 解析专注度数据
                            attention = buffer[header_index + 32]
                            if 0 <= attention <= 100:
                                if attention == 100:
                                    attention = 99
                                queue.put(attention)
                                logger.debug(f"设备{device_id}读取到专注度: {attention}")
                        except Exception as e:
                            logger.error(f"解析数据失败: {e}")
                        buffer = buffer[header_index + 4:]
                time.sleep(0.05)  # 减少CPU占用
            else:
                time.sleep(1)  # 串口未连接，等待重连
        except Exception as e:
            logger.error(f"读取数据失败: {e}")
            time.sleep(1)

def process_data():
    """处理队列中的数据并更新全局专注度值"""
    global Attention_1, Attention_2
    while running:
        try:
            # 处理设备1的数据
            if not data_queue_1.empty():
                Attention_1 = data_queue_1.get()
            
            # 处理设备2的数据
            if not data_queue_2.empty():
                Attention_2 = data_queue_2.get()
            
            time.sleep(0.01)
        except Exception as e:
            logger.error(f"处理数据失败: {e}")
            time.sleep(0.1)

def gears(pwm, attention):
    """根据专注度设置PWM档位"""
    # 挡位 1:70   2：66   3：58
    if attention <= 0:
        pwm.ChangeDutyCycle(100)
    elif attention <= LOW_FOCUS_THRESHOLD:
        pwm.ChangeDutyCycle(70)
    elif attention <= MEDIUM_FOCUS_THRESHOLD:
        pwm.ChangeDutyCycle(66)
    elif attention <= 100:
        pwm.ChangeDutyCycle(58)

def cleanup():
    """清理资源"""
    global ser_1, ser_2, running
    running = False
    
    logger.info("正在清理资源...")
    
    # 停止PWM
    try:
        pwm_1.stop()
        pwm_2.stop()
        logger.info("PWM已停止")
    except Exception as e:
        logger.error(f'停止PWM失败: {e}')
    
    # 关闭串口
    try:
        if ser_1 is not None:
            ser_1.close()
        if ser_2 is not None:
            ser_2.close()
        logger.info("串口已关闭")
    except Exception as e:
        logger.error(f'关闭串口失败: {e}')
    
    # 清理GPIO
    try:
        GPIO.output(STBY, GPIO.LOW)
        GPIO.cleanup()
        logger.info("GPIO已清理")
    except Exception as e:
        logger.error(f'清理GPIO失败: {e}')
    
    logger.info("资源清理完成")

def f1():
    """数据采集线程"""
    global ser_1, ser_2, running
    # 初始化串口
    while running:
        if load_usart():
            break
        logger.info("尝试重新连接串口...")
        time.sleep(2)
    
    # 启动数据读取线程
    threads = []
    
    # 只启动已连接设备的线程
    if ser_1 is not None and ser_1.is_open:
        thread1 = threading.Thread(target=read_data, args=(ser_1, data_queue_1, 1), daemon=True)
        thread1.start()
        threads.append(thread1)
        logger.info("设备1数据读取线程已启动")
    
    if ser_2 is not None and ser_2.is_open:
        thread2 = threading.Thread(target=read_data, args=(ser_2, data_queue_2, 2), daemon=True)
        thread2.start()
        threads.append(thread2)
        logger.info("设备2数据读取线程已启动")
    
    # 启动数据处理线程
    thread3 = threading.Thread(target=process_data, daemon=True)
    thread3.start()
    threads.append(thread3)
    logger.info("数据处理线程已启动")
    
    logger.info("数据采集线程已启动")
    
    while running:
        try:
            # 定期检查串口连接状态
            if (ser_1 is None or not ser_1.is_open) or (ser_2 is None or not ser_2.is_open):
                logger.warning("串口连接断开，尝试重连...")
                load_usart()
            time.sleep(5)
        except Exception as e:
            logger.error(f"数据采集线程错误: {e}")
            time.sleep(1)

def f2():
    """电机控制线程"""
    global running, Attention_1, Attention_2
    while running:
        try:
            # 设置电平
            GPIO.output(AIN1, GPIO.HIGH)
            GPIO.output(AIN2, GPIO.LOW)
            GPIO.output(BIN1, GPIO.LOW)
            GPIO.output(BIN2, GPIO.HIGH)
        except KeyboardInterrupt:
            # 清理GPIO设置
            cleanup()
            break
        except Exception as e:
            logger.error(f'GPIO控制失败: {e}')

        # 均衡化控制
        if Attention_1 == 0:
            pwm_1.ChangeDutyCycle(0)
        else:
            pwm_1.ChangeDutyCycle(25 + Attention_1 / 4)
        
        if Attention_2 == 0:
            pwm_2.ChangeDutyCycle(0)
        else:
            pwm_2.ChangeDutyCycle(25 + Attention_2 / 4)
        
        time.sleep(0.01)