# config_handler.py
import os
import configparser
import logging

logger = logging.getLogger(__name__)  # 初始化日志模块

class ConfigHandler:
    def __init__(self, config_file=None):  # 配置文件名
        # region  获取程序的路径 + 创建配置解析器实例 + 读取配置文件
        # 获取当前脚本（config_handler.py）所在的目录
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        # 确定最终的配置文件路径
        if config_file is None:
            self.config_file = os.path.join(self.script_dir, "config.ini")  # 拼接绝对路径
        else:
            # 若用户指定了路径，转换为绝对路径（避免相对路径问题）
            self.config_file = os.path.abspath(config_file)

        self.config = configparser.ConfigParser()  # 创建配置解析器实例

        # 检查配置文件是否存在（使用最终确定的 self.config_file）
        if not os.path.exists(self.config_file):
            self._create_default_config()  # 不存在则创建默认配置

        # 读取配置文件（同样使用 self.config_file）
        self.config.read(self.config_file, encoding='utf-8')
        # endregion

    def _create_default_config(self):
        """创建包含所有必要配置项的默认配置文件"""
        self.config['USER_INFO'] = {
            'username': 'your_email@example.com',  # 用户邮箱
            'password': 'your_password'           # 用户密码
        }
        self.config['SETTINGS'] = {
            'timeout': '10',                      # 超时时间（秒）
            'retry_attempts': '3',                # 最大重试次数
            'chrome_driver_path': '',             # Chrome驱动路径（留空自动管理）
            'download_dir': os.path.expanduser("~/Downloads")  # 下载文件保存目录
        }

        # 写入默认配置到文件
        with open(self.config_file, 'w', encoding='utf-8') as f:
            self.config.write(f)
        logger.info(f"已创建默认配置文件: {self.config_file}")

    def get_user_info(self):
        """获取用户名和密码"""
        return {
            'username': self.config.get('USER_INFO', 'username'),
            'password': self.config.get('USER_INFO', 'password')
        }

    def get_timeout(self):
        """获取超时时间（整数）"""
        return self.config.getint('SETTINGS', 'timeout', fallback=10)

    def get_retry_attempts(self):
        """获取最大重试次数（整数）"""
        return self.config.getint('SETTINGS', 'retry_attempts', fallback=3)

    def get_chrome_driver_path(self):
        """获取Chrome驱动路径"""
        return self.config.get('SETTINGS', 'chrome_driver_path', fallback='')

    def get_download_dir(self):
        """获取下载目录（统一提供给所有程序使用）"""
        return self.config.get('SETTINGS', 'download_dir', fallback=os.path.expanduser("~/Downloads"))
    def get_listen_dir(self):
        """获取下载目录（统一提供给所有程序使用）"""
        return self.config.get('SETTINGS', 'listen_dir', fallback=os.path.expanduser("~/Downloads"))

    def set_config_value(self, section, key, value):
        """
        向配置文件中写入/修改指定字段的值
        Args:
            section: 配置节（如'SETTINGS'）
            key: 字段名（如'download_dir'）
            value: 要设置的值（字符串类型）
        Returns:
            bool: 操作成功返回True，失败返回False
        """
        try:
            # 若节不存在，先创建节
            if not self.config.has_section(section):
                self.config.add_section(section)
            # 设置字段值（确保值为字符串类型）
            self.config.set(section, key, str(value))
            # 写入配置文件（覆盖原文件）
            with open(self.config_file, 'w', encoding='utf-8') as f:
                self.config.write(f)
            return True
        except Exception as e:
            logger.error(f"修改配置文件[{section}] {key} 失败：{str(e)}")
            return False


    # 配置文件处理
    # class ConfigHandler:
    #     def __init__(self, config_file='config.ini'):
    #         self.config_file = config_file
    #         self.config = configparser.ConfigParser()  # 创建一个配置文件解析器对象
    #
    #         # 如果配置文件不存在，创建默认配置
    #         if not os.path.exists(config_file):
    #             self._create_default_config()
    #
    #         self.config.read(config_file, encoding='utf-8')  # 读取并解析指定的配置文件
    #
    #     def _create_default_config(self):
    #         """创建默认配置文件"""
    #         self.config['USER_INFO'] = {
    #             'username': 'your_email@example.com',
    #             'password': 'your_password'
    #         }
    #         self.config['SETTINGS'] = {
    #             'timeout': '10',
    #             'retry_attempts': '3',
    #             'chrome_driver_path': '',  # 留空将使用自动管理的driver
    #             'download_dir': os.path.expanduser("~/Downloads")  # 添加默认下载目录配置
    #         }
    #
    #         with open(self.config_file, 'w', encoding='utf-8') as f:
    #             self.config.write(f)
    #         logger.info(f"已创建默认配置文件: {self.config_file}")
    #
    #     def get_user_info(self):
    #         """获取用户信息"""
    #         return {
    #             'username': self.config.get('USER_INFO', 'username'),
    #             'password': self.config.get('USER_INFO', 'password')
    #         }
    #
    #     def get_timeout(self):
    #         """获取超时时间"""
    #         return self.config.getint('SETTINGS', 'timeout', fallback=10)
    #
    #     def get_retry_attempts(self):
    #         """获取重试次数"""
    #         return self.config.getint('SETTINGS', 'retry_attempts', fallback=3)
    #
    #     def get_chrome_driver_path(self):
    #         """获取Chrome驱动路径"""
    #         return self.config.get('SETTINGS', 'chrome_driver_path', fallback='')
    #
    #     def get_download_dir(self):
    #         """获取下载目录"""
    #         return self.config.get('SETTINGS', 'download_dir', fallback=os.path.expanduser("C:/Users/Lenovo/Downloads"))



    # 配置文件处理
    # class ConfigHandler:
    #     def __init__(self, config_file='config.ini'):
    #         self.config_file = config_file
    #         self.config = configparser.ConfigParser()  # 创建一个配置文件解析器对象
    #
    #         # 如果配置文件不存在，创建默认配置
    #         if not os.path.exists(config_file):
    #             self._create_default_config()
    #
    #         self.config.read(config_file, encoding='utf-8')  # 读取并解析指定的配置文件
    #
    #     def _create_default_config(self):
    #         """创建默认配置文件"""
    #         self.config['USER_INFO'] = {
    #             'username': 'your_email@example.com',
    #             'password': 'your_password'
    #         }
    #         self.config['SETTINGS'] = {
    #             'timeout': '10',
    #             'retry_attempts': '3',
    #             'chrome_driver_path': ''  # 留空将使用自动管理的driver
    #         }
    #
    #         with open(self.config_file, 'w', encoding='utf-8') as f:
    #             self.config.write(f)
    #         logger.info(f"已创建默认配置文件: {self.config_file}")
    #
    #     def get_user_info(self):
    #         """获取用户信息"""
    #         return {
    #             'username': self.config.get('USER_INFO', 'username'),
    #             'password': self.config.get('USER_INFO', 'password')
    #         }
    #
    #     def get_timeout(self):
    #         """获取超时时间"""
    #         return self.config.getint('SETTINGS', 'timeout', fallback=10)
    #
    #     def get_retry_attempts(self):
    #         """获取重试次数"""
    #         return self.config.getint('SETTINGS', 'retry_attempts', fallback=3)
    #
    #     def get_chrome_driver_path(self):
    #         """获取Chrome驱动路径"""
    #         return self.config.get('SETTINGS', 'chrome_driver_path', fallback='')
    #