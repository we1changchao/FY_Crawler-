# region 导入库
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (TimeoutException,NoSuchElementException,ElementClickInterceptedException, StaleElementReferenceException)
from selenium.webdriver.common.keys import Keys
import ddddocr
import time
import os
from PIL import Image
import io
import sys
import logging
import configparser
from pathlib import Path
import traceback
from webdriver_manager.chrome import ChromeDriverManager
from ftplib import FTP
from urllib.parse import urlparse
from config_handler import ConfigHandler   # 从config_handler.py中导入ConfigHandler类
# endregion

# region 基础日志配置
log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "submit_order.log")  # 设置日志文件路径

# 配置基础日志
logging.basicConfig(
    level=logging.INFO,  # 仅输出 ≥ INFO 级别的日志
    format='%(asctime)s - %(levelname)s - %(message)s',  # 定义输出格式
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8', mode='w'),  # 配置覆盖写
        logging.StreamHandler()    # 配置输出到控制台
    ],
    force=True  # 强制重新配置
)
# 获取logger
logger = logging.getLogger(__name__)

# 测试日志系统
logger.info("=== 日志初始化成功 ===")
# endregion

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
        # region 初始化浏览器
        try:
            chrome_options = Options()  # 创建设置浏览器对象
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

            # # 关键：启用无头模式（不显示浏览器窗口）
            # chrome_options.add_argument('--headless=new')  # Chrome 112+ 推荐的新无头模式
            # # 兼容旧版本 Chrome 可加：chrome_options.add_argument('--headless')

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
            logger.error(f"[错误]浏览器初始化失败--{str(e)}")
            # logger.error(traceback.format_exc())    # 将程序运行时的错误堆栈信息详细记录到日志中
            return False
        # endregion

    def safe_find_element(self, by, value, retry=0):
        # region 安全查找元素，带重试机制
        """
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
            logger.error(f"[错误]多次尝试查找，但是失败了")
            # logger.error(traceback.format_exc())
            return None
        # endregion

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
                logger.info(f"点击了元素{value}")
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
            logger.error(f"[错误]多次尝试点击，但是失败了")
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
            logger.error(f"[错误]多次尝试后仍无法输入文本到元素，但是失败了")
            # logger.error(traceback.format_exc())
            return False
         #endregion

    def safe_send_keys1(self, by, value, text):
        # region 专门用于日期输入
        try:
            # 使用浏览器类中已定义的显式等待对象（self.browser.wait）
            element = self.wait.until(
                EC.visibility_of_element_located((by, value))
            )
            # 对 readonly 元素，用 JS 设置值
            self.driver.execute_script(f"arguments[0].value = '{text}';", element)
            logger.info(f"成功通过JS设置文本到元素-- {by}: {value}")  # 增加日志
            return True
        except Exception as e:
            logger.error(f"JS设置文本失败--{e}")
            return False
        # endregion

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
            # logger.error(traceback.format_exc())
            return None
        # endregion


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
            'choose_MERSI_3e': (By.XPATH, '/html/body/span/span/span[2]/ul/li[3]'),  # 数据名称中选择MERSI 3e里面的
            'choose_MERSI_3e1': (By.XPATH,'//ul[contains(@id, "select2-sel-dataType-results")]//li[contains(text(), "中分辨率光谱成像仪(MERSI)")]'),  # 数据名称中选择MERSI 3e里面的


            # 输入空间范围数据
            'click_GeographicalRange': (By.XPATH, '//*[@id="txt-spaceArea"]'),  # 点击 空间范围
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
            'disChoose_250data': (By.XPATH, '//*[@id="fileListHead"]/th[3]/div/ul/li[3]/a/input'),  # 取消选择250m的卫星数据 也就是3D的第三个
            '3E_delete4': (By.XPATH, '//*[@id="fileListHead"]/th[3]/div/ul/li[4]/a/input'),  # 产品名去第4个
            '3E_delete1': (By.XPATH, '//*[@id="fileListHead"]/th[3]/div/ul/li[1]/a/input'),  # 产品名去第1个
            '3D_delete3': (By.XPATH, '//*[@id="fileListHead"]/th[3]/div/ul/li[3]/a/input'),  # 产品名去第3个

            'choseAll': (By.XPATH, '//*[@id="allSele1"]'),  # 全部选择

            'click_filter': (By.XPATH, '//*[@id="searchId"]'),  # 点击"筛选”
            'commit_edit': (By.XPATH, '//*[@id="commitEdit"]'),   # 去购物车
            'submit_order': (By.XPATH, '/html/body/div[4]/div/div[3]/div[2]/div[2]/div[4]/button'),  # 提交订单
            'check_order' : (By.XPATH ,'//*[@id="submit-order"]/div[2]/div/div[3]/button[1]'),  # 看订单状态

            'beginDate': (By.XPATH, '//*[@id="c-beginDate"]'),  # 开始时间
            'endDate': (By.XPATH, '//*[@id="c-endDate"]'),  # 结束时间

            'deleteWindow': (By.XPATH, '//*[@id="fileListModal"]/div[2]/div/div[1]/button/span'),  # 关闭模态框

            'page_all_choose': (By.XPATH, '//*[@id="seleCurrentPage1"]'),  # 选择本页全部
            'second_data_row': (By.XPATH, '/html/body/div[9]/div/div[2]/div/div[2]/div[2]/div/table/tbody/tr[2]/td[1]/input'),  # 第二个多选框

        }

    def run(self,time_param,time_param2,North,South,East,West,selected_text_comboBox):
        # region 运行主程序
        try:
            # 初始化浏览器
            if not self.browser.init_browser():
                logger.error("[错误]无法初始化浏览器，程序退出")
                sys.exit(1)  # 1表示浏览器初始化失败

            # 打开网站
            logger.info(f"[流程]正在打开风云卫星数据网站......")
            self.browser.driver.get(self.base_url)
            time.sleep(3)

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
            if not self._submit_order(time_param,time_param2,North,South,East,West):
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
            if self.browser.driver:
                self.browser.driver.quit()
            pass
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

                # ④验证登录是否成功  看是否能找到”风云极轨卫星“的元素
                try:
                    fengyun_element = WebDriverWait(self.browser.driver, 3).until(
                        EC.presence_of_element_located(self.locators['FengYun_satellite'])
                    )
                    logger.info("成功找到'风云极轨卫星'元素登录成功")
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

    def _select_satellite_data(self,selected_text_comboBox):
        # region 选择FY3D卫星的 时间+空间范围
        logger.info("[流程]开始选择卫星数据......")
        time.sleep(3)

        if not self.browser.safe_click_element(*self.locators['FengYun_satellite']):  # 选择“风云极轨卫星”
            return False
       # if selected_text_comboBox.split(":",1)[0] == "FY-3D" :
        if not self.browser.safe_click_element(*self.locators['fy3d_satellite']):  # 选择“FY-3D”      !!!
            return False
        if not self.browser.safe_click_element(*self.locators['level1_data']):  # 选择"1级数据"
            return False
        if not self.browser.safe_click_element(*self.locators['data_type_select']):  # 点击"数据名称"白框
            return False
        time.sleep(2)
        if not self.browser.safe_click_element(*self.locators['choose_MERSI']):  # 选择“MERSI”
            return False

        logger.info("[流程]FY-3D卫星数据筛选完成")
        return True
        # endregion

    def _select_Range(self,time_param,time_param2,North,South,East,West):
        # region 空间范围选择 +  时间输入
        logger.info("[流程]开始选择空间范围......")
        time.sleep(2.5)

        if not self.browser.safe_click_element(*self.locators['click_GeographicalRange']):  # 点击“空间范围”
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

        if not self.browser.safe_click_element(*self.locators['click_displayRange']):  # 点击“显示范围”
            return False
        if not self.browser.safe_click_element(*self.locators['click_confirm1']):  # 点击"确定“
            return False

        # 输入开始日期 结束日期
        if not self.browser.safe_send_keys1(*self.locators['beginDate'],time_param):  # 输入开始时间
            return False
        if not self.browser.safe_send_keys1(*self.locators['endDate'], time_param2):  # 输入结束时间
            return False
        time.sleep(0.5)


        logger.info("[流程]空间范围选择完成")
        return True
        # endregion

    def _submit_order(self,time_param,time_param2,North,South,East,West):
        # region 模态框筛选3D数据+选择3E数据+模态框筛选3E数据+提交订单+订单号写入txt
        logger.info("[流程]开始筛选数据提交订单......")
        time.sleep(2)

        if not self.browser.safe_click_element(*self.locators['search_button']):  # 点击"检索"
            return False
        time.sleep(3)

        #  筛选FY-3D数据
        if not self.browser.safe_click_element(*self.locators['click_productName']):  # 点击”产品名“
            return False
        if not self.browser.safe_click_element(*self.locators['disChoose_250data']):  # 取消第三个框
            return False
        if not self.browser.safe_click_element(*self.locators['click_filter']):  # 点击“筛选"
            return False
        if not self.browser.safe_click_element(*self.locators['choseAll']):  # 点击选中所有符合的项
            return False

        # 点× 关闭这个模态框
        if not self.browser.safe_click_element(*self.locators['deleteWindow']):
            return False

        # 选择FY-3E相关数据
        if not self.browser.safe_click_element(*self.locators['fy3e_satellite']):  # 选择“FY-3E”    ！！！接下来直接点击白框了
            return False
        if not self.browser.safe_click_element(*self.locators['data_type_select']):  # 点击"数据名称"白框
            return False
        if not self.browser.safe_click_element(*self.locators['choose_MERSI_3e1']):  # 选择"MERSI"
            return False

        self._select_Range(time_param, time_param2, North, South, East, West)  # 再选择一次空间和时间

        if not self.browser.safe_click_element(*self.locators['search_button']):  # 点击“检索”
            return False
        time.sleep(3)

        # 筛选"FY-3E"数据
        if not self.browser.safe_click_element(*self.locators['click_productName']):  # 点击“产品名”
            return False
        if not self.browser.safe_click_element(*self.locators['3E_delete4']):  # 取消不需要的数据分辨率
            return False
        if not self.browser.safe_click_element(*self.locators['3E_delete1']):
            return False
        if not self.browser.safe_click_element(*self.locators['click_filter']):  # 点击"筛选"
            return False
        if not self.browser.safe_click_element(*self.locators['choseAll']):  # 点击选中所有符合的项
            return False

        if not self.browser.safe_click_element(*self.locators['commit_edit']):  # 去购物车
            return False
        if not self.browser.safe_click_element(*self.locators['submit_order']):  # 提交订单
            return False
        time.sleep(1)

        # 等待模态框加载完成，获取所有订单号元素
        try:
            # 用find_elements（复数）定位所有class="order-code"的元素，且限定在模态框内   ！！！
            order_code_elements = WebDriverWait(self.browser.driver, self.config.get_timeout()).until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, "#submit-order .order-code")  # 定位模态框内所有符合条件的元素
                )
            )
            # 遍历元素，提取所有订单号文本，存入列表
            all_order_ids = [element.text for element in order_code_elements]

            # 获取相对路径，把这些订单号写入txt
            script_path = os.path.abspath(__file__)     # ！！！
            script_dir = os.path.dirname(script_path)
            order_file = os.path.join(script_dir, "download.txt")
            # 写入指定TXT文件
            with open(order_file, "w", encoding="utf-8") as f:
                # 每个订单号占一行
                for order_id in all_order_ids:
                    f.write(f"{order_id}\n")

            logger.info(f"成功写入{len(all_order_ids)}个订单号到download.txt")
        except Exception as e:
            logger.error("[错误]获取订单号失败")

        logger.info("[流程]筛选数据提交订单完成")
        return True
        # endregion

    def _check_order(self):
        # region 查看订单
        logger.info("[流程]开始查看订单......")

        if not self.browser.safe_click_element(*self.locators['check_order']):
            return False

        logger.info("[流程]查看订单完成")
        return True
        # endregion

    def update_ini_from_external(self, external_save_dir):
        # region更新数据下载路径
        """
        根据外部传递的下载目录更新INI配置文件中的download_dir
        Args:
            external_save_dir: 外部传递的下载目录路径（字符串）
        Returns:
            bool: 更新成功返回True，失败返回False
        """
        try:
            # 1.验证外部目录的有效性（确保路径存在，不存在则创建）
            if not os.path.exists(external_save_dir):
                os.makedirs(external_save_dir, exist_ok=True)  # exist_ok=True避免目录已存在时报错
                logger.info(f"外部目录不存在，已自动创建：{external_save_dir}")

            # 调用ConfigHandler的方法修改配置（ConfigHandler中的set_config_value方法）
            # 2.更新下载目录（download_dir）
            success_download = self.config.set_config_value(
                section='SETTINGS',
                key='download_dir',
                value=external_save_dir
            )

            # 3. 验证是否全部更新成功
            if success_download:
                logger.info(f"已将配置文件中的下载目录更新为：{external_save_dir}")
                return True
            else:
                logger.error("[错误]更新配置文件中的下载目录失败")
                return False

        except Exception as e:
            logger.error("[错误]更新配置文件时发生错误")
            # logger.error(traceback.format_exc())  # 记录详细堆栈信息
            return False
        # endregion

if __name__  ==  "__main__":
    #region main

    # 检验传递参数的个数
    if len(sys.argv) < 9:  # !!!
        logger.error("[错误]提交订单收到的参数不够")
        sys.exit(101)  # 101 参数不够返回

    time_param = sys.argv[1]  # 开始时间
    time_param2 = sys.argv[2]  # 结束时间
    North = sys.argv[3]  # 北纬
    South = sys.argv[4]  # 南纬
    East = sys.argv[5]  # 东经
    West = sys.argv[6]  # 西经
    selected_text_comboBox = sys.argv[7]  # 卫星数据类型
    external_save_dir = sys.argv[8]  # 文件下载位置

    logger.info("[流程]订单提交程序启动......")
    downloader = SatelliteDataDownloader()

    if not downloader.update_ini_from_external(external_save_dir):
        logger.error("[错误]配置文件文件更新失败，程序退出")
        sys.exit(102)  # 102 ini文件更新错误返回

    downloader.run(time_param,time_param2,North,South,East,West,selected_text_comboBox)
    # endregion







