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
import psutil
import gc
# endregion

# region基础日志配置
log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "download.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_path, encoding='utf-8', mode='w'),
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
    if not filename:
        filename = f"ftp_download_{int(time.time())}.hdf"
    save_path = os.path.join(save_dir, filename)
    os.makedirs(save_dir, exist_ok=True)  # 确保保存目录存在
    # endregion
    # region重试下载循环
    for retry in range(max_retry):
        logger.info(f"开始FTP下载（第{retry + 1}/{max_retry}次尝试）: {filename}")
        logger.info(f"{'=' * 50}")

        # 初始化变量
        download_aborted = False
        last_data_time = time.time()
        monitor_thread = None
        ftp = None

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

            # 获取文件大小
            file_size = ftp.size(path)
            downloaded_size = 0
            last_reported_percent = -5  # 上次报告的进度

            # 3. 启动空闲超时监控线程
            import threading

            def monitor_idle():
                nonlocal download_aborted
                while not download_aborted:
                    time.sleep(5)
                    if time.time() - last_data_time > idle_timeout:
                        logger.warning(f"⚠️  警告：{idle_timeout}秒未接收数据，中断下载！")
                        download_aborted = True
                        if ftp:
                            ftp.abort()

            monitor_thread = threading.Thread(target=monitor_idle)
            monitor_thread.daemon = True
            monitor_thread.start()

            # 4. 执行下载（带进度回调）
            with open(save_path, 'wb') as file:
                def callback(data):
                    nonlocal downloaded_size, last_data_time, last_reported_percent
                    if download_aborted:
                        return

                    file.write(data)
                    downloaded_size += len(data)
                    last_data_time = time.time()

                    # 进度打印（每5%输出一次）
                    if file_size > 0:
                        current_percent = (downloaded_size / file_size) * 100
                        if current_percent - last_reported_percent >= 5:
                            reported_percent = int(current_percent // 5 * 5)
                            logger.info(f"下载进度: {reported_percent}%")
                            last_reported_percent = reported_percent

                ftp.retrbinary(f'RETR {path}', callback)

            # 6. 下载完成后清理
            download_aborted = True
            if monitor_thread and monitor_thread.is_alive():
                monitor_thread.join(timeout=5)

            # 强制输出100%进度
            logger.info(f"下载进度: 100%")


            # 6. 验证文件完整性
            local_file_size = os.path.getsize(save_path)
            if file_size > 0 and abs(local_file_size - file_size) > 1024:  # 允许1KB误差
                raise ValueError(f"文件不完整！服务器大小{file_size}字节，本地大小{local_file_size}字节")

            # 7. 输出完成信息
            logger.info(f"✅ FTP文件下载成功！")
            logger.info(f"📁 保存路径: {save_path}")
            logger.info(f"📊 文件大小: {local_file_size:,} 字节")

            if ftp:
                ftp.quit()
            return True

        except TimeoutError as e:
            # 处理空闲超时异常
            logger.info(f"❌ {str(e)}")
            if os.path.exists(save_path):
                os.remove(save_path)
            if retry < max_retry - 1:
                logger.info(f"⏳ 剩余{max_retry - retry - 1}次重试机会，5秒后重试...")
                time.sleep(5)
            continue

        except Exception as e:
            logger.info(f"❌ FTP下载过程中出现错误: {str(e)[:200]}")
            # 清理不完整文件
            if os.path.exists(save_path):
                os.remove(save_path)
            # 重试判断
            if retry < max_retry - 1:
                logger.info(f"⏳ 剩余{max_retry - retry - 1}次重试机会，3秒后重试...")
                time.sleep(3)
            continue

        finally:
            # 确保资源清理
            download_aborted = True
            if monitor_thread and monitor_thread.is_alive():
                monitor_thread.join(timeout=5)
            try:
                if ftp:
                    ftp.quit()
            except:
                pass

    # 所有重试都失败
    logger.info(f"❌ 所有{max_retry}次FTP下载尝试均失败！")
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
            # [1] 无头模式
            chrome_options.add_argument('--headless=new')  # Chrome 112+推荐的无头模式
            chrome_options.add_argument('--disable-gpu')  # 无头模式下禁用GPU

            chrome_options.page_load_strategy = 'eager'  # 页面加载策略设置为"急切"模式  如果实在不行就改成normal试一下
            chrome_options.add_argument('--disable-background-timer-throttling')  # 禁用后台标签页的定时器节流
            chrome_options.add_argument('--disable-renderer-backgrounding')  # 禁用渲染进程的后台降级
            chrome_options.add_argument('--no-sandbox')  # 禁用 Chrome 的沙箱模式
            chrome_options.add_argument('--window-size=1920,1080')  # 指定浏览器窗口的初始尺寸为 1920x1080 像素
            chrome_options.add_argument('--disable-gpu')  # 禁用 GPU 加速
            chrome_options.add_argument('--disable-dev-shm-usage')  # 禁用 /dev/shm 临时目录的使用（Linux 系统特有）
            chrome_options.add_argument('--ignore-certificate-errors')  # 忽略 SSL 证书错误。
            # chrome_options.add_experimental_option('detach', True)  # 保持浏览器打开状态,让Chrome浏览器在自动化脚本执行完毕后不自动关闭
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
            logger.error(f"[错误]浏览器初始化失败: {str(e)}")
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
            logger.error("[错误]多次尝试后仍无法找到元素")
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
                element = WebDriverWait(self.driver, self.retry_attempts).until(EC.element_to_be_clickable((by, value)))
                element.click()
                time.sleep(3)
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
            logger.error(f"[错误]多次尝试后仍无法点击元素")
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
            logger.error("[错误]多次尝试后仍无法输入文本到元素")
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
            return None
        # endregion

    def click_and_collect_links(self, file_button_locator):
        """点击文件按钮并收集链接，不立即下载"""
        original_window = self.driver.current_window_handle
        start_time = time.time()
        listen_dir = self.listen_dir
        observer = None

        try:
            # 初始化文件监控
            event_handler = TxtFileHandler()
            observer = Observer()
            observer.schedule(event_handler, listen_dir, recursive=False)
            observer.start()
            time.sleep(2)

            # 点击文件按钮
            if not self.safe_click_element(*file_button_locator):
                logger.error("[流程]无法点击文件按钮")
                return None

            # 等待操作结果
            timeout = 30
            while time.time() - start_time < timeout:
                # 检查是否有新txt文件下载
                if event_handler.event_detected:
                    file_content = event_handler.read_file_content()
                    observer.stop()
                    observer.join()
                    logger.info("捕获到直接下载的TXT文件")

                    # 提取链接并返回（不下载）
                    http_matches, ftp_matches = self.extract_links(file_content)
                    return {
                        'type': 'file',
                        'http_links': http_matches,
                        'ftp_links': ftp_matches,
                        'path': event_handler.new_txt_file
                    }

                # 检查是否打开了新窗口
                if len(self.driver.window_handles) > 1:
                    for window_handle in self.driver.window_handles:
                        if window_handle != original_window:
                            self.driver.switch_to.window(window_handle)
                            new_window_url = self.driver.current_url
                            logger.info(f"检测到新窗口，URL: {new_window_url}")

                            page_content = self.driver.page_source
                            pre_element = self.driver.find_element(By.TAG_NAME, 'pre')
                            raw_text = pre_element.text.strip()

                            # 提取链接并返回（不下载）
                            http_matches, ftp_matches = self.extract_links(raw_text)

                            observer.stop()
                            observer.join()

                            return {
                                'type': 'page',
                                'http_links': http_matches,
                                'ftp_links': ftp_matches,
                                'url': new_window_url,
                                'new_window_handle': window_handle
                            }

                time.sleep(1)

            # 超时处理
            logger.warning("[错误]超时未检测到下载或页面跳转")
            return None

        except Exception as e:
            logger.error(f"[错误]点击并收集链接时出错: {str(e)}")
            return None
        finally:
            # 确保监控器停止
            if observer and observer.is_alive():
                try:
                    observer.stop()
                    observer.join(timeout=3)
                except Exception as e:
                    logger.warning(f"停止文件监控器时出错: {e}")

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
                (By.XPATH, '//*[@id="displayOrderBody"]/tr[4]/td[8]/a/span'),  # 第4个按钮
                (By.XPATH, '//*[@id="displayOrderBody"]/tr[5]/td[8]/a/span'),  # 第5个按钮
                (By.XPATH, '//*[@id="displayOrderBody"]/tr[6]/td[8]/a/span'),  # 第6个按钮
                (By.XPATH, '//*[@id="displayOrderBody"]/tr[7]/td[8]/a/span'),  # 第7个按钮
                (By.XPATH, '//*[@id="displayOrderBody"]/tr[8]/td[8]/a/span'),  # 第8个按钮
                (By.XPATH, '//*[@id="displayOrderBody"]/tr[9]/td[8]/a/span'),  # 第9个按钮
                (By.XPATH, '//*[@id="displayOrderBody"]/tr[10]/td[8]/a/span'),  # 第10个按钮
            ]
        }

    def run(self,content):
        # region运行主程序
        try:

            all_http_links = []
            all_ftp_links = []

            # region 初始化浏览器+打开网站+执行登录流程+点击我的订单
            # 初始化浏览器
            if not self.browser.init_browser():
                logger.error("[错误]无法初始化浏览器，程序退出")
                sys.exit(1)  # 1表示浏览器初始化失败

            # 打开网站
            logger.info("[流程]打开风云卫星数据网站......")
            self.browser.driver.get(self.base_url)
            time.sleep(2)  # 初始加载等待

            # 执行登录流程
            if not self._login():
                logger.error("[错误]登录失败，程序退出")
                sys.exit(2)  # 2表示登录失败

            # 登录成功后， 点击我的订单  跳转页面
            if not self.browser.safe_click_element(*self.locators['my_order']):
                logger.error("[错误]无法点击'我的订单'，程序终止")
                if self.browser.driver:
                    self.browser.driver.quit()
                sys.exit(3)  # 3 表示导航失败
            # endregion

            # 等待跳转完成，并记录主窗口句柄和URL
            time.sleep(3)  # 等待页面跳转加载
            self.main_window_handle = self.browser.driver.current_window_handle  # 记录当前窗口（我的订单页面）
            self.main_page_url = self.browser.driver.current_url  # 记录我的订单页面实际URL
            logger.info(
                f"成功跳转至我的订单页面，主窗口句柄：{self.main_window_handle}，URL：{self.main_page_url}")

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
            logger.info(f"[流程]共有{line_count}个订单，开始收集所有下载链接..")
            # endregion

            # region 循环下载各个订单
            for i in range(line_count):
                # 检查是否有对应的按钮定位符（避免索引越界）
                if i >= len(self.locators['file_buttons']):
                    logger.error(f"未定义第{i + 1}个按钮的定位符，请补充locators['file_buttons']")
                    continue

                # 获取当前行对应的按钮定位符
                current_button = self.locators['file_buttons'][i]
                logger.info(f"[流程]点击第{i + 1}个文件按钮")

                # 点击按钮收集链接（不下载）
                result = self.browser.click_and_collect_links(current_button)

                if result:
                    # 收集链接
                    all_http_links.extend(result.get('http_links', []))
                    all_ftp_links.extend(result.get('ftp_links', []))
                    logger.info(
                        f"[流程]第{i + 1}个订单收集到 {len(result.get('http_links', []))} 个HTTP链接和 {len(result.get('ftp_links', []))} 个FTP链接")
                else:
                    logger.warning(f"[流程]第{i + 1}个订单未能收集到链接")

                # 清理临时文件
                if result and result.get('path') and os.path.exists(result['path']):
                    os.remove(result['path'])
                    logger.info(f"已清理临时TXT文件：{result['path']}")

                # 点击之后 可能跳转页面 这时候需要返回页面 以便于等会儿的重新点击
                self.back_to_main_page()

                self.browser.driver.refresh()
                time.sleep(3)  # 刷新后等待页面完全加载

            # region 集中下载所有链接
            logger.info(f"[流程]链接收集完成，总计 {len(all_http_links)} 个HTTP链接和 {len(all_ftp_links)} 个FTP链接")
            logger.info("[流程]开始集中下载所有文件...")

            # 关闭浏览器，释放内存
            if self.browser.driver:
                self.browser.driver.quit()
                self.browser.driver = None

            # 执行集中下载
            save_dir = self.config.get_download_dir()
            self.download_all_links_concentrated(all_http_links, all_ftp_links, save_dir)

            logger.info("[流程]所有文件下载完成！")
            # endregion

        except Exception as e:
            logger.error(f"[错误]程序运行出错: {str(e)}")
            logger.error(traceback.format_exc())
        finally:
            # [关闭浏览器]
            if hasattr(self, 'browser') and self.browser.driver:
                self.browser.driver.quit()
        # endregion



    def download_all_links_concentrated(self, http_links, ftp_links, save_dir):
        failed_files = []

        # HTTP链接文件路径
        http_links_file = os.path.join(save_dir, "http_links.txt")
        # FTP链接文件路径
        ftp_links_file = os.path.join(save_dir, "ftp_links.txt")
        with open(http_links_file, 'w', encoding='utf-8') as f:
            for link in http_links:
                f.write(link + '\n')
        with open(ftp_links_file, 'w', encoding='utf-8') as f:
            for link in ftp_links:
                f.write(link + '\n')

        # 下载前强制垃圾回收
        import gc
        gc.collect()

        """集中下载所有链接"""
        total_files = len(http_links) + len(ftp_links)
        success_count = 0
        failed_count = 0

        logger.info(f"[流程]开始下载 {total_files} 个文件...")

        # 下载HTTP链接
        if http_links:
            logger.info(f"[流程]开始下载 {len(http_links)} 个HTTP文件")
            for i, hdf_url in enumerate(http_links, 1):
                filename = os.path.basename(hdf_url.split('?')[0])
                logger.info(f"[流程]进度: {i}/{len(http_links)} - {filename}")

                if download_http_file(hdf_url, save_dir, idle_timeout=60, max_retry=3):
                    success_count += 1
                    logger.info(f"[流程]✅ HTTP文件下载成功: {i}/{len(http_links)}")
                else:
                    failed_count += 1
                    logger.error(f"[流程]❌ HTTP文件下载失败: {i}/{len(http_links)}")
                    failed_files.append((hdf_url, filename))
                # 显示总体进度
                current_total = i + min(len(ftp_links), 0)  # 假设FTP还没开始
                overall_progress = (current_total / total_files) * 100
                print(f"总体进度: {overall_progress:.1f}% ({current_total}/{total_files})", end='', flush=True)

        gc.collect()

        # 下载FTP链接
        if ftp_links:
            logger.info(f"[流程]开始下载 {len(ftp_links)} 个FTP文件")
            for i, hdf_url in enumerate(ftp_links, 1):
                filename = os.path.basename(urlparse(hdf_url).path)
                logger.info(f"[流程]进度: {i}/{len(ftp_links)} - {filename}")

                if download_ftp_with_progress(hdf_url, save_dir, timeout=30, idle_timeout=60, max_retry=3):
                    success_count += 1
                    logger.info(f"[流程]✅ FTP文件下载成功: {i}/{len(ftp_links)}")
                else:
                    failed_count += 1
                    logger.error(f"[流程]❌ FTP文件下载失败: {i}/{len(ftp_links)}")
                    failed_files.append((hdf_url, filename))

                # 显示总体进度
                current_total = len(http_links) + i
                overall_progress = (current_total / total_files) * 100
                print(f"\r总体进度: {overall_progress:.1f}% ({current_total}/{total_files})", end='', flush=True)

        gc.collect()
        # 输出统计
        logger.info(f"[流程]下载完成: 总计{total_files}个文件, 成功{success_count}个, 失败{failed_count}个")

        # 新增：汇总输出失败文件列表
        logger.info(f"\n[流程]下载完成: 总计{total_files}个文件, 成功{success_count}个, 失败{failed_count}个")
        if failed_files:
            logger.warning(f"[流程] 共{len(failed_files)}个文件下载失败：")
            for idx, (link, filename) in enumerate(failed_files, 1):
                logger.warning(f"[流程] {idx}. 文件名: {filename}  链接: {link}")
            # 可选：将失败列表保存到文件（方便后续重试）
            failed_file_path = os.path.join(save_dir, "failed_downloads.txt")
            with open(failed_file_path, 'w', encoding='utf-8') as f:
                f.write("下载失败的文件列表：\n")
                for link, filename in failed_files:
                    f.write(f"文件名: {filename}\n链接: {link}\n\n")
            logger.info(f"[流程] 失败文件列表已保存至：{failed_file_path}")
        else:
            logger.info("[流程] 所有文件均下载成功！")

    def _login(self,first_page=1):
        # region 登录

        logger.info("[流程]开始登录流程......")
        max_login_retries = self.config.get_retry_attempts()

        # 1. 在主网页寻找并点击登录按钮
        if(first_page==1):
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
        logger.error("[错误]订单执行参数个数不够")
        sys.exit(101)  # 101 参数不够返回

    txt_order_path = sys.argv[1]  # 订单号txt的路径

    # 读取文件中的所有订单号（每行一个）
    with open(txt_order_path, 'r', encoding='utf-8') as f:
        # 读取所有行，去除空行和首尾空白
        content = [line.strip() for line in f.readlines() if line.strip()]
        # 有效行数 = 订单号列表的长度
        valid_line_count = len(content)
        logger.info(content)

    downloader = SatelliteDataDownloader()
    downloader.run(content)
    # endregion






