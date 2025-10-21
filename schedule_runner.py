import schedule
import time
import subprocess
import logging
from datetime import datetime

# 配置日志前清除所有已存在的处理器
logger = logging.getLogger()
if logger.hasHandlers():
    logger.handlers.clear()

# 配置日志（记录程序运行状态，方便排查问题）
logging.basicConfig(
    filename='schedule_log.log',  # 日志文件
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def run_program(program_path):
    """通用函数：运行指定的Python程序"""
    try:
        # 调用外部Python程序（使用subprocess确保独立运行）
        # 第一个参数是Python解释器路径，第二个是程序路径
        result = subprocess.run(
            ["python", program_path],  # 若用python3需替换为"python3"
            check=True,  # 若程序运行出错（返回非0状态码），会触发异常
            capture_output=True,  # 捕获程序输出
            text=True,  # 输出转为字符串（而非字节）
            encoding = 'utf-8'  # 强制用utf-8解码输出
        )
        logging.info(f"程序 {program_path} 运行成功！输出：{result.stdout}")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"程序 {program_path} 运行失败！错误：{e.stderr}")
        return False
    except Exception as e:
        logging.error(f"调用程序 {program_path} 时发生异常：{str(e)}")
        return False

# 定义两个程序的路径（请替换为你的实际路径）
PROGRAM_A_PATH = "D:/Pycharmcode/test/submit_order.py"  # 程序A的绝对路径
PROGRAM_B_PATH = "D:/Pycharmcode/test/download.py"  # 程序B的绝对路径

# 设定定时任务
def schedule_tasks():
    # 每天8:00运行程序A
    schedule.every().day.at("22:00").do(
        run_program,  # 要执行的函数
        program_path=PROGRAM_A_PATH  # 传递参数（程序A的路径）
    )
    logging.info(f"已设置定时任务：每天08:00运行 {PROGRAM_A_PATH}")

    # 每天16:30运行程序B
    schedule.every().day.at("22:07").do(
        run_program,
        program_path=PROGRAM_B_PATH
    )
    logging.info(f"已设置定时任务：每天16:30运行 {PROGRAM_B_PATH}")

    # 循环检查并执行任务
    logging.info("调度程序启动，开始等待定时任务...")
    while True:
        schedule.run_pending()  # 运行所有到期的任务
        time.sleep(60)  # 每60秒检查一次（减少CPU占用）

if __name__ == "__main__":
    schedule_tasks()
