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


# 带进度显示的FTP下载函数
def download_ftp_with_progress(ftp_url, save_dir):     # 参数（url ，保存位置）
    """下载FTP文件并显示进度"""
    try:
        # urlparse 是 Python 内置的 URL 解析工具，能从类似 ftp://user:pass@host/path/file.txt 的链接中提取关键信息。
        parsed_url = urlparse(ftp_url)  # 解析FTP URL（分离主机、路径、用户名、密码等）
        os.makedirs(save_dir, exist_ok=True)  # 创建本地保存目录（若不存在）
        filename = os.path.basename(parsed_url.path)  # 从URL路径中提取文件名（如 "file.txt"）
        save_path = os.path.join(save_dir, filename)   # 拼接本地保存的完整路径

        # 解析 FTP 连接信息
        username = parsed_url.username if parsed_url.username else 'anonymous'   # 用户名（默认匿名）
        password = parsed_url.password if parsed_url.password else ''   # 密码（默认空）
        host = parsed_url.hostname   # FTP服务器主机地址（如 ftp.example.com）
        path = parsed_url.path   # 服务器上的文件路径（如 /data/file.txt）

        # 连接FTP服务器
        ftp = FTP(host)   # 建立与FTP服务器的连接
        ftp.login(username, password)  # 使用用户名密码登录

        # 获取文件大小
        ftp.voidcmd('TYPE I') # 切换到二进制传输模式（适用于所有文件类型，避免文本模式的编码问题）
        file_size = ftp.size(path)   # 获取服务器上文件的总大小（字节）
        downloaded_size = 0  # 记录已下载的字节数（初始为0）

        # 下载文件并显示进度
        with open(save_path, 'wb') as file:  # 以二进制写模式打开本地文件
            def callback(data):    # 回调函数：每次接收数据时触发
                nonlocal downloaded_size  # 引用外部变量 downloaded_size
                file.write(data)  # 将接收到的数据写入本地文件
                downloaded_size += len(data)   # 更新已下载大小

                # 显示下载进度
                if file_size > 0:
                    progress = (downloaded_size / file_size) * 100  # 进度百分比
                    print(f"\r下载进度: {filename} {progress:.2f}%", end='', flush=True)  # 实时刷新显示

            ftp.retrbinary(f'RETR {path}', callback)   # 二进制方式下载文件，每收到数据调用 callback

        if file_size > 0:
            print()  # 换行
        ftp.quit()
        logger.info(f"成功下载: {filename}")
        return True
    except Exception as e:
        logger.error(f"FTP下载失败: {str(e)}")
        return False

def get_order_status(browser, order_number):
    """
    根据订单号查找对应行，并返回订单状态
    :param browser: SatelliteBrowser 实例（包含 webdriver）
    :param order_number: 要查询的订单号（如 "C202510300255033490"）
    :return: 订单状态（如 "准备中"）或 None（未找到时）
    """
    try:
        # 定位tbody
        tbody = browser.safe_find_element(By.ID, "displayOrderBody")
        if not tbody:
            return None

        # 遍历所有行
        rows = tbody.find_elements(By.TAG_NAME, "tr")
        for row in rows:
            # 定位该行的“订单号”列（第一个td）
            order_td = row.find_element(By.CSS_SELECTOR, "td:nth-child(1)")
            if order_td.text.strip() == order_number:
                # 找到匹配的行，定位“状态”列（第5个td）
                status_td = row.find_element(By.CSS_SELECTOR, "td:nth-child(4)")
                return status_td.text.strip()

        # 遍历完所有行未找到匹配订单号
        return None
    except Exception as e:
        logger.error(f"查询订单状态失败: {str(e)}")
        return None



# 文件下载监控处理器
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
        self.listen_dir = config.get_listen_dir()

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
        listen_dir = self.listen_dir

        # 初始化文件监控
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
                                'raw_content': page_content,   # 原始HTML（与content一致，可能用于备份）
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
            'file_button': (By.XPATH, '//*[@id="displayOrderBody"]/tr[1]/td[8]/a/span')  #
        }

    def run(self,content):
        """运行主程序"""
        try:
            # 初始化浏览器
            if not self.browser.init_browser():
                logger.error("无法初始化浏览器，程序退出")
                return

            # 打开网站
            logger.info(f"打开网站: {self.base_url}")
            self.browser.driver.get(self.base_url)
            time.sleep(2)  # 初始加载等待

            # 执行登录流程
            if not self._login():
                logger.error("登录失败，程序退出")
                return

            # 登录成功后， 点击我的订单  跳转页面
            if not self.browser.safe_click_element(*self.locators['my_order']):
                return False

            order_status = get_order_status(self.browser, content)
            print("!!!!!!!!!!")
            print(content)
            if order_status:
                print(f"!!!!!!!!!!!订单的状态是：{order_status}")
                # 判断状态：准备成功则继续，准备中则退出程序
                if order_status == "准备中":
                    logger.info("订单状态为【准备中】，停止程序")
                    sys.exit(0)  # 正常退出程序
            else:
                print(f"未找到订单")
                logger.error("未找到目标订单，停止程序")
                if self.browser.driver:
                    self.browser.driver.quit()
                sys.exit(1)  # 异常退出


            # 点击文件按钮并读取内容
            logger.info("开始点击文件按钮并读取内容")
            result = self.browser.click_and_read_content(self.locators['file_button'])

            # 调用封装后的函数处理结果
            self.process_result(result)

        except Exception as e:
            logger.error(f"程序运行出错: {str(e)}")
            logger.error(traceback.format_exc())
        finally:
            # 可以根据需要决定是否关闭浏览器
            # if self.browser.driver:
            #     self.browser.driver.quit()
            pass

        # 封装的核心函数：处理读取结果（原代码中这部分逻辑）

    def process_result(self, result):
        """处理从文件或页面提取的结果，提取并下载HDF链接"""
        if not result:
            logger.warning("无有效结果可处理")
            return

        save_dir = self.config.get_download_dir()
        # 初始化下载统计
        total_downloads = 0
        successful_downloads = 0
        failed_downloads = 0

        # 根据结果类型处理（文件或页面）
        if result['type'] == 'file':
            logger.info("成功获取下载的txt文件内容")
            raw_text = result['raw_content'].strip()
            # 提取HTTP和FTP链接
            http_matches, ftp_matches = self.extract_links(raw_text)
            # 下载链接
            total_downloads, successful_downloads, failed_downloads = self.download_links(
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
            self.download_links_page(http_matches, ftp_matches, save_dir)

        # 输出下载统计（仅文件类型需要）
        if result['type'] == 'file':
            logger.info(
                f"下载完成统计: 总计{total_downloads}个文件, 成功{successful_downloads}个, 失败{failed_downloads}个")
            if successful_downloads > 0:
                logger.info(f"✅ 成功下载{successful_downloads}个HDF文件！")
            if failed_downloads > 0:
                logger.error(f"❌ {failed_downloads}个HDF文件下载失败！")

    def extract_links(self, raw_text):
        """提取文本中的HTTP和FTP链接（复用正则逻辑）"""
        # 识别HTTP链接
        http_pattern = r'http://[^\s"]+\.HDF(?:\?[^\s"]+)?'
        http_matches = re.findall(http_pattern, raw_text, re.IGNORECASE)
        # 识别FTP链接
        ftp_pattern = r'ftp://(?:[^\s:@]+:[^\s:@]+@)?[^\s/]+/[^\s"]+\.HDF'
        ftp_matches = re.findall(ftp_pattern, raw_text, re.IGNORECASE)
        return http_matches, ftp_matches

    def download_links(self, http_matches, ftp_matches, save_dir):
        """下载文件类型结果中的链接（带统计）"""
        total = len(http_matches) + len(ftp_matches)
        success = 0
        failed = 0

        # 下载HTTP链接
        if http_matches:
            logger.info(f"从txt文件中提取到{len(http_matches)}个HTTP格式HDF链接，开始下载...")
            for i, hdf_url in enumerate(http_matches, 1):
                logger.info(f"正在下载第{i}/{len(http_matches)}个HTTP链接: {hdf_url}")
                if download_http_file(hdf_url, save_dir):
                    success += 1
                    logger.info(f"✅ 第{i}个HTTP链接下载成功: {hdf_url}")
                else:
                    failed += 1
                    logger.error(f"❌ 第{i}个HTTP链接下载失败: {hdf_url}")

        # 下载FTP链接
        if ftp_matches:
            logger.info(f"从txt文件中提取到{len(ftp_matches)}个FTP格式HDF链接，开始下载...")
            for i, hdf_url in enumerate(ftp_matches, 1):
                logger.info(f"正在下载第{i}/{len(ftp_matches)}个FTP链接: {hdf_url}")
                if download_ftp_with_progress(hdf_url, save_dir):
                    success += 1
                    logger.info(f"✅ 第{i}个FTP链接下载成功: {hdf_url}")
                else:
                    failed += 1
                    logger.error(f"❌ 第{i}个FTP链接下载失败: {hdf_url}")

        # 未识别到链接的处理
        if not http_matches and not ftp_matches:
            logger.error("未找到有效HDF链接（支持格式：HTTP带参数/纯链接、FTP带用户名/匿名登录）")
        return total, success, failed

    def download_links_page(self, http_matches, ftp_matches, save_dir):
        """下载页面类型结果中的链接（增加统计功能）"""
        total = len(http_matches) + len(ftp_matches)
        success = 0
        failed = 0

        if http_matches:
            logger.info(f"从页面中提取到{len(http_matches)}个HTTP格式HDF链接，开始下载...")
            for i, hdf_url in enumerate(http_matches, 1):
                logger.info(f"正在下载第{i}/{len(http_matches)}个HTTP链接: {hdf_url}")
                if download_http_file(hdf_url, save_dir):
                    success += 1
                    logger.info(f"✅ 第{i}个HTTP链接下载成功: {hdf_url}")
                else:
                    failed += 1
                    logger.error(f"❌ 第{i}个HTTP链接下载失败: {hdf_url}")

        if ftp_matches:
            logger.info(f"从页面中提取到{len(ftp_matches)}个FTP格式HDF链接，开始下载...")
            for i, hdf_url in enumerate(ftp_matches, 1):
                logger.info(f"正在下载第{i}/{len(ftp_matches)}个FTP链接: {hdf_url}")
                if download_ftp_with_progress(hdf_url, save_dir):
                    success += 1
                    logger.info(f"✅ 第{i}个FTP链接下载成功: {hdf_url}")
                else:
                    failed += 1
                    logger.error(f"❌ 第{i}个FTP链接下载失败: {hdf_url}")

        # 输出汇总统计
        if total == 0:
            logger.error("页面中未找到有效HDF链接")
        else:
            logger.info(f"页面链接处理完成：总计{total}个文件, 成功{success}个, 失败{failed}个")
            if success > 0:
                logger.info(f"✅ 成功下载{success}个HDF文件！")
            if failed > 0:
                logger.error(f"❌ {failed}个HDF文件下载失败！")


    def _login(self):
        """ 执行登录流程（增加验证码错误重试逻辑） """
        logger.info("开始登录流程")
        max_login_retries = self.config.get_retry_attempts()  # 从配置文件获取最大重试次数（与原重试次数一致）

        # 1. 先点击登录按钮（仅需点击一次，弹出登录弹窗）
        if not self.browser.safe_click_element(*self.locators['login_button']):
            return False


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
    if len(sys.argv) < 2:
        print("错误：未收到时间参数")
        sys.exit(1)

    txt_order_path = sys.argv[1]

    with open(txt_order_path, 'r', encoding='utf-8') as f:
        content = f.read()  # 读取全部内容
        # 可选：去除首尾空白（如换行符、空格）
        content = content.strip()
        print("从txt里面读取的内容："+content)
    downloader = SatelliteDataDownloader()
    downloader.run(content)
    logger.info("===== 订单下载完成了 =====")





