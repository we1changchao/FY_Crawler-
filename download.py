# 导入所需库
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
'''
从textt中导入ftp下载方法
'''
from download_http_file import download_http_file

import sys
from bs4 import BeautifulSoup
import re
import requests

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
logger.info(f"日志文件路径: {log_path}")
logger.info(f"当前工作目录: {os.getcwd()}")


# 新增：带进度显示的FTP下载函数
def download_ftp_with_progress(ftp_url, save_dir):
    """下载FTP文件并显示进度"""
    try:
        parsed_url = urlparse(ftp_url)
        os.makedirs(save_dir, exist_ok=True)
        filename = os.path.basename(parsed_url.path)
        save_path = os.path.join(save_dir, filename)

        # 解析FTP凭据
        username = parsed_url.username if parsed_url.username else 'anonymous'
        password = parsed_url.password if parsed_url.password else ''
        host = parsed_url.hostname
        path = parsed_url.path

        # 连接FTP服务器
        ftp = FTP(host)
        ftp.login(username, password)

        # 获取文件大小
        ftp.voidcmd('TYPE I')  # 二进制传输模式
        file_size = ftp.size(path)
        downloaded_size = 0

        # 下载文件
        with open(save_path, 'wb') as file:
            def callback(data):
                nonlocal downloaded_size
                file.write(data)
                downloaded_size += len(data)

                # 显示下载进度
                if file_size > 0:
                    progress = (downloaded_size / file_size) * 100
                    print(f"\r下载进度: {filename} {progress:.2f}%", end='', flush=True)

            ftp.retrbinary(f'RETR {path}', callback)

        if file_size > 0:
            print()  # 换行
        ftp.quit()
        logger.info(f"成功下载: {filename}")
        return True
    except Exception as e:
        logger.error(f"FTP下载失败: {str(e)}")
        return False


# 文件下载监控处理器、



class TxtFileHandler(FileSystemEventHandler):
    """监控下载文件夹，捕获txt文件（包括临时文件重命名）"""
    def __init__(self):
        self.new_txt_file = None   # 存储最终识别到的 .txt 文件路径
        self.event_detected = False  # 标记是否检测到有效的目标文件（通常是 .txt 文件）
        self.tmp_files = set()  # 记录所有下载过程中产生的临时文件路径（如 .tmp、.crdownload 等浏览器临时文件）。  集合

    def on_created(self, event):
        """捕获新创建的文件（包括临时文件）"""
        if not event.is_directory:
            logger.info(f"文件创建: {event.src_path}")
            # 记录临时文件
            if event.src_path.endswith(('.tmp', '.crdownload')):
                self.tmp_files.add(event.src_path)  # 若符合临时文件特征，就将其路径添加到 self.tmp_files 集合中，用于后续跟踪。
            # 直接捕获txt文件
            elif event.src_path.endswith('.txt'):
                self.new_txt_file = event.src_path
                self.event_detected = True

    def on_moved(self, event):
        """跟踪所有重命名步骤，更新临时文件记录"""
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

    def read_file_content(self):
        """读取文本文件内容（优化版：增加存在性校验和编码容错）"""
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

    def init_browser(self):
        """初始化浏览器"""
        try:
            # 创建设置浏览器对象
            chrome_options = Options()

            # 基本配置
            chrome_options.page_load_strategy = 'eager'  # 或 'normal' 页面加载策略设置为"急切"模式
            chrome_options.add_argument('--disable-background-timer-throttling')  #禁用后台标签页的定时器节流
            chrome_options.add_argument('--disable-renderer-backgrounding')  #禁用渲染进程的后台降级

            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--ignore-certificate-errors')

            # 配置Chrome选项中的下载偏好
            prefs = {
                "download.prompt_for_download": False,  # 禁用下载弹窗（核心设置）
                "download.directory_upgrade": True,  # 允许目录升级
                "plugins.always_open_pdf_externally": True,  # 辅助设置（避免其他文件类型弹窗）
                "profile.default_content_settings.popups": 0  # 禁用弹窗
            }
            chrome_options.add_experimental_option("prefs", prefs)  # 应用偏好设置

            # 保持浏览器打开状态
            chrome_options.add_experimental_option('detach', True)

            # 设置Chrome驱动
            driver_path = self.config.get_chrome_driver_path()
            if driver_path and os.path.exists(driver_path):
                service = Service(driver_path)
            else:
                # 自动下载并使用合适版本的chromedriver
                service = Service(ChromeDriverManager().install())
                logger.info("使用自动管理的ChromeDriver")

            # 创建并启动浏览器
            self.driver = webdriver.Chrome(service=service, options=chrome_options)

            # 设置隐式等待
            self.driver.implicitly_wait(self.timeout)

            # 创建显式等待对象
            self.wait = WebDriverWait(self.driver, self.timeout)

            logger.info("浏览器初始化成功")
            return True

        except Exception as e:
            logger.error(f"浏览器初始化失败: {str(e)}")
            logger.error(traceback.format_exc())
            return False


    def safe_find_element(self, by, value, retry=0):
        """安全查找元素，带重试机制"""
        try:
            return self.wait.until(EC.presence_of_element_located((by, value)))
        except (TimeoutException, StaleElementReferenceException) as e:
            if retry < self.retry_attempts:
                logger.warning(f"查找元素失败，重试 {retry + 1}/{self.retry_attempts} - {by}: {value}")
                time.sleep(1)
                return self.safe_find_element(by, value, retry + 1)
            logger.error(f"多次尝试后仍无法找到元素: {by}: {value}")
            logger.error(traceback.format_exc())
            return None

    def safe_click_element(self, by, value, retry=0):
        """安全点击元素，带重试机制"""
        try:
            element = self.wait.until(EC.element_to_be_clickable((by, value)))
            element.click()
            logger.info(f"成功点击元素: {by}: {value}")
            return True
        except (TimeoutException, ElementClickInterceptedException, StaleElementReferenceException) as e:
            if retry < self.retry_attempts:
                logger.warning(f"点击元素失败，重试 {retry + 1}/{self.retry_attempts} - {by}: {value}")
                # 尝试滚动到元素
                try:
                    element = self.driver.find_element(by, value)
                    self.driver.execute_script("arguments[0].scrollIntoView();", element)
                    time.sleep(1)
                except:
                    pass
                return self.safe_click_element(by, value, retry + 1)
            logger.error(f"多次尝试后仍无法点击元素: {by}: {value}")
            logger.error(traceback.format_exc())
            return False

    def safe_send_keys(self, by, value, text, retry=0):
        """安全输入文本，带重试机制"""
        try:
            element = self.wait.until(EC.element_to_be_clickable((by, value)))
            element.clear()
            element.send_keys(text)
            logger.info(f"成功输入文本到元素: {by}: {value}")
            return True
        except (TimeoutException, StaleElementReferenceException) as e:
            if retry < self.retry_attempts:
                logger.warning(f"输入文本失败，重试 {retry + 1}/{self.retry_attempts} - {by}: {value}")
                time.sleep(1)
                return self.safe_send_keys(by, value, text, retry + 1)
            logger.error(f"多次尝试后仍无法输入文本到元素: {by}: {value}")
            logger.error(traceback.format_exc())
            return False

    def solve_captcha(self, captcha_xpath, retry=0):
        """解决验证码"""
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

    def click_and_read_content(self, file_button_locator):
        """点击文件按钮并根据结果读取内容（下载txt或页面内容）"""
        # 记录点击前的窗口句柄和下载目录状态
        original_window = self.driver.current_window_handle  # 记录当前浏览器窗口的唯一标识（句柄），用于后续在多个窗口之间切换时，能准确回到初始窗口
        start_time = time.time()
        download_dir = self.download_dir

        # 初始化文件监控
        event_handler = TxtFileHandler()    # 自定义的 文件下载监控处理器
        observer = Observer()  # watchdog 库中创建文件系统监控器实例的核心代码，用于启动一个后台线程来监听指定目录的文件变化（如创建、删除、修改、移动等）。
        observer.schedule(event_handler, download_dir, recursive=False)
        observer.start()

        # 等待监控完全启动
        time.sleep(2)

        try:
            # 点击文件按钮
            if not self.safe_click_element(*file_button_locator):
                logger.error("无法点击文件按钮")
                return None

            # 等待操作结果（最多60秒）
            timeout = 30
            while time.time() - start_time < timeout:
                # 检查是否有新txt文件下载
                if event_handler.event_detected:
                    observer.stop()
                    observer.join()
                    logger.info("捕获到直接下载的TXT文件")
                    return {
                        'type': 'file',
                        'content': event_handler.read_file_content(),
                        'path': event_handler.new_txt_file,
                        'raw_content': event_handler.read_file_content()  # 新增：返回完整原始文本，用于提取FTP链接
                    }

                # 检查是否打开了新窗口
                if len(self.driver.window_handles) > 1:  #判断当前浏览器是否打开了多个窗口
                    # 切换到新窗口
                    for window_handle in self.driver.window_handles:
                        if window_handle != original_window:
                            self.driver.switch_to.window(window_handle)
                            new_window_url = self.driver.current_url
                            logger.info(f"检测到新窗口，它的URL为: {new_window_url}")
                            # 若新窗口是HTML页面，读取页面内容
                            logger.info("新窗口是HTML页面，读取页面源码")
                            page_content = self.driver.page_source
                            logger.info(f"--------HTMl页面内容:{page_content}")
                            # 定位<pre>标签并获取文本
                            pre_element = self.driver.find_element(By.TAG_NAME, 'pre')
                            raw_text = pre_element.text.strip()  # 得到包含链接的文本
                            logger.info(f"--------真实的页面内容:{raw_text}")
                            observer.stop()
                            observer.join()
                            return {
                                'type': 'page',
                                'content': page_content,
                                'url': new_window_url,
                                'raw_content': page_content,
                                'raw_text': raw_text
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

# 主程序类
class SatelliteDataDownloader:
    def __init__(self):
        self.config = ConfigHandler()
        self.browser = SatelliteBrowser(self.config)
        self.user_info = self.config.get_user_info()
        self.base_url = 'https://satellite.nsmc.org.cn/DataPortal/cn/home/index.html'

        # 页面元素定位符
        self.locators = {
            'login_button': (By.XPATH, '//*[@id="common-login"]'),  # 点击登录
            'username_input': (By.XPATH, '//*[@id="inputUserNameCN"]'),  # 输入用户名
            'password_input': (By.XPATH, '//*[@id="inputPasswordCN"]'),  # 输入密码
            'captcha_image': (By.XPATH, '//*[@id="logincn"]/div[2]/div/div/div[2]/div[2]/div[4]/div/img'),  # 验证码图像
            'captcha_input': (By.XPATH, '//*[@id="inputValidateCodeCN"]'),  # 输入验证码
            'submit_login': (By.XPATH, '//*[@id="logincn"]/div[2]/div/div/div[2]/div[2]/div[6]/button'),  # 提交登录
            # 添加文件按钮定位符（请根据实际页面更新）
            'my_order': (By.XPATH, '//*[@id="u-myorder"]'),  # 点击我的订单
            'file_button': (By.XPATH, '//*[@id="displayOrderBody"]/tr[1]/td[8]/a/span')  # //*[@id="displayOrderBody"]/tr[3]/td[8]/a/span
        }

    def run(self):
        """运行主程序"""
        try:
            # 初始化浏览器
            if not self.browser.init_browser():
                logger.error("无法初始化浏览器，程序退出")
                return

            # 打开网站
            logger.info(f"打开网站: {self.base_url}")
            self.browser.driver.get(self.base_url)
            time.sleep(5)  # 初始加载等待

            # 执行登录流程
            if not self._login():
                logger.error("登录失败，程序退出")
                return

            time.sleep(1)
            # 登录成功后， 点击我的订单  跳转页面
            if not self.browser.safe_click_element(*self.locators['my_order']):
                return False

            time.sleep(1)
            # 点击文件按钮并读取内容
            logger.info("开始点击文件按钮并读取内容")
            result = self.browser.click_and_read_content(self.locators['file_button'])

            # 处理读取结果
            if result:
                if result['type'] == 'file':
                    print(result['content'])
                    # ftp://A202510130830070581:6cq9Cv_Y@ftp.nsmc.org.cn/FY3D_MERSI_GBAL_L1_20251013_0500_GEO1K_MS.HDF
                    logger.info("成功获取下载的txt文件内容")
                    raw_text = result['raw_content'].strip()  # 去除首尾空格/换行
                    save_dir = self.config.get_download_dir()
                    download_success = False
                    hdf_url = None
                    # 初始化下载统计
                    total_downloads = 0
                    successful_downloads = 0
                    failed_downloads = 0


                    # -------------------------- 第一步：双格式链接识别（HTTP + FTP） --------------------------
                    # 1. 识别HTTP格式HDF链接（支持带参数如?AccessKey=...和纯链接两种场景）
                    http_pattern = r'http://[^\s"]+\.HDF(?:\?[^\s"]+)?'  # 非捕获组(?:...)避免匹配冗余分组
                    http_matches = re.findall(http_pattern, raw_text, re.IGNORECASE)  # 忽略大小写（适配.HDF/.hdf）

                    # 2. 识别FTP格式HDF链接（支持带用户名密码如ftp://user:pass@xxx.xx/...和匿名登录两种场景）
                    ftp_pattern = r'ftp://(?:[^\s:@]+:[^\s:@]+@)?[^\s/]+/[^\s"]+\.HDF'  # (?:user:pass@)为可选匿名登录
                    ftp_matches = re.findall(ftp_pattern, raw_text, re.IGNORECASE)

                    all_matches = http_matches + ftp_matches
                    total_downloads = len(all_matches)

                    # -------------------------- 第二步：确定有效链接并执行下载 --------------------------
                    # # 修改1：下载所有HTTP链接
                    # if http_matches:
                    #     logger.info(f"从txt文件中提取到{len(http_matches)}个HTTP格式HDF链接，开始下载...")
                    #     for i, hdf_url in enumerate(http_matches, 1):
                    #         logger.info(f"正在下载第{i}/{len(http_matches)}个HTTP链接: {hdf_url}")
                    #         # 修改2：使用带进度显示的下载函数
                    #         if not download_http_file(hdf_url):
                    #             logger.error(f"第{i}个HTTP链接下载失败: {hdf_url}")
                    # 下载所有HTTP链接
                    if http_matches:
                        logger.info(f"从txt文件中提取到{len(http_matches)}个HTTP格式HDF链接，开始下载...")
                        for i, hdf_url in enumerate(http_matches, 1):
                            logger.info(f"正在下载第{i}/{len(http_matches)}个HTTP链接: {hdf_url}")
                            if download_http_file(hdf_url):
                                successful_downloads += 1
                                logger.info(f"✅ 第{i}个HTTP链接下载成功: {hdf_url}")
                            else:
                                failed_downloads += 1
                                logger.error(f"❌ 第{i}个HTTP链接下载失败: {hdf_url}")

                    # # 修改1：下载所有FTP链接
                    # if ftp_matches:
                    #     logger.info(f"从txt文件中提取到{len(ftp_matches)}个FTP格式HDF链接，开始下载...")
                    #     for i, hdf_url in enumerate(ftp_matches, 1):
                    #         logger.info(f"正在下载第{i}/{len(ftp_matches)}个FTP链接: {hdf_url}")
                    #         # 修改2：使用带进度显示的下载函数
                    #         if not download_ftp_with_progress(hdf_url, save_dir):
                    #             logger.error(f"第{i}个FTP链接下载失败: {hdf_url}")
                    # 下载所有FTP链接
                    if ftp_matches:
                        logger.info(f"从txt文件中提取到{len(ftp_matches)}个FTP格式HDF链接，开始下载...")
                        for i, hdf_url in enumerate(ftp_matches, 1):
                            logger.info(f"正在下载第{i}/{len(ftp_matches)}个FTP链接: {hdf_url}")
                            if download_ftp_with_progress(hdf_url, save_dir):
                                successful_downloads += 1
                                logger.info(f"✅ 第{i}个FTP链接下载成功: {hdf_url}")
                            else:
                                failed_downloads += 1
                                logger.error(f"❌ 第{i}个FTP链接下载失败: {hdf_url}")

                    # 场景3：同时识别到两种格式链接（极端场景，取HTTP优先，可根据需求调整）
                    elif http_matches and ftp_matches:
                        hdf_url = http_matches[0]
                        logger.warning(f"从txt文件中同时提取到HTTP和FTP链接，优先使用HTTP链接：{hdf_url}")
                        logger.warning(f"忽略的FTP链接：{ftp_matches[0]}")
                        download_success = download_http_file(hdf_url)

                    # 场景4：未识别到任何有效链接
                    else:
                        logger.error("txt文件中未找到有效HDF链接（支持格式：HTTP带参数/纯链接、FTP带用户名/匿名登录）")
                        # 清理临时TXT文件（无论是否下载，都删除临时文件）
                        if result.get('path') and os.path.exists(result['path']):
                            os.remove(result['path'])
                            logger.info(f"已清理临时TXT文件：{result['path']}")
                        return

                    # -------------------------- 第三步：下载结果处理 + 临时文件清理 --------------------------
                    # 输出下载统计
                    logger.info(f"下载完成统计: 总计{total_downloads}个文件, 成功{successful_downloads}个, 失败{failed_downloads}个")

                    if successful_downloads > 0:
                        logger.info(f"✅ 成功下载{successful_downloads}个HDF文件！")
                    if failed_downloads > 0:
                        logger.error(f"❌ {failed_downloads}个HDF文件下载失败！")

                    # 清理临时TXT文件（无论下载成功/失败，均删除，避免残留）
                    if result.get('path') and os.path.exists(result['path']):
                        os.remove(result['path'])
                        logger.info(f"已清理临时TXT文件：{result['path']}")
                if result['type'] == 'page':
                    logger.info('识别到是页面了，并且拿到了页面内容')
                    raw_text = result['raw_text']
                    save_dir = self.config.get_download_dir()

                    # 从页面内容提取所有链接并下载
                    http_pattern = r'http://[^\s"]+\.HDF(?:\?[^\s"]+)?'
                    http_matches = re.findall(http_pattern, raw_text, re.IGNORECASE)

                    ftp_pattern = r'ftp://(?:[^\s:@]+:[^\s:@]+@)?[^\s/]+/[^\s"]+\.HDF'
                    ftp_matches = re.findall(ftp_pattern, raw_text, re.IGNORECASE)

                    if http_matches:
                        logger.info(f"从页面中提取到{len(http_matches)}个HTTP格式HDF链接，开始下载...")
                        for i, hdf_url in enumerate(http_matches, 1):
                            logger.info(f"正在下载第{i}/{len(http_matches)}个HTTP链接: {hdf_url}")
                            if not download_http_file(hdf_url):
                                logger.error(f"第{i}个HTTP链接下载失败: {hdf_url}")

                    if ftp_matches:
                        logger.info(f"从页面中提取到{len(ftp_matches)}个FTP格式HDF链接，开始下载...")
                        for i, hdf_url in enumerate(ftp_matches, 1):
                            logger.info(f"正在下载第{i}/{len(ftp_matches)}个FTP链接: {hdf_url}")
                            if not download_ftp_with_progress(hdf_url, save_dir):
                                logger.error(f"第{i}个FTP链接下载失败: {hdf_url}")

                    if not http_matches and not ftp_matches:
                        logger.error("页面中未找到有效HDF链接")
                    else:
                        logger.info("页面链接处理完成")


        except Exception as e:
            logger.error(f"程序运行出错: {str(e)}")
            logger.error(traceback.format_exc())
        finally:
            # 可以根据需要决定是否关闭浏览器
            # if self.browser.driver:
            #     self.browser.driver.quit()
            pass




    def _login(self):
        """ 执行登录流程（增加验证码错误重试逻辑） """
        logger.info("开始登录流程")
        max_login_retries = self.config.get_retry_attempts()  # 从配置文件获取最大重试次数（与原重试次数一致）

        # 1. 先点击登录按钮（仅需点击一次，弹出登录弹窗）
        if not self.browser.safe_click_element(*self.locators['login_button']):
            return False
        time.sleep(1)

        # 2. 循环重试验证码（直到登录成功或达到最大次数）
        for retry in range(max_login_retries):
            try:
                # --------------------------
                # 步骤1：输入用户名和密码（每次重试无需重复输入，但若页面刷新可保留）
                # --------------------------
                if retry == 0:  # 第一次重试时输入用户名密码，后续重试无需重复输入
                    if not self.browser.safe_send_keys(*self.locators['username_input'], self.user_info['username']):
                        continue  # 用户名输入失败，直接重试
                    if not self.browser.safe_send_keys(*self.locators['password_input'], self.user_info['password']):
                        continue  # 密码输入失败，直接重试

                # --------------------------
                # 步骤2：识别并输入验证码（每次重试都需重新识别）
                # --------------------------
                # 清除原有的验证码（避免与新验证码叠加）
                captcha_input = self.browser.safe_find_element(*self.locators['captcha_input'])
                if captcha_input:
                    captcha_input.clear()
                    time.sleep(0.5)

                # 识别新验证码
                captcha_text = self.browser.solve_captcha(self.locators['captcha_image'][1])
                if not captcha_text:
                    logger.warning(f"验证码识别失败，重试 {retry + 1}/{max_login_retries}")
                    continue  # 识别失败，直接重试

                # 输入新验证码
                if not self.browser.safe_send_keys(*self.locators['captcha_input'], captcha_text):
                    logger.warning(f"验证码输入失败，重试 {retry + 1}/{max_login_retries}")
                    continue  # 输入失败，直接重试

                # --------------------------
                # 步骤3：提交登录并判断是否成功
                # --------------------------
                if not self.browser.safe_click_element(*self.locators['submit_login']):
                    logger.warning(f"登录提交失败，重试 {retry + 1}/{max_login_retries}")
                    continue  # 提交失败，直接重试
                time.sleep(3)  # 等待登录结果（关键：给页面足够时间判断登录状态）

                # --------------------------
                # 步骤4：验证登录是否成功（核心判定逻辑）
                # 判定标准：能找到“风云极轨卫星”元素 → 登录成功；找不到 → 验证码错误
                # --------------------------
                logger.info("验证登录结果：尝试查找'我的订单'元素")
                fengyun_element = self.browser.safe_find_element(
                    *self.locators['my_order'])  # 注意key是'FengYun_satellite'（原代码中首字母大写）
                if fengyun_element:
                    logger.info("登录成功：成功找到'我的订单'元素")
                    return True  # 登录成功，退出循环
                else:
                    raise Exception("验证码错误：未找到'我的订单'元素")  # 触发异常，进入重试流程

            except Exception as e:
                # 捕获“验证码错误”或其他登录异常，准备刷新验证码重试
                if retry < max_login_retries - 1:  # 不是最后一次重试，刷新验证码
                    logger.warning(f"登录失败（{str(e)}），刷新验证码重试 {retry + 2}/{max_login_retries}")
                    # 关键：点击验证码图片，刷新新的验证码（触发页面重新生成验证码）
                    captcha_image = self.browser.safe_find_element(*self.locators['captcha_image'])
                    if captcha_image:
                        captcha_image.click()  # 点击验证码刷新
                        time.sleep(1)  # 等待新验证码加载
                    else:
                        logger.error("无法找到验证码图片，无法刷新")
                        continue
                else:
                    # 最后一次重试失败，返回登录失败
                    logger.error(f"达到最大登录重试次数（{max_login_retries}次），登录失败")
                    return False

        # 所有重试都失败，返回False
        logger.error("登录流程全部重试失败")
        return False
# 主程序入口
if __name__ == "__main__":
    logger.info("===== 开始下载订单了 =====")
    downloader = SatelliteDataDownloader()
    downloader.run()
    logger.info("===== 订单下载完成了 =====")





