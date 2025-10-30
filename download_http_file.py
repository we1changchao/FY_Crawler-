import requests
import urllib.parse
from pathlib import Path
import os
import time


def download_http_file(url1,save_dir):

    # 禁用 SSL 安全警告
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    url = url1


    # 分割URL，去掉问号后的参数部分（如 ?id=123）
    url_without_params = url.split('?')[0]
    # 按斜杠分割路径，取最后一个元素作为文件名（如从 "http://example.com/file.zip" 提取 "file.zip"）
    filename = url_without_params.split('/')[-1]

    # 创建下载目录
    os.makedirs(save_dir, exist_ok=True)  # 创建本地保存目录（若不存在）
    file_path = os.path.join(save_dir, filename)   # 拼接本地保存的完整路径

    # 设置请求头，模拟浏览器行为
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': '*/*',
        'Accept-Encoding': 'identity',
        'Connection': 'keep-alive',
    }

    #  开始下载
    try:
        print(f"开始下载文件: {filename}")

        # 创建会话对象
        session = requests.Session()
        session.headers.update(headers)

        # 发送GET请求，stream=True用于大文件下载
        response = session.get(url, stream=True, verify=False, timeout=30)

        # 检查请求是否成功
        if response.status_code == 200:
            # 获取文件大小
            total_size = int(response.headers.get('content-length', 0))

            # 新增：时间控制变量（控制进度输出频率）
            last_print_time = time.time()  # 记录上次输出时间
            print_interval = 0.25  # 输出间隔（0.25秒）

            # 写入文件
            with open(file_path, 'wb') as file:
                if total_size == 0:
                    file.write(response.content)
                else:
                    downloaded = 0
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            file.write(chunk)
                            downloaded += len(chunk)
                            # 显示下载进度
                            if total_size > 0:
                                current_time = time.time()  # 当前时间
                                if current_time - last_print_time >= print_interval:
                                    progress = (downloaded / total_size) * 100
                                    print(f"\r下载进度: {progress:.2f}%", end='', flush=True)
            # 下载完成后，强制输出100%进度
            if total_size > 0:
                print(f"\r下载进度: {filename} 100.00%", end='', flush=True)
            print(f"\n文件下载完成: {file_path}")
            print(f"文件大小: {os.path.getsize(file_path)} 字节")

            return True
        else:
            print(f"下载失败，状态码: {response.status_code}")
            print(f"响应内容: {response.text[:500]}")
            return False

    except requests.exceptions.SSLError as e:
        print(f"SSL错误: {e}")
        print("尝试使用验证...")
        # 如果SSL验证失败，尝试使用验证
        try:
            response = requests.get(url, stream=True, verify=True, headers=headers, timeout=30)
            if response.status_code == 200:
                with open(file_path, 'wb') as file:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            file.write(chunk)
                print(f"文件下载完成: {file_path}")
                return True
        except Exception as e:
            print(f"再次尝试失败: {e}")
            return False

    except Exception as e:
        print(f"下载过程中出现错误: {e}")
        return False


# def main():
#     # 禁用不安全的请求警告（仅用于开发环境）
#     import urllib3
#     urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
#
#     print("FY4B卫星数据自动化下载工具")
#     print("=" * 50)
#
#     # 执行下载
#     success = download_http_file()
#
#     if success:
#         print("\n下载成功！")
#     else:
#         print("\n下载失败，请检查网络连接或URL有效性")
#
#
# if __name__ == "__main__":
#     main()