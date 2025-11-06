# 导入所需库
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
import sys
import logging
import configparser
from pathlib import Path
import traceback
from webdriver_manager.chrome import ChromeDriverManager  # 自动管理chromedriver
from ftplib import FTP
from urllib.parse import urlparse
'''
从textt中导入ftp下载方法
'''
from config_handler import ConfigHandler

# 设置日志文件路径
log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "submit_order.log")

# 配置基础日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8', mode='a'),  # 使用'mode='w''确保每次运行重新写入
        logging.StreamHandler()
    ],
    force=True  # 强制重新配置
)
# 获取logger
logger = logging.getLogger(__name__)

# 测试日志系统
logger.info("=== 日志系统初始化 ===")
logger.info(f"日志文件路径: {log_file}")
logger.info(f"当前工作目录: {os.getcwd()}")


# 浏览器操作类
class SatelliteBrowser:
    def __init__(self, config):
        self.config = config  # 日志配置
        self.driver = None
        self.wait = None
        self.timeout = config.get_timeout()
        self.retry_attempts = config.get_retry_attempts()
        self.ocr = ddddocr.DdddOcr()

    def init_browser(self):
        """初始化浏览器"""
        try:
            # 1创建设置浏览器对象
            chrome_options = Options()
            # 2基本配置
            chrome_options.page_load_strategy = 'eager'  # 或 'normal' 页面加载策略设置为"急切"模式
            chrome_options.add_argument('--disable-background-timer-throttling')  #禁用后台标签页的定时器节流
            chrome_options.add_argument('--disable-renderer-backgrounding')  #禁用渲染进程的后台降级

            chrome_options.add_argument('--no-sandbox')  # 禁用 Chrome 的沙箱模式。
            chrome_options.add_argument('--window-size=1920,1080')  # 指定浏览器窗口的初始尺寸为 1920x1080 像素
            chrome_options.add_argument('--disable-gpu')  # 禁用 GPU 加速
            chrome_options.add_argument('--disable-dev-shm-usage')  # 禁用 /dev/shm 临时目录的使用（Linux 系统特有）。
            chrome_options.add_argument('--ignore-certificate-errors')  # 忽略 SSL 证书错误。
            chrome_options.add_experimental_option('detach', True)  # # 保持浏览器打开状态,让Chrome浏览器在自动化脚本执行完毕后不自动关闭。

            # # 关键：启用无头模式（不显示浏览器窗口）
            # chrome_options.add_argument('--headless=new')  # Chrome 112+ 推荐的新无头模式
            # # 兼容旧版本 Chrome 可加：chrome_options.add_argument('--headless')

            # 设置Chrome驱动
            driver_path = self.config.get_chrome_driver_path()   # 从配置文件中获取驱动文件的path
            if driver_path and os.path.exists(driver_path):
                service = Service(driver_path)  # 用于管理 Chrome驱动程序的进程
            else:
                # 自动下载并使用合适版本的chromedriver
                service = Service(ChromeDriverManager().install())
                logger.info("使用自动管理的ChromeDriver")

            # 创建并启动浏览器    设置等待
            self.driver = webdriver.Chrome(service=service, options=chrome_options)  # 传入自定义的Service对象，chrome_options对象
            self.driver.implicitly_wait(self.timeout)  # 设置隐式等待
            self.wait = WebDriverWait(self.driver, self.timeout)  # 创建显式等待对象

            logger.info("浏览器初始化成功")
            return True

        except Exception as e:
            logger.error(f"浏览器初始化失败: {str(e)}")
            logger.error(traceback.format_exc())    # 将程序运行时的错误堆栈信息详细记录到日志中
            return False

    def safe_find_element(self, by, value, retry=0):
        """
        安全查找元素，带重试机制
         Args:
        by: 元素定位方式（如 By.ID、By.XPATH、By.CSS_SELECTOR 等）
        value: 定位方式对应的值（如 ID 属性值、XPath 表达式等）
        retry: 当前重试次数，默认为 0（表示首次尝试）
        """
        try:
            return self.wait.until(EC.presence_of_element_located((by, value)))  # 使用创建的显式等待对象 self.wait等待元素「出现」
        except (TimeoutException, StaleElementReferenceException) as e:  # 捕获两种异常：显式等待超时和元素已失效（如页面刷新导致元素被重新渲染）
            if retry < self.retry_attempts:
                logger.warning(f"查找元素失败，重试 {retry + 1}/{self.retry_attempts} - {by}: {value}")
                time.sleep(1)
                return self.safe_find_element(by, value, retry + 1)
            logger.error(f"多次尝试后仍无法找到元素: {by}: {value}")
            logger.error(traceback.format_exc())
            return None

    # def safe_click_element(self, by, value, retry=0):
    #     """安全点击元素，带重试机制"""
    #     try:
    #         element = self.wait.until(EC.element_to_be_clickable((by, value)))
    #         element.click()
    #         logger.info(f"成功点击元素: {by}: {value}")
    #         return True
    #     except (TimeoutException, ElementClickInterceptedException, StaleElementReferenceException) as e:  # 捕获三种异常：超时异常 元素点击被拦截异常 元素过时异常
    #         if retry < self.retry_attempts:
    #             logger.warning(f"点击元素失败，重试 {retry + 1}/{self.retry_attempts} - {by}: {value}")
    #             # 尝试滚动到元素
    #             try:
    #                 element = self.driver.find_element(by, value)  # 简单的查找元素 不是自己写的safe查找
    #                 self.driver.execute_script("arguments[0].scrollIntoView();", element)  # 这段代码可以确保元素进入视野，再进行后续操作
    #                 time.sleep(1)
    #             except:
    #                 pass
    #             return self.safe_click_element(by, value, retry + 1)
    #         logger.error(f"多次尝试后仍无法点击元素: {by}: {value}")
    #         logger.error(traceback.format_exc())
    #         return False

    def safe_click_element(self, by, value, retries=3, wait=1):
        for i in range(retries):
            try:
                element = WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((by, value)))
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
            logger.info("使用JS点击成功")
            return True
        except Exception as e:
            logger.error(f"多次尝试后仍无法点击元素: {by}: {value}")
            logger.error(e)
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

    def safe_send_keys1(self, by, value, text):
        try:
            # 使用浏览器类中已定义的显式等待对象（self.browser.wait）
            element = self.wait.until(
                EC.visibility_of_element_located((by, value))
            )
            # 对 readonly 元素，用 JS 设置值
            self.driver.execute_script(f"arguments[0].value = '{text}';", element)
            logger.info(f"成功通过JS设置文本到元素: {by}: {value}")  # 增加日志
            return True
        except Exception as e:
            logger.error(f"JS设置文本失败：{e}")  # 使用logger而非print
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


# 主程序类
class SatelliteDataDownloader:
    def __init__(self):
        self.config = ConfigHandler()
        self.browser = SatelliteBrowser(self.config)  # SatelliteBrowser是上面自定义的浏览器类
        self.user_info = self.config.get_user_info()  # 自定义函数在 config_handler里面  获取账号密码
        self.base_url = 'https://satellite.nsmc.org.cn/DataPortal/cn/home/index.html'  # 风云卫星主网页

        # 页面元素定位符
        self.locators = {
            # 登录
            'login_button': (By.XPATH, '//*[@id="common-login"]'),   # 点击“登录”
            'username_input': (By.XPATH, '//*[@id="inputUserNameCN"]'),  # 输入用户名
            'password_input': (By.XPATH, '//*[@id="inputPasswordCN"]'),  # 输入密码
            'captcha_image': (By.XPATH, '//*[@id="logincn"]/div[2]/div/div/div[2]/div[2]/div[4]/div/img'),  # 验证码图像
            'captcha_input': (By.XPATH, '//*[@id="inputValidateCodeCN"]'),  # 输入验证码
            'submit_login': (By.XPATH, '//*[@id="logincn"]/div[2]/div/div/div[2]/div[2]/div[6]/button'),  # 点击“登录”

            # 卫星选择
            'FengYun_satellite': (By.XPATH, '/html/body/div[4]/div[4]/div[1]/div/div[1]/div[1]/ul/li[2]'),  # 点击“风云极轨卫星”
            'fy3d_satellite': (By.XPATH, '/html/body/div[4]/div[4]/div[1]/div/div[1]/div[3]/ul/li[4]'),   # FY-3D
            'fy3e_satellite': (By.XPATH, '/html/body/div[4]/div[4]/div[1]/div/div[1]/div[3]/ul/li[3]'),   # FY-3E
            'level1_data': (By.XPATH, '/html/body/div[4]/div[4]/div[1]/div/div[1]/div[4]/ul/li[1]'),   # 1级数据
            'data_type_select': (By.XPATH, '//*[@id="select2-sel-dataType-container"]'),     # 点击“数据名称”白框
            'choose_MERSI': (By.XPATH, '/html/body/span/span/span[2]/ul/li[1]'),  # 数据名称中选择MERSI
            'choose_MERSI_3e': (By.XPATH, '/html/body/span/span/span[2]/ul/li[3]'), # 数据名称中选择MERSI 3e里面的
            'choose_MERSI_3e1': (By.XPATH,'//ul[contains(@id, "select2-sel-dataType-results")]//li[contains(text(), "中分辨率光谱成像仪(MERSI)")]'),

            'click_GeographicalRange': (By.XPATH, '//*[@id="txt-spaceArea"]'),     # 点击 空间范围
            # 输入空间范围数据
            'N_degree': (By.XPATH, '//*[@id="other-North_D"]'),
            'N_minute': (By.XPATH, '//*[@id="other-North_M"]'),
            'W_degree': (By.XPATH, '//*[@id="other-West_D"]'),
            'W_minute': (By.XPATH, '//*[@id="other-West_M"]'),
            'E_degree': (By.XPATH, '//*[@id="other-East_D"]'),
            'E_minute': (By.XPATH, '//*[@id="other-East_M"]'),
            'S_degree': (By.XPATH, '//*[@id="other-South_D"]'),
            'S_minute': (By.XPATH, '//*[@id="other-South_M"]'),
            'click_displayRange': (By.XPATH, '//*[@id="other-GISWebLocation"]/input'),  # 点击显示该范围
            'click_confirm1': (By.XPATH, '//*[@id="btn-space-area-confirm"]'),  # 点击确定

            'search_button': (By.XPATH, '//*[@id="btn-search"]'),     # 点击"检索"

            # 数据筛选
            # 选择产品
            'click_productName': (By.XPATH, '//*[@id="menuProNames"]'),  # 点击 ”产品名“
            'disChoose_250data': (By.XPATH, '//*[@id="fileListHead"]/th[3]/div/ul/li[3]/a/input'),  # 取消选择250m的卫星数据
            'click_filter': (By.XPATH, '//*[@id="searchId"]'),  # 点击"筛选”

            'second_data_row': (By.XPATH, '/html/body/div[9]/div/div[2]/div/div[2]/div[2]/div/table/tbody/tr[2]/td[1]/input'),  # 第二个多选框
            'page_all_choose':(By.XPATH,'//*[@id="seleCurrentPage1"]'),
            'commit_edit': (By.XPATH, '//*[@id="commitEdit"]'),   # 去购物车
            'send_email_checkbox': (By.XPATH, '//*[@id="chkIsSendMail"]'),   # 发邮件
            'submit_order': (By.XPATH, '/html/body/div[4]/div/div[3]/div[2]/div[2]/div[4]/button'),  # 提交订单

            'check_order' : (By.XPATH ,'//*[@id="submit-order"]/div[2]/div/div[3]/button[1]'),  # 看订单状态

            # 全部选择
            'click_AllChoose': (By.XPATH, '//*[@id="allSele1"]'),  # 点击"全部选择"

            'beginDate': (By.XPATH, '//*[@id="c-beginDate"]'),  # 开始时间
            'endDate': (By.XPATH, '//*[@id="c-endDate"]'),  # 结束时间

        }

    def run(self,time_param,time_param2,North,South,East,West,selected_text_comboBox):
        """运行主程序"""
        try:
            # 初始化浏览器
            if not self.browser.init_browser():
                logger.error("[错误]无法初始化浏览器，程序退出")
                sys.exit(1)  # 非0退出码（1表示浏览器初始化失败）

            # 打开网站
            logger.info(f"正在打开网站，网址为： {self.base_url}")
            self.browser.driver.get(self.base_url)
            time.sleep(3)  # 初始加载等待

            # 执行登录流程
            if not self._login():
                logger.error("[错误]登录失败，程序退出")
                sys.exit(2)  # 2表示登录失败

            # 选择卫星数据
            if not self._select_satellite_data(selected_text_comboBox):
                logger.error("[错误]选择卫星数据失败，程序退出")
                sys.exit(3)  # 3表示卫星选择失败

            # 选择地理范围
            if not self._select_Range(time_param,time_param2,North,South,East,West):
                logger.error("[错误]选择地理范围失败，程序退出")
                sys.exit(4)  # 4表示地理范围选择失败

            # 提交订单
            if not self._submit_order():
                logger.error("[错误]提交订单失败，程序退出")
                sys.exit(5)  # 5表示订单提交失败

            # 查看订单
            if not self._check_order():
                logger.error("[错误]查看订单失败，程序退出")
                sys.exit(6)  # 6表示查看订单失败
            logger.info("[流程]提交订单所有操作完成")

            sys.exit(0)  # 全部成功，显式返回0

        except Exception as e:
            logger.error(f"[错误]程序运行出错: {str(e)}")
            logger.error(traceback.format_exc())
        finally:
            # 可以根据需要决定是否关闭浏览器
            # if self.browser.driver:
            #     self.browser.driver.quit()
            pass

    def _login(self):
        logger.info("[流程]开始登录流程......")
        max_login_retries = self.config.get_retry_attempts()

        # 1. 在主网页寻找并点击登录按钮
        if not self.browser.safe_click_element(*self.locators['login_button']):
            return False

        # 2. 循环重试登录
        for retry in range(max_login_retries):
            try:
                # 步骤1：首次输入用户名密码
                if retry == 0:
                    if not self.browser.safe_send_keys(*self.locators['username_input'], self.user_info['username']):
                        continue
                    if not self.browser.safe_send_keys(*self.locators['password_input'], self.user_info['password']):
                        continue

                # 步骤2：处理验证码
                captcha_input = self.browser.safe_find_element(*self.locators['captcha_input'])
                if captcha_input:
                    captcha_input.clear()
                    time.sleep(0.5)

                captcha_text = self.browser.solve_captcha(self.locators['captcha_image'][1])
                if not captcha_text:
                    logger.warning(f"验证码识别失败，重试 {retry + 1}/{max_login_retries}")
                    continue

                if not self.browser.safe_send_keys(*self.locators['captcha_input'], captcha_text):
                    logger.warning(f"验证码输入失败，重试 {retry + 1}/{max_login_retries}")
                    continue

                # 步骤3：提交登录
                if not self.browser.safe_click_element(*self.locators['submit_login']):
                    logger.warning(f"登录提交失败，重试 {retry + 1}/{max_login_retries}")
                    continue
                time.sleep(3)

                # 步骤4：验证登录成功（只查1次，不抛异常）
                try:
                    fengyun_element = WebDriverWait(self.browser.driver, 3).until(
                        EC.presence_of_element_located(self.locators['FengYun_satellite'])
                    )
                    logger.info("[流程]成功找到'风云极轨卫星'元素，登录成功")
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


    def _select_satellite_data(self,selected_text_comboBox):
        """选择卫星数据"""
        logger.info("[流程]开始选择卫星数据......")
        time.sleep(3)
        # 选择风云极轨卫星
        if not self.browser.safe_click_element(*self.locators['FengYun_satellite']):
            return False


        # 选择卫星 是3D还是3E
        if selected_text_comboBox.split(":",1)[0] == "FY-3D" :
            if not self.browser.safe_click_element(*self.locators['fy3d_satellite']):
                return False

        elif selected_text_comboBox.split(":",1)[0] == "FY-3E":
            if not self.browser.safe_click_element(*self.locators['fy3e_satellite']):
                return False

        # 选择1级数据
        if not self.browser.safe_click_element(*self.locators['level1_data']):
            return False
        # 等待数据名称 可见
        if not self.browser.safe_click_element(*self.locators['data_type_select']):
            return False
        # self.browser.wait.until(
        #     EC.presence_of_element_located(self.locators['data_type_select'])
        # )
        # time.sleep(2)
        # # 点击数据名称框
        # # 定位触发按钮（通过容器 id 找子元素）
        # trigger = WebDriverWait(self.browser.driver, 10).until(
        #     EC.element_to_be_clickable(
        #         (By.XPATH,'//*[@id="select2-sel-dataType-container"]')
        #     )
        # )
        # trigger.click()
        # # 等待下拉框展开（验证选项列表可见）
        # WebDriverWait(self.browser.driver, 10).until(
        #     EC.visibility_of_element_located(
        #         (By.XPATH,'/html/body/span/span')
        #     )
        # )
        time.sleep(2)  # 给下拉框展开动画留时间

        # 选择MERSI
        if selected_text_comboBox.split(":", 1)[0] == "FY-3D":
            if not self.browser.safe_click_element(*self.locators['choose_MERSI']):
                return False

        elif selected_text_comboBox.split(":", 1)[0] == "FY-3E":
            if not self.browser.safe_click_element(*self.locators['choose_MERSI_3e1']):
                return False



        logger.info("[流程卫星数据选择完成")
        return True

    def _select_Range(self,time_param,time_param2,North,South,East,West):
        """空间范围选择"""
        logger.info("[流程]开始选择空间范围......")
        #点击 “空间范围”
        time.sleep(2)
        # 等待下拉菜单消失
        time.sleep(0.5)  # 给动画一点缓冲时间

        if not self.browser.safe_click_element(*self.locators['click_GeographicalRange']):
            return False
        # 输入坐标
        if not self.browser.safe_send_keys(*self.locators['N_degree'], South.split(".",1)[0]):   # 60
            return False
        if not self.browser.safe_send_keys(*self.locators['N_minute'], South.split(".",1)[1]):   # 00
            return False
        if not self.browser.safe_send_keys(*self.locators['W_degree'], West.split(".",1)[0]):
            return False
        if not self.browser.safe_send_keys(*self.locators['W_minute'], West.split(".",1)[1]):
            return False
        if not self.browser.safe_send_keys(*self.locators['E_degree'], East.split(".",1)[0]):
            return False
        if not self.browser.safe_send_keys(*self.locators['E_minute'], East.split(".",1)[1]):
            return False
        if not self.browser.safe_send_keys(*self.locators['S_degree'], North.split(".",1)[0]):
            return False
        if not self.browser.safe_send_keys(*self.locators['S_minute'], North.split(".",1)[1]):
            return False
        # 点击显示范围  点击确定
        if not self.browser.safe_click_element(*self.locators['click_displayRange']):
            return False
        if not self.browser.safe_click_element(*self.locators['click_confirm1']):
            return False

        # 输入开始日期 结束日期
        if not self.browser.safe_send_keys1(*self.locators['beginDate'],time_param):
            return False
        if not self.browser.safe_send_keys1(*self.locators['endDate'], time_param2):
            return False
        time.sleep(0.5)


        logger.info("[流程]空间范围选择完成")
        return True

    def _submit_order(self):
        """提交订单"""
        logger.info("[流程]开始筛选数据提交订单......")
        time.sleep(2)
        # 点击检索
        if not self.browser.safe_click_element(*self.locators['search_button']):
            return False
        time.sleep(3)  # 等待搜索结果
        #  筛选数据
        # 点击”产品名“
        if not self.browser.safe_click_element(*self.locators['click_productName']):
            return False
        # 取消250数据
        if not self.browser.safe_click_element(*self.locators['disChoose_250data']):
            return False
        # 点击筛选
        if not self.browser.safe_click_element(*self.locators['click_filter']):
            return False
        # 选中第二个数据
        if not self.browser.safe_click_element(*self.locators['second_data_row']):
            return False
        # if not self.browser.safe_click_element(*self.locators['page_all_choose']):
        #     return False
        # 去购物车
        if not self.browser.safe_click_element(*self.locators['commit_edit']):
            return False
        # 勾选发送确认邮件
        if not self.browser.safe_click_element(*self.locators['send_email_checkbox']):
            return False
        # 提交订单
        if not self.browser.safe_click_element(*self.locators['submit_order']):
            return False
        time.sleep(1)
        # 等待模态框加载完成，获取所有订单号元素
        try:
            # 关键：用find_elements（复数）定位所有class="order-code"的元素，且限定在模态框内
            order_code_elements = WebDriverWait(self.browser.driver, 10).until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, "#submit-order .order-code")  # 定位模态框内所有符合条件的元素
                )
            )

            # 遍历元素，提取所有订单号文本，存入列表
            all_order_ids = [element.text for element in order_code_elements]
            print("!!!!!!!")
            print(all_order_ids)
            # 写入指定TXT文件（例如：order_ids.txt）
            with open("D:/Pycharmcode/test/download.txt", "w", encoding="utf-8") as f:
                # 每个订单号占一行
                for order_id in all_order_ids:
                    f.write(f"{order_id}\n")

            logger.info(f"成功写入{len(all_order_ids)}个订单号到download.txt")

        except Exception as e:
            logger.error(f"获取订单号失败：{e}")


        logger.info("[流程]筛选数据提交订单完成")
        return True

    def _check_order(self):
        """检查订单"""
        logger.info("[流程]开始查看订单......")

        if not self.browser.safe_click_element(*self.locators['check_order']):
            return False

        logger.info("[流程]查看订单完成")
        return True

    def update_ini_from_external(self, external_save_dir):
        """
        根据外部传递的下载目录更新INI配置文件中的download_dir和listen_dir字段
        Args:
            external_save_dir: 外部传递的下载目录路径（字符串）
        Returns:
            bool: 更新成功返回True，失败返回False
        """
        try:
            # 1. 验证外部目录的有效性（确保路径存在，不存在则创建）
            if not os.path.exists(external_save_dir):
                os.makedirs(external_save_dir, exist_ok=True)  # exist_ok=True避免目录已存在时报错
                logger.info(f"外部目录不存在，已自动创建：{external_save_dir}")

            # 2. 调用ConfigHandler的方法修改配置（需先在ConfigHandler中添加set_config_value方法）
            # 更新下载目录（download_dir）
            success_download = self.config.set_config_value(
                section='SETTINGS',
                key='download_dir',
                value=external_save_dir
            )

            # 3. 验证是否全部更新成功
            if success_download :
                logger.info(f"已将配置文件中的下载目录更新为：{external_save_dir}")
                return True
            else:
                logger.error("更新配置文件中的下载目录失败")
                return False

        except Exception as e:
            logger.error(f"更新INI文件时发生错误：{str(e)}")
            logger.error(traceback.format_exc())  # 记录详细堆栈信息
            return False


    # 主程序入口
if __name__  ==  "__main__":


    # 获取传递的参数（sys.argv[1] 对应 time_param）
    if len(sys.argv) < 2:
        logger.info("错误：未收到时间参数")
        sys.exit(1)
    #   开始时间
    time_param = sys.argv[1]
    time_param2 = sys.argv[2]
    North  =sys.argv[3]
    South =sys.argv[4]
    East =sys.argv[5]
    West = sys.argv[6]
    selected_text_comboBox =sys.argv[7]
    external_save_dir=sys.argv[8]


    logger.info("[流程]订单提交程序启动......")
    downloader = SatelliteDataDownloader()

    if not downloader.update_ini_from_external(external_save_dir):
        logger.error("[错误]INI文件更新失败，程序退出")
        sys.exit(1)

    downloader.run(time_param,time_param2,North,South,East,West,selected_text_comboBox)



    # # 1. 替换为你的FTP链接（注意：XX0_DBwJ需替换为真实密码）
    # your_ftp_url = "ftp://A202509250821065252:XX0_DBwJ@ftp.nsmc.org.cn/FY3D_IPMNT_GBAL_L1_20250925_0247_030KM_MS.HDF"
    # # 2. 替换为你的本地保存目录（如Windows路径：D:/FY3D_Data，Mac/Linux路径：/home/user/FY3D_Data）
    # local_save_directory = "D:/FYData"
    #
    # # 3. 执行下载
    # download_ftp_file(your_ftp_url, local_save_directory)





