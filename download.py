# region导入所需库
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException,
    ElementClickInterceptedException, StaleElementReferenceException
)
from selenium.webdriver.common.keys import Keys
import ddddocr  # 用于验证码识别
import time
import os
from PIL import Image
import io
import logging
import configparser
from pathlib import Path
import traceback
from webdriver_manager.chrome import ChromeDriverManager  # 自动管理chromedriver
from ftplib import FTP
from urllib.parse import urlparse
from config_handler import ConfigHandler  # 关键：替换原有内部ConfigHandler
import sys
from bs4 import BeautifulSoup
import re
import requests
from download_http_file import download_http_file
# endregion

# region基础日志配置
log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "download.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_path, encoding='utf-8', mode='a'),
        logging.StreamHandler(sys.stdout)
    ],
    force=True
)

logger = logging.getLogger(__name__)
# 测试日志写入
logger.info("=== 日志系统初始化测试 ===")
# endregion

# 带进度显示的FTP下载函数（已整合重试逻辑）
def download_ftp_with_progress(ftp_url, save_dir, timeout=30, idle_timeout=60, max_retry=3):
    # region解析文件名+拼接下载路径
    """

    :param ftp_url:
    :param save_dir:
    :param timeout:若 30 秒内无法与 FTP 服务器,会抛出超时异常，触发重试。  若 30 秒内无任何数据交互
    :param idle_timeout: 控制 文件传输过程中的 “空闲等待时间”，避免下载中途卡住
    :param max_retry:
    :return:
    """
    parsed_url = urlparse(ftp_url)
    filename = os.path.basename(parsed_url.path)
    save_path = os.path.join(save_dir, filename)
    os.makedirs(save_dir, exist_ok=True)  # 确保保存目录存在
    # endregion
    # region重试下载循环
    for retry in range(max_retry):
        logger.info(f"[FTP下载] 第{retry+1}/{max_retry}次尝试：文件={filename}，URL={ftp_url}")
        try:
            # 1. FTP连接配置
            # ftp://A202511071509111775:r2u__Rgh@ftp.nsmc.org.cn/FY3D_MERSI_GBAL_L1_20251105_1935_1000M_MS.HDF
            username = parsed_url.username if parsed_url.username else 'anonymous'  # A202511071509111775
            password = parsed_url.password if parsed_url.password else ''  # r2u__Rgh
            host = parsed_url.hostname   # 主机名 ftp.nsmc.org.cn
            path = parsed_url.path  # 文件路径 /FY3D_MERSI_GBAL_L1_20251105_1935_1000M_MS.HDF，即文件在服务器上的位置

            # 2. 建立FTP连接
            ftp = FTP(host, timeout=timeout)
            ftp.login(username, password)
            ftp.voidcmd('TYPE I')  # 二进制传输模式
            ftp.sock.settimeout(timeout)  # socket超时设置
            file_size = ftp.size(path)  # 获取文件总大小
            downloaded_size = 0

            # 3. 进度监控和超时监控变量
            last_print_time = time.time()
            print_interval = 2  # 最少打印时间间隔
            last_progress = -0.1
            min_progress_change = 1  # 最小输出变化百分比
            last_data_time = time.time()  # 最后一次接收数据的时间
            download_aborted = False
            last_actual_progress = 0.0  # 跟踪真正的进度，判断是否真的停滞

            # 4. 启动空闲超时监控线程
            import threading

            def monitor_idle():
                nonlocal download_aborted
                while not download_aborted:
                    time.sleep(5)  # 每5秒检查一次
                    if time.time() - last_data_time > idle_timeout:
                        logger.warning(f"[FTP下载] 超时警告：{idle_timeout}秒未接收数据，中断下载")
                        download_aborted = True
                        ftp.abort()  # 强制中断FTP连接

            monitor_thread = threading.Thread(target=monitor_idle)
            monitor_thread.daemon = True
            monitor_thread.start()

            # 5. 执行下载（带进度回调）
            with open(save_path, 'wb') as file:
                def callback(data):
                    nonlocal downloaded_size, last_print_time, last_progress, last_data_time,last_actual_progress
                    file.write(data)
                    downloaded_size += len(data)
                    last_data_time = time.time()  # 每次接收数据更新时间

                    # 进度打印（控制台+日志）
                    if file_size > 0:
                        current_progress = (downloaded_size / file_size) * 100
                        current_time = time.time()  # 当前时间
                        # 停滞警告（10秒无进度更新）
                        if (current_time - last_print_time > 10) and (current_progress < 99.9):
                            if abs(current_progress - last_actual_progress) < 0.1:
                                logger.warning(
                                    f"[FTP下载] 停滞警告：{filename} 当前进度{current_progress:.2f}%（10秒无实质更新）")
                                # 更新上次实际进度
                            last_actual_progress = current_progress
                        # 进度更新（每2秒或进度变化≥5%时打印）
                        if (current_time - last_print_time >= print_interval) and \
                                (current_progress - last_progress >= min_progress_change):
                            print(f"\r下载进度: {filename} {current_progress:.2f}%", end='', flush=True)
                            logger.info(f"[FTP下载] 进度：{filename} {current_progress:.2f}%")
                            last_print_time = current_time
                            last_progress = current_progress
                            last_actual_progress = current_progress  # 同步更新实际进度

                ftp.retrbinary(f'RETR {path}', callback)

            # 6. 下载完成后清理
            download_aborted = True
            monitor_thread.join()  # 等待监控线程退出

            # 7. 验证文件完整性
            local_file_size = os.path.getsize(save_path)
            if file_size > 0 and local_file_size != file_size:
                raise ValueError(f"文件不完整：服务器大小{file_size}字节，本地大小{local_file_size}字节")

            # 8. 输出完成信息
            print(f"\r下载进度: {filename} 100.00%", end='', flush=True)
            print()
            ftp.quit()
            logger.info(f"[FTP下载] 成功：{filename}（大小：{local_file_size:,}字节）")
            return True

        except Exception as e:
            # 异常处理：清理不完整文件 + 重试判断
            logger.error(f"[FTP下载] 第{retry+1}次失败：{str(e)[:200]}")
            if os.path.exists(save_path):
                os.remove(save_path)
                logger.warning(f"[FTP下载] 已清理不完整文件：{save_path}")
            # 关闭FTP连接（避免资源泄露）
            try:
                ftp.quit()
            except:
                pass
            # 还有重试次数就等待后重试
            if retry < max_retry - 1:
                wait_time = 3
                logger.warning(f"[FTP下载] 剩余{max_retry - retry - 1}次重试，{wait_time}秒后重试...")
                time.sleep(wait_time)
                continue
            # 所有重试失败
            logger.error(f"[FTP下载] 所有{max_retry}次尝试均失败：{filename}")
            return False
    # endregion

def get_order_status(browser, order_number):
    # region 根据订单号 查找订单状态
    """
    根据订单号查找对应行，并返回订单状态
    :param browser: SatelliteBrowser 实例（包含 webdriver）
    :param order_number: 要查询的订单号（如 "C202510300255033490"）
    :return: 订单状态（如 "准备中"）或 None（未找到时）
    """
    try:
        # 定位tbody
        tbody = browser.safe_find_element(By.ID, "displayOrderBody")  # 查找页面中 ID 为displayOrderBody的表格主体元素（<tbody>标签）
        if not tbody:
            return None

        # 遍历所有行
        rows = tbody.find_elements(By.TAG_NAME, "tr")
        for row in rows:
            # 定位该行的“订单号”列（第一个td）
            order_td = row.find_element(By.CSS_SELECTOR, "td:nth-child(1)")
            if order_td.text.strip() == order_number:
                # 找到匹配的行，定位“状态”列（第4个td）
                status_td = row.find_element(By.CSS_SELECTOR, "td:nth-child(4)")
                return status_td.text.strip()

        # 遍历完所有行未找到匹配订单号
        return None
    except Exception as e:
        logger.error(f"查询订单状态失败: {str(e)}")
        return None
    # endregion


# 文件下载监控处理器
class TxtFileHandler(FileSystemEventHandler):
    """监控下载文件夹，捕获txt文件（包括临时文件重命名）"""
    def __init__(self):
        self.new_txt_file = None   # 存储最终识别到的 .txt 文件路径
        self.event_detected = False  # 标记是否检测到有效的目标文件（通常是 .txt 文件）
        self.tmp_files = set()  # 记录所有下载过程中产生的临时文件路径（如 .tmp、.crdownload 等浏览器临时文件）。  集合

    def on_created(self, event):
        # region 监控文件创建
        if not event.is_directory:  # 避免无关目录干扰 即 如果不是目录才确定是文件
            logger.info(f"文件创建: {event.src_path}")
            # 记录临时文件
            if event.src_path.endswith(('.tmp', '.crdownload')):
                self.tmp_files.add(event.src_path)  # 若符合临时文件特征，就将其路径添加到 self.tmp_files 集合中，用于后续跟踪。
            # 直接捕获txt文件
            elif event.src_path.endswith('.txt'):
                self.new_txt_file = event.src_path
                self.event_detected = True
        # endregion

    def on_moved(self, event):
        # region跟踪所有重命名步骤，更新临时文件记录
        if not event.is_directory:
            logger.info(f"文件重命名: {event.src_path} → {event.dest_path}")

            # 1. 如果原文件是临时文件，先移除旧路径
            if event.src_path in self.tmp_files:
                self.tmp_files.remove(event.src_path)

            # 2. 若目标文件是中间临时文件（.crdownload），记录为新临时文件
            if event.dest_path.endswith('.crdownload'):
                logger.info(f"记录中间临时文件: {event.dest_path}")
                self.tmp_files.add(event.dest_path)

            # 3. 若目标文件是最终的.txt，标记为检测到
            elif event.dest_path.endswith('.txt'):
                logger.info(f"检测到最终txt文件: {event.dest_path}")
                self.new_txt_file = event.dest_path
                self.event_detected = True
        # endregion

    def read_file_content(self):
        # region读取文本文件内容（优化版：增加存在性校验和编码容错）
        if not self.new_txt_file:
            logger.error("未检测到有效的txt文件路径")
            return None

        # 二次确认文件存在且是文件（非目录）
        if not os.path.exists(self.new_txt_file) or not os.path.isfile(self.new_txt_file):
            logger.error(f"文件不存在或不是有效文件: {self.new_txt_file}")
            return None

        # 尝试多种编码读取（应对不同编码的txt文件）
        encodings = ['utf-8', 'gbk', 'gb2312', 'latin-1']
        for encoding in encodings:
            try:
                with open(self.new_txt_file, 'r', encoding=encoding) as f:
                    content = f.read()
                logger.info(f"成功读取txt内容（编码：{encoding}，{len(content)}字符）")
                return content
            except UnicodeDecodeError:
                continue  # 编码错误则尝试下一种编码
            except Exception as e:
                logger.error(f"读取文件时出错: {str(e)}")
                return None

        # 所有编码都尝试失败
        logger.error(f"无法解析文件编码，文件路径: {self.new_txt_file}")
        return None
        # endregion

# 浏览器操作类
class SatelliteBrowser:
    def __init__(self, config):
        self.config = config
        self.driver = None
        self.wait = None
        self.timeout = config.get_timeout()
        self.retry_attempts = config.get_retry_attempts()
        self.ocr = ddddocr.DdddOcr()
        self.download_dir = config.get_download_dir()  # 下载目录
        self.listen_dir = config.get_listen_dir()

    def init_browser(self):
        # region初始化浏览器
        try:
            # 创建设置浏览器对象
            chrome_options = Options()
            # 基本配置
            chrome_options.page_load_strategy = 'eager'  # 页面加载策略设置为"急切"模式  如果实在不行就改成normal试一下
            chrome_options.add_argument('--disable-background-timer-throttling')  # 禁用后台标签页的定时器节流
            chrome_options.add_argument('--disable-renderer-backgrounding')  # 禁用渲染进程的后台降级
            chrome_options.add_argument('--no-sandbox')  # 禁用 Chrome 的沙箱模式
            chrome_options.add_argument('--window-size=1920,1080')  # 指定浏览器窗口的初始尺寸为 1920x1080 像素
            chrome_options.add_argument('--disable-gpu')  # 禁用 GPU 加速
            chrome_options.add_argument('--disable-dev-shm-usage')  # 禁用 /dev/shm 临时目录的使用（Linux 系统特有）
            chrome_options.add_argument('--ignore-certificate-errors')  # 忽略 SSL 证书错误。
            chrome_options.add_experimental_option('detach', True)  # 保持浏览器打开状态,让Chrome浏览器在自动化脚本执行完毕后不自动关闭
            # 配置Chrome选项中的下载偏好
            prefs = {
                "download.prompt_for_download": False,  # 禁用下载弹窗（核心设置）
                "download.directory_upgrade": True,  # 允许目录升级  允许浏览器自动创建不存在的下载目录
                "plugins.always_open_pdf_externally": True,  # 辅助设置（避免其他文件类型弹窗）
                "profile.default_content_settings.popups": 0  # 禁用弹窗
            }
            chrome_options.add_experimental_option("prefs", prefs)  # 应用偏好设置

            # 设置Chrome驱动
            driver_path = self.config.get_chrome_driver_path()
            if driver_path and os.path.exists(driver_path):
                service = Service(driver_path)  # 用于管理 Chrome驱动程序的进程
            else:
                service = Service(ChromeDriverManager().install())   # 自动下载并使用合适版本的chromedriver
                logger.info("使用自动管理的ChromeDriver")

            # 创建并启动浏览器    设置等待
            self.driver = webdriver.Chrome(service=service, options=chrome_options)  # 传入自定义的Service对象，chrome_options对象
            self.driver.implicitly_wait(self.timeout)  # 设置隐式等待
            self.wait = WebDriverWait(self.driver, self.timeout)  # 创建显式等待对象
            logger.info("浏览器初始化成功")
            return True

        except Exception as e:
            logger.error(f"浏览器初始化失败: {str(e)}")
            #logger.error(traceback.format_exc())
            return False
        # endregion

    def safe_find_element(self, by, value, retry=0):
        # region 安全查找元素，带重试机制
        try:
            return self.wait.until(EC.presence_of_element_located((by, value)))  # 使用创建的显式等待对象 self.wait等待元素「出现」

        except (TimeoutException, StaleElementReferenceException) as e:  # 捕获两种异常：显式等待超时和元素已失效（如页面刷新导致元素被重新渲染）
            if retry < self.retry_attempts:
                logger.warning(f"查找元素失败，重试 {retry + 1}/{self.retry_attempts} - {by}: {value}")
                time.sleep(1)
                return self.safe_find_element(by, value, retry + 1)
            logger.error(f"多次尝试后仍无法找到元素: {by}: {value}")
            # logger.error(traceback.format_exc())
            return None
        # endregion

    # 旧的safe_click_element
    # def safe_click_element(self, by, value, retries=3, wait=1):
    #
    #     """
    #     Args:
    #     by: 元素定位方式（如 By.ID、By.XPATH、By.CSS_SELECTOR 等）
    #     value: 定位方式对应的值（如 ID 属性值、XPath 表达式等）
    #     retries: 重试次数
    #     """
    #     for i in range(retries):
    #         try:
    #             # 显示等待这个元素可以被点击
    #             # element = WebDriverWait(self.driver, self.retry_attempts).until(EC.element_to_be_clickable((by, value))) ！！！
    #             element = WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((by, value))) # 这个10 需要改
    #             element.click()
    #             time.sleep(3)    # ！！！
    #             return True
    #         except Exception as e:
    #             logger.warning(f"点击元素失败，重试 {i + 1}/{retries} - {by}: {value}")
    #             time.sleep(wait)
    #     # 尝试JS点击
    #     try:
    #         element = self.driver.find_element(by, value)
    #         self.driver.execute_script("arguments[0].click();", element)
    #         logger.info(f"使用JS点击成功--{by}: {value}")
    #         return True
    #     except Exception as e:
    #         logger.error(f"多次尝试后仍无法点击元素--{by}: {value}")
    #         # logger.error(e)
    #         return False

    def safe_click_element(self, by, value, retries=3, wait=1):
        # region 带重试机制的显式等待并点击元素
        """
        Args:
        by: 元素定位方式（如 By.ID、By.XPATH、By.CSS_SELECTOR 等）
        value: 定位方式对应的值（如 ID 属性值、XPath 表达式等）
        retries: 重试次数
        """
        for i in range(retries):
            try:
                # 显示等待这个元素可以被点击
                # element = WebDriverWait(self.driver, self.retry_attempts).until(EC.element_to_be_clickable((by, value))) ！！！
                element = WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((by, value))) # 这个10 需要改
                element.click()
                time.sleep(3)    # ！！！
                return True
            except Exception as e:
                logger.warning(f"点击元素失败，重试 {i + 1}/{retries} - {by}: {value}")
                time.sleep(wait)
        # 尝试JS点击
        try:
            element = self.driver.find_element(by, value)
            self.driver.execute_script("arguments[0].click();", element)
            logger.info(f"使用JS点击成功--{by}: {value}")
            return True
        except Exception as e:
            logger.error(f"多次尝试后仍无法点击元素--{by}: {value}")
            # logger.error(e)
            return False
        # endregion

    def safe_send_keys(self, by, value, text, retry=0):
        # region 安全输入文本，带重试机制
        try:
            element = self.wait.until(EC.element_to_be_clickable((by, value)))
            element.clear()
            element.send_keys(text)
            logger.info(f"成功输入文本到元素---{text}:{by}: {value}")
            return True
        except (TimeoutException, StaleElementReferenceException) as e:
            if retry < self.retry_attempts:
                logger.warning(f"输入文本失败，重试 {retry + 1}/{self.retry_attempts} - {by}: {value}")
                time.sleep(1)
                return self.safe_send_keys(by, value, text, retry + 1)
            logger.error(f"多次尝试后仍无法输入文本到元素: {by}: {value}")
            # logger.error(traceback.format_exc())
            return False
         #endregion

    def solve_captcha(self, captcha_xpath, retry=0):
        # region解决验证码
        try:
            # 获取验证码图片
            captcha_element = self.safe_find_element(By.XPATH, captcha_xpath)
            if not captcha_element:
                return None

            png_data = captcha_element.screenshot_as_png
            # 识别验证码
            result = self.ocr.classification(png_data)
            logger.info(f"识别到验证码: {result}")
            return result
        except Exception as e:
            if retry < self.retry_attempts:
                logger.warning(f"验证码识别失败，重试 {retry + 1}/{self.retry_attempts}")
                time.sleep(1)
                return self.solve_captcha(captcha_xpath, retry + 1)
            logger.error(f"验证码识别失败: {str(e)}")
            logger.error(traceback.format_exc())
            return None
        # endregion

    def click_and_read_content(self, file_button_locator):
        # region 点击文件按钮并(判断txt生成 以及 新页面)根据结果读取内容 返回
        # 记录点击前的窗口句柄和下载目录状态
        original_window = self.driver.current_window_handle  # 记录当前浏览器窗口的唯一标识（句柄），用于后续在多个窗口之间切换时，能准确回到初始窗口
        start_time = time.time()
        listen_dir = self.listen_dir

        # 初始化文件监控 线程启动
        event_handler = TxtFileHandler()    # 自定义的 文件下载监控处理器
        observer = Observer()  # watchdog 库中创建文件系统监控器实例的核心代码，用于启动一个后台线程来监听指定目录的文件变化（如创建、删除、修改、移动等）。
        observer.schedule(event_handler, listen_dir, recursive=False)  # 请监控 download_dir 目录下的文件变化，当变化时，用 event_handler 中定义的规则来处理这些事件
        observer.start()

        # 等待监控完全启动
        time.sleep(2)

        try:
            # 点击文件按钮
            if not self.safe_click_element(*file_button_locator):
                logger.error("无法点击文件按钮")
                return None

            # 等待操作结果
            timeout = 30
            while time.time() - start_time < timeout:
                # 检查是否有新txt文件下载
                if event_handler.event_detected:
                    observer.stop()
                    observer.join()
                    logger.info("捕获到直接下载的TXT文件")
                    return {
                        'type': 'file',
                        'content': event_handler.read_file_content(),  # 返回txt的内容  ！！！ 冗余 应该需要改
                        'path': event_handler.new_txt_file,  # 返回txt文本的路径
                        'raw_content': event_handler.read_file_content()  # 返回txt的内容，和上面的一样
                    }

                # 检查是否打开了新窗口
                if len(self.driver.window_handles) > 1:  # 判断当前浏览器是否打开了多个窗口
                    # 切换到新窗口
                    for window_handle in self.driver.window_handles:
                        if window_handle != original_window:
                            self.driver.switch_to.window(window_handle)  # 切换到新窗口
                            new_window_url = self.driver.current_url   # 获取新窗口的URL
                            logger.info(f"检测到新窗口，它的URL为: {new_window_url}")
                            # 若新窗口是HTML页面，读取页面内容
                            logger.info("新窗口是HTML页面，读取页面源码")
                            page_content = self.driver.page_source   # 读取新窗口的完整HTML源码
                            logger.info(f"--------HTMl页面内容:{page_content}")
                            # 定位<pre>标签并获取文本
                            pre_element = self.driver.find_element(By.TAG_NAME, 'pre')
                            raw_text = pre_element.text.strip()  # 得到包含链接的文本
                            logger.info(f"--------真实的页面内容:{raw_text}")
                            observer.stop()
                            observer.join()
                            return {
                                'type': 'page',
                                'content': page_content,  # 完整HTML源码
                                'url': new_window_url,   # 新窗口的URL
                                'raw_content': page_content,   # 原始HTML（与content一致，可能用于备份）  ！！！
                                'raw_text': raw_text  # <pre>标签中的纯文本（核心数据，如链接列表）
                            }

                time.sleep(1)  # 降低检查频率，减少资源占用

            # 超时处理
            logger.warning("超时未检测到下载或页面跳转")
            observer.stop()
            observer.join()
            return None

        except Exception as e:
            logger.error(f"点击并读取内容时出错: {str(e)}")
            observer.stop()
            observer.join()
            return None
        # endregion

# 主程序类
class SatelliteDataDownloader:
    def __init__(self):
        self.config = ConfigHandler()
        self.browser = SatelliteBrowser(self.config)
        self.user_info = self.config.get_user_info()
        self.base_url = 'https://satellite.nsmc.org.cn/DataPortal/cn/home/index.html'

        # 将查看订单的页面定为主界面
        self.main_page_config = {
            'url_keyword': '/myOrder',  # 我的订单页面URL特征（根据实际URL调整，比如URL包含/myOrder）
            'identifier': (By.ID, 'displayOrderBody')  # 我的订单页面唯一元素（订单表格tbody，必存在）
        }
        self.main_window_handle = None  # 存储「我的订单」页面的主窗口句柄
        self.main_page_url = None  # 存储实际的我的订单页面URL（跳转后记录）

        # 页面元素定位符
        self.locators = {
            # 登录
            'login_button': (By.XPATH, '//*[@id="common-login"]'),  # 点击登录
            'username_input': (By.XPATH, '//*[@id="inputUserNameCN"]'),  # 输入用户名
            'password_input': (By.XPATH, '//*[@id="inputPasswordCN"]'),  # 输入密码
            'captcha_image': (By.XPATH, '//*[@id="logincn"]/div[2]/div/div/div[2]/div[2]/div[4]/div/img'),  # 验证码图像
            'captcha_input': (By.XPATH, '//*[@id="inputValidateCodeCN"]'),  # 输入验证码
            'submit_login': (By.XPATH, '//*[@id="logincn"]/div[2]/div/div/div[2]/div[2]/div[6]/button'),  # 提交登录

            # 点击我的订单，跳转我的订单页面
            'my_order': (By.XPATH, '//*[@id="u-myorder"]'),  # 点击我的订单

            # 表单里面的文件按钮
            'file_buttons': [
                (By.XPATH, '//*[@id="displayOrderBody"]/tr[1]/td[8]/a/span'),  # 第1个按钮
                (By.XPATH, '//*[@id="displayOrderBody"]/tr[2]/td[8]/a/span'),  # 第2个按钮
                (By.XPATH, '//*[@id="displayOrderBody"]/tr[3]/td[8]/a/span'),  # 第3个按钮
                (By.XPATH, '//*[@id="displayOrderBody"]/tr[3]/td[8]/a/span'),  # 第4个按钮
                (By.XPATH, '//*[@id="displayOrderBody"]/tr[3]/td[8]/a/span'),  # 第5个按钮
                (By.XPATH, '//*[@id="displayOrderBody"]/tr[3]/td[8]/a/span'),  # 第6个按钮
                (By.XPATH, '//*[@id="displayOrderBody"]/tr[3]/td[8]/a/span'),  # 第7个按钮
                (By.XPATH, '//*[@id="displayOrderBody"]/tr[3]/td[8]/a/span'),  # 第8个按钮
                (By.XPATH, '//*[@id="displayOrderBody"]/tr[3]/td[8]/a/span'),  # 第9个按钮
                (By.XPATH, '//*[@id="displayOrderBody"]/tr[3]/td[8]/a/span'),  # 第10个按钮
            ]
        }

    def run(self,content):
        # region运行主程序
        try:
            # region 初始化浏览器+打开网站+执行登录流程+点击我的订单
            # 初始化浏览器
            if not self.browser.init_browser():
                logger.error("无法初始化浏览器，程序退出")
                sys.exit(1)  # 1表示浏览器初始化失败

            # 打开网站
            logger.info("[流程]打开风云卫星数据网站......")
            self.browser.driver.get(self.base_url)
            time.sleep(2)  # 初始加载等待

            # 执行登录流程
            if not self._login():
                logger.error("登录失败，程序退出")
                sys.exit(2)  # 2表示登录失败

            # 登录成功后， 点击我的订单  跳转页面
            if not self.browser.safe_click_element(*self.locators['my_order']):
                logger.error("无法点击'我的订单'，程序终止")
                if self.browser.driver:
                    self.browser.driver.quit()
                sys.exit(3)  # 3 表示导航失败
            # endregion

            # 等待跳转完成，并记录主窗口句柄和URL
            time.sleep(3)  # 等待页面跳转加载
            self.main_window_handle = self.browser.driver.current_window_handle  # 记录当前窗口（我的订单页面）
            self.main_page_url = self.browser.driver.current_url  # 记录我的订单页面实际URL
            logger.info(
                f"[流程]成功跳转至我的订单页面，主窗口句柄：{self.main_window_handle}，URL：{self.main_page_url}")

            # region 遍历每个订单号检查状态
            for order_number in content:
                print(f"正在查询订单号：{order_number}")
                order_status = get_order_status(self.browser, order_number)

                if order_status:
                    print(f"订单 {order_number} 的状态是：{order_status}")
                    # 若当前订单状态为“准备中”，立即退出程序
                    if order_status == "准备中":
                        logger.info(f"[流程]订单 {order_number} 订单状态为【准备中】，停止程序")
                        # 关闭浏览器并退出
                        if self.browser.driver:
                            self.browser.driver.quit()
                        sys.exit(0)  # 正常退出（表示需要重试）  ！！！
                else:
                    logger.warning(f"未找到订单 {order_number}")

            # 所有订单均查询完毕，且均未出现“准备中”状态
            logger.info("[流程]所有订单均处于准备成功状态，执行数据下载")

            # 根据txt行数（content长度）循环点击对应按钮
            line_count = len(content)  # 获取txt有效行数
            logger.info(f"[流程]共有{line_count}个订单，将执行{line_count}次下载操作......")
            # endregion

            # region 循环下载各个订单
            for i in range(line_count):  # ！！！有问题
                # 检查是否有对应的按钮定位符（避免索引越界）
                if i >= len(self.locators['file_buttons']):
                    logger.error(f"未定义第{i + 1}个按钮的定位符，请补充locators['file_buttons']")
                    continue

                # 获取当前行对应的按钮定位符
                current_button = self.locators['file_buttons'][i]
                logger.info(f"[流程]开始第{i + 1}/{line_count}次下载，点击按钮：{current_button}")

                # 点击按钮并处理结果
                result = self.browser.click_and_read_content(current_button)
                self.process_result(result)

                # 处理完成后返回「我的订单」主页面
                self.back_to_main_page()

                # 刷新页面，确保最新状态
                logger.info(f"[校验]刷新页面，准备校验第{i + 1}个按钮状态...")
                self.browser.driver.refresh()
                time.sleep(4)  # 刷新后等待页面完全加载
                # 2. 校验下一个按钮是否存在（当前循环是第i次，下一次是i+1，但当前需确保本次按钮可点击？修正：当前循环是第i次，需确保当前按钮可点击，避免会话失效）
                # 注意：当前循环处理的是第i个按钮，此处校验的是“当前要点击的按钮”是否存在（因返回主页面+刷新后可能失效）
                try:
                    # 尝试找到当前要点击的按钮（最多等待5秒）
                    WebDriverWait(self.browser.driver, 5).until(
                        EC.presence_of_element_located(current_button)
                    )
                    logger.info(f"[校验]✅ 第{i + 1}个按钮存在，继续执行")
                    # 3. 若能找到按钮，直接继续下一次循环（或当前循环后续逻辑）
                    time.sleep(2)
                    continue
                except TimeoutException:
                    logger.warning(f"[校验]❌ 未找到第{i + 1}个按钮，开始检测登录状态...")

                # 4. 未找到按钮，检测是否需要重新登录（查找“登录”按钮）
                try:
                    # 查找登录按钮（使用已定义的locators['submit_login']）
                    login_btn = self.browser.safe_find_element(*self.locators['submit_login'], retry=1)
                    if login_btn:
                        logger.warning(f"[校验]检测到登录按钮，会话已失效，开始自动重登...")

                        # 5. 执行重登录流程
                        if self._login():
                            logger.info(f"[重登]✅ 登录成功，重新跳转至我的订单页面...")
                            # 6. 重登后再次点击“我的订单”（确保回到订单页）
                            if self.browser.safe_click_element(*self.locators['my_order']):
                                time.sleep(3)  # 等待跳转加载
                                # 7. 再次校验当前按钮是否存在
                                try:
                                    WebDriverWait(self.browser.driver, 5).until(
                                        EC.presence_of_element_located(current_button)
                                    )
                                    logger.info(f"[重登校验]✅ 第{i + 1}个按钮已找到，继续下载...")
                                    time.sleep(2)
                                    continue
                                except TimeoutException:
                                    logger.error(f"[重登校验]❌ 重登后仍未找到第{i + 1}个按钮，跳过该订单")
                                    continue
                        else:
                            logger.error(f"[重登]❌ 重登录失败，跳过该订单")
                            continue
                    else:
                        # 未找到登录按钮，也未找到订单按钮（页面异常）
                        logger.error(f"[校验]❌ 未找到登录按钮和第{i + 1}个按钮，跳过该订单")
                        continue
                except Exception as e:
                    logger.error(f"[校验]检测登录状态/按钮时出错：{str(e)}", exc_info=True)
                    continue

                # 每次操作后等待1-2秒，避免页面未响应
                time.sleep(2)
            # endregion

        except Exception as e:
            logger.error(f"程序运行出错: {str(e)}")
            logger.error(traceback.format_exc())
        finally:
            # 可以根据需要决定是否关闭浏览器
            # if self.browser.driver:
            #     self.browser.driver.quit()
            pass

    # 封装的核心函数：处理读取结果
    def process_result(self, result):
        # region 处理从文件或页面提取的结果，提取并下载HDF链接
        if not result:
            logger.warning("无有效结果可处理")
            return

        save_dir = self.config.get_download_dir()

        # 根据结果类型处理（文件或页面）
        if result['type'] == 'file':
            logger.info("成功获取下载的txt文件内容")
            raw_text = result['raw_content'].strip()
            # 提取HTTP和FTP链接
            http_matches, ftp_matches = self.extract_links(raw_text)
            # 下载链接
            self.download_all_links(
                http_matches, ftp_matches, save_dir
            )
            # 清理临时TXT文件
            if result.get('path') and os.path.exists(result['path']):
                os.remove(result['path'])
                logger.info(f"已清理临时TXT文件：{result['path']}")

        elif result['type'] == 'page':
            logger.info('识别到是页面了，并且拿到了页面内容')
            raw_text = result['raw_text']
            # 提取HTTP和FTP链接
            http_matches, ftp_matches = self.extract_links(raw_text)
            # 下载链接（页面处理不统计成功/失败数，保持原逻辑）
            self.download_all_links(http_matches, ftp_matches, save_dir)
        # endregion

    def extract_links(self, raw_text):
        # region 用正则表达式 在内容中提取多个http 和ftp 的链接
        # 识别HTTP链接
        # http://clouddata.nsmc.org.cn:8089/DATA/FY3/FY3E/MERSI/L1/GEO1K/2025/20251106/FY3E_MERSI_GRAN_L1_20251106_2315_GEO1K_V0.HDF?AccessKeyId=LKI0VZTG4IR1UYTUSXQZ&Expires=1762851421&Signature=8RpriAMBD%2FgFVDlrGjszPcuUspE%3D
        http_pattern = r'http://[^\s"]+\.HDF(?:\?[^\s"]+)?'
        http_matches = re.findall(http_pattern, raw_text, re.IGNORECASE)
        # 识别FTP链接
        # ftp:// A202511070914090878 : F_8rCimc@ftp.nsmc.org.cn/FY3D_MERSI_GBAL_L1_20251106_2300_1000M_MS.HDF
        ftp_pattern = r'ftp://(?:[^\s:@]+:[^\s:@]+@)?[^\s/]+/[^\s"]+\.HDF'
        ftp_matches = re.findall(ftp_pattern, raw_text, re.IGNORECASE)
        return http_matches, ftp_matches
        # endregion

    def download_all_links(self, http_matches, ftp_matches, save_dir, return_stats=False):
        # region根据链接，去循环调用下载函数
        """
        通用链接下载函数（适配文件/页面两种场景）
        :param http_matches: HTTP链接列表
        :param ftp_matches: FTP链接列表
        :param save_dir: 保存目录
        :param return_stats: 是否返回统计结果（文件场景用True，页面场景用False）
        :return: 若return_stats=True，返回 (total, success, failed)；否则返回None
        """
        total = len(http_matches) + len(ftp_matches)
        success = 0
        failed = 0

        # 下载HTTP链接
        if http_matches:
            logger.info(f"[流程]提取到{len(http_matches)}个HTTP格式HDF链接，开始下载...")
            for i, hdf_url in enumerate(http_matches, 1):
                logger.info(f"[流程]正在下载第{i}/{len(http_matches)}个HTTP链接: {hdf_url}")
                if download_http_file(
                        hdf_url,
                        save_dir,
                        idle_timeout=60,
                        max_retry=3
                ):
                    success += 1
                    logger.info(f"[流程]✅ 第{i}个HTTP链接下载成功: {hdf_url}")
                else:
                    failed += 1
                    logger.error(f"❌ 第{i}个HTTP链接下载失败（已重试2次）: {hdf_url}")

        # 下载FTP链接
        if ftp_matches:
            logger.info(f"[流程]提取到{len(ftp_matches)}个FTP格式HDF链接，开始下载...")
            for i, hdf_url in enumerate(ftp_matches, 1):
                logger.info(f"[流程]正在下载第{i}/{len(ftp_matches)}个FTP链接: {hdf_url}")
                if download_ftp_with_progress(
                        hdf_url,
                        save_dir,
                        timeout=30,
                        idle_timeout=60,
                        max_retry=3
                ):
                    success += 1
                    logger.info(f"[流程]✅ 第{i}个FTP链接下载成功: {hdf_url}")
                else:
                    failed += 1
                    logger.error(f"[流程]❌ 第{i}个FTP链接多次重试失败: {hdf_url}")

        # 无链接处理
        if not http_matches and not ftp_matches:
            logger.error("未找到有效HDF链接（支持格式：HTTP带参数/纯链接、FTP带用户名/匿名登录）")
            if return_stats:
                return 0, 0, 0

        # 输出统计日志（两种场景都需要）
        logger.info(f"[流程]链接处理完成：总计{total}个文件, 成功{success}个, 失败{failed}个")
        if success > 0:
            logger.info(f"[流程]✅ 成功下载{success}个HDF文件！")
        if failed > 0:
            logger.error(f"❌ {failed}个HDF文件下载失败！")

        # 根据参数决定是否返回统计结果
        if return_stats:
            return total, success, failed
        return None
        # endregion

    def _login(self):
        # region 登录
        logger.info("[流程]开始登录流程......")
        max_login_retries = self.config.get_retry_attempts()

        # 1. 在主网页寻找并点击登录按钮
        if not self.browser.safe_click_element(*self.locators['login_button']):
            return False

        # 2. 循环重试登录
        for retry in range(max_login_retries):
            try:
                # ①首次尝试，输入用户名密码
                if retry == 0:
                    if not self.browser.safe_send_keys(*self.locators['username_input'], self.user_info['username']):
                        continue
                    if not self.browser.safe_send_keys(*self.locators['password_input'], self.user_info['password']):
                        continue

                # ②处理验证码
                captcha_input = self.browser.safe_find_element(*self.locators['captcha_input'])  # 找到验证码输入框
                if captcha_input:
                    captcha_input.clear()  # 先清空输入框
                    time.sleep(0.5)

                captcha_text = self.browser.solve_captcha(self.locators['captcha_image'][1])  # 获取验证码识别结果
                if not captcha_text:
                    logger.warning(f"验证码识别失败，重试 {retry + 1}/{max_login_retries}")
                    continue

                if not self.browser.safe_send_keys(*self.locators['captcha_input'], captcha_text):  # 将验证结果输入到输入框
                    logger.warning(f"验证码输入失败，重试 {retry + 1}/{max_login_retries}")
                    continue

                # ③提交登录
                if not self.browser.safe_click_element(*self.locators['submit_login']):  # 点击”提交“按钮
                    logger.warning(f"登录提交失败，重试 {retry + 1}/{max_login_retries}")
                    continue
                time.sleep(3)

                # ④验证登录是否成功  看是否能找到”我的订单“的元素
                try:
                    fengyun_element = WebDriverWait(self.browser.driver, 3).until(
                        EC.presence_of_element_located(self.locators['my_order'])
                    )
                    logger.info("成功找到'风云极轨卫星'元素 证明登录成功")
                    logger.info("[流程]网页登录成功")
                    return True
                except TimeoutException:
                    # 未找到元素：刷新验证码，进入下一次重试
                    logger.warning(f"未找到'风云极轨卫星'元素，本次登录失败，准备重试 {retry + 2}/{max_login_retries}")
                    captcha_image = self.browser.safe_find_element(*self.locators['captcha_image'])
                    if captcha_image:
                        captcha_image.click()
                        time.sleep(1)
                    continue  # 直接进入下一次循环，不触发外层except

            # 处理其他异常（如元素定位失败、点击失败等）
            except Exception as e:
                if retry < max_login_retries - 1:
                    logger.warning(f"登录发生其他错误（{str(e)}），重试 {retry + 2}/{max_login_retries}")
                    captcha_image = self.browser.safe_find_element(*self.locators['captcha_image'])
                    if captcha_image:
                        captcha_image.click()
                        time.sleep(1)
                else:
                    logger.error(f"达到最大重试次数（{max_login_retries}次），登录失败")
                    return False

        logger.error("[错误]登录流程全部重试失败")  # 所有登录重试次数耗尽且均未成功时触发
        return False
        # endregion

    def back_to_main_page(self):
        # region 回到我的订单界面
        """
        检查当前页面是否是「我的订单」主页面，若不是则关闭当前窗口并返回
        :return: bool - 是否成功返回主页面
        """
        driver = self.browser.driver

        if not driver or not self.main_window_handle or not self.main_page_url:
            logger.error("浏览器未初始化或主窗口信息未记录，无法返回我的订单页面")
            return False

        try:
            # 1. 检查当前窗口是否是主窗口（通过句柄判断）
            current_window = driver.current_window_handle
            if current_window == self.main_window_handle:
                # 2. 验证当前页面是否是「我的订单」页面（URL特征+订单表格元素）
                if self.main_page_config['url_keyword'] in driver.current_url and \
                        self.browser.safe_find_element(*self.main_page_config['identifier']):
                    logger.info("✅ 当前已在我的订单页面，无需切换")
                    return True
                else:
                    logger.warning("当前窗口是主窗口，但页面不是我的订单页面，重新加载...")
                    driver.get(self.main_page_url)
                    time.sleep(3)
                    # 重新验证订单表格是否存在
                    return self.browser.safe_find_element(*self.main_page_config['identifier']) is not None

            # 3. 非主窗口：关闭当前窗口并切换回主窗口
            logger.info(f"❌ 当前在非主窗口（句柄：{current_window}），关闭并返回我的订单页面")
            # 关闭当前非主窗口（比如下载时打开的新窗口）
            driver.close()
            # 切换到「我的订单」主窗口
            driver.switch_to.window(self.main_window_handle)
            time.sleep(3)

            # 4. 验证是否成功返回「我的订单」页面
            if self.browser.safe_find_element(*self.main_page_config['identifier']):
                logger.info("✅ 成功关闭非主窗口并返回我的订单页面")
                return True
            else:
                logger.warning("切换到主窗口，但未找到订单表格，重新加载我的订单页面...")
                driver.get(self.main_page_url)
                time.sleep(4)
                return self.browser.safe_find_element(*self.main_page_config['identifier']) is not None

        except Exception as e:
            logger.error(f"返回我的订单页面时出错：{str(e)}")
            logger.error(traceback.format_exc())
            # 异常情况下，强制切换回主窗口并重新加载
            try:
                driver.switch_to.window(self.main_window_handle)
                driver.get(self.main_page_url)
                time.sleep(4)
                return self.browser.safe_find_element(*self.main_page_config['identifier']) is not None
            except:
                return False
        # endregion

# 主程序入口
if __name__ == "__main__":
    # region main
    logger.info("[流程]开始下载订单数据......")

    if len(sys.argv) < 2:
        print("参数个数不够")
        sys.exit(101)  # 101 参数不够返回

    txt_order_path = sys.argv[1]  # 订单号txt的路径

    # 读取文件中的所有订单号（每行一个）
    with open(txt_order_path, 'r', encoding='utf-8') as f:
        # 读取所有行，去除空行和首尾空白
        content = [line.strip() for line in f.readlines() if line.strip()]
        # 有效行数 = 订单号列表的长度
        valid_line_count = len(content)
        print(content)

    downloader = SatelliteDataDownloader()
    downloader.run(content)
    # endregion






