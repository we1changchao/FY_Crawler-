# region 导入库
import requests
import urllib.parse
from pathlib import Path
import os
import time
import threading
from config_handler import ConfigHandler
import  logging
import sys
# endregion


# 配置日志：输出到download.log文件，设置格式和级别
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



def download_http_file(url, save_dir, timeout=30, idle_timeout=60, max_retry=3):
    # region下载 http形式的文件
    """
    增强版HTTP下载函数：解决停滞问题
    :param url: 下载URL
    :param save_dir: 保存目录
    :param timeout: 请求超时时间（秒）
    :param idle_timeout: 无数据传输超时时间（秒）
    :param max_retry: 失败重试次数
    :return: 是否下载成功
    """

    # region禁用 SSL 安全警告
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    # endregion

    # region 解析URL→提取文件名→创建保存目录（准备工作）
    # 分割URL，去掉问号后的参数部分（如 ?id=123）
    url_without_params = url.split('?')[0]
    # 按斜杠分割路径，取最后一个元素作为文件名（如从 "http://example.com/file.zip" 提取 "file.zip"）
    filename = url_without_params.split('/')[-1]

    # 处理特殊情况：文件名为空时生成默认名
    if not filename:
        filename = f"download_{int(time.time())}.hdf"
    # 创建下载目录
    os.makedirs(save_dir, exist_ok=True)
    file_path = os.path.join(save_dir, filename)
    # endregion

    # region 设置请求头，模拟浏览器行为
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': '*/*',
        'Accept-Encoding': 'identity',
        'Connection': 'keep-alive',
    }
    # endregion

    #   region重试循环
    for retry in range(max_retry):
        logger.info(f"开始下载（第{retry + 1}/{max_retry}次尝试）: {filename}")
        logger.info(f"{'=' * 50}")

        # 初始化变量
        download_aborted = False  # 是否中断下载
        last_data_time = time.time()  # 最后一次接收数据的时间
        response = None
        monitor_thread = None

        try:
            # 1. 实时检测文件下载过程中是否长时间无数据传输，若超过阈值则主动中断下载
            def monitor_idle():
                nonlocal download_aborted, response  # 声明这两个变量是 “外层嵌套函数的局部变量”，允许在当前内层函数中修改它们的值
                while not download_aborted:
                    time.sleep(5)  # 每5秒检查一次
                    # 若超过idle_timeout秒无数据传输，中断下载
                    if time.time() - last_data_time > idle_timeout:
                        logger.warning(f"\n⚠️  警告：{idle_timeout}秒未接收数据，中断下载！")
                        download_aborted = True
                        # 主动关闭响应流，释放连接
                        if response:
                            response.close()

            # 启动监控线程（守护线程，主程序退出时自动结束）
            monitor_thread = threading.Thread(target=monitor_idle)
            monitor_thread.daemon = True
            monitor_thread.start()

            # 2. 发送HTTP请求
            session = requests.Session()
            session.headers.update(headers)
            response = session.get(url, stream=True, verify=False, timeout=timeout)

            # 3. 检查请求状态
            if response.status_code == 200:
                total_size = int(response.headers.get('content-length', 0))  # 获取文件的大小  ！！！如果服务器未提供
                downloaded = 0  # 目前下载的大小
                last_reported_percent = -5  # 上次报告的进度（初始值设为-5，确保0%能触发首次输出）

                # 4. 写入文件（带停滞监控）
                with open(file_path, 'wb') as file:
                    for chunk in response.iter_content(chunk_size=8192):
                        # 检查是否被监控线程中断
                        if download_aborted:
                            # 退出当前的下载循环和监控线程，并触发外层的 except TimeoutError 异常处理逻辑 —— 最终会执行 “清理不完整文件→判断是否重试→重试或返回失败” 的流程
                            raise TimeoutError(f"下载停滞超过{idle_timeout}秒，已中断")
                        if chunk:
                            file.write(chunk)
                            downloaded += len(chunk)
                            last_data_time = time.time()  # 每次接收数据更新时间

                            # 进度打印（每5%输出一次）
                            if total_size > 0:
                                current_percent = (downloaded / total_size) * 100
                                if current_percent - last_reported_percent >= 5:
                                    reported_percent = int(current_percent // 5 * 5)
                                    logger.info(f"下载进度: {filename} {reported_percent}%")
                                    last_reported_percent = reported_percent

                # 5. 下载完成后处理
                download_aborted = True  # 通知监控线程结束
                monitor_thread.join()  # 等待监控线程退出

                # 强制输出100%进度
                logger.info(f"下载进度: {filename} 100%")

                # 6. 验证文件完整性
                local_file_size = os.path.getsize(file_path)
                if total_size > 0 and abs(local_file_size - total_size) > 1024:  # 允许1KB误差
                    raise ValueError(f"文件不完整！服务器大小{total_size}字节，本地大小{local_file_size}字节")

                logger.info(f"✅ 文件下载成功！")
                logger.info(f"📁 保存路径: {file_path}")
                logger.info(f"📊 文件大小: {local_file_size:,} 字节")
                return True

            else:
                logger.error(f"❌ 下载失败，状态码: {response.status_code}")
                logger.info(f"📝 响应内容: {response.text[:500]}")   #！！！
                # 重试前清理不完整文件
                if os.path.exists(file_path):
                    os.remove(file_path)
                if retry < max_retry - 1:
                    logger.info(f"⏳ {max_retry - retry - 1}次重试机会，3秒后重试...")
                    time.sleep(3)
                continue

        except requests.exceptions.SSLError as e:  # 处理 SSL 错误（服务端证书不兼容场景）
            logger.error(f"❌ SSL错误: {str(e)[:200]}")
            logger.info("🔄 尝试启用SSL验证重试...")
            try:
                response = requests.get(url, stream=True, verify=True, headers=headers, timeout=timeout)
                if response.status_code == 200:
                    with open(file_path, 'wb') as file:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                file.write(chunk)
                    logger.info(f"✅ SSL验证模式下载成功！")
                    logger.info(f"📁 保存路径: {file_path}")
                    return True
            except Exception as e2:
                logger.error(f"❌ SSL验证模式重试失败: {str(e2)[:200]}")
                if os.path.exists(file_path):
                    os.remove(file_path)
                if retry < max_retry - 1:
                    logger.info(f"⏳ {max_retry - retry - 1}次重试机会，3秒后重试...")
                    time.sleep(3)
                continue

        except TimeoutError as e:  # 处理停滞超时异常（监控线程触发的中断）
            # 捕获空闲超时异常
            logger.error(f"❌ {str(e)}")
            if os.path.exists(file_path):
                os.remove(file_path)
            if retry < max_retry - 1:
                logger.info(f"⏳ {max_retry - retry - 1}次重试机会，5秒后重试...")
                time.sleep(5)
            continue

        except Exception as e:
            logger.error(f"❌ 下载过程中出现错误: {str(e)[:200]}")
            # 清理不完整文件
            if os.path.exists(file_path):
                os.remove(file_path)
            # 重试判断
            if retry < max_retry - 1:
                logger.info(f"⏳ {max_retry - retry - 1}次重试机会，3秒后重试...")
                time.sleep(3)
            continue

        finally:
            # 确保监控线程和响应流被正确关闭
            download_aborted = True
            if monitor_thread and monitor_thread.is_alive():
                monitor_thread.join(timeout=5)
            if response:
                response.close()

    # 所有重试都失败
    logger.error(f"❌ 所有{max_retry}次下载尝试均失败！")
    return False
    # endregion
