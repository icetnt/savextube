# -*- coding: utf-8 -*-
# 在最开始就禁用SSL警告
import os
# 设置环境变量禁用SSL警告
os.environ['PYTHONWARNINGS'] = 'ignore:Unverified HTTPS request'
os.environ['URLLIB3_DISABLE_WARNINGS'] = '1'

import warnings
warnings.filterwarnings('ignore', message='Unverified HTTPS request')
warnings.filterwarnings('ignore', message='.*certificate verification.*')
warnings.filterwarnings('ignore', message='.*SSL.*')
warnings.filterwarnings('ignore', category=UserWarning, module='urllib3')

import logging.handlers
import os
import sys
import asyncio
import logging
import logging
logging.getLogger("telethon").setLevel(logging.WARNING)
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional, Dict, Any
from enum import Enum
from dataclasses import dataclass
import time
import threading
import requests
import urllib3
# 立即禁用urllib3的SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 尝试禁用其他可能存在的SSL警告
try:
    urllib3.disable_warnings(urllib3.exceptions.SubjectAltNameWarning)
except AttributeError:
    pass  # 该警告类型不存在，忽略

try:
    urllib3.disable_warnings(urllib3.exceptions.InsecurePlatformWarning)
except AttributeError:
    pass  # 该警告类型不存在，忽略

try:
    urllib3.disable_warnings(urllib3.exceptions.SNIMissingWarning)
except AttributeError:
    pass  # 该警告类型不存在，忽略

import re
import uuid
import mimetypes
import json
import subprocess
from telethon import TelegramClient, types
from telethon.sessions import StringSession
from telegram import (
    Update,
    InputFile,
    Audio,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackContext,
    CallbackQueryHandler,
)
import yt_dlp
import qbittorrentapi
import signal
import gc
from concurrent.futures import ThreadPoolExecutor

# 网络错误处理相关导入
import httpx
from telegram.error import NetworkError, TimedOut, RetryAfter

# 健康检查服务器相关
from flask import Flask, jsonify, request
import threading

def extract_xiaohongshu_url(text):
    import re
    # 先尝试提取标准http/https链接
    urls = re.findall(r'http[s]?://[^\s]+', text)
    for url in urls:
        if 'xhslink.com' in url or 'xiaohongshu.com' in url:
            return url
    
    # 如果没有找到标准链接，尝试提取其他格式的小红书链接
    # 匹配 p://、tp://、ttp:// 等协议，并转换为https://
    non_http_urls = re.findall(r'(p|tp|ttp)://([^\s]+)', text)
    for protocol, url in non_http_urls:
        if 'xhslink.com' in url or 'xiaohongshu.com' in url:
            return f"https://{url}"
    
    # 匹配没有协议的小红书域名
    domain_urls = re.findall(r'(xhslink\.com/[^\s]+|xiaohongshu\.com/[^\s]+)', text)
    for url in domain_urls:
        return f"https://{url}"
    
    return None
# 抖音和小红书下载相关导入
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("警告: playwright 未安装，抖音和小红书下载功能将不可用")


# 程序版本信息
BOT_VERSION = "v0.6 (Enhanced)"
# 创建 Flask 应用
app = Flask(__name__)
# 全局心跳变量
last_heartbeat = time.time()

# 尝试导入 gallery-dl
try:
    import gallery_dl
    GALLERY_DL_AVAILABLE = True
except ImportError:
    GALLERY_DL_AVAILABLE = False
    print("警告: gallery-dl 未安装，X图片下载功能将不可用")


def update_heartbeat():
    """更新心跳时间"""
    global last_heartbeat
    last_heartbeat = time.time()


@app.route("/health")
def health():
    """健康检查端点"""
    global last_heartbeat
    current_time = time.time()
    time_since_last_heartbeat = current_time - last_heartbeat
    # 超过 1 小时无活动，认为程序可能无响应
    if time_since_last_heartbeat > 3600:
        return (
            jsonify(
                {
                    "status": "unhealthy",
                    "message": "程序可能无响应",
                    "last_heartbeat": time_since_last_heartbeat,
                    "timestamp": current_time,
                }
            ),
            503,
        )
    return jsonify(
        {
            "status": "healthy",
            "message": "程序运行正常",
            "last_heartbeat": time_since_last_heartbeat,
            "timestamp": current_time,
        }
    )


def run_health_check_server():
    """在后台线程中运行健康检查服务器"""
    port = int(os.getenv("HEALTHCHECK_PORT", 8080))
    # 设置日志级别为 ERROR 以抑制开发服务器警告
    import logging

    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)
    # 清除可能冲突的环境变量
    os.environ.pop("WERKZEUG_RUN_MAIN", None)
    os.environ.pop("WERKZEUG_SERVER_FD", None)
    try:
        # 使用更稳定的启动方式
        from werkzeug.serving import make_server

        server = make_server("0.0.0.0", port, app)
        server.serve_forever()
    except Exception as e:
        logger.error(f"健康检查服务器启动失败: {e}")
        # 回退到原始方法
        try:
            app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
        except Exception as e2:
            logger.error(f"健康检查服务器回退启动也失败: {e2}")


try:
    from telegram import Update
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        filters,
        ContextTypes,
    )
    import yt_dlp
except ImportError as e:
    print(f"Error importing required packages: {e}")
    print("Please install: pip install python-telegram-bot yt-dlp requests")
    sys.exit(1)

# 配置增强的日志系统
def setup_logging():
    """配置增强的日志系统，支持远程NAS目录"""
    # 从环境变量获取日志配置
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_dir = os.getenv("LOG_DIR", "./logs")  # 改为当前目录下的logs
    log_max_size = int(os.getenv("LOG_MAX_SIZE", "10")) * 1024 * 1024  # 默认10MB
    log_backup_count = int(os.getenv("LOG_BACKUP_COUNT", "5"))
    log_to_console = os.getenv("LOG_TO_CONSOLE", "true").lower() == "true"
    log_to_file = os.getenv("LOG_TO_FILE", "true").lower() == "true"
    # 创建日志目录（支持远程NAS路径）
    log_path = Path(log_dir)
    try:
        log_path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"警告：无法创建日志目录 {log_path}: {e}")
        # 如果无法创建远程目录，回退到本地目录
        log_path = Path("./logs")  # 改为当前目录下的logs
        log_path.mkdir(parents=True, exist_ok=True)
        print(f"已回退到本地日志目录: {log_path}")
    # 配置日志格式
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    # 创建格式化器
    formatter = logging.Formatter(log_format, date_format)
    # 获取根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level))
    # 清除现有的处理器
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    # 文件日志处理器（带轮转）
    if log_to_file:
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                log_path / "savextube.log",
                maxBytes=log_max_size,
                backupCount=log_backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            file_handler.setLevel(getattr(logging, log_level))
            root_logger.addHandler(file_handler)
        except Exception as e:
            print(f"警告：无法创建文件日志处理器: {e}")
            log_to_file = False
    # 控制台日志处理器
    if log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(getattr(logging, log_level))
        root_logger.addHandler(console_handler)

    # 设置第三方库的日志级别，减少冗余输出
    # httpx - Telegram API 请求日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # urllib3 - HTTP 请求日志
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
    logging.getLogger("urllib3.util.retry").setLevel(logging.ERROR)
    # 禁用urllib3的所有警告
    logging.getLogger("urllib3").disabled = True

# 设置日志
setup_logging()
logger = logging.getLogger("savextube")

# 统一的进度管理函数
def create_unified_progress_hook(message_updater=None, progress_data=None):
    """
    创建统一的进度回调函数，适用于所有基于 yt-dlp 的下载
    
    Args:
        message_updater: 同步或异步消息更新函数
        progress_data: 进度数据字典，用于存储最终文件名等信息
    
    Returns:
        progress_hook: 统一的进度回调函数
    """
    def progress_hook(d):
        try:
            if d.get('status') == 'downloading':
                # 安全地获取下载进度信息
                downloaded = d.get('downloaded_bytes', 0) or 0
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0) or 0
                
                # 确保数值有效
                if downloaded is None:
                    downloaded = 0
                if total is None or total <= 0:
                    total = 1  # 避免除零错误
                
                # 计算进度百分比
                if total > 0:
                    percent = (downloaded / total) * 100
                else:
                    percent = 0
                
                # 格式化速度
                speed = d.get('speed', 0) or 0
                if speed and speed > 0:
                    speed_str = f"{speed / 1024 / 1024:.2f} MB/s"
                else:
                    speed_str = "未知"
                
                # 格式化剩余时间
                eta = d.get('eta', 0) or 0
                if eta and eta > 0:
                    eta_str = f"{eta}秒"
                else:
                    eta_str = "未知"
                
                # 获取文件名
                filename = os.path.basename(d.get('filename', '')) or "正在下载..."
                
                # 更新进度数据
                if progress_data:
                    progress_data.update({
                        'downloaded': downloaded,
                        'total': total,
                        'percent': percent,
                        'speed': speed_str,
                        'eta': eta_str,
                        'status': 'downloading',
                        'filename': filename
                    })
                
                # 记录进度信息
                logger.info(f"下载进度: {percent:.1f}% ({downloaded}/{total} bytes) - {speed_str} - 剩余: {eta_str}")
                
                # 如果有消息更新器，调用它
                if message_updater:
                    try:
                        # 检查是否为协程对象（错误情况）
                        if asyncio.iscoroutine(message_updater):
                            logger.error(f"❌ [progress_hook] message_updater 是协程对象，不是函数！")
                            return

                        # 检查是否为异步函数
                        if asyncio.iscoroutinefunction(message_updater):
                            # 异步函数，使用 run_coroutine_threadsafe
                            try:
                                loop = asyncio.get_running_loop()
                            except RuntimeError:
                                try:
                                    loop = asyncio.get_event_loop()
                                except RuntimeError:
                                    loop = asyncio.new_event_loop()
                                    asyncio.set_event_loop(loop)

                            # 直接传递原始进度数据字典
                            asyncio.run_coroutine_threadsafe(
                                message_updater(d), loop)
                        else:
                            # 同步函数，直接调用
                            message_updater(d)
                    except Exception as e:
                        logger.warning(f"⚠️ 更新进度消息失败: {e}")
                        logger.warning(f"⚠️ 异常类型: {type(e)}")
                        import traceback
                        logger.warning(f"⚠️ 异常堆栈: {traceback.format_exc()}")
                        
            if d.get('status') == 'finished':
                logger.info("下载完成，开始后处理...")
                
                # 更新进度数据
                if progress_data:
                    progress_data['status'] = 'finished'
                
                # 安全地获取文件名
                filename = d.get('filename', '')
                if filename and progress_data:
                    progress_data['final_filename'] = filename
                    logger.info(f"最终文件名: {filename}")

                    # 监控文件合并状态
                    if filename.endswith('.part'):
                        logger.warning(f"⚠️ 文件合并可能失败: {filename}")
                    else:
                        logger.info(f"✅ 文件下载并合并成功: {filename}")
                else:
                    logger.warning("progress_hook 中未获取到文件名")
                
                # 如果有消息更新器，发送完成消息
                if message_updater:
                    try:
                        # 添加详细的调试日志
                        logger.info(f"🔍 [progress_hook] finished状态 - message_updater 类型: {type(message_updater)}")
                        
                        # 检查是否为协程对象（错误情况）
                        if asyncio.iscoroutine(message_updater):
                            logger.error(f"❌ [progress_hook] finished状态 - message_updater 是协程对象，不是函数！")
                            return
                        
                        # 检查是否为异步函数
                        if asyncio.iscoroutinefunction(message_updater):
                            logger.info(f"🔍 [progress_hook] finished状态 - 检测到异步函数，使用 run_coroutine_threadsafe")
                            # 异步函数，使用 run_coroutine_threadsafe
                            try:
                                loop = asyncio.get_running_loop()
                            except RuntimeError:
                                try:
                                    loop = asyncio.get_event_loop()
                                except RuntimeError:
                                    loop = asyncio.new_event_loop()
                                    asyncio.set_event_loop(loop)
                            
                            # 直接传递原始进度数据字典
                            asyncio.run_coroutine_threadsafe(
                                message_updater(d), loop)
                        else:
                            logger.info(f"🔍 [progress_hook] finished状态 - 检测到同步函数，直接调用")
                            # 同步函数，直接调用
                            message_updater(d)
                    except Exception as e:
                        logger.warning(f"⚠️ 更新完成消息失败: {e}")
                        logger.warning(f"⚠️ 异常类型: {type(e)}")
                        import traceback
                        logger.warning(f"⚠️ 异常堆栈: {traceback.format_exc()}")
                    
        except Exception as e:
            logger.error(f"progress_hook 处理错误: {e}")
            import traceback
            logger.error(f"progress_hook 异常堆栈: {traceback.format_exc()}")
            # 不中断下载，只记录错误
    
    return progress_hook
def create_bilibili_message_updater(status_message, context, progress_data):
    """
    专门为B站多P下载创建的消息更新器
    完全复制YouTube的成功逻辑
    """
    import time
    import asyncio

    # 缓存上次发送的内容，避免重复发送
    last_progress_text = {"text": None}

    # --- 进度回调 ---
    last_update_time = {"time": time.time()}
    last_progress_percent = {"value": 0}
    progress_state = {"last_stage": None, "last_percent": 0, "finished_shown": False}
    last_progress_text = {"text": ""}

    # 创建B站专用的消息更新器函数
    async def bilibili_message_updater(text_or_dict):
        try:
            logger.info(f"🔍 bilibili_message_updater 被调用，参数类型: {type(text_or_dict)}")
            logger.info(f"🔍 bilibili_message_updater 参数内容: {text_or_dict}")

            # 如果已经显示完成状态，忽略所有后续调用
            if progress_state["finished_shown"]:
                logger.info("B站下载已完成，忽略bilibili_message_updater后续调用")
                return

            # 处理字符串类型，避免重复发送相同内容
            if isinstance(text_or_dict, str):
                if text_or_dict == last_progress_text["text"]:
                    logger.info("🔍 跳过重复内容")
                    return  # 跳过重复内容
                last_progress_text["text"] = text_or_dict
                await status_message.edit_text(text_or_dict)
                return

            # 检查是否为字典类型（来自progress_hook的进度数据）
            if isinstance(text_or_dict, dict):
                logger.info(f"🔍 检测到字典类型，状态: {text_or_dict.get('status')}")

                # 记录文件名（用于文件查找）
                if text_or_dict.get("status") == "finished":
                    filename = text_or_dict.get('filename', '')
                    if filename:
                        # 记录到progress_data中
                        if 'downloaded_files' not in progress_data:
                            progress_data['downloaded_files'] = []
                        progress_data['downloaded_files'].append(filename)
                        logger.info(f"📝 B站下载器记录完成文件: {filename}")

                if text_or_dict.get("status") == "finished":
                    # 对于finished状态，不调用update_progress，避免显示错误的进度信息
                    logger.info("🔍 检测到finished状态，跳过update_progress调用")
                    return
                elif text_or_dict.get("status") == "downloading":
                    # 这是来自progress_hook的下载进度数据
                    logger.info("🔍 检测到下载进度数据，准备调用 update_progress...")
                    # 这里需要实现update_progress逻辑，暂时先记录
                    logger.info(f"📊 B站下载进度: {text_or_dict}")
                else:
                    # 其他字典状态，转换为文本
                    logger.info(f"🔍 其他字典状态: {text_or_dict}")
                    dict_text = str(text_or_dict)
                    if dict_text == last_progress_text["text"]:
                        logger.info("🔍 跳过重复字典内容")
                        return  # 跳过重复内容
                    last_progress_text["text"] = dict_text
                    await status_message.edit_text(dict_text)
            else:
                # 普通文本消息
                logger.info(f"🔍 普通文本消息: {text_or_dict}")
                text_str = str(text_or_dict)
                if text_str == last_progress_text["text"]:
                    logger.info("🔍 跳过重复文本内容")
                    return  # 跳过重复内容
                last_progress_text["text"] = text_str
                await status_message.edit_text(text_str)
        except Exception as e:
            logger.error(f"❌ bilibili_message_updater 处理错误: {e}")
            logger.error(f"❌ 异常类型: {type(e)}")
            import traceback
            logger.error(f"❌ 异常堆栈: {traceback.format_exc()}")
            if "Message is not modified" not in str(e):
                logger.warning(f"更新B站状态消息失败: {e}")

    return bilibili_message_updater

def single_video_progress_hook(message_updater=None, progress_data=None, status_message=None, context=None):
    """
    适用于所有单集下载的 yt-dlp 进度回调，下载过程中显示进度，下载完成后显示文件信息。
    整合了完整的进度显示逻辑，包括进度条、速度、剩余时间等。
    """
    # 初始化进度数据
    if progress_data is None:
        progress_data = {"final_filename": None, "lock": threading.Lock()}
    
    # 初始化更新频率控制
    last_update_time = {"time": 0}
    
    def progress_hook(d):
        # 支持字符串类型，直接发到Telegram
        import os
        if isinstance(d, str):
            if message_updater and status_message:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    try:
                        loop = asyncio.get_event_loop()
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                
                async def do_update():
                    try:
                        await status_message.edit_text(d)
                    except Exception as e:
                        logger.warning(f"发送字符串进度到TG失败: {e}")
                
                asyncio.run_coroutine_threadsafe(do_update(), loop)
            return
        
        # 添加类型检查，确保d是字典类型
        if not isinstance(d, dict):
            logger.warning(f"progress_hook接收到非字典类型参数: {type(d)}, 内容: {d}")
            return
        
        # 更新 progress_data
        try:
            if d['status'] == 'downloading':
                raw_filename = d.get('filename', '')
                display_filename = os.path.basename(raw_filename) if raw_filename else 'video.mp4'
                progress_data.update({
                    'filename': display_filename,
                    'total_bytes': d.get('total_bytes') or d.get('total_bytes_estimate', 0),
                    'downloaded_bytes': d.get('downloaded_bytes', 0),
                    'speed': d.get('speed', 0),
                    'status': 'downloading',
                    'progress': (d.get('downloaded_bytes', 0) / (d.get('total_bytes') or d.get('total_bytes_estimate', 1))) * 100 if (d.get('total_bytes') or d.get('total_bytes_estimate', 0)) > 0 else 0.0
                })
            elif d['status'] == 'finished':
                final_filename = d.get('filename', '')
                display_filename = os.path.basename(final_filename) if final_filename else 'video.mp4'
                progress_data.update({
                    'filename': display_filename,
                    'status': 'finished',
                    'final_filename': final_filename,
                    'progress': 100.0
                })
                logger.info(f"📝 记录最终文件名: {final_filename}")
        except Exception as e:
            logger.error(f"更新 progress_data 错误: {str(e)}")
        
        # 如果没有status_message和context，使用简单的message_updater
        if not status_message or not context:
            if message_updater:
                if asyncio.iscoroutinefunction(message_updater):
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        try:
                            loop = asyncio.get_event_loop()
                        except RuntimeError:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                    asyncio.run_coroutine_threadsafe(message_updater(d), loop)
                else:
                    try:
                        message_updater(d)
                    except Exception as e:
                        logger.warning(f"进度回调调用失败: {e}")
            return
        
        # 完整的进度显示逻辑
        now = time.time()

        # 动态更新频率控制：小文件使用更高频率
        total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
        if total_bytes > 0 and total_bytes < 5 * 1024 * 1024:  # 小于5MB的文件
            update_interval = 0.2  # 200ms更新一次
        else:
            update_interval = 1.0  # 大文件1秒更新一次

        if now - last_update_time['time'] < update_interval:
            return
        
        # 处理下载完成状态 - 直接显示完成信息并返回
        if d.get('status') == 'finished':
            logger.info("yt-dlp下载完成，显示完成信息")

            # 获取进度信息
            filename = progress_data.get('filename', 'video.mp4')
            total_bytes = progress_data.get('total_bytes', 0)
            downloaded_bytes = progress_data.get('downloaded_bytes', 0)

            # 监控文件合并状态
            actual_filename = d.get('filename', filename)
            if actual_filename.endswith('.part'):
                logger.warning(f"⚠️ 文件合并可能失败: {actual_filename}")
            else:
                logger.info(f"✅ 文件下载并合并成功: {actual_filename}")
            
            # 显示完成信息
            display_filename = _clean_filename_for_display(filename)
            progress_bar = _create_progress_bar(100.0)
            size_mb = total_bytes / (1024 * 1024) if total_bytes > 0 else downloaded_bytes / (1024 * 1024)
            
            completion_text = (
                f"📝 文件：{display_filename}\n"
                f"💾 大小：{size_mb:.2f}MB\n"
                f"⚡ 速度：完成\n"
                f"⏳ 预计剩余：0秒\n"
                f"📊 进度：{progress_bar} (100.0%)"
            )
            
            async def do_update():
                try:
                    await status_message.edit_text(completion_text)
                    logger.info("显示下载完成进度信息")
                except Exception as e:
                    logger.warning(f"显示完成进度信息失败: {e}")
            
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            
            asyncio.run_coroutine_threadsafe(do_update(), loop)
            return
        
        # 处理下载中状态
        if d.get('status') == 'downloading':
            last_update_time['time'] = now
            
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            downloaded_bytes = d.get('downloaded_bytes', 0)
            speed_bytes_s = d.get('speed', 0)
            eta_seconds = d.get('eta', 0)
            filename = d.get('filename', '') or "正在下载..."
            
            # 计算进度
            if total_bytes > 0:
                progress = (downloaded_bytes / total_bytes) * 100
                progress_bar = _create_progress_bar(progress)
                size_mb = total_bytes / (1024 * 1024)
                speed_mb = (speed_bytes_s or 0) / (1024 * 1024)
                
                # 计算预计剩余时间
                eta_text = ""
                if speed_bytes_s and total_bytes and downloaded_bytes < total_bytes:
                    remaining = total_bytes - downloaded_bytes
                    eta = int(remaining / speed_bytes_s)
                    mins, secs = divmod(eta, 60)
                    if mins > 0:
                        eta_text = f"{mins}分{secs}秒"
                    else:
                        eta_text = f"{secs}秒"
                elif speed_bytes_s:
                    eta_text = "计算中"
                else:
                    eta_text = "未知"
                
                display_filename = _clean_filename_for_display(filename)
                progress_text = (
                    f"📝 文件：{display_filename}\n"
                    f"💾 大小：{size_mb:.2f}MB\n"
                    f"⚡ 速度：{speed_mb:.2f}MB/s\n"
                    f"⏳ 预计剩余：{eta_text}\n"
                    f"📊 进度：{progress_bar} ({progress:.1f}%)"
                )
                
                async def do_update():
                    try:
                        await status_message.edit_text(progress_text)
                    except Exception as e:
                        if "Message is not modified" not in str(e):
                            logger.warning(f"更新进度失败: {e}")
                
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    try:
                        loop = asyncio.get_event_loop()
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                
                asyncio.run_coroutine_threadsafe(do_update(), loop)
            else:
                # 没有总大小信息时的处理
                display_filename = _clean_filename_for_display(filename)
                downloaded_mb = downloaded_bytes / (1024 * 1024)
                speed_mb = (speed_bytes_s or 0) / (1024 * 1024)
                
                progress_text = (
                    f"📝 文件：{display_filename}\n"
                    f"💾 已下载：{downloaded_mb:.2f}MB\n"
                    f"⚡ 速度：{speed_mb:.2f}MB/s\n"
                    f"⏳ 预计剩余：未知\n"
                    f"📊 进度：计算中..."
                )
                
                async def do_update():
                    try:
                        await status_message.edit_text(progress_text)
                    except Exception as e:
                        if "Message is not modified" not in str(e):
                            logger.warning(f"更新进度失败: {e}")
                
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    try:
                        loop = asyncio.get_event_loop()
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                
                asyncio.run_coroutine_threadsafe(do_update(), loop)
    
    # 辅助函数
    def _clean_filename_for_display(filename):
        """清理文件名用于显示"""
        try:
            # 移除时间戳前缀如果存在
            import re
            import os
            if re.match(r"^\d{10}_", filename):
                display_name = filename[11:]
            else:
                display_name = filename

            # 如果文件名太长，进行智能截断
            if len(display_name) > 35:
                name, ext = os.path.splitext(display_name)
                display_name = name[:30] + "..." + ext

            return display_name
        except BaseException:
            return filename if len(filename) <= 35 else filename[:32] + "..."
    
    def _create_progress_bar(percent: float, length: int = 20) -> str:
        """创建进度条"""
        filled_length = int(length * percent / 100)
        bar = "█" * filled_length + "░" * (length - filled_length)
        return bar
    
    return progress_hook
class VideoDownloader:
    # 平台枚举定义
    class Platform(str, Enum):
        DOUYIN = "douyin"
        KUAISHOU = "kuaishou"
        XIAOHONGSHU = "xiaohongshu"
        UNKNOWN = "unknown"
    
    def __init__(
        self,
        base_download_path: str,
        x_cookies_path: str = None,
        b_cookies_path: str = None,
        youtube_cookies_path: str = None,
        douyin_cookies_path: str = None,
        kuaishou_cookies_path: str = None,
        facebook_cookies_path: str = None,
    ):
        self.download_path = Path(base_download_path).resolve()
        self.x_download_path = self.download_path / "X"
        self.bilibili_download_path = self.download_path / "Bilibili"
        self.youtube_download_path = self.download_path / "YouTube"
        self.music_download_path = self.download_path / "Music"
        self.pornhub_download_path = self.download_path / "Pornhub"
        self.telegram_download_path = self.download_path / "Telegram"
        self.telegraph_download_path = self.download_path / "Telegraph"
        self.douyin_download_path = self.download_path / "Douyin"
        self.kuaishou_download_path = self.download_path / "Kuaishou"
        self.facebook_download_path = self.download_path / "Facebook"
        self.weibo_download_path = self.download_path / "Weibo"
        self.instagram_download_path = self.download_path / "Instagram"
        self.tiktok_download_path = self.download_path / "TikTok"
        self.x_cookies_path = x_cookies_path
        self.b_cookies_path = b_cookies_path
        self.youtube_cookies_path = youtube_cookies_path
        self.douyin_cookies_path = douyin_cookies_path
        self.kuaishou_cookies_path = kuaishou_cookies_path
        self.facebook_cookies_path = facebook_cookies_path
        self.proxy_host = os.environ.get("PROXY_HOST")
        self._main_loop = None
        try:
            import asyncio

            self._main_loop = asyncio.get_running_loop()
        except Exception:
            self._main_loop = None
        # 从环境变量获取是否转换格式的配置
        self.convert_to_mp4 = (
            os.getenv("YOUTUBE_CONVERT_TO_MP4", "true").lower() == "true"
        )
        logger.info(f"视频格式转换: {'开启' if self.convert_to_mp4 else '关闭'}")
        # 支持自定义下载目录
        self.custom_download_path = (
            os.getenv("CUSTOM_DOWNLOAD_PATH", "false").lower() == "true"
        )
        if self.custom_download_path:
            # 如果启用了自定义下载路径，从环境变量读取各平台的下载路径
            self.x_download_path = Path(
                os.getenv("X_DOWNLOAD_PATH", str(self.download_path / "X"))
            ).resolve()
            self.youtube_download_path = Path(
                os.getenv("YOUTUBE_DOWNLOAD_PATH", str(self.download_path / "YouTube"))
            ).resolve()
            self.xvideos_download_path = Path(
                os.getenv("XVIDEOS_DOWNLOAD_PATH", str(self.download_path / "Xvideos"))
            ).resolve()
            self.pornhub_download_path = Path(
                os.getenv("PORNHUB_DOWNLOAD_PATH", str(self.download_path / "Pornhub"))
            ).resolve()
            self.bilibili_download_path = Path(
                os.getenv(
                    "BILIBILI_DOWNLOAD_PATH", str(self.download_path / "Bilibili")
                )
            ).resolve()
            self.music_download_path = Path(
                os.getenv("MUSIC_DOWNLOAD_PATH", str(self.download_path / "Music"))
            ).resolve()
            self.telegram_download_path = Path(
                os.getenv(
                    "TELEGRAM_DOWNLOAD_PATH", str(self.download_path / "Telegram")
                )
            ).resolve()
            self.telegraph_download_path = Path(
                os.getenv(
                    "TELEGRAPH_DOWNLOAD_PATH", str(self.download_path / "Telegraph")
                )
            ).resolve()
            self.douyin_download_path = Path(
                os.getenv(
                    "DOUYIN_DOWNLOAD_PATH", str(self.download_path / "Douyin")
                )
            ).resolve()
            self.kuaishou_download_path = Path(
                os.getenv(
                    "KUAISHOU_DOWNLOAD_PATH", str(self.download_path / "Kuaishou")
                )
            ).resolve()
            self.facebook_download_path = Path(
                os.getenv(
                    "FACEBOOK_DOWNLOAD_PATH", str(self.download_path / "Facebook")
                )
            ).resolve()
            self.xiaohongshu_download_path = Path(
                os.getenv(
                    "XIAOHONGSHU_DOWNLOAD_PATH", str(self.download_path / "Xiaohongshu")
                )
            ).resolve()
            self.weibo_download_path = Path(
                os.getenv(
                    "WEIBO_DOWNLOAD_PATH", str(self.download_path / "Weibo")
                )
            ).resolve()
            self.instagram_download_path = Path(
                os.getenv(
                    "INSTAGRAM_DOWNLOAD_PATH", str(self.download_path / "Instagram")
                )
            ).resolve()
            self.tiktok_download_path = Path(
                os.getenv(
                    "TIKTOK_DOWNLOAD_PATH", str(self.download_path / "TikTok")
                )
            ).resolve()
        else:
            # 如果未启用自定义下载路径，使用默认的子目录结构
            self.x_download_path = self.download_path / "X"
            self.youtube_download_path = self.download_path / "YouTube"
            self.xvideos_download_path = self.download_path / "Xvideos"
            self.pornhub_download_path = self.download_path / "Pornhub"
            self.bilibili_download_path = self.download_path / "Bilibili"
            self.music_download_path = self.download_path / "Music"
            self.telegram_download_path = self.download_path / "Telegram"
            self.telegraph_download_path = self.download_path / "Telegraph"
            self.xiaohongshu_download_path = self.download_path / "Xiaohongshu"
            self.weibo_download_path = self.download_path / "Weibo"
            self.instagram_download_path = self.download_path / "Instagram"
            self.tiktok_download_path = self.download_path / "TikTok"
        # 创建所有下载目录
        for path in [
            self.x_download_path,
            self.youtube_download_path,
            self.xvideos_download_path,
            self.pornhub_download_path,
            self.bilibili_download_path,
            self.music_download_path,
            self.telegram_download_path,
            self.telegraph_download_path,
            self.douyin_download_path,
            self.kuaishou_download_path,
            self.facebook_download_path,
            self.xiaohongshu_download_path,
            self.weibo_download_path,
            self.instagram_download_path,
            self.tiktok_download_path,
        ]:
            path.mkdir(parents=True, exist_ok=True)
        logger.info(f"X 下载路径: {self.x_download_path}")
        logger.info(f"YouTube 下载路径: {self.youtube_download_path}")
        logger.info(f"Xvideos 下载路径: {self.xvideos_download_path}")
        logger.info(f"Pornhub 下载路径: {self.pornhub_download_path}")
        logger.info(f"Bilibili 下载路径: {self.bilibili_download_path}")
        logger.info(f"音乐下载路径: {self.music_download_path}")
        logger.info(f"Telegram 文件下载路径: {self.telegram_download_path}")
        logger.info(f"Telegraph 文件下载路径: {self.telegraph_download_path}")
        logger.info(f"抖音下载路径: {self.douyin_download_path}")
        logger.info(f"快手下载路径: {self.kuaishou_download_path}")
        logger.info(f"Facebook下载路径: {self.facebook_download_path}")
        logger.info(f"小红书下载路径: {self.xiaohongshu_download_path}")
        logger.info(f"微博下载路径: {self.weibo_download_path}")
        logger.info(f"Instagram下载路径: {self.instagram_download_path}")
        logger.info(f"TikTok下载路径: {self.tiktok_download_path}")
        # 如果设置了 Bilibili cookies，记录日志
        if self.b_cookies_path:
            logger.info(f"Bilibili Cookies 路径: {self.b_cookies_path}")
        # 如果设置了 YouTube cookies，记录日志
        if self.youtube_cookies_path:
            logger.info(f"🍪 使用YouTube cookies: {self.youtube_cookies_path}")
            
        # 如果设置了抖音 cookies，记录日志
        if self.douyin_cookies_path:
            logger.info(f"🍪 使用抖音 cookies: {self.douyin_cookies_path}")

        # 如果设置了快手 cookies，记录日志
        if self.kuaishou_cookies_path:
            logger.info(f"🍪 使用快手 cookies: {self.kuaishou_cookies_path}")
            
        # 测试代理连接
        if self.proxy_host:
            if self._test_proxy_connection():
                logger.info(f"代理服务器已配置并连接成功: {self.proxy_host}")
                logger.info(f"yt-dlp 使用代理: {self.proxy_host}")
                # 设置系统代理环境变量
                os.environ['HTTP_PROXY'] = self.proxy_host
                os.environ['HTTPS_PROXY'] = self.proxy_host
                os.environ['NO_PROXY'] = 'localhost,127.0.0.1'
            else:
                logger.warning(f"代理服务器已配置但连接失败: {self.proxy_host}")
                logger.info("yt-dlp 直接连接")
                self.proxy_host = None  # 连接失败时禁用代理
                # 清除系统代理环境变量
                os.environ.pop('HTTP_PROXY', None)
                os.environ.pop('HTTPS_PROXY', None)
                os.environ.pop('NO_PROXY', None)
        else:
            logger.info("代理服务器未配置，将直接连接")
            logger.info("yt-dlp 直接连接")
            
        # 创建 gallery-dl.conf 配置文件
        try:
            self._create_gallery_dl_config()
        except Exception as e:
            logger.warning(f"创建 gallery-dl 配置文件失败: {e}")

    def _parse_cookies_file(self, cookies_path: str) -> dict:
        """解析 Netscape 格式的 X cookies 文件并转换为 JSON 格式"""
        try:
            cookies_dict = {}
            
            with open(cookies_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # 跳过注释行和空行
                    if line.startswith('#') or not line:
                        continue
                    
                    # Netscape 格式: domain, domain_specified, path, secure, expiry, name, value
                    parts = line.split('\t')
                    if len(parts) >= 7:
                        domain = parts[0]
                        secure = parts[3] == 'TRUE'
                        expiry = parts[4]
                        name = parts[5]
                        value = parts[6]
                        
                        # 只处理 twitter.com 和 x.com 的 cookies
                        if domain in ['.twitter.com', '.x.com', 'twitter.com', 'x.com']:
                            cookies_dict[name] = value
                            logger.debug(f"解析 X cookie: {name} = {value[:10]}...")
            
            logger.info(f"成功解析 {len(cookies_dict)} 个 X cookies")
            return cookies_dict
            
        except Exception as e:
            logger.error(f"解析 X cookies 文件失败: {e}")
            return {}

    def _parse_douyin_cookies_file(self, cookies_path: str) -> dict:
        """解析 Netscape 格式的抖音 cookies 文件并转换为 JSON 格式"""
        try:
            cookies_dict = {}
            
            with open(cookies_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # 跳过注释行和空行
                    if line.startswith('#') or not line:
                        continue
                    
                    # Netscape 格式: domain, domain_specified, path, secure, expiry, name, value
                    parts = line.split('\t')
                    if len(parts) >= 7:
                        domain = parts[0]
                        secure = parts[3] == 'TRUE'
                        expiry = parts[4]
                        name = parts[5]
                        value = parts[6]
                        
                        # 只处理抖音相关的 cookies
                        if domain in ['.douyin.com', 'douyin.com', 'www.douyin.com', 'v.douyin.com', 'www.iesdouyin.com', 'iesdouyin.com']:
                            cookies_dict[name] = value
                            logger.debug(f"解析抖音 cookie: {name} = {value[:10]}...")
            
            logger.info(f"成功解析 {len(cookies_dict)} 个抖音 cookies")
            return cookies_dict
            
        except Exception as e:
            logger.error(f"解析抖音 cookies 文件失败: {e}")
            return {}

    def _parse_kuaishou_cookies_file(self, cookies_path: str) -> dict:
        """解析 Netscape 格式的快手 cookies 文件并转换为 JSON 格式"""
        try:
            cookies_dict = {}

            with open(cookies_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        parts = line.split('\t')
                        if len(parts) >= 7:
                            domain = parts[0]
                            flag = parts[1] == 'TRUE'
                            path = parts[2]
                            secure = parts[3] == 'TRUE'
                            expiry = parts[4]
                            name = parts[5]
                            value = parts[6]

                            # 只处理快手相关的 cookies
                            if domain in ['.kuaishou.com', 'kuaishou.com', 'www.kuaishou.com', 'v.kuaishou.com']:
                                cookies_dict[name] = value
                                logger.debug(f"解析快手 cookie: {name} = {value[:10]}...")

            logger.info(f"成功解析 {len(cookies_dict)} 个快手 cookies")
            return cookies_dict

        except Exception as e:
            logger.error(f"解析快手 cookies 文件失败: {e}")
            return {}

    def _test_proxy_connection(self) -> bool:
        """测试代理服务器连接"""
        if not self.proxy_host:
            return False
        try:
            # 解析代理地址
            proxy_url = urlparse(self.proxy_host)
            proxies = {"http": self.proxy_host, "https": self.proxy_host}
            # 设置超时时间为5秒
            response = requests.get(
                "http://www.google.com", proxies=proxies, timeout=5, verify=False
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"代理连接测试失败: {str(e)}")
            return False

    def is_x_url(self, url: str) -> bool:
        """检查是否为 X (Twitter) URL"""
        parsed = urlparse(url)
        return parsed.netloc.lower() in [
            "twitter.com",
            "x.com",
            "www.twitter.com",
            "www.x.com",
        ]

    def is_youtube_url(self, url: str) -> bool:
        """检查是否为 YouTube URL"""
        parsed = urlparse(url)
        return parsed.netloc.lower() in [
            "youtube.com",
            "www.youtube.com",
            "youtu.be",
            "m.youtube.com",
        ]

    def is_facebook_url(self, url: str) -> bool:
        """检查是否为 Facebook URL"""
        parsed = urlparse(url)
        return parsed.netloc.lower() in [
            "facebook.com",
            "www.facebook.com",
            "m.facebook.com",
            "fb.watch",
            "fb.com",
        ]

    def is_xvideos_url(self, url: str) -> bool:
        """检查是否为 xvideos URL"""
        parsed = urlparse(url)
        return any(
            domain in parsed.netloc for domain in ["xvideos.com", "www.xvideos.com"]
        )

    def is_pornhub_url(self, url: str) -> bool:
        """检查是否为 pornhub URL"""
        parsed = urlparse(url)
        return any(
            domain in parsed.netloc
            for domain in ["pornhub.com", "www.pornhub.com", "cn.pornhub.com"]
        )

    def is_bilibili_url(self, url: str) -> bool:
        """检查是否为 Bilibili URL"""
        parsed = urlparse(url)
        return parsed.netloc.lower() in [
            "bilibili.com",
            "www.bilibili.com",
            "space.bilibili.com",
            "b23.tv",
        ]

    def is_telegraph_url(self, url: str) -> bool:
        """检查是否为 Telegraph URL"""
        parsed = urlparse(url)
        return parsed.netloc.lower() in ["telegra.ph", "telegraph.co"]

    def is_douyin_url(self, url: str) -> bool:
        """检查是否为抖音 URL"""
        parsed = urlparse(url)
        return parsed.netloc.lower() in [
            "douyin.com",
            "www.douyin.com",
            "v.douyin.com",
            "www.iesdouyin.com",
            "iesdouyin.com"
        ]

    def is_kuaishou_url(self, url: str) -> bool:
        """检查是否为快手 URL"""
        parsed = urlparse(url)
        # 支持多种快手URL格式
        if parsed.netloc.lower() in [
            "kuaishou.com",
            "www.kuaishou.com",
            "v.kuaishou.com",
            "m.kuaishou.com",
            "f.kuaishou.com"
        ]:
            return True

        # 检查URL路径是否包含快手特征
        if 'kuaishou.com' in url.lower():
            return True

        return False

    def extract_urls_from_text(self, text: str) -> list:
        """从文本中提取所有URL - 改进版本支持更多格式"""
        urls = []

        # 基础URL正则模式 - 支持中文文本中的URL
        url_patterns = [
            # 标准HTTP/HTTPS URL
            r'https?://[^\s\u4e00-\u9fff]+',
            # 快手短链接特殊处理
            r'v\.kuaishou\.com/[A-Za-z0-9]+',
            # 抖音短链接
            r'v\.douyin\.com/[A-Za-z0-9]+',
            # Facebook链接
            r'facebook\.com/[A-Za-z0-9/._-]+',
            r'fb\.watch/[A-Za-z0-9]+',
            # 其他短链接格式
            r'[a-zA-Z0-9.-]+\.com/[A-Za-z0-9/]+',
        ]

        for pattern in url_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                # 清理URL末尾的标点符号
                clean_url = match.rstrip('.,;!?。，；！？')
                # 确保URL有协议前缀
                if not clean_url.startswith(('http://', 'https://')):
                    clean_url = 'https://' + clean_url
                urls.append(clean_url)

        # 去重并保持顺序
        seen = set()
        unique_urls = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return unique_urls

    def _extract_clean_url_from_text(self, text: str) -> str:
        """从包含描述文本的字符串中提取纯净的URL"""
        try:
            # 使用已有的URL提取方法
            urls = self.extract_urls_from_text(text)
            if urls:
                return urls[0]  # 返回第一个找到的URL

            # 如果没有找到，可能文本本身就是一个URL
            text = text.strip()
            if text.startswith(('http://', 'https://')):
                # 提取URL部分（到第一个空格为止）
                url_part = text.split()[0] if ' ' in text else text
                return url_part

            return None
        except Exception as e:
            logger.warning(f"提取纯净URL失败: {e}")
            return None

    def is_xiaohongshu_url(self, url: str) -> bool:
        """检查是否为小红书 URL"""
        parsed = urlparse(url)
        return parsed.netloc.lower() in [
            "xiaohongshu.com",
            "www.xiaohongshu.com",
            "xhslink.com",
        ]

    def is_weibo_url(self, url: str) -> bool:
        """检查是否为微博 URL"""
        parsed = urlparse(url)
        return parsed.netloc.lower() in [
            "weibo.com",
            "www.weibo.com",
            "m.weibo.com",
            "video.weibo.com",
            "t.cn",  # 微博短链接
            "weibo.cn",  # 微博短链接
            "sinaurl.cn",  # 新浪短链接
        ]

    def _expand_weibo_short_url(self, url: str) -> str:
        """展开微博短链接为长链接"""
        import requests
        import re

        try:
            # 检查是否为微博短链接
            parsed = urlparse(url)
            short_domains = ["t.cn", "weibo.cn", "sinaurl.cn"]

            if parsed.netloc.lower() in short_domains:
                logger.info(f"🔄 检测到微博短链接，开始展开: {url}")

                # 优先使用移动端User-Agent，避免重定向到登录页面
                mobile_headers = {
                    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Mobile/15E148 Safari/604.1',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1'
                }

                # 桌面端User-Agent作为备用
                desktop_headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1'
                }

                # 先尝试移动端User-Agent的GET请求
                expanded_url = None
                try:
                    logger.info(f"🔄 使用移动端User-Agent请求...")
                    response = requests.get(url, headers=mobile_headers, allow_redirects=True, timeout=10)
                    expanded_url = response.url
                    logger.info(f"🔄 移动端请求重定向到: {expanded_url}")

                    # 检查是否得到了有效的微博视频URL
                    if "weibo.com" in expanded_url and ("tv/show" in expanded_url or "video" in expanded_url):
                        logger.info(f"✅ 移动端请求成功获取微博视频URL")
                        # 如果是h5.video.weibo.com，转换为标准的weibo.com格式
                        if "h5.video.weibo.com" in expanded_url:
                            expanded_url = expanded_url.replace("h5.video.weibo.com", "weibo.com/tv")
                            logger.info(f"🔄 转换为标准格式: {expanded_url}")
                    else:
                        logger.info(f"⚠️ 移动端请求未获取到标准微博视频URL，尝试桌面端...")
                        raise Exception("移动端未获取到标准URL")

                except Exception as e:
                    logger.warning(f"⚠️ 移动端请求失败: {e}")
                    # 如果移动端请求失败，尝试桌面端请求
                    try:
                        logger.info(f"🔄 使用桌面端User-Agent请求...")
                        response = requests.get(url, headers=desktop_headers, allow_redirects=True, timeout=10)
                        expanded_url = response.url
                        logger.info(f"🔄 桌面端请求重定向到: {expanded_url}")
                    except Exception as e2:
                        logger.warning(f"⚠️ 桌面端请求也失败: {e2}")
                        return url

                # 检查展开后的URL是否有效
                if expanded_url and expanded_url != url:
                    # 进一步处理可能的中间跳转页面
                    if "passport.weibo.com" in expanded_url and "url=" in expanded_url:
                        # 从跳转页面URL中提取真实的目标URL
                        import urllib.parse
                        try:
                            # 尝试多种URL参数提取方式
                            match = re.search(r'url=([^&]+)', expanded_url)
                            if match:
                                encoded_url = match.group(1)
                                # 多次URL解码，因为可能被多次编码
                                real_url = urllib.parse.unquote(encoded_url)
                                real_url = urllib.parse.unquote(real_url)  # 再次解码

                                # 清理URL参数，移除不必要的参数
                                if '?' in real_url:
                                    base_url, params = real_url.split('?', 1)
                                    # 保留重要参数，移除跟踪参数
                                    important_params = []
                                    for param in params.split('&'):
                                        if '=' in param:
                                            key, value = param.split('=', 1)
                                            if key in ['fid', 'id', 'video_id']:  # 保留重要的视频ID参数
                                                important_params.append(param)

                                    if important_params:
                                        real_url = base_url + '?' + '&'.join(important_params)
                                    else:
                                        real_url = base_url

                                logger.info(f"🔄 从跳转页面提取真实URL: {real_url}")
                                expanded_url = real_url
                        except Exception as e:
                            logger.warning(f"⚠️ 提取真实URL失败: {e}")
                            # 如果提取失败，尝试直接使用原始短链接
                            logger.info(f"🔄 回退到原始短链接: {url}")
                            expanded_url = url

                    logger.info(f"✅ 微博短链接展开成功: {url} -> {expanded_url}")
                    return expanded_url
                else:
                    logger.warning(f"⚠️ 短链接展开后URL无变化，使用原URL: {url}")
                    return url
            else:
                # 不是短链接，直接返回原URL
                return url

        except Exception as e:
            logger.warning(f"⚠️ 展开微博短链接失败: {e}")
            logger.warning(f"⚠️ 将使用原始URL: {url}")
            return url

    def is_instagram_url(self, url: str) -> bool:
        """检查是否为Instagram URL"""
        parsed = urlparse(url)
        return parsed.netloc.lower() in [
            "instagram.com",
            "www.instagram.com",
            "m.instagram.com",
        ]

    def is_tiktok_url(self, url: str) -> bool:
        """检查是否为TikTok URL"""
        parsed = urlparse(url)
        return parsed.netloc.lower() in [
            "tiktok.com",
            "www.tiktok.com",
            "m.tiktok.com",
            "vm.tiktok.com",
        ]

    def is_x_playlist_url(self, url: str) -> tuple:
        """
        检查是否为X播放列表URL，并提取播放列表信息
        Returns:
            tuple: (is_playlist, playlist_info) 或 (False, None)
        """
        import yt_dlp
        
        try:
            # 首先检查是否为X URL
            if not self.is_x_url(url):
                return False, None
            
            # 使用yt-dlp检查是否为播放列表
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
            }
            
            if self.proxy_host:
                ydl_opts['proxy'] = self.proxy_host
            
            if self.x_cookies_path:
                ydl_opts['cookiefile'] = self.x_cookies_path
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # 检查是否为播放列表
                if info and '_type' in info and info['_type'] == 'playlist':
                    entries = info.get('entries', [])
                    if len(entries) > 1:
                        playlist_info = {
                            'total_videos': len(entries),
                            'playlist_title': info.get('title', 'X播放列表'),
                            'playlist_url': url,
                            'entries': entries
                        }
                        logger.info(f"检测到X播放列表: {playlist_info['playlist_title']}, 共{len(entries)}个视频")
                        return True, playlist_info
                
                # 检查是否有多个条目
                if info and 'entries' in info and len(info['entries']) > 1:
                    playlist_info = {
                        'total_videos': len(info['entries']),
                        'playlist_title': info.get('title', 'X播放列表'),
                        'playlist_url': url,
                        'entries': info['entries']
                    }
                    logger.info(f"检测到X播放列表: {playlist_info['playlist_title']}, 共{len(info['entries'])}个视频")
                    return True, playlist_info
                    
            return False, None
        except Exception as e:
            logger.warning(f"检查X播放列表时出错: {e}")
            return False, None

    def is_bilibili_list_url(self, url: str) -> tuple:
        """
        检查是否为B站用户列表URL，并提取用户ID和列表ID
        Returns:
            tuple: (is_list, uid, list_id) 或 (False, None, None)
        """
        import re

        # 匹配B站用户列表URL:
        # https://space.bilibili.com/477348669/lists/2111173?type=season
        pattern = r"space\.bilibili\.com/(\d+)/lists/(\d+)"
        match = re.search(pattern, url)
        if match:
            uid = match.group(1)
            list_id = match.group(2)
            return True, uid, list_id
        return False, None, None

    def is_bilibili_multi_part_video(self, url: str) -> tuple:
        """
        检查是否为B站多P视频，并提取BV号
        Returns:
            tuple: (is_multi_part, bv_id) 或 (False, None)
        """
        import re
        import yt_dlp
        try:
            # 首先尝试从URL中提取BV号
            bv_pattern = r'BV[a-zA-Z0-9]+'
            bv_match = re.search(bv_pattern, url)

            # 如果URL中没有BV号，可能是短链接，需要先解析
            if not bv_match and ("b23.tv" in url or "b23.wtf" in url):
                logger.info(f"🔄 检测到B站短链接，先解析获取真实URL: {url}")
                try:
                    # 使用yt-dlp解析短链接
                    temp_opts = {
                        'quiet': True,
                        'no_warnings': True,
                    }
                    with yt_dlp.YoutubeDL(temp_opts) as ydl:
                        temp_info = ydl.extract_info(url, download=False)

                    if temp_info.get('webpage_url'):
                        real_url = temp_info['webpage_url']
                        logger.info(f"🔄 短链接解析结果: {real_url}")
                        # 从真实URL中提取BV号
                        bv_match = re.search(bv_pattern, real_url)
                        if bv_match:
                            logger.info(f"✅ 从短链接中提取到BV号: {bv_match.group(0)}")
                except Exception as e:
                    logger.warning(f"⚠️ 解析短链接失败: {e}")

            if not bv_match:
                return False, None

            bv_id = bv_match.group(0)
            
            # 使用yt-dlp检查是否为多P视频或合集
            # 先尝试快速检测（extract_flat=True）
            ydl_opts_flat = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                'flat_playlist': True,
            }

            try:
                with yt_dlp.YoutubeDL(ydl_opts_flat) as ydl:
                    info = ydl.extract_info(url, download=False)

                    # 检查是否有多个条目
                    if info and '_type' in info and info['_type'] == 'playlist':
                        entries = info.get('entries', [])
                        if len(entries) > 1:
                            logger.info(f"✅ 检测到B站多内容视频: {bv_id}, 共{len(entries)}个条目")
                            return True, bv_id

                    # 检查是否有分P信息
                    if info and 'entries' in info and len(info['entries']) > 1:
                        logger.info(f"✅ 检测到B站多内容视频: {bv_id}, 共{len(info['entries'])}个条目")
                        return True, bv_id
            except Exception as e:
                logger.warning(f"快速检测失败: {e}")

            # 如果快速检测失败，尝试完整检测（extract_flat=False）
            logger.info(f"🔄 快速检测未发现多内容，尝试完整检测: {bv_id}")

            # 使用输出捕获来检测anthology
            import io
            from contextlib import redirect_stdout, redirect_stderr

            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()

            ydl_opts_full = {
                'quiet': False,  # 改为False以便看到更多信息
                'no_warnings': False,  # 改为False以便看到警告信息
                'extract_flat': False,
                'noplaylist': False,
                'simulate': True,  # 添加模拟模式
            }

            try:
                with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                    with yt_dlp.YoutubeDL(ydl_opts_full) as ydl:
                        info = ydl.extract_info(url, download=False)

                # 检查捕获的输出中是否包含anthology
                stdout_output = stdout_capture.getvalue()
                stderr_output = stderr_capture.getvalue()
                all_output = (stdout_output + stderr_output).lower()

                if 'anthology' in all_output or 'extracting videos in anthology' in all_output:
                    logger.info(f"✅ 从yt-dlp输出中检测到anthology: {bv_id}")
                    return True, bv_id

                # 检查是否有多个条目
                    if info and '_type' in info and info['_type'] == 'playlist':
                        entries = info.get('entries', [])
                        if len(entries) > 1:
                            logger.info(f"✅ 完整检测发现B站多内容视频: {bv_id}, 共{len(entries)}个条目")
                            return True, bv_id

                    # 检查是否有分P信息
                    if info and 'entries' in info and len(info['entries']) > 1:
                        logger.info(f"✅ 完整检测发现B站多内容视频: {bv_id}, 共{len(info['entries'])}个条目")
                        return True, bv_id

                    # 检查是否包含anthology信息（B站合集的特征）
                    info_str = str(info).lower()
                    if info and any(key in info_str for key in ['anthology', 'collection', 'series']):
                        logger.info(f"✅ 检测到B站合集特征: {bv_id}")
                        return True, bv_id

                    # 额外检查：使用模拟下载来检测anthology
                    try:
                        logger.info(f"🔍 使用模拟下载检测anthology: {bv_id}")

                        # 使用更详细的日志捕获anthology信息
                        import io
                        import sys
                        from contextlib import redirect_stdout, redirect_stderr

                        # 捕获yt-dlp的输出
                        stdout_capture = io.StringIO()
                        stderr_capture = io.StringIO()

                        simulate_opts = {
                            'quiet': False,  # 改为False以捕获anthology信息
                            'no_warnings': False,  # 改为False以捕获更多信息
                            'simulate': True,
                            'extract_flat': False,
                        }

                        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                            with yt_dlp.YoutubeDL(simulate_opts) as sim_ydl:
                                sim_info = sim_ydl.extract_info(url, download=False)

                        # 检查捕获的输出中是否包含anthology
                        stdout_output = stdout_capture.getvalue().lower()
                        stderr_output = stderr_capture.getvalue().lower()
                        all_output = stdout_output + stderr_output

                        if 'anthology' in all_output or 'extracting videos in anthology' in all_output:
                            logger.info(f"✅ 从输出中检测到anthology关键词: {bv_id}")
                            return True, bv_id

                        # 检查模拟下载的信息中是否包含anthology
                        sim_str = str(sim_info).lower()
                        if 'anthology' in sim_str:
                            logger.info(f"✅ 模拟下载检测到anthology关键词: {bv_id}")
                            return True, bv_id

                        # 检查是否有多个entries
                        if sim_info and 'entries' in sim_info and len(sim_info['entries']) > 1:
                            logger.info(f"✅ 模拟下载检测到多个条目: {bv_id}, 共{len(sim_info['entries'])}个")
                            return True, bv_id

                    except Exception as sim_e:
                        logger.warning(f"模拟下载检测失败: {sim_e}")

                    # 尝试从重定向URL中提取用户ID，检查用户空间是否有多个视频
                    webpage_url = info.get('webpage_url', '')
                    if webpage_url and 'up_id=' in webpage_url:
                        import re
                        up_id_match = re.search(r'up_id=(\d+)', webpage_url)
                        if up_id_match:
                            up_id = up_id_match.group(1)
                            logger.info(f"🔍 尝试检查用户空间: {up_id}")

                            # 检查用户空间是否有多个视频
                            user_space_url = f"https://space.bilibili.com/{up_id}"
                            try:
                                user_opts = {
                                    'quiet': True,
                                    'no_warnings': True,
                                    'extract_flat': True,
                                    'flat_playlist': True,
                                }
                                with yt_dlp.YoutubeDL(user_opts) as user_ydl:
                                    user_info = user_ydl.extract_info(user_space_url, download=False)

                                if user_info and 'entries' in user_info:
                                    user_entries = user_info['entries']
                                    if len(user_entries) > 1:
                                        logger.info(f"✅ 用户空间检测到多个视频: {len(user_entries)}个，可能是合集分享")
                                        return True, bv_id
                            except Exception as user_e:
                                logger.warning(f"用户空间检测失败: {user_e}")

            except Exception as e:
                logger.warning(f"完整检测失败: {e}")
                    
            return False, bv_id
        except Exception as e:
            logger.warning(f"检查B站多P视频时出错: {e}")
            return False, None

    def is_youtube_playlist_url(self, url: str) -> tuple:
        """检查是否为 YouTube 播放列表 URL"""
        import re

        # 匹配 YouTube 播放列表 URL
        patterns = [
            r"(?:youtube\.com/playlist\?list=|youtube\.com/watch\?.*&list=)([a-zA-Z0-9_-]+)",
            r"youtube\.com/playlist\?list=([a-zA-Z0-9_-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                playlist_id = match.group(1)
                return True, playlist_id
        return False, None

    def is_youtube_channel_playlists_url(self, url: str) -> tuple:
        """检查是否为 YouTube 频道播放列表页面 URL 或频道主页 URL"""
        import re

        # 首先匹配已经包含 /playlists 的URL
        playlists_patterns = [
            r"youtube\.com/@([^/\?]+)/playlists",
            r"youtube\.com/c/([^/\?]+)/playlists",
            r"youtube\.com/channel/([^/\?]+)/playlists",
            r"youtube\.com/user/([^/\?]+)/playlists",
        ]
        for pattern in playlists_patterns:
            match = re.search(pattern, url)
            if match:
                channel_identifier = match.group(1)
                return True, url

        # 然后匹配频道主页URL，自动转换为播放列表URL
        channel_patterns = [
            r"youtube\.com/@([^/\?]+)(?:\?.*)?$",  # @username 格式
            r"youtube\.com/c/([^/\?]+)(?:\?.*)?$",  # /c/channel 格式
            r"youtube\.com/channel/([^/\?]+)(?:\?.*)?$",  # /channel/ID 格式
            r"youtube\.com/user/([^/\?]+)(?:\?.*)?$",  # /user/username 格式
        ]
        for pattern in channel_patterns:
            match = re.search(pattern, url)
            if match:
                channel_identifier = match.group(1)
                # 构建播放列表URL
                if "@" in url:
                    playlists_url = f"https://www.youtube.com/@{channel_identifier}/playlists"
                elif "/c/" in url:
                    playlists_url = f"https://www.youtube.com/c/{channel_identifier}/playlists"
                elif "/channel/" in url:
                    playlists_url = f"https://www.youtube.com/channel/{channel_identifier}/playlists"
                elif "/user/" in url:
                    playlists_url = f"https://www.youtube.com/user/{channel_identifier}/playlists"
                else:
                    playlists_url = url

                logger.info(f"🔍 检测到YouTube频道主页，转换为播放列表URL: {playlists_url}")
                return True, playlists_url
        return False, None

    def get_download_path(self, url: str) -> Path:
        """根据 URL 确定下载路径"""
        if self.is_x_url(url):
            return self.x_download_path.resolve()
        elif self.is_youtube_url(url):
            return self.youtube_download_path.resolve()
        elif self.is_xvideos_url(url):
            return self.xvideos_download_path.resolve()
        elif self.is_pornhub_url(url):
            return self.pornhub_download_path.resolve()
        elif self.is_bilibili_url(url):
            return self.bilibili_download_path.resolve()
        elif self.is_telegraph_url(url):
            return self.telegraph_download_path.resolve()
        elif self.is_douyin_url(url):
            return self.douyin_download_path.resolve()
        elif self.is_kuaishou_url(url):
            return self.kuaishou_download_path.resolve()
        elif self.is_facebook_url(url):
            return self.facebook_download_path.resolve()
        elif self.is_xiaohongshu_url(url):
            return self.xiaohongshu_download_path.resolve()  # 小红书使用自己的目录
        elif self.is_weibo_url(url):
            return self.weibo_download_path.resolve()
        elif self.is_instagram_url(url):
            return self.instagram_download_path.resolve()
        elif self.is_tiktok_url(url):
            return self.tiktok_download_path.resolve()
        else:
            return self.youtube_download_path.resolve()

    def get_platform_name(self, url: str) -> str:
        """获取平台名称"""
        if self.is_x_url(url):
            return "x"
        elif self.is_youtube_url(url):
            return "youtube"
        elif self.is_xvideos_url(url):
            return "xvideos"
        elif self.is_pornhub_url(url):
            return "pornhub"
        elif self.is_bilibili_url(url):
            return "bilibili"
        elif self.is_telegraph_url(url):
            return "telegraph"
        elif self.is_douyin_url(url):
            return "douyin"
        elif self.is_kuaishou_url(url):
            return "kuaishou"
        elif self.is_facebook_url(url):
            return "facebook"
        elif self.is_xiaohongshu_url(url):
            return "xiaohongshu"
        elif self.is_weibo_url(url):
            return "weibo"
        elif self.is_instagram_url(url):
            return "instagram"
        elif self.is_tiktok_url(url):
            return "tiktok"
        else:
            return "other"

    def check_ytdlp_version(self) -> Dict[str, Any]:
        """检查yt-dlp版本"""
        try:
            import yt_dlp

            version = yt_dlp.version.__version__
            return {
                "success": True,
                "version": version,
                "info": f"yt-dlp 版本: {version}",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def check_video_formats(self, url: str) -> Dict[str, Any]:
        """检查视频的可用格式"""
        try:
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "listformats": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                formats = info.get("formats", [])
                video_formats = []
                audio_formats = []
                for fmt in formats:
                    format_info = {
                        "id": fmt.get("format_id", "unknown"),
                        "ext": fmt.get("ext", "unknown"),
                        "quality": fmt.get("format_note", "unknown"),
                        "filesize": fmt.get("filesize", 0),
                        "height": fmt.get("height", 0),
                        "width": fmt.get("width", 0),
                        "fps": fmt.get("fps", 0),
                        "vcodec": fmt.get("vcodec", "none"),
                        "acodec": fmt.get("acodec", "none"),
                        "format_type": (
                            "video" if fmt.get("vcodec", "none") != "none" else "audio"
                        ),
                    }
                    if format_info["format_type"] == "video":
                        video_formats.append(format_info)
                    else:
                        audio_formats.append(format_info)
                # 按质量排序
                video_formats.sort(
                    key=lambda x: (x["height"], x["filesize"]), reverse=True
                )
                audio_formats.sort(key=lambda x: x["filesize"], reverse=True)
                # 检查是否有高分辨率格式
                has_high_res = any(f.get("height", 0) >= 2160 for f in video_formats)
                has_4k = any(f.get("height", 0) >= 2160 for f in video_formats)
                has_1080p = any(f.get("height", 0) >= 1080 for f in video_formats)
                has_720p = any(f.get("height", 0) >= 720 for f in video_formats)
                return {
                    "success": True,
                    "title": info.get("title", "Unknown"),
                    "duration": info.get("duration", 0),
                    "video_formats": video_formats[:10],  # 只显示前10个视频格式
                    "audio_formats": audio_formats[:5],  # 只显示前5个音频格式
                    "quality_info": {
                        "has_4k": has_4k,
                        "has_1080p": has_1080p,
                        "has_720p": has_720p,
                        "total_video_formats": len(video_formats),
                        "total_audio_formats": len(audio_formats),
                    },
                }
        except Exception as e:
            logger.error(f"格式检查失败: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_media_info(self, file_path: str) -> Dict[str, Any]:
        """使用 ffprobe 获取媒体文件的详细信息"""
        try:
            # 首先检查文件是否存在
            if not os.path.exists(file_path):
                logger.warning(f"⚠️ 文件不存在: {file_path}")
                return {}
            
            # 检查文件大小
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                logger.warning(f"⚠️ 文件大小为0: {file_path}")
                return {}
            
            cmd = [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(file_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            info = json.loads(result.stdout)
            media_info = {}
            if "format" in info:
                duration = float(info["format"].get("duration", 0))
                if duration > 0:
                    media_info["duration"] = (
                        time.strftime("%H:%M:%S", time.gmtime(duration))
                        if duration >= 3600
                        else time.strftime("%M:%S", time.gmtime(duration))
                    )
                size = int(info["format"].get("size", 0) or 0)
                if size > 0:
                    media_info["size"] = f"{size / (1024 * 1024):.2f} MB"
            video_stream = next(
                (s for s in info.get("streams", []) if s.get("codec_type") == "video"),
                None,
            )
            if video_stream:
                width, height = video_stream.get("width"), video_stream.get("height")
                if width and height:
                    media_info["resolution"] = f"{width}x{height}"
            audio_stream = next(
                (s for s in info.get("streams", []) if s.get("codec_type") == "audio"),
                None,
            )
            if audio_stream:
                bit_rate = int(audio_stream.get("bit_rate", 0))
                if bit_rate > 0:
                    media_info["bit_rate"] = f"{bit_rate // 1000} kbps"
            return media_info
        except (
            subprocess.CalledProcessError,
            FileNotFoundError,
            json.JSONDecodeError,
        ) as e:
            logger.warning(f"⚠️ 无法使用 ffprobe 获取媒体信息: {e}")
            # 返回基本的文件信息
            try:
                if os.path.exists(file_path):
                    file_size = os.path.getsize(file_path)
                    if file_size > 0:
                        return {"size": f"{file_size / (1024 * 1024):.2f} MB"}
            except Exception as e2:
                logger.warning(f"⚠️ 获取文件大小失败: {e2}")
            return {}

    def single_video_find_downloaded_file(
        self, download_path: Path, progress_data: dict = None, expected_title: str = None, url: str = None
    ) -> str:
        """
        单视频下载的文件查找方法

        Args:
            download_path: 下载目录
            progress_data: 进度数据，包含final_filename
            expected_title: 预期的文件名（不包含扩展名）
            url: 原始URL，用于判断平台类型

        Returns:
            str: 找到的文件路径，如果没找到返回None
        """
        # 1. 优先使用progress_hook记录的文件路径
        if progress_data and progress_data.get("final_filename"):
            final_file_path = progress_data["final_filename"]
            
            # 检查是否是中间文件，如果是则直接查找合并后的文件
            original_path = Path(final_file_path)
            base_name = original_path.stem
            
            # 检查是否是中间文件（包含.f140, .f401等格式标识符）
            is_intermediate_file = False
            if "." in base_name:
                parts = base_name.split(".")
                # 如果最后一部分是数字（如f140, f401），则移除它
                if (
                    len(parts) > 1
                    and parts[-1].startswith("f")
                    and parts[-1][1:].isdigit()
                ):
                    base_name = ".".join(parts[:-1])
                    is_intermediate_file = True
            
            # 如果是中间文件，直接查找合并后的文件
            if is_intermediate_file:
                logger.info(f"🔍 检测到中间文件，直接查找合并后的文件: {final_file_path}")
                # 构造最终文件名（优先查找.mp4，然后是其他格式）
                possible_extensions = [".mp4", ".mkv", ".webm", ".avi", ".mov"]
                for ext in possible_extensions:
                    final_merged_file = original_path.parent / f"{base_name}{ext}"
                    logger.info(f"🔍 尝试查找合并后的文件: {final_merged_file}")
                    
                    if os.path.exists(final_merged_file):
                        logger.info(f"✅ 找到合并后的文件: {final_merged_file}")
                        return str(final_merged_file)
                
                logger.warning(f"⚠️ 未找到合并后的文件，基础名称: {base_name}")
            else:
                # 不是中间文件，直接检查是否存在
                if os.path.exists(final_file_path):
                    logger.info(f"✅ 使用progress_hook记录的文件路径: {final_file_path}")
                    return final_file_path
                else:
                    # 检查是否为中间文件（包含格式代码的文件）
                    original_path = Path(final_file_path)
                    filename = original_path.name

                    # 检查是否为DASH中间文件
                    is_dash_intermediate = (
                        '.fdash-' in filename or
                        '.f' in filename and filename.count('.') >= 2 or
                        'dash-' in filename
                    )

                    if is_dash_intermediate:
                        logger.info(f"🔍 检测到DASH中间文件，尝试查找合并后的文件: {filename}")
                        # 尝试查找合并后的文件
                        base_name = filename.split('.f')[0] if '.f' in filename else filename.split('.')[0]
                        ext = '.mp4'  # 合并后通常是mp4格式
                        final_merged_file = original_path.parent / f"{base_name}{ext}"

                        if os.path.exists(final_merged_file):
                            logger.info(f"✅ 找到DASH合并后的文件: {final_merged_file}")
                            return str(final_merged_file)
                        else:
                            logger.info(f"🔍 DASH合并文件不存在，将使用其他方法查找: {final_merged_file}")
                    else:
                        logger.warning(f"⚠️ progress_hook记录的文件路径不存在: {final_file_path}")

        # 2. 基于预期文件名查找
        if expected_title:
            logger.info(f"🔍 基于预期文件名查找: {expected_title}")
            # 使用统一的文件名清理方法
            safe_title = self._sanitize_filename(expected_title)
            if safe_title:
                # 尝试不同的扩展名
                possible_extensions = [".mp4", ".mkv", ".webm", ".avi", ".mov"]
                for ext in possible_extensions:
                    expected_file = download_path / f"{safe_title}{ext}"
                    logger.info(f"🔍 尝试查找文件: {expected_file}")
                    if os.path.exists(expected_file):
                        logger.info(f"✅ 找到基于标题的文件: {expected_file}")
                        return str(expected_file)
                
                logger.warning(f"⚠️ 未找到基于标题的文件: {safe_title}")

        # 3. 基于平台特定逻辑查找
        if url:
            logger.info(f"🔍 基于平台特定逻辑查找: {url}")
            try:
                if self.is_x_url(url):
                    # X平台：基于视频标题查找
                    logger.info("🔍 X平台：尝试获取视频标题并查找")
                    info_opts = {
                        "quiet": True,
                        "no_warnings": True,
                        "socket_timeout": 15,
                        "retries": 2,
                    }
                    if self.x_cookies_path and os.path.exists(self.x_cookies_path):
                        info_opts["cookiefile"] = self.x_cookies_path
                    
                    with yt_dlp.YoutubeDL(info_opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                        if info and info.get('title'):
                            title = info.get('title')
                            safe_title = self._sanitize_filename(title)
                            if safe_title:
                                logger.info(f"🔍 X平台标题: {safe_title}")
                                # 尝试不同的扩展名
                                possible_extensions = [".mp4", ".mkv", ".webm", ".avi", ".mov"]
                                for ext in possible_extensions:
                                    expected_file = download_path / f"{safe_title}{ext}"
                                    logger.info(f"🔍 尝试查找X平台文件: {expected_file}")
                                    if os.path.exists(expected_file):
                                        logger.info(f"✅ 找到X平台文件: {expected_file}")
                                        return str(expected_file)
                                
                                logger.warning(f"⚠️ 未找到X平台文件，标题: {safe_title}")
                            else:
                                logger.warning("⚠️ X平台标题为空或无效")
                        else:
                            logger.warning("⚠️ 无法获取X平台视频标题")
                else:
                    # 其他平台：基于标题查找（如果还没有尝试过）
                    if not expected_title:
                        logger.info("🔍 其他平台：尝试获取视频标题并查找")
                        info_opts = {
                            "quiet": True,
                            "no_warnings": True,
                            "socket_timeout": 15,
                            "retries": 2,
                        }
                        if self.youtube_cookies_path and os.path.exists(self.youtube_cookies_path):
                            info_opts["cookiefile"] = self.youtube_cookies_path
                        if self.douyin_cookies_path and os.path.exists(self.douyin_cookies_path):
                            info_opts["cookiefile"] = self.douyin_cookies_path
                        
                        with yt_dlp.YoutubeDL(info_opts) as ydl:
                            info = ydl.extract_info(url, download=False)
                            if info and info.get('title'):
                                title = info.get('title')
                                safe_title = self._sanitize_filename(title)
                                if safe_title:
                                    logger.info(f"🔍 其他平台标题: {safe_title}")
                                    # 尝试不同的扩展名
                                    possible_extensions = [".mp4", ".mkv", ".webm", ".avi", ".mov"]
                                    for ext in possible_extensions:
                                        expected_file = download_path / f"{safe_title}{ext}"
                                        logger.info(f"🔍 尝试查找其他平台文件: {expected_file}")
                                        if os.path.exists(expected_file):
                                            logger.info(f"✅ 找到其他平台文件: {expected_file}")
                                            return str(expected_file)
                                    
                                    logger.warning(f"⚠️ 未找到其他平台文件，标题: {safe_title}")
            except Exception as e:
                logger.warning(f"⚠️ 平台特定查找失败: {e}")

        # 4. 如果都找不到，记录错误并返回None
        logger.error("❌ 无法找到预期的下载文件")
        return None

    async def _download_with_ytdlp_unified(
        self, 
        url: str, 
        download_path: Path, 
        message_updater=None, 
        platform_name: str = "Unknown",
        content_type: str = "video",
        format_spec: str = "best[height<=1080]",
        cookies_path: str = None
    ) -> Dict[str, Any]:
        """
        统一的 yt-dlp 下载函数
        
        Args:
            url: 下载URL
            download_path: 下载目录
            message_updater: 消息更新器
            platform_name: 平台名称
            content_type: 内容类型 (video/image)
            format_spec: 格式规格
            cookies_path: cookies文件路径
            
        Returns:
            Dict[str, Any]: 下载结果
        """
        try:
            import yt_dlp
            
            # 确保下载目录存在
            os.makedirs(download_path, exist_ok=True)
            
            # 配置 yt-dlp
            ydl_opts = {
                'format': format_spec,
                'outtmpl': os.path.join(str(download_path), '%(title).50s.%(ext)s'),
                'verbose': False,
                'no_warnings': True,
                'extract_flat': False,
                'ignoreerrors': False,
                'no_check_certificate': True,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                }
            }
            
            # 添加 cookies 支持
            if cookies_path and os.path.exists(cookies_path):
                ydl_opts["cookiefile"] = cookies_path
                logger.info(f"🍪 使用cookies: {cookies_path}")
            
            # 进度数据存储
            progress_data = {"final_filename": None, "lock": threading.Lock()}
            
            # 使用统一的单集下载进度回调
            # 检查 message_updater 是否是增强版进度回调函数
            if callable(message_updater) and message_updater.__name__ == 'enhanced_progress_callback':
                # 如果是增强版进度回调，直接使用它返回的 progress_hook
                progress_hook = message_updater(progress_data)
            else:
                # 否则使用标准的 single_video_progress_hook
                progress_hook = single_video_progress_hook(message_updater, progress_data)
            
            ydl_opts["progress_hooks"] = [progress_hook]
            
            # 开始下载
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info(f"🎬 yt-dlp 开始下载 {platform_name} {content_type}...")
                info = ydl.extract_info(url, download=True)
                
                if not info:
                    raise Exception(f"yt-dlp 未获取到{content_type}信息")
                
                # 检查info的类型，确保它是字典
                if not isinstance(info, dict):
                    logger.error(f"❌ yt-dlp 返回了非字典类型的结果: {type(info)}, 内容: {info}")
                    raise Exception(f"yt-dlp 返回了意外的数据类型: {type(info)}")
                
                # 查找下载的文件
                filename = ydl.prepare_filename(info)
                logger.info(f"🔍 yt-dlp 准备的文件名: {filename}")
                
                if not os.path.exists(filename):
                    logger.info(f"⚠️ 准备的文件名不存在，尝试查找实际下载的文件...")
                    # 尝试查找实际下载的文件
                    download_path_found = self.single_video_find_downloaded_file(
                        download_path, 
                        progress_data, 
                        info.get('title', ''), 
                        url
                    )
                    if download_path_found:
                        filename = download_path_found
                        logger.info(f"✅ 找到实际下载的文件: {filename}")
                    else:
                        raise Exception(f"未找到下载的{content_type}文件")
                else:
                    logger.info(f"✅ 使用yt-dlp准备的文件名: {filename}")
                
                # 重命名文件以使用清理过的文件名
                try:
                    original_filename = filename
                    file_dir = os.path.dirname(filename)
                    file_ext = os.path.splitext(filename)[1]
                    
                    # 获取原始标题并清理
                    original_title = info.get('title', f'{platform_name}_{content_type}')
                    clean_title = self._sanitize_filename(original_title)
                    
                    # 构建新的文件名
                    new_filename = os.path.join(file_dir, f"{clean_title}{file_ext}")
                    
                    # 如果新文件名与旧文件名不同，则重命名
                    if new_filename != original_filename:
                        # 如果新文件名已存在，添加数字后缀
                        counter = 1
                        final_filename = new_filename
                        while os.path.exists(final_filename):
                            name_without_ext = os.path.splitext(new_filename)[0]
                            final_filename = f"{name_without_ext}_{counter}{file_ext}"
                            counter += 1
                        
                        # 重命名文件
                        os.rename(original_filename, final_filename)
                        filename = final_filename
                        logger.info(f"✅ 文件已重命名为: {os.path.basename(filename)}")
                    else:
                        logger.info(f"✅ 文件名无需重命名")
                        
                except Exception as e:
                    logger.warning(f"⚠️ 重命名文件失败，使用原始文件名: {e}")
                    # 继续使用原始文件名
                
                # 获取文件信息
                file_size = os.path.getsize(filename)
                size_mb = file_size / 1024 / 1024
                
                logger.info(f"✅ {platform_name} {content_type}下载成功: {filename} ({size_mb:.1f} MB)")
                
                # 构建返回结果
                result = {
                    "success": True,
                    "platform": platform_name,
                    "content_type": content_type,
                    "download_path": filename,
                    "full_path": filename,
                    "size_mb": size_mb,
                    "title": info.get('title', f'{platform_name}{content_type}'),
                    "uploader": info.get('uploader', f'{platform_name}用户'),
                    "filename": os.path.basename(filename),
                }
                
                # 根据内容类型添加特定信息
                if content_type == "video":
                    # 视频特有信息
                    duration = info.get('duration', 0)
                    width = info.get('width', 0)
                    height = info.get('height', 0)
                    resolution = f"{width}x{height}" if width and height else "未知"
                    
                    # 格式化时长
                    if duration:
                        minutes, seconds = divmod(int(duration), 60)
                        hours, minutes = divmod(minutes, 60)
                        if hours > 0:
                            duration_str = f"{hours}:{minutes:02d}:{seconds:02d}"
                        else:
                            duration_str = f"{minutes}:{seconds:02d}"
                    else:
                        duration_str = "未知"
                    
                    result.update({
                        "duration": duration,
                        "duration_str": duration_str,
                        "resolution": resolution,
                        "width": width,
                        "height": height,
                    })
                else:
                    # 图片特有信息
                    width = info.get('width', 0)
                    height = info.get('height', 0)
                    resolution = f"{width}x{height}" if width and height else "未知"
                    
                    result.update({
                        "resolution": resolution,
                        "width": width,
                        "height": height,
                    })
                
                return result
                
        except Exception as e:
            logger.error(f"❌ yt-dlp 下载 {platform_name} {content_type}失败: {e}")
            return {
                "success": False,
                "error": f"yt-dlp 下载失败: {str(e)}",
                "platform": platform_name,
                "content_type": content_type
            }

    def cleanup_duplicates(self):
        """清理重复文件"""
        try:
            cleaned_count = 0
            for directory in [self.x_download_path, self.youtube_download_path]:
                if directory.exists():
                    for file in directory.glob("*"):
                        if file.is_file() and " #" in file.name:
                            # 检查是否是视频文件
                            if any(
                                file.name.endswith(ext)
                                for ext in [".mp4", ".mkv", ".webm", ".mov", ".avi"]
                            ):
                                try:
                                    file.unlink()
                                    logger.info(f"删除重复文件: {file.name}")
                                    cleaned_count += 1
                                except Exception as e:
                                    logger.error(f"删除文件失败: {e}")
            return cleaned_count
        except Exception as e:
            logger.error(f"清理重复文件失败: {e}")
            return 0

    def _generate_display_filename(self, original_filename, timestamp):
        """生成用户友好的显示文件名"""
        try:
            # 移除时间戳前缀
            if original_filename.startswith(f"{timestamp}_"):
                display_name = original_filename[len(f"{timestamp}_") :]
            else:
                display_name = original_filename
            # 如果文件名太长，截断它
            if len(display_name) > 35:
                name, ext = os.path.splitext(display_name)
                display_name = name[:30] + "..." + ext
            return display_name
        except BaseException:
            return original_filename

    def _detect_x_content_type(self, url: str) -> str:
        """检测 X 链接的内容类型（图片/视频）"""
        logger.info(f"🔍 开始检测 X 内容类型: {url}")
        
        # 方法1: 使用 yt-dlp 检测（最准确）
        content_type = self._detect_with_ytdlp(url)
        if content_type:
            return content_type
        
        # 方法2: 使用 curl 检测（备用）
        content_type = self._detect_with_curl(url)
        if content_type:
            return content_type
        
        # 方法3: 默认处理 - 当成视频用 yt-dlp 下载
        logger.info("🎬 检测失败，默认为视频类型，使用 yt-dlp 下载")
        return "video"

    def _detect_with_ytdlp(self, url: str) -> str:
        """使用 yt-dlp 检测内容类型"""
        try:
            import yt_dlp
            
            # 配置 yt-dlp 选项
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": False,  # 不使用 flat 模式，获取完整信息
                "skip_download": True,  # 不下载，只获取信息
                "socket_timeout": 15,   # 15秒超时
                "retries": 2,           # 减少重试次数
            }
            
            # 添加 cookies 支持
            if self.x_cookies_path and os.path.exists(self.x_cookies_path):
                ydl_opts["cookiefile"] = self.x_cookies_path
                logger.info(f"🍪 yt-dlp 使用X cookies: {self.x_cookies_path}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info("🔍 yt-dlp 开始提取信息...")
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    logger.warning("⚠️ yt-dlp 未获取到信息")
                    return None
                
                # 优先检查是否有视频格式（最高优先级）
                formats = info.get('formats', [])
                if formats:
                    # 查找有视频编码的格式
                    video_formats = [f for f in formats if f.get('vcodec') and f.get('vcodec') != 'none']
                    if video_formats:
                        logger.info(f"🎬 yt-dlp 检测到视频内容，找到 {len(video_formats)} 个视频格式")
                        return "video"
                
                # 检查其他视频指标
                if info.get('duration') and info.get('duration') > 0:
                    logger.info(f"🎬 yt-dlp 通过时长检测到视频内容: {info.get('duration')}秒")
                    return "video"
                
                # 检查文件扩展名（视频优先）
                filename = info.get('filename', '')
                if any(ext in filename.lower() for ext in ['.mp4', '.webm', '.mov', '.avi']):
                    logger.info(f"🎬 yt-dlp 通过文件名检测到视频内容: {filename}")
                    return "video"
                
                # 最后检查是否有图片信息
                thumbnails = info.get('thumbnails', [])
                if thumbnails:
                    logger.info(f"📸 yt-dlp 检测到图片内容，找到 {len(thumbnails)} 个缩略图")
                    return "image"
                
                # 检查图片文件扩展名
                if any(ext in filename.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                    logger.info(f"📸 yt-dlp 通过文件名检测到图片内容: {filename}")
                    return "image"
                
                logger.info("🎬 yt-dlp 未检测到明确内容类型，默认为视频类型")
                return "video"
                
        except Exception as e:
            logger.warning(f"⚠️ yt-dlp 检测失败: {e}")
        return None

    def _detect_with_curl(self, url: str) -> str:
        """使用 curl 检测内容类型（备用方法）"""
        try:
            import subprocess
            import re
            import gzip
            
            # 构建 curl 命令
            curl_cmd = [
                "curl", "-s", "-L", "-k",  # 静默模式，跟随重定向，禁用SSL验证
                "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "-H", "Accept-Language: en-US,en;q=0.5",
                "-H", "Accept-Encoding: gzip, deflate, br",
                "-H", "DNT: 1",
                "-H", "Connection: keep-alive",
                "-H", "Upgrade-Insecure-Requests: 1",
                "--max-time", "10",  # 10秒超时
            ]
            
            # 如果有 cookies，添加 cookies 文件
            if self.x_cookies_path and os.path.exists(self.x_cookies_path):
                curl_cmd.extend(["-b", self.x_cookies_path])
                logger.info(f"🍪 curl 使用X cookies: {self.x_cookies_path}")
            
            curl_cmd.append(url)
            
            # 执行 curl 命令
            logger.info("🔍 curl 开始检测内容类型...")
            result = subprocess.run(curl_cmd, capture_output=True, timeout=15)
            
            if result.returncode != 0:
                logger.warning(f"⚠️ curl 请求失败: {result.stderr}")
                return None
            
            # 处理响应内容
            try:
                html_content = result.stdout.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    html_content = gzip.decompress(result.stdout).decode('utf-8')
                except Exception:
                    html_content = result.stdout.decode('utf-8', errors='ignore')
            
            # 检测视频相关的 HTML 元素
            video_patterns = [
                r'<video[^>]*>',
                r'data-testid="videoPlayer"',
                r'data-testid="video"',
                r'aria-label="[^"]*video[^"]*"',
                r'class="[^"]*video[^"]*"',
            ]
            
            # 检测图片相关的 HTML 元素
            image_patterns = [
                r'<img[^>]*>',
                r'data-testid="tweetPhoto"',
                r'data-testid="image"',
                r'aria-label="[^"]*image[^"]*"',
                r'class="[^"]*image[^"]*"',
            ]
            
            # 检查视频模式
            for pattern in video_patterns:
                if re.search(pattern, html_content, re.IGNORECASE):
                    logger.info(f"🎬 curl 检测到视频内容 (模式: {pattern})")
                    return "video"
            
            # 检查图片模式
            for pattern in image_patterns:
                if re.search(pattern, html_content, re.IGNORECASE):
                    logger.info(f"📸 curl 检测到图片内容 (模式: {pattern})")
                    return "image"
            
            # 文本检测
            if re.search(r'video|mp4|webm|mov', html_content, re.IGNORECASE):
                logger.info("🎬 curl 通过文本检测到视频内容")
                return "video"
            
            if re.search(r'image|photo|jpg|jpeg|png|gif|webp', html_content, re.IGNORECASE):
                logger.info("📸 curl 通过文本检测到图片内容")
                return "image"
            
            logger.info("📸 curl 未检测到明确内容类型")
            return None
                
        except subprocess.TimeoutExpired:
            logger.warning("⚠️ curl 请求超时")
            return None
        except Exception as e:
            logger.warning(f"⚠️ curl 检测失败: {e}")
            return None

    async def download_video(
        self, url: str, message_updater=None, auto_playlist=False, status_message=None, loop=None
    ) -> Dict[str, Any]:
        # 自动修正小红书短链协议
        if url.startswith("tp://"):
            logger.info("检测到 tp:// 协议，自动修正为 http://")
            url = "http://" + url[5:]
        elif url.startswith("tps://"):
            logger.info("检测到 tps:// 协议，自动修正为 https://")
            url = "https://" + url[6:]

        # 自动展开微博短链接
        if self.is_weibo_url(url):
            logger.info(f"🔍 检测到微博URL，开始展开短链接: {url}")
            expanded_url = self._expand_weibo_short_url(url)
            if expanded_url != url:
                logger.info(f"🔄 短链接展开成功: {url} -> {expanded_url}")
                url = expanded_url
                logger.info(f"🔄 使用展开后的微博链接: {url}")
            else:
                logger.info(f"ℹ️ URL无需展开或展开失败，继续使用原URL: {url}")
        # 添加详细的调试日志
        logger.info(f"🔍 download_video 开始处理URL: {url}")
        logger.info(f"🔍 自动下载全集模式: {'开启' if auto_playlist else '关闭'}")
        # 检查URL类型
        is_bilibili = self.is_bilibili_url(url)
        is_list, uid, list_id = self.is_bilibili_list_url(url)
        is_multi_part, bv_id = self.is_bilibili_multi_part_video(url)
        is_youtube_playlist, playlist_id = self.is_youtube_playlist_url(url)
        is_youtube_channel, channel_url = self.is_youtube_channel_playlists_url(url)
        is_x = self.is_x_url(url)
        is_telegraph = self.is_telegraph_url(url)
        is_douyin = self.is_douyin_url(url)
        is_kuaishou = self.is_kuaishou_url(url)
        is_facebook = self.is_facebook_url(url)
        platform = self.get_platform_name(url)
        logger.info(f"🔍 URL识别结果:")
        logger.info(f"  - is_bilibili_url: {is_bilibili}")
        logger.info(
            f"  - is_bilibili_list_url: {is_list}, uid: {uid}, list_id: {list_id}"
        )
        logger.info(
            f"  - is_bilibili_multi_part: {is_multi_part}, bv_id: {bv_id}"
        )
        logger.info(
            f"  - is_youtube_playlist: {is_youtube_playlist}, playlist_id: {playlist_id}"
        )
        logger.info(f"  - is_youtube_channel: {is_youtube_channel}, channel_url: {channel_url if is_youtube_channel else 'None'}")
        logger.info(f"  - is_x_url: {is_x}")
        logger.info(f"  - is_telegraph_url: {is_telegraph}")
        logger.info(f"  - platform: {platform}")
        download_path = self.get_download_path(url)
        logger.info(f"📁 获取到的下载路径: {download_path}")
        
        # 处理 X 链接 - 多集检测优先
        if is_x:
            is_x_playlist, playlist_info = self.is_x_playlist_url(url)
            if is_x_playlist:
                logger.info(f"🎬 检测到X多集视频，共{playlist_info['total_videos']}个视频")
                return await self._download_x_playlist(url, download_path, message_updater, playlist_info)
            logger.info("🔍 检测到X链接，开始检测内容类型...")
            # 检测内容类型
            content_type = self._detect_x_content_type(url)
            logger.info(f"📊 检测到内容类型: {content_type}")
            if content_type == "video":
                # 视频使用统一的单视频下载函数
                logger.info("🎬 X 视频使用统一的单视频下载函数")
                return await self._download_single_video(url, download_path, message_updater)
            else:
                # 图片使用 gallery-dl 下载
                logger.info("📸 X 图片使用 gallery-dl 下载")
                return await self.download_with_gallery_dl(url, download_path, message_updater)
        # 处理 Telegraph 链接（使用 gallery-dl）
        if is_telegraph:
            logger.info(f"📸 检测到Telegraph链接，使用 gallery-dl 下载")
            return await self.download_with_gallery_dl(url, download_path, message_updater)

        # 处理抖音链接 - 使用Playwright方法
        if is_douyin:
            logger.info("🎬 检测到抖音链接，使用Playwright方法下载")
            # 创建一个模拟的message对象用于Playwright方法
            class MockMessage:
                def __init__(self, chat_id=0):
                    self.chat_id = chat_id
                    self.message_id = 0

            mock_message = MockMessage()
            return await self._download_douyin_with_playwright(url, mock_message, message_updater)

        # 处理快手链接 - 使用Playwright方法
        if is_kuaishou:
            logger.info("⚡ 检测到快手链接，使用Playwright方法下载")
            # 创建一个模拟的message对象用于Playwright方法
            class MockMessage:
                def __init__(self, chat_id=0):
                    self.chat_id = chat_id
                    self.message_id = 0

            mock_message = MockMessage()
            return await self._download_kuaishou_with_playwright(url, mock_message, message_updater)

        # 处理Facebook链接 - 使用yt-dlp方法（参考YouTube单集下载）
        if self.is_facebook_url(url):
            logger.info("📘 检测到Facebook链接，使用yt-dlp方法下载")
            return await self._download_single_video(url, download_path, message_updater)

        # 处理小红书链接 - 使用Playwright方法
        if self.is_xiaohongshu_url(url):
            logger.info("📖 检测到小红书链接，使用Playwright方法下载")
            # 创建一个模拟的message对象用于Playwright方法
            class MockMessage:
                def __init__(self, chat_id=0):
                    self.chat_id = chat_id
                    self.message_id = 0

            mock_message = MockMessage()
            return await self._download_xiaohongshu_with_playwright(url, mock_message, message_updater)

        # 处理 YouTube 频道播放列表
        if is_youtube_channel:
            logger.info("✅ 检测到YouTube频道播放列表，开始下载所有播放列表")
            # message_updater参数已正确传递
            return await self._download_youtube_channel_playlists(
                channel_url, download_path, message_updater, status_message, loop
            )
        # 处理 YouTube 播放列表
        if is_youtube_playlist:
            logger.info(f"✅ 检测到YouTube播放列表，播放列表ID: {playlist_id}")
            return await self._download_youtube_playlist_with_progress(
                playlist_id, download_path, message_updater
            )
        # 如果是B站链接，根据设置选择下载器
        if self.is_bilibili_url(url):
            # 优先检查：如果明确检测到是单集视频，直接使用通用下载器
            if not is_multi_part and not is_list:
                logger.info("✅ 检测到B站单集视频，直接使用通用下载器")
                return await self._download_single_video(url, download_path, message_updater)

            # 如果检测到多P或合集，且开启了自动下载全集，使用专门的B站下载器
            elif auto_playlist and (is_multi_part or is_list):
                logger.info("✅ 检测到B站多P视频或合集，且开启多P自动下载全集，使用专门的B站下载器")
                return await self._download_bilibili_video(
                    url, download_path, message_updater, auto_playlist
                )

            # 其他情况（检测到多P但未开启多P自动下载全集）使用通用下载器
            else:
                logger.info("✅ 检测到B站多P视频或合集，但未开启多P自动下载全集，使用通用下载器下载当前集")
                return await self._download_single_video(url, download_path, message_updater)
        # 处理新增的平台（微博、Instagram、TikTok）
        if self.is_weibo_url(url) or self.is_instagram_url(url) or self.is_tiktok_url(url):
            logger.info(f"✅ 检测到{platform}视频，使用通用下载器")
            return await self._download_single_video(url, download_path, message_updater)

        # 处理单个视频（包括YouTube单个视频）
        logger.info(f"✅ 使用通用下载器处理单个视频，平台: {platform}")
        return await self._download_single_video(url, download_path, message_updater)

    async def _download_bilibili_video(
        self, url: str, download_path: str, message_updater=None, auto_playlist=False
    ) -> Dict[str, Any]:
        """下载B站多P视频或合集"""
        import os
        from pathlib import Path
        import time
        import re
        logger.info(f"🎬 开始下载B站多P视频或合集: {url}")

        # 检查是否为B站用户自定义列表URL
        is_list, uid, list_id = self.is_bilibili_list_url(url)
        is_multi_part, bv_id = self.is_bilibili_multi_part_video(url)
        
        # 记录下载开始时间
        download_start_time = time.time()
        logger.info(f"⏰ 下载开始时间: {download_start_time}")
        
        logger.info(f"🔍 检测结果: 列表={is_list}, 多P={is_multi_part}, BV号={bv_id}")
        
        # 简化：不需要跟踪下载文件，使用目录遍历

        # 简化方案：直接删除目录遍历，使用现有的进度回调机制

        # 预先获取播放列表信息，以便知道应该有哪些文件
        # 简化：不需要预先获取播放列表信息，直接下载后用目录遍历

        def progress_callback(d):
            # 简化的进度回调，只处理message_updater，不记录文件
            if message_updater:
                try:
                    import asyncio
                    if asyncio.iscoroutinefunction(message_updater):
                        # 如果是协程函数，需要在事件循环中运行
                        try:
                            loop = asyncio.get_running_loop()
                        except RuntimeError:
                            try:
                                loop = asyncio.get_event_loop()
                            except RuntimeError:
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                        asyncio.run_coroutine_threadsafe(message_updater(d), loop)
                    else:
                        # 同步函数，直接调用
                        message_updater(d)
                except Exception as e:
                    logger.debug(f"📝 message_updater调用失败: {e}")

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                self.smart_download_bilibili,
                url,
                str(download_path),
                progress_callback,
                auto_playlist,
            )

            # 检查是否为单视频，如果是则回退到通用下载器
            if isinstance(result, dict) and result.get("status") == "single_video":
                logger.info("🔄 smart_download_bilibili 检测到单视频，回退到通用下载器")
                return await self._download_single_video(url, download_path, message_updater)

            if not result:
                return {'success': False, 'error': 'B站下载失败'}

            # 检查是否为包含完整文件信息的结果（BV号循环法）
            if isinstance(result, dict) and result.get("status") == "success" and "files" in result:
                logger.info("✅ smart_download_bilibili 返回了完整的文件信息，直接使用")
                return {
                    'success': True,
                    'is_playlist': result.get('is_playlist', True),
                    'file_count': result.get('file_count', 0),
                    'total_size_mb': result.get('total_size_mb', 0),
                    'files': result.get('files', []),
                    'platform': result.get('platform', 'bilibili'),
                    'download_path': result.get('download_path', str(download_path)),
                    'filename': result.get('filename', ''),
                    'size_mb': result.get('size_mb', 0),
                    'resolution': result.get('resolution', '未知'),
                    'episode_count': result.get('episode_count', 0),
                    'video_type': result.get('video_type', 'playlist')
                }

            await asyncio.sleep(1)
            
            # 简化：直接使用目录遍历查找文件
            video_files = []

            # 简化：直接跳到目录遍历，删除所有复杂的文件记录逻辑
            if False:  # 禁用复杂逻辑
                logger.info(f"📋 找到 {len(downloaded_files)} 个实际下载文件记录")
                for filename in downloaded_files:
                    file_path = Path(filename)
                    if file_path.exists():
                        try:
                            mtime = os.path.getmtime(file_path)
                            video_files.append((file_path, mtime))
                            logger.info(f"✅ 找到本次下载文件: {file_path.name}")
                        except OSError:
                            continue
                    else:
                        logger.warning(f"⚠️ 记录的文件不存在: {filename}")
            elif False:  # 禁用复杂逻辑
                # 检查是否为B站合集下载（有files字段）
                if progress_data.get("files"):
                    # B站合集下载：直接使用预期文件名查找
                    logger.info("🔍 B站合集下载：使用预期文件名直接查找")
                    logger.info(f"📋 预期文件数量: {len(progress_data['files'])}")
                    logger.info(f"📁 搜索目录: {download_path}")

                    for file_info in progress_data["files"]:
                        expected_filename = file_info['filename']
                        expected_path = download_path / expected_filename

                        if expected_path.exists():
                            try:
                                mtime = os.path.getmtime(expected_path)
                                video_files.append((expected_path, mtime))
                                logger.info(f"✅ 找到预期文件: {expected_filename}")
                            except OSError:
                                logger.warning(f"⚠️ 无法获取文件时间: {expected_filename}")
                        else:
                            logger.warning(f"⚠️ 预期文件不存在: {expected_filename}")
                else:
                    # 其他类型下载：直接使用progress_data中的预期文件列表
                    expected_files_list = progress_data.get('expected_files', [])
                    logger.info("🔍 使用progress_data中的预期文件列表")

                    logger.info(f"📋 预期文件数量: {len(expected_files_list)}")
                    logger.info(f"📁 搜索目录: {download_path}")

                    def clean_filename_for_matching(filename):
                        """清理文件名用于匹配，删除yt-dlp格式代码，保留版本号等重要信息"""
                        import re
                        if not filename:
                            return ""

                        # 删除yt-dlp的各种格式代码
                        # 1. 删除 .f137+140 格式（在扩展名前）
                        cleaned = re.sub(r'\.[fm]\d+(\+\d+)*', '', filename)

                        # 2. 删除 .f100026 格式（嵌入在文件名中间）
                        cleaned = re.sub(r'\.f\d+', '', cleaned)

                        # 3. 删除 .m4a, .webm 等临时格式，替换为 .mp4
                        cleaned = re.sub(r'\.(webm|m4a|mp3)$', '.mp4', cleaned)

                        # 修复可能的双扩展名问题（如 .m4a.mp4 -> .mp4）
                        cleaned = re.sub(r'\.(webm|m4a|mp3)\.mp4$', '.mp4', cleaned)

                        # 4. 删除序号前缀（如 "23. "），因为预期文件名没有序号
                        cleaned = re.sub(r'^\d+\.\s*', '', cleaned)

                        # 5. 对B站多P标题进行智能处理（和预期文件名保持一致）
                        # 查找 pxx 模式，如果找到就从 pxx 开始截取
                        pattern = r'\s+[pP](\d{1,3})\s+'
                        match = re.search(pattern, cleaned)
                        if match:
                            start_pos = match.start() + 1  # +1 是为了跳过前面的空格
                            cleaned = cleaned[start_pos:]

                        # 6. 统一特殊字符（解决全角/半角差异）
                        # 将半角竖线转换为全角竖线，与_basic_sanitize_filename保持一致
                        cleaned = cleaned.replace('|', '｜')
                        # 将普通斜杠转换为大斜杠符号，与_basic_sanitize_filename保持一致
                        cleaned = cleaned.replace('/', '⧸')
                        # 保留全角字符，不进行额外转换
                        # cleaned = re.sub(r'[【】]', '_', cleaned)  # 注释掉，保留原始字符

                        # 确保以 .mp4 结尾
                        if not cleaned.endswith('.mp4'):
                            cleaned = cleaned.rstrip('.') + '.mp4'

                        return cleaned

                    for expected_file in expected_files_list:
                        # 尝试多种可能的文件名格式
                        base_title = expected_file.get('title', '')
                        base_filename = expected_file.get('filename', '')

                        possible_names = [
                            base_filename,  # 原始文件名
                            base_title,     # 原始标题
                            f"{base_title}.mp4",  # 标题+.mp4
                            clean_filename_for_matching(base_filename),  # 清理后的文件名
                            clean_filename_for_matching(base_title),     # 清理后的标题
                        ]

                        # 去重并过滤空值
                        possible_names = list(dict.fromkeys([name for name in possible_names if name]))

                        found = False
                        for possible_name in possible_names:
                            # 1. 先在下载目录直接查找
                            expected_path = download_path / possible_name
                            if expected_path.exists():
                                try:
                                    mtime = os.path.getmtime(expected_path)
                                    video_files.append((expected_path, mtime))
                                    logger.info(f"✅ 找到预期文件: {possible_name}")
                                    found = True
                                    break
                                except OSError:
                                    continue

                            # 2. 在子目录中查找（递归搜索）
                            for video_ext in ["*.mp4", "*.mkv", "*.webm", "*.avi", "*.mov", "*.flv"]:
                                matching_files = list(Path(download_path).rglob(video_ext))
                                for file_path in matching_files:
                                    # 检查文件名是否匹配（考虑序号前缀）
                                    actual_filename = file_path.name
                                    cleaned_actual = clean_filename_for_matching(actual_filename)
                                    cleaned_expected = clean_filename_for_matching(possible_name)

                                    if cleaned_actual == cleaned_expected:
                                        try:
                                            mtime = os.path.getmtime(file_path)
                                            video_files.append((file_path, mtime))
                                            logger.info(f"✅ 在子目录找到文件: {file_path.relative_to(download_path)}")
                                            found = True
                                            break
                                        except OSError:
                                            continue
                                if found:
                                    break
                            if found:
                                break

                        if not found:
                            logger.warning(f"⚠️ 未找到预期文件: {expected_file.get('title', 'unknown')}")
                            logger.info(f"   尝试的文件名: {possible_names}")
            else:
                # B站多P下载：智能查找子目录中的文件
                logger.info("🎯 B站多P下载：没有预期文件列表，智能查找子目录中的文件")
                logger.info(f"🔍 搜索路径: {download_path}")

                # 检查下载路径是否存在
                if not Path(download_path).exists():
                    logger.error(f"❌ 下载路径不存在: {download_path}")
                    return {"success": False, "error": "下载路径不存在"}

                # 智能查找：优先查找最新创建的子目录
                try:
                    all_items = list(Path(download_path).iterdir())
                    subdirs = [item for item in all_items if item.is_dir()]

                    if subdirs:
                        # 按修改时间排序，找到最新的子目录
                        latest_subdir = max(subdirs, key=lambda x: x.stat().st_mtime)
                        logger.info(f"📁 找到最新子目录: {latest_subdir.name}")

                        # 在子目录中查找视频文件
                        video_extensions = ["*.mp4", "*.mkv", "*.webm", "*.avi", "*.mov", "*.flv"]
                        for ext in video_extensions:
                            matching_files = list(latest_subdir.glob(ext))
                            if matching_files:
                                logger.info(f"✅ 在子目录中找到 {len(matching_files)} 个 {ext} 文件")
                                for file_path in matching_files:
                                    try:
                                        mtime = os.path.getmtime(file_path)
                                        video_files.append((file_path, mtime))
                                        logger.info(f"✅ 找到文件: {file_path.name}")
                                    except OSError:
                                        continue
                    else:
                        logger.warning("⚠️ 未找到子目录，在根目录查找")
                        # 如果没有子目录，在根目录查找
                        video_extensions = ["*.mp4", "*.mkv", "*.webm", "*.avi", "*.mov", "*.flv"]
                        for ext in video_extensions:
                            matching_files = list(Path(download_path).glob(ext))
                            for file_path in matching_files:
                                try:
                                    mtime = os.path.getmtime(file_path)
                                    video_files.append((file_path, mtime))
                                    logger.info(f"✅ 找到文件: {file_path.name}")
                                except OSError:
                                    continue

                except Exception as e:
                    logger.error(f"❌ 智能查找失败: {e}")
                    return {"success": False, "error": f"文件查找失败: {e}"}
            
            # 如果没有找到文件，记录详细信息用于调试
            if not video_files:
                logger.warning("⚠️ 未找到任何匹配文件")
                logger.info(f"🔍 搜索路径: {download_path}")
                return {"success": False, "error": "目录遍历未找到视频文件"}

            video_files.sort(key=lambda x: x[0].name)

            # 检测PART文件
            part_files = self._detect_part_files(download_path)
            success_count = len(video_files)
            part_count = len(part_files)

            # 在日志中显示详细统计
            logger.info(f"📊 下载完成统计：")
            logger.info(f"✅ 成功文件：{success_count} 个")
            if part_count > 0:
                logger.warning(f"⚠️ 未完成文件：{part_count} 个")
                self._log_part_files_details(part_files)
            else:
                logger.info("✅ 未发现PART文件，所有下载都已完成")

            if is_list:
                logger.info(f"🎉 B站合集下载完成，统计本次下载文件")
                if video_files:
                    total_size_mb = 0
                    file_info_list = []
                    all_resolutions = set()
                    for file_path, mtime in video_files:
                        size_mb = os.path.getsize(file_path) / (1024 * 1024)
                        total_size_mb += size_mb
                        media_info = self.get_media_info(str(file_path))
                        resolution = media_info.get('resolution', '未知')
                        if resolution != '未知':
                            all_resolutions.add(resolution)
                        file_info_list.append({
                            'filename': os.path.basename(file_path),
                            'size_mb': size_mb,
                            'resolution': resolution,
                            'abr': media_info.get('bit_rate')
                        })
                    filename_list = [info['filename'] for info in file_info_list]
                    filename_display = '\n'.join([f"  {i+1:02d}. {name}" for i, name in enumerate(filename_list)])
                    resolution_display = ', '.join(sorted(all_resolutions)) if all_resolutions else '未知'
                    return {
                        'success': True,
                        'is_playlist': True,
                        'file_count': len(video_files),
                        'total_size_mb': total_size_mb,
                        'files': file_info_list,
                        'platform': 'bilibili',
                        'download_path': str(download_path),
                        'filename': filename_display,
                        'size_mb': total_size_mb,
                        'resolution': resolution_display,
                        'episode_count': len(video_files),
                        # 添加PART文件统计信息
                        'success_count': success_count,
                        'part_count': part_count,
                        'part_files': [str(pf) for pf in part_files] if part_files else []
                    }
                else:
                    return {'success': False, 'error': 'B站合集下载完成但未找到本次下载的文件'}
            else:
                # 多P视频下载，统计本次下载文件
                if video_files:
                    # 如果有多个文件，应该使用播放列表格式显示
                    if len(video_files) > 1:
                        total_size_mb = 0
                        file_info_list = []
                        all_resolutions = set()
                        for file_path, mtime in video_files:
                            size_mb = os.path.getsize(file_path) / (1024 * 1024)
                            total_size_mb += size_mb
                            media_info = self.get_media_info(str(file_path))
                            resolution = media_info.get('resolution', '未知')
                            if resolution != '未知':
                                all_resolutions.add(resolution)
                            file_info_list.append({
                                'filename': os.path.basename(file_path),
                                'size_mb': size_mb,
                                'resolution': resolution,
                                'abr': media_info.get('bit_rate')
                            })
                        filename_list = [info['filename'] for info in file_info_list]
                        filename_display = '\n'.join([f"  {i+1:02d}. {name}" for i, name in enumerate(filename_list)])
                        resolution_display = ', '.join(sorted(all_resolutions)) if all_resolutions else '未知'
                        return {
                            'success': True,
                            'is_playlist': True,
                            'video_type': 'playlist',
                            'file_count': len(video_files),
                            'total_size_mb': total_size_mb,
                            'files': file_info_list,
                            'platform': 'bilibili',
                            'download_path': str(download_path),
                            'filename': filename_display,
                            'size_mb': total_size_mb,
                            'resolution': resolution_display,
                            'episode_count': len(video_files)
                        }
                    else:
                        # 只有一个文件，使用单个视频格式
                        video_files.sort(key=lambda x: x[1], reverse=True)
                        final_file_path = str(video_files[0][0])
                        media_info = self.get_media_info(final_file_path)
                        size_mb = os.path.getsize(final_file_path) / (1024 * 1024)
                        return {
                            'success': True,
                            'filename': os.path.basename(final_file_path),
                            'full_path': final_file_path,
                            'size_mb': size_mb,
                            'platform': 'bilibili',
                            'download_path': str(download_path),
                            'resolution': media_info.get('resolution', '未知'),
                            'abr': media_info.get('bit_rate')
                        }
                else:
                    return {'success': False, 'error': 'B站多P下载完成但未找到本次下载的文件'}

        except Exception as e:
            logger.error(f"B站下载失败: {e}")
            return {"success": False, "error": str(e)}

    async def _download_single_video(
        self, url: str, download_path: Path, message_updater=None
    ) -> Dict[str, Any]:
        """下载单个视频（包括YouTube单个视频）"""
        import os
        logger.info(f"🎬 开始下载单个视频: {url}")
        # 1. 预先获取信息以确定文件名
        try:
            logger.info("🔍 步骤1: 预先获取视频信息...")
            info_opts = {
                "quiet": True,
                "no_warnings": True,
                "socket_timeout": 30,  # 30秒超时
                "retries": 3,  # 减少重试次数
            }
            if self.proxy_host:
                info_opts["proxy"] = self.proxy_host
                logger.info(f"🌐 使用代理: {self.proxy_host}")
            if (
                self.is_x_url(url)
                and self.x_cookies_path
                and os.path.exists(self.x_cookies_path)
            ):
                info_opts["cookiefile"] = self.x_cookies_path
                logger.info(f"🍪 使用X cookies: {self.x_cookies_path}")
            if (
                self.is_youtube_url(url)
                and self.youtube_cookies_path
                and os.path.exists(self.youtube_cookies_path)
            ):
                info_opts["cookiefile"] = self.youtube_cookies_path
                logger.info(f"🍪 使用YouTube cookies: {self.youtube_cookies_path}")
            if (
                self.is_douyin_url(url)
                and self.douyin_cookies_path
                and os.path.exists(self.douyin_cookies_path)
            ):
                info_opts["cookiefile"] = self.douyin_cookies_path
                logger.info(f"🍪 使用抖音 cookies: {self.douyin_cookies_path}")
            logger.info("🔍 步骤2: 开始提取视频信息...")
            # 使用异步执行器来添加超时控制
            loop = asyncio.get_running_loop()

            def extract_video_info():
                with yt_dlp.YoutubeDL(info_opts) as ydl:
                    logger.info("📡 正在从平台获取视频数据...")
                    return ydl.extract_info(url, download=False)

            # 设置30秒超时
            try:
                info = await asyncio.wait_for(
                    loop.run_in_executor(None, extract_video_info), timeout=60.0
                )
                logger.info(f"✅ 视频信息获取完成，数据类型: {type(info)}")

                video_id = info.get("id")
                title = info.get("title")
                # 清理标题中的非法字符
                if title:
                    title = self._sanitize_filename(title)
                else:
                    title = self._sanitize_filename(video_id)
                logger.info(f"📝 视频标题: {title}")
                logger.info(f"🆔 视频ID: {video_id}")
            except asyncio.TimeoutError:
                logger.error("❌ 获取视频信息超时（30秒）")
                return {
                    "success": False,
                    "error": "获取视频信息超时，请检查网络连接或稍后重试。",
                }
        except Exception as e:
            logger.error(f"❌ 无法预先获取视频信息: {e}")
            # 如果预先获取信息失败，提供一个回退方案
            title = self._sanitize_filename(str(int(time.time())))
            logger.info(f"📝 使用时间戳作为标题: {title}")
        # 2. 根据平台和获取到的信息构造精确的输出模板
        if self.is_youtube_url(url):
            outtmpl = str(download_path.absolute() / f"{title}.%(ext)s")
        elif self.is_x_url(url):
            outtmpl = str(download_path.absolute() / f"{title}.%(ext)s")
        else:  # 其他平台
            outtmpl = str(download_path.absolute() / f"{title}.%(ext)s")
        # 添加明显的outtmpl日志
        logger.info(f"🔧 [SINGLE_VIDEO] outtmpl 绝对路径: {outtmpl}")
        logger.info(f"📁 下载路径: {download_path}")
        logger.info(f"📝 输出模板: {outtmpl}")
        logger.info("🔍 步骤3: 配置下载选项...")
        ydl_opts = {
            "outtmpl": outtmpl,
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
            "noplaylist": True,
            "nocheckcertificate": True,
            "ignoreerrors": True,
            "logtostderr": True,  # 改为True，确保进度回调正常工作
            "quiet": False,  # 改为False，确保进度回调正常工作
            "no_warnings": False,  # 改为False，确保能看到警告信息
            "default_search": "auto",
            "source_address": "0.0.0.0",
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
            "retries": 5,  # 减少重试次数
            "fragment_retries": 5,
            "skip_unavailable_fragments": True,
            "keepvideo": False,
            "prefer_ffmpeg": True,
            "socket_timeout": 30,  # 30秒超时
            "progress": True,  # 添加这个参数，确保进度回调被启用
            # HLS下载特殊配置
            "hls_use_mpegts": False,  # 使用mp4容器而不是ts
            "hls_prefer_native": True,  # 优先使用原生HLS下载器
            "concurrent_fragment_downloads": 3,  # 并发下载分片数量
            "buffersize": 1024,  # 缓冲区大小
            "http_chunk_size": 10485760,  # 10MB分块大小
        }
        # 针对性地添加 Cookies
        if (
            self.is_x_url(url)
            and self.x_cookies_path
            and os.path.exists(self.x_cookies_path)
        ):
            ydl_opts["cookiefile"] = self.x_cookies_path
            logger.info(f"🍪 为X链接添加cookies: {self.x_cookies_path}")
        if (
            self.is_youtube_url(url)
            and self.youtube_cookies_path
            and os.path.exists(self.youtube_cookies_path)
        ):
            ydl_opts["cookiefile"] = self.youtube_cookies_path
            logger.info(f"🍪 为YouTube链接添加cookies: {self.youtube_cookies_path}")
        if (
            self.is_douyin_url(url)
            and self.douyin_cookies_path
            and os.path.exists(self.douyin_cookies_path)
        ):
            ydl_opts["cookiefile"] = self.douyin_cookies_path
            logger.info(f"🍪 为抖音链接添加cookies: {self.douyin_cookies_path}")
        elif self.is_douyin_url(url):
            logger.warning("⚠️ 检测到抖音链接但未设置cookies文件")
            if self.douyin_cookies_path:
                logger.warning(f"⚠️ 抖音cookies文件不存在: {self.douyin_cookies_path}")
            else:
                logger.warning("⚠️ 未设置DOUYIN_COOKIES环境变量")
        # 添加代理
        if self.proxy_host:
            ydl_opts["proxy"] = self.proxy_host
        # 3. 设置进度回调
        logger.info("🔍 步骤3: 设置进度回调...")
        progress_data = {"final_filename": None, "lock": threading.Lock()}

        # 使用增强版的 single_video_progress_hook，包含完整的进度显示逻辑
        # 检查 message_updater 是否是增强版进度回调函数
        if callable(message_updater) and message_updater.__name__ == 'enhanced_progress_callback':
            # 如果是增强版进度回调，直接使用它返回的 progress_hook
            progress_hook = message_updater(progress_data)
        else:
            # 否则使用标准的 single_video_progress_hook
            progress_hook = single_video_progress_hook(message_updater, progress_data)
        
        ydl_opts['progress_hooks'] = [progress_hook]
        # 4. 运行下载
        logger.info("🔍 步骤4: 开始下载视频（设置60秒超时）...")

        def run_download():
            try:
                logger.info(f"🔧 [SINGLE_VIDEO_DOWNLOAD] 最终ydl_opts: {ydl_opts}")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    logger.info("🚀 开始下载视频...")
                    ydl.download([url])
                return True
            except Exception as e:
                error_message = str(e)
                logger.error(f"❌ 下载失败: {error_message}")
                progress_data["error"] = error_message
                return False

        # 设置60秒超时用于下载
        try:
            success = await asyncio.wait_for(
                loop.run_in_executor(None, run_download), timeout=600.0  # 增加到10分钟
            )
        except asyncio.TimeoutError:
            logger.error("❌ 视频下载超时（10分钟）")
            return {
                "success": False,
                "error": "视频下载超时，请检查网络连接或稍后重试。",
            }
        if not success:
            error = progress_data.get("error", "下载器在执行时发生未知错误")
            return {"success": False, "error": error}
        # 5. 查找文件并返回结果
        logger.info("🔍 步骤5: 查找下载的文件...")
        time.sleep(1)  # 等待文件系统同步

        # 使用单视频文件查找方法
        final_file_path = self.single_video_find_downloaded_file(download_path, progress_data, title, url)

        # 处理最终文件
        if final_file_path and os.path.exists(final_file_path):
            logger.info("🔍 步骤6: 获取媒体信息...")
            media_info = self.get_media_info(final_file_path)

            # 安全地获取文件大小
            try:
                file_size_bytes = os.path.getsize(final_file_path)
                size_mb = file_size_bytes / (1024 * 1024)
            except (OSError, TypeError):
                size_mb = 0.0

            logger.info("🎉 视频下载任务完成!")
            return {
                "success": True,
                "filename": os.path.basename(final_file_path),
                "full_path": final_file_path,
                "size_mb": size_mb,
                "platform": self.get_platform_name(url),
                "download_path": str(download_path),
                "resolution": media_info.get("resolution", "未知"),
                "abr": media_info.get("bit_rate"),
                "title": title,
            }
        else:
            return {
                "success": False,
                "error": "下载完成但无法在文件系统中找到最终文件。",
            }



    async def _download_youtube_channel_playlists(
        self, channel_url: str, download_path: Path, message_updater=None, status_message=None, loop=None
    ) -> Dict[str, Any]:
        """下载YouTube频道的所有播放列表"""
        logger.info(f"🎬 开始下载YouTube频道播放列表: {channel_url}")
        logger.info(f"📁 下载路径: {download_path}")
        # 移除调试日志

        # 确保事件循环正确设置
        try:
            import asyncio
            self._main_loop = asyncio.get_running_loop()
            logger.info(f"✅ 成功设置事件循环: {self._main_loop}")
        except Exception as e:
            logger.warning(f"⚠️ 无法获取事件循环: {e}")
            self._main_loop = None



        # YouTube频道播放列进度管理器 - 专门用于跟踪YouTube频道播放列表下载的总体进度
        global_progress = {
            "total_playlists": 0,
            "completed_playlists": 0,
            "total_videos": 0,
            "completed_videos": 0,
            "total_size_mb": 0,
            "downloaded_size_mb": 0,
            "channel_name": "",
            "start_time": time.time()
        }

        try:
            # 更新状态消息
            if message_updater:
                try:
                    if asyncio.iscoroutinefunction(message_updater):
                        await message_updater("🔍 正在获取频道信息...")
                    else:
                        message_updater("🔍 正在获取频道信息...")
                except Exception as e:
                    logger.warning(f"更新状态消息失败: {e}")
            logger.info("🔍 步骤1: 准备获取频道信息...")
            # 获取频道信息 - 添加超时控制
            info_opts = {
                "quiet": True,
                "extract_flat": True,
                "ignoreerrors": True,
                "socket_timeout": 30,  # 30秒超时
                "retries": 3,  # 减少重试次数
                "fragment_retries": 3,
            }
            if self.proxy_host:
                info_opts["proxy"] = self.proxy_host
                logger.info(f"🌐 使用代理: {self.proxy_host}")
            if self.youtube_cookies_path and os.path.exists(self.youtube_cookies_path):
                info_opts["cookiefile"] = self.youtube_cookies_path
                logger.info(f"🍪 使用YouTube cookies: {self.youtube_cookies_path}")
            logger.info("🔍 步骤2: 开始提取频道信息（设置30秒超时）...")
            # 使用异步执行器来添加超时控制
            loop = asyncio.get_running_loop()

            def extract_channel_info():
                logger.info("📡 正在从YouTube获取频道数据...")
                with yt_dlp.YoutubeDL(info_opts) as ydl:
                    logger.info("🔗 开始网络请求...")
                    result = ydl.extract_info(channel_url, download=False)
                    logger.info(f"📊 网络请求完成，结果类型: {type(result)}")
                    return result

            # 设置30秒超时
            try:
                if message_updater:
                    try:
                        if asyncio.iscoroutinefunction(message_updater):
                            await message_updater("⏳ 正在连接YouTube服务器...")
                        else:
                            message_updater("⏳ 正在连接YouTube服务器...")
                    except Exception as e:
                        logger.warning(f"更新状态消息失败: {e}")
                info = await asyncio.wait_for(
                    loop.run_in_executor(None, extract_channel_info), timeout=60.0
                )
                logger.info(f"✅ 频道信息获取完成，数据类型: {type(info)}")
                if message_updater:
                    try:
                        if asyncio.iscoroutinefunction(message_updater):
                            await message_updater("✅ 频道信息获取成功，正在分析...")
                        else:
                            message_updater("✅ 频道信息获取成功，正在分析...")
                    except Exception as e:
                        logger.warning(f"更新状态消息失败: {e}")
            except asyncio.TimeoutError:
                logger.error("❌ 获取频道信息超时（30秒）")
                if message_updater:
                    try:
                        if asyncio.iscoroutinefunction(message_updater):
                            await message_updater(
                                "❌ 获取频道信息超时，请检查网络连接或稍后重试。"
                            )
                        else:
                            message_updater(
                                "❌ 获取频道信息超时，请检查网络连接或稍后重试。"
                            )
                    except Exception as e:
                        logger.warning(f"更新状态消息失败: {e}")
                return {
                    "success": False,
                    "error": "获取频道信息超时，请检查网络连接或稍后重试。",
                }
            logger.info("🔍 步骤3: 检查频道信息结构...")
            if not info:
                logger.error("❌ 频道信息为空")
                if message_updater:
                    try:
                        if asyncio.iscoroutinefunction(message_updater):
                            await message_updater("❌ 无法获取频道信息。")
                        else:
                            message_updater("❌ 无法获取频道信息。")
                    except Exception as e:
                        logger.warning(f"更新状态消息失败: {e}")
                return {"success": False, "error": "无法获取频道信息。"}
            if "entries" not in info:
                logger.warning("❌ 频道信息中没有找到 'entries' 字段")
                logger.info(
                    f"📊 频道信息包含的字段: {list(info.keys()) if isinstance(info, dict) else '非字典类型'}"
                )
                if message_updater:
                    try:
                        if asyncio.iscoroutinefunction(message_updater):
                            await message_updater("❌ 此频道主页未找到任何播放列表。")
                        else:
                            message_updater("❌ 此频道主页未找到任何播放列表。")
                    except Exception as e:
                        logger.warning(f"更新状态消息失败: {e}")
                return {"success": False, "error": "此频道主页未找到任何播放列表。"}
            entries = info.get("entries", [])
            logger.info(f"📊 找到 {len(entries)} 个条目")
            if not entries:
                logger.warning("❌ 频道条目列表为空")
                if message_updater:
                    try:
                        if asyncio.iscoroutinefunction(message_updater):
                            await message_updater("❌ 此频道主页未找到任何播放列表。")
                        else:
                            message_updater("❌ 此频道主页未找到任何播放列表。")
                    except Exception as e:
                        logger.warning(f"更新状态消息失败: {e}")
                return {"success": False, "error": "此频道主页未找到任何播放列表。"}
            logger.info("🔍 步骤4: 分析频道条目...")
            if message_updater:
                try:
                    if asyncio.iscoroutinefunction(message_updater):
                        await message_updater(f"🔍 正在分析 {len(entries)} 个频道条目...")
                    else:
                        message_updater(f"🔍 正在分析 {len(entries)} 个频道条目...")
                except Exception as e:
                    logger.warning(f"更新状态消息失败: {e}")
            playlist_entries = []
            for i, entry in enumerate(entries):
                if entry:
                    entry_type = entry.get("_type", "unknown")
                    entry_id = entry.get("id", "no_id")
                    entry_title = entry.get("title", "no_title")
                    logger.info(
                        f"  📋 条目 {i + 1}: 类型={entry_type}, ID={entry_id}, 标题={entry_title}"
                    )
                    # 兼容 _type == 'playlist' 或 _type == 'url' 且 url 指向 playlist
                    if entry_type == "playlist":
                        playlist_entries.append(entry)
                        logger.info(f"    ✅ 识别为播放列表")
                    elif entry_type == "url" and "playlist?list=" in (
                        entry.get("url") or ""
                    ):
                        playlist_entries.append(entry)
                        logger.info(f"    ✅ 识别为播放列表URL")
                else:
                    logger.warning(f"  ⚠️ 条目 {i + 1} 为空")
            logger.info(f"📊 总共找到 {len(playlist_entries)} 个播放列表")

            if not playlist_entries:
                logger.warning("❌ 没有找到任何播放列表")
                if message_updater:
                    try:
                        if asyncio.iscoroutinefunction(message_updater):
                            await message_updater("❌ 频道中没有找到任何播放列表。")
                        else:
                            message_updater("❌ 频道中没有找到任何播放列表。")
                    except Exception as e:
                        logger.warning(f"更新状态消息失败: {e}")
                return {"success": False, "error": "频道中没有找到任何播放列表。"}

            logger.info("🔍 步骤5: 创建频道目录...")
            channel_name = re.sub(
                r'[\\/:*?"<>|]', "_", info.get("uploader", "Unknown Channel")
            ).strip()
            channel_path = download_path / channel_name
            channel_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"📁 频道目录: {channel_path}")

            logger.info("🔍 步骤6: 开始下载播放列表...")
            if message_updater:
                try:
                    if asyncio.iscoroutinefunction(message_updater):
                        await message_updater(
                            f"🎬 开始下载 {len(playlist_entries)} 个播放列表..."
                        )
                    else:
                        message_updater(
                            f"🎬 开始下载 {len(playlist_entries)} 个播放列表..."
                        )
                except Exception as e:
                    logger.warning(f"更新状态消息失败: {e}")

            # 初始化全局进度数据
            global_progress["total_playlists"] = len(playlist_entries)
            global_progress["channel_name"] = channel_name
            
            # 计算总视频数（如果可能的话）
            total_video_count = 0
            for entry in playlist_entries:
                if entry and "video_count" in entry:
                    total_video_count += entry.get("video_count", 0)
            
            # 如果无法从API获取视频数量，设置为-1表示需要动态计算
            if total_video_count == 0:
                logger.info("📊 无法从API获取视频数量，将在下载过程中动态计算")
                global_progress["total_videos"] = -1  # 使用-1表示需要动态计算
            else:
                global_progress["total_videos"] = total_video_count
            
            logger.info(f"📊 全局进度初始化: {global_progress['total_playlists']} 个播放列表, {global_progress['total_videos']} 个视频")

            downloaded_playlists = []
            playlist_stats = []  # 存储每个播放列表的统计信息

            for i, entry in enumerate(playlist_entries, 1):
                playlist_id = entry.get("id")
                playlist_title = entry.get("title", f"Playlist_{playlist_id}")
                logger.info(
                    f"🎬 开始下载第 {i}/{len(playlist_entries)} 个播放列表: {playlist_title}"
                )
                logger.info(f"    📋 播放列表ID: {playlist_id}")

                # 先检查播放列表是否已完整下载
                check_result = self._check_playlist_already_downloaded(playlist_id, channel_path)

                if message_updater:
                    try:
                        if asyncio.iscoroutinefunction(message_updater):
                            if check_result.get("already_downloaded", False):
                                await message_updater(
                                    f"✅ 检查第 {i}/{len(playlist_entries)} 个播放列表：{playlist_title} (已完整下载)"
                                )
                            else:
                                await message_updater(
                                    f"📥 正在下载第 {i}/{len(playlist_entries)} 个播放列表：{playlist_title}"
                                )
                        else:
                            if check_result.get("already_downloaded", False):
                                message_updater(
                                    f"✅ 检查第 {i}/{len(playlist_entries)} 个播放列表：{playlist_title} (已完整下载)"
                                )
                            else:
                                message_updater(
                                    f"📥 正在下载第 {i}/{len(playlist_entries)} 个播放列表：{playlist_title}"
                                )
                    except Exception as e:
                        logger.warning(f"更新状态消息失败: {e}")

                # 创建播放列表专用的进度回调
                playlist_progress_data = {
                    "playlist_index": i,
                    "total_playlists": len(playlist_entries),
                    "playlist_title": playlist_title,
                    "current_video": 0,
                    "total_videos": 0,
                    "downloaded_videos": 0,
                }

                def create_playlist_progress_callback(progress_data):
                    last_update = {"percent": -1, "time": 0, "text": ""}
                    import time as _time

                    def escape_num(text):
                        # 转义MarkdownV2特殊字符，包括小数点
                        if not isinstance(text, str):
                            text = str(text)
                        escape_chars = [
                            "_",
                            "*",
                            "[",
                            "]",
                            "(",
                            ")",
                            "~",
                            "`",
                            ">",
                            "#",
                            "+",
                            "-",
                            "=",
                            "|",
                            "{",
                            "}",
                            ".",
                            "!",
                        ]
                        for char in escape_chars:
                            text = text.replace(char, "\\" + char)
                        return text

                    def progress_callback(d):
                        if d.get("status") == "downloading":
                            # 修正当前视频序号为本播放列表的当前下载视频序号/总数
                            cur_idx = (
                                d.get("playlist_index")
                                or d.get("info_dict", {}).get("playlist_index")
                                or 1
                            )
                            total_idx = (
                                d.get("playlist_count")
                                or d.get("info_dict", {}).get("n_entries")
                                or progress_data.get("total_videos")
                                or 1
                            )
                            progress_text = (
                                f"📥 正在下载第{escape_num(progress_data['playlist_index'])}/{escape_num(progress_data['total_playlists'])}个播放列表：{escape_num(progress_data['playlist_title'])}\n\n"
                                f"📺 当前视频: {escape_num(cur_idx)}/{escape_num(total_idx)}\n"
                            )
                            percent = 0
                            if d.get("filename"):
                                filename = os.path.basename(d.get("filename", ""))
                                total_bytes = d.get("total_bytes") or d.get(
                                    "total_bytes_estimate", 0
                                )
                                downloaded_bytes = d.get("downloaded_bytes", 0)
                                speed_bytes_s = d.get("speed", 0)
                                eta_seconds = d.get("eta", 0)
                                if total_bytes and total_bytes > 0:
                                    downloaded_mb = downloaded_bytes / (1024 * 1024)
                                    total_mb = total_bytes / (1024 * 1024)
                                    speed_mb_s = (
                                        speed_bytes_s / (1024 * 1024)
                                        if speed_bytes_s
                                        else 0
                                    )
                                    percent = int(downloaded_bytes * 100 / total_bytes)
                                    bar = self._make_progress_bar(percent)
                                    try:
                                        minutes, seconds = divmod(int(eta_seconds), 60)
                                        eta_str = f"{minutes:02d}:{seconds:02d}"
                                    except (ValueError, TypeError):
                                        eta_str = "未知"
                                    downloaded_mb_str = f"{downloaded_mb:.2f}"
                                    total_mb_str = f"{total_mb:.2f}"
                                    speed_mb_s_str = f"{speed_mb_s:.2f}"
                                    percent_str = f"{percent:.1f}"
                                    progress_text += (
                                        f"📝 文件: `{escape_num(filename)}`\n"
                                        f"💾 大小: `{escape_num(downloaded_mb_str)}MB / {escape_num(total_mb_str)}MB`\n"
                                        f"⚡ 速度: `{escape_num(speed_mb_s_str)}MB/s`\n"
                                        f"⏳ 预计剩余: `{escape_num(eta_str)}`\n"
                                        f"📊 进度: {bar} `{escape_num(percent_str)}%`"
                                    )
                                else:
                                    downloaded_mb = (
                                        downloaded_bytes / (1024 * 1024)
                                        if downloaded_bytes > 0
                                        else 0
                                    )
                                    speed_mb_s = (
                                        speed_bytes_s / (1024 * 1024)
                                        if speed_bytes_s
                                        else 0
                                    )
                                    downloaded_mb_str = f"{downloaded_mb:.2f}"
                                    speed_mb_s_str = f"{speed_mb_s:.2f}"
                                    progress_text += (
                                        f"📝 文件: `{escape_num(filename)}`\n"
                                        f"💾 大小: `{escape_num(downloaded_mb_str)}MB`\n"
                                        f"⚡ 速度: `{escape_num(speed_mb_s_str)}MB/s`\n"
                                        f"📊 进度: 下载中..."
                                    )
                            now = _time.time()
                            # 更频繁的进度更新：每5%进度变化或每1秒更新一次
                            if (
                                abs(percent - last_update["percent"]) >= 5
                            ) or (now - last_update["time"] > 1):
                                if progress_text != last_update["text"]:
                                    last_update["percent"] = percent
                                    last_update["time"] = now
                                    last_update["text"] = progress_text
                                    import asyncio

                                    # 移除调试日志，直接处理进度更新

                                    # 🎯 智能 TG 消息更新：从 message_updater 中提取 TG 对象
                                    tg_updated = False

                                    # 方法1：如果直接传递了 TG 对象，优先使用
                                    if status_message and loop:
                                        try:
                                            def fix_markdown_v2(text):
                                                # 简化版本：移除了粗体标记，直接转义所有特殊字符
                                                text = text.replace('\\', '')
                                                special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
                                                for char in special_chars:
                                                    text = text.replace(char, f'\\{char}')
                                                return text

                                            fixed_text = fix_markdown_v2(progress_text)
                                            future = asyncio.run_coroutine_threadsafe(
                                                status_message.edit_text(fixed_text, parse_mode="MarkdownV2"),
                                                loop
                                            )
                                            future.result(timeout=3.0)
                                            tg_updated = True
                                        except:
                                            try:
                                                clean_text = progress_text.replace('\\', '')
                                                future = asyncio.run_coroutine_threadsafe(
                                                    status_message.edit_text(clean_text),
                                                    loop
                                                )
                                                future.result(timeout=3.0)
                                                tg_updated = True
                                            except:
                                                tg_updated = False
                                    else:
                                        tg_updated = False

                                    # 方法3：修复 message_updater 调用
                                    if not tg_updated and message_updater:
                                        try:
                                            # 🔧 修复：创建一个包装函数，让 message_updater 能处理字符串
                                            def fixed_message_updater(text):
                                                """修复的消息更新器，能处理字符串类型的进度"""
                                                # 从 message_updater 的闭包中提取必要的对象
                                                if hasattr(message_updater, '__closure__') and message_updater.__closure__:
                                                    for cell in message_updater.__closure__:
                                                        try:
                                                            value = cell.cell_contents
                                                            # 找到 TG 消息对象
                                                            if hasattr(value, 'edit_text') and hasattr(value, 'chat_id'):
                                                                status_msg = value
                                                                # 找到事件循环
                                                                for cell2 in message_updater.__closure__:
                                                                    try:
                                                                        value2 = cell2.cell_contents
                                                                        if hasattr(value2, 'run_until_complete'):
                                                                            event_loop = value2
                                                                            # 直接更新 TG 消息
                                                                            def fix_markdown_v2(text):
                                                                                text = text.replace('\\', '')
                                                                                special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
                                                                                for char in special_chars:
                                                                                    text = text.replace(char, f'\\{char}')
                                                                                return text

                                                                            try:
                                                                                fixed_text = fix_markdown_v2(text)
                                                                                future = asyncio.run_coroutine_threadsafe(
                                                                                    status_msg.edit_text(fixed_text, parse_mode="MarkdownV2"),
                                                                                    event_loop
                                                                                )
                                                                                future.result(timeout=3.0)
                                                                                return True
                                                                            except:
                                                                                # 降级到普通文本
                                                                                clean_text = text.replace('\\', '')
                                                                                future = asyncio.run_coroutine_threadsafe(
                                                                                    status_msg.edit_text(clean_text),
                                                                                    event_loop
                                                                                )
                                                                                future.result(timeout=3.0)
                                                                                return True
                                                                    except:
                                                                        continue
                                                        except:
                                                            continue

                                                # 如果提取失败，调用原函数（但这会失败）
                                                logger.warning(f"⚠️ 无法从 message_updater 提取 TG 对象，尝试原调用")
                                                return False

                                            # 使用修复的函数
                                            if not fixed_message_updater(progress_text):
                                                logger.warning(f"⚠️ 修复的 message_updater 失败")

                                        except Exception as e:
                                            logger.error(f"❌ 调用修复的 message_updater 失败: {e}")

                                    if not tg_updated and not message_updater:
                                        logger.warning(f"⚠️ 没有可用的消息更新方法")
                        elif d.get("status") == "finished":
                            progress_data["downloaded_videos"] += 1
                            logger.info(
                                f"✅ 播放列表 {progress_data['playlist_title']} 第 {progress_data['downloaded_videos']} 个视频下载完成"
                            )

                            # 监控文件合并状态
                            if 'filename' in d:
                                filename = d['filename']
                                if filename.endswith('.part'):
                                    logger.warning(f"⚠️ 文件合并可能失败: {filename}")
                                else:
                                    logger.info(f"✅ 文件下载并合并成功: {filename}")

                    return progress_callback

                # 下载播放列表
                result = await self._download_youtube_playlist_with_progress(
                    playlist_id,
                    channel_path,
                    create_playlist_progress_callback(playlist_progress_data),
                )

                if result.get("success"):
                    downloaded_playlists.append(
                        result.get("playlist_title", playlist_title)
                    )

                    # 更新完成状态消息
                    if message_updater:
                        try:
                            if asyncio.iscoroutinefunction(message_updater):
                                if result.get("already_downloaded", False):
                                    await message_updater(
                                        f"✅ 第 {i}/{len(playlist_entries)} 个播放列表：{playlist_title} (已存在)"
                                    )
                                else:
                                    await message_updater(
                                        f"✅ 第 {i}/{len(playlist_entries)} 个播放列表：{playlist_title} (下载完成)"
                                    )
                            else:
                                if result.get("already_downloaded", False):
                                    message_updater(
                                        f"✅ 第 {i}/{len(playlist_entries)} 个播放列表：{playlist_title} (已存在)"
                                    )
                                else:
                                    message_updater(
                                        f"✅ 第 {i}/{len(playlist_entries)} 个播放列表：{playlist_title} (下载完成)"
                                    )
                        except Exception as e:
                            logger.warning(f"更新完成状态消息失败: {e}")

                    # 获取视频数量，如果result中没有，则通过扫描目录计算
                    video_count = result.get("video_count", 0)
                    if video_count == 0:
                        # 备用方法：扫描播放列表目录计算实际文件数量
                        playlist_path = Path(result.get("download_path", ""))
                        if playlist_path.exists():
                            video_files = (
                                list(playlist_path.glob("*.mp4"))
                                + list(playlist_path.glob("*.mkv"))
                                + list(playlist_path.glob("*.webm"))
                            )
                            video_count = len(video_files)
                            logger.info(f"📊 通过扫描目录计算播放列表 '{playlist_title}' 的集数: {video_count}")
                    
                    playlist_stats.append(
                        {
                            "title": result.get("playlist_title", playlist_title),
                            "video_count": video_count,
                            "download_path": result.get("download_path", ""),
                            "total_size_mb": result.get("total_size_mb", 0),
                            "resolution": result.get("resolution", "未知"),
                            # 添加PART文件统计信息
                            "success_count": result.get("success_count", video_count),
                            "part_count": result.get("part_count", 0),
                        }
                    )
                    # 更新全局进度
                    global_progress["completed_playlists"] += 1
                    logger.info(f"    ✅ 播放列表 '{playlist_title}' 下载成功，集数: {video_count}")
                else:
                    error_msg = result.get("error", "未知错误")
                    logger.error(
                        f"    ❌ 播放列表 '{playlist_title}' 下载失败: {error_msg}"
                    )

            logger.info(
                f"📊 下载完成统计: {len(downloaded_playlists)}/{len(playlist_entries)} 个播放列表成功"
            )
            if not downloaded_playlists:
                logger.error("❌ 所有播放列表都下载失败了")
                if message_updater:
                    try:
                        if asyncio.iscoroutinefunction(message_updater):
                            await message_updater("❌ 频道中的所有播放列表都下载失败了。")
                        else:
                            message_updater("❌ 频道中的所有播放列表都下载失败了。")
                    except Exception as e:
                        logger.warning(f"更新状态消息失败: {e}")
                return {"success": False, "error": "频道中的所有播放列表都下载失败了。"}
            logger.info("🎉 频道播放列表下载任务完成!")

            # 构建详细的完成统计信息
            total_videos = sum(stat["video_count"] for stat in playlist_stats)
            total_size_mb = sum(stat["total_size_mb"] for stat in playlist_stats)

            # 按先获取下载列表的文件查找逻辑：根据下载列表中的文件名精确查找
            downloaded_files = []
            for stat in playlist_stats:
                playlist_path = Path(stat["download_path"])
                if playlist_path.exists():
                    # 先获取该播放列表的下载信息，然后根据文件名精确查找
                    try:
                        # 获取播放列表信息以获取预期的文件名列表
                        info_opts = {
                            "quiet": True,
                            "extract_flat": True,
                            "ignoreerrors": True,
                        }
                        if self.proxy_host:
                            info_opts["proxy"] = self.proxy_host
                        if self.youtube_cookies_path and os.path.exists(
                            self.youtube_cookies_path
                        ):
                            info_opts["cookiefile"] = self.youtube_cookies_path

                        # 从播放列表路径中提取playlist_id
                        playlist_id = (
                            playlist_path.name.split("_")[-1]
                            if "_" in playlist_path.name
                            else ""
                        )
                        if not playlist_id:
                            # 如果无法从路径提取，尝试从stat中获取
                            playlist_id = stat.get("playlist_id", "")

                        if playlist_id:
                            with yt_dlp.YoutubeDL(info_opts) as ydl:
                                playlist_info = ydl.extract_info(
                                    f"https://www.youtube.com/playlist?list={playlist_id}",
                                    download=False,
                                )
                                entries = playlist_info.get("entries", [])

                                # 根据下载列表中的条目查找对应的文件
                                for i, entry in enumerate(entries, 1):
                                    if entry:
                                        # 构造预期的文件名
                                        title = entry.get("title", f"Video_{i}")
                                        safe_title = re.sub(r'[\\/:*?"<>|]', "", title)[
                                            :60
                                        ]
                                        expected_filename = f"{i}. {safe_title}.mp4"

                                        # 精确查找该文件
                                        expected_file_path = (
                                            playlist_path / expected_filename
                                        )
                                        if expected_file_path.exists():
                                            file_size = (
                                                expected_file_path.stat().st_size
                                                / (1024 * 1024)
                                            )  # MB
                                            downloaded_files.append(
                                                {
                                                    "filename": expected_filename,
                                                    "path": str(expected_file_path),
                                                    "size_mb": file_size,
                                                    "playlist": stat["title"],
                                                    "video_title": title,
                                                }
                                            )
                                            logger.info(
                                                f"✅ 找到文件: {expected_filename} ({file_size:.2f}MB)")
                                        else:
                                            # 如果精确匹配失败，尝试模糊匹配
                                            logger.warning(
                                                f"⚠️ 未找到预期文件: {expected_filename}"
                                            )
                                            logger.info(f"🔍 尝试模糊匹配查找文件...")

                                            # 查找包含编号和部分标题的文件
                                            # 使用前20个字符进行模糊匹配
                                            pattern = f"{i:02d}.*{safe_title[:20]}*"
                                            matching_files = list(
                                                playlist_path.glob(f"{i:02d}.*")
                                            )

                                            if matching_files:
                                                # 找到匹配的文件
                                                actual_file = matching_files[0]
                                                file_size = (
                                                    actual_file.stat().st_size
                                                    / (1024 * 1024)
                                                )  # MB
                                                downloaded_files.append(
                                                    {
                                                        "filename": actual_file.name,
                                                        "path": str(actual_file),
                                                        "size_mb": file_size,
                                                        "playlist": stat["title"],
                                                        "video_title": title,
                                                    }
                                                )
                                                logger.info(
                                                    f"✅ 通过模糊匹配找到文件: {actual_file.name}"
                                                )
                                            else:
                                                logger.warning(
                                                    f"⚠️ 模糊匹配也未找到文件，编号: {i}, 标题: {safe_title}"
                                                )
                    except Exception as e:
                        logger.warning(f"获取播放列表信息失败: {e}")
                        # 如果获取列表失败，回退到扫描目录
                        video_files = (
                            list(playlist_path.glob("*.mp4"))
                            + list(playlist_path.glob("*.mkv"))
                            + list(playlist_path.glob("*.webm"))
                        )
                        for video_file in video_files:
                            file_size = video_file.stat().st_size / (1024 * 1024)  # MB
                            downloaded_files.append(
                                {
                                    "filename": video_file.name,
                                    "path": str(video_file),
                                    "size_mb": file_size,
                                    "playlist": stat["title"],
                                }
                            )

            # 计算总文件大小和PART文件统计
            total_size_mb = sum(stat['total_size_mb'] for stat in playlist_stats)
            total_size_gb = total_size_mb / 1024

            # 计算总的成功和未完成文件数量
            total_success_count = sum(stat.get('success_count', stat.get('video_count', 0)) for stat in playlist_stats)
            total_part_count = sum(stat.get('part_count', 0) for stat in playlist_stats)

            # 格式化总大小显示 - 只显示一个单位
            if total_size_gb >= 1.0:
                total_size_str = f"{total_size_gb:.2f}GB"
            else:
                total_size_str = f"{total_size_mb:.2f}MB"

            # 构建完成消息
            completion_text = (
                f"📺 YouTube频道播放列表下载完成\n\n"
                f"📺 频道: `{self._escape_markdown(channel_name)}`\n"
                f"📊 播放列表数量: `{self._escape_markdown(str(len(downloaded_playlists)))}`\n\n"
                f"已下载的播放列表:\n"
            )

            for i, stat in enumerate(playlist_stats, 1):
                completion_text += (
                    f"  {self._escape_markdown(str(i))}. {self._escape_markdown(stat['title'])} ({self._escape_markdown(str(stat['video_count']))} 集)\n"
                )

            # 构建下载统计信息
            stats_text = f"✅ 成功: `{total_success_count} 个`"
            if total_part_count > 0:
                stats_text += f"\n⚠️ 未完成: `{total_part_count} 个`"
                stats_text += f"\n💡 提示: 发现未完成文件，可能需要重新下载"

            # 添加统计信息、总大小和保存位置（放在最后）
            completion_text += (
                f"\n📊 下载统计:\n{stats_text}\n"
                f"💾 文件总大小: `{self._escape_markdown(total_size_str)}`\n"
                f"📂 保存位置: `{self._escape_markdown(str(channel_path))}`"
            )

            if message_updater:
                try:
                    if asyncio.iscoroutinefunction(message_updater):
                        await message_updater(completion_text)
                    else:
                        message_updater(completion_text)
                except Exception as e:
                    logger.warning(f"更新状态消息失败: {e}")

            return {
                "success": True,
                "is_channel": True,
                "channel_title": channel_name,
                    "download_path": str(channel_path),
                    "playlists_downloaded": downloaded_playlists,
                    "playlist_stats": playlist_stats,
                    "total_videos": total_videos,
                    "total_size_mb": total_size_mb,
                    "downloaded_files": downloaded_files,
                }

        except Exception as e:
            logger.error(f"❌ YouTube频道播放列表下载失败: {e}")
            import traceback

            logger.error(f"详细错误信息: {traceback.format_exc()}")
            if message_updater:
                try:
                    if asyncio.iscoroutinefunction(message_updater):
                        await message_updater(f"❌ 下载失败: {str(e)}")
                    else:
                        message_updater(f"❌ 下载失败: {str(e)}")
                except Exception as e2:
                    logger.warning(f"更新状态消息失败: {e2}")
            return {"success": False, "error": str(e)}

    def smart_download_bilibili(
        self, url: str, download_path: str, progress_callback=None, auto_playlist=False
    ):
        """智能下载B站视频，支持单视频、分集、合集"""
        import re
        import subprocess
        import os
        import threading
        from pathlib import Path

        logger.info(f"🎬 开始智能下载B站视频: {url}")
        logger.info(f"📁 下载路径: {download_path}")
        logger.info(f"🔄 自动下载全集: {auto_playlist}")

        # 保存原始工作目录
        original_cwd = os.getcwd()
        logger.info(f"📁 原始工作目录: {original_cwd}")

        try:
            # 检查是否为B站用户列表URL
            is_list, uid, list_id = self.is_bilibili_list_url(url)
            if is_list:
                logger.info(f"📋 检测到B站用户列表: UID={uid}, ListID={list_id}")

                # 使用BV号循环法下载用户列表
                bv_list = self.get_bilibili_list_videos(uid, list_id)
                if not bv_list:
                    return {"status": "failure", "error": "无法获取用户列表视频信息"}

                logger.info(f"📋 获取到 {len(bv_list)} 个视频")

                # 获取列表标题
                try:
                    list_info = self.get_bilibili_list_info(uid, list_id)
                    playlist_title = list_info.get("title", f"BilibiliList-{list_id}")
                except BaseException:
                    playlist_title = f"BilibiliList-{list_id}"
                safe_playlist_title = re.sub(
                    r'[\\/:*?"<>|]', "_", playlist_title
                ).strip()
                final_download_path = Path(download_path) / safe_playlist_title
                final_download_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"📁 为合集创建下载目录: {final_download_path}")
                # 使用yt-dlp print记录文件名的方案（与多P下载保持一致）
                success_count = 0
                downloaded_files = []  # 记录实际下载的文件信息

                for idx, (bv, title) in enumerate(bv_list, 1):
                    safe_title = re.sub(r'[\\/:*?"<>|]', "", title)[:60]
                    # 使用绝对路径构建输出模板
                    outtmpl = str(
                        final_download_path / f"{idx:02d}. {safe_title}.%(ext)s"
                    )

                    # 更新下载进度显示
                    if progress_callback:
                        progress_callback({
                            'status': 'downloading',
                            'filename': f'{idx:02d}. {safe_title}',
                            '_percent_str': f'{idx}/{len(bv_list)}',
                            '_eta_str': f'第{idx}个，共{len(bv_list)}个',
                            'info_dict': {'title': title}
                        })

                    # 1. 先用yt-dlp print获取实际文件名
                    video_url = f"https://www.bilibili.com/video/{bv}"
                    cmd_print = [
                        "yt-dlp", "--print", "filename", "-o", outtmpl, video_url
                    ]

                    try:
                        print_result = subprocess.run(cmd_print, capture_output=True, text=True, cwd=str(final_download_path))
                        if print_result.returncode == 0:
                            full_expected_path = print_result.stdout.strip()
                            # 只保留文件名部分，不包含路径
                            expected_filename = os.path.basename(full_expected_path)
                            logger.info(f"📝 预期文件名: {expected_filename}")
                        else:
                            # 如果print失败，使用构造的文件名
                            expected_filename = f"{idx:02d}. {safe_title}.mp4"
                            logger.warning(f"⚠️ print文件名失败，使用构造文件名: {expected_filename}")
                    except Exception as e:
                        expected_filename = f"{idx:02d}. {safe_title}.mp4"
                        logger.warning(f"⚠️ print文件名异常: {e}，使用构造文件名: {expected_filename}")

                    # 2. 执行下载（使用yt-dlp Python API支持进度回调）
                    ydl_opts_single = {
                        'outtmpl': outtmpl,
                        'merge_output_format': 'mp4',
                        'quiet': False,
                        'no_warnings': False,
                        'progress_hooks': [
                            lambda d: progress_callback(d) if progress_callback else None
                        ],
                    }

                    # 添加代理和cookies配置
                    if self.proxy_host:
                        ydl_opts_single['proxy'] = self.proxy_host
                    if self.b_cookies_path and os.path.exists(self.b_cookies_path):
                        ydl_opts_single['cookiefile'] = self.b_cookies_path

                    logger.info(f"🚀 下载第{idx}个: {bv} - {title}")
                    logger.info(f"📝 文件名模板: {outtmpl}")

                    try:
                        # 使用yt-dlp Python API，支持进度回调
                        with yt_dlp.YoutubeDL(ydl_opts_single) as ydl:
                            ydl.download([video_url])
                        success_count += 1
                        logger.info(f"✅ 第{idx}个下载成功")

                        # 3. 根据预期文件名查找实际文件
                        expected_path = final_download_path / expected_filename
                        if expected_path.exists():
                            size_mb = os.path.getsize(expected_path) / (1024 * 1024)
                            media_info = self.get_media_info(str(expected_path))
                            downloaded_files.append({
                                'filename': expected_filename,
                                'size_mb': size_mb,
                                'resolution': media_info.get('resolution', '未知'),
                                'abr': media_info.get('bit_rate')
                            })
                            logger.info(f"📁 记录文件: {expected_filename} ({size_mb:.1f}MB)")
                        else:
                            logger.warning(f"⚠️ 预期文件不存在: {expected_filename}")
                    except Exception as e:
                        logger.error(f"❌ 第{idx}个下载失败: {e}")

                logger.info(
                    f"🎉 BV号循环法下载完成: {success_count}/{len(bv_list)} 个成功"
                )

                if success_count > 0:
                    # 使用已记录的文件信息（不遍历目录）
                    total_size_mb = sum(file_info['size_mb'] for file_info in downloaded_files)
                    all_resolutions = {file_info['resolution'] for file_info in downloaded_files if file_info['resolution'] != '未知'}

                    filename_list = [info['filename'] for info in downloaded_files]
                    filename_display = '\n'.join([f"  {i+1:02d}. {name}" for i, name in enumerate(filename_list)])
                    resolution_display = ', '.join(sorted(all_resolutions)) if all_resolutions else '未知'

                    logger.info(f"📊 用户列表下载统计: {len(downloaded_files)}个文件, 总大小{total_size_mb:.1f}MB")

                    return {
                        "status": "success",
                        "video_type": "playlist",
                        "count": success_count,
                        "playlist_title": safe_playlist_title,
                        "download_path": str(final_download_path),
                        # 使用预期文件信息，避免目录遍历
                        "is_playlist": True,
                        "file_count": len(downloaded_files),
                        "total_size_mb": total_size_mb,
                        "files": downloaded_files,
                        "platform": "bilibili",
                        "filename": filename_display,
                        "size_mb": total_size_mb,
                        "resolution": resolution_display,
                        "episode_count": len(downloaded_files)
                    }
                else:
                    return {"status": "failure", "error": "用户列表视频全部下载失败"}
            # 下面是原有的B站单视频/合集/分集下载逻辑
            logger.info(f"🔍 正在检查视频类型: {url}")

            # 处理短链接，提取BV号
            original_url = url
            if "b23.tv" in url or "b23.wtf" in url:
                logger.info("🔄 检测到B站短链接，尝试提取BV号...")
                try:
                    # 先获取重定向后的URL
                    temp_opts = {
                        "quiet": True,
                        "no_warnings": True,
                    }
                    with yt_dlp.YoutubeDL(temp_opts) as ydl:
                        temp_info = ydl.extract_info(url, download=False)

                    if temp_info.get("webpage_url"):
                        redirected_url = temp_info["webpage_url"]
                        logger.info(f"🔄 短链接重定向到: {redirected_url}")

                        # 从重定向URL中提取BV号
                        bv_match = re.search(r"BV[0-9A-Za-z]+", redirected_url)
                        if bv_match:
                            bv_id = bv_match.group()
                            # 构造原始链接（不带分P标识）
                            original_url = f"https://www.bilibili.com/video/{bv_id}/"
                            logger.info(f"🔄 提取到BV号: {bv_id}")
                            logger.info(f"🔄 使用原始链接: {original_url}")
                        else:
                            logger.warning("⚠️ 无法从重定向URL中提取BV号")
                    else:
                        logger.warning("⚠️ 短链接重定向失败")
                except Exception as e:
                    logger.warning(f"⚠️ 处理短链接时出错: {e}")

            # 修改检测逻辑，确保能正确识别多P视频
            if auto_playlist:
                # 开启自动下载全集时，强制检测playlist
                check_opts = {
                    "quiet": True,
                    "flat_playlist": True,
                    "extract_flat": True,
                    "print": "%(id)s %(title)s",
                    "noplaylist": False,  # 关键：不阻止playlist检测
                    "yes_playlist": True,  # 关键：允许playlist检测
                    "extract_flat": True,  # 确保提取所有条目
                }
            else:
                # 关闭自动下载全集时，阻止playlist检测
                check_opts = {
                    "quiet": True,
                    "flat_playlist": True,
                    "extract_flat": True,
                    "print": "%(id)s %(title)s",
                    "noplaylist": True,  # 阻止playlist检测
                }

            # 使用处理后的URL进行检测
            with yt_dlp.YoutubeDL(check_opts) as ydl:
                info = ydl.extract_info(original_url, download=False)

            entries = info.get("entries", [])
            count = len(entries) if entries else 1
            logger.info(f"📋 检测到 {count} 个视频")

            # 如果只有一个视频，尝试anthology检测和强制playlist检测
            if count == 1:
                # 特殊检测：使用模拟下载检测anthology
                logger.info("🔍 使用模拟下载检测anthology...")
                anthology_detected = False
                try:
                    # 捕获yt-dlp的输出来检测anthology
                    cmd_simulate = ['yt-dlp', '--simulate', '--verbose', original_url]
                    result = subprocess.run(cmd_simulate, capture_output=True, text=True)
                    output = result.stdout + result.stderr

                    if 'extracting videos in anthology' in output.lower():
                        anthology_detected = True
                        logger.info("✅ 检测到anthology关键词，这是一个合集")
                    else:
                        logger.info("❌ 未检测到anthology关键词")

                except Exception as e:
                    logger.warning(f"⚠️ anthology检测失败: {e}")

                # 如果检测到anthology或开启了auto_playlist，尝试强制检测playlist
                if anthology_detected or auto_playlist:
                    if anthology_detected:
                        logger.info("🔄 检测到anthology，强制使用合集模式")
                    else:
                        logger.info("🔄 开启自动下载全集，尝试强制检测playlist...")

                    force_check_opts = {
                        "quiet": True,
                        "flat_playlist": True,
                        "extract_flat": True,
                        "print": "%(id)s %(title)s",
                        "noplaylist": False,
                        "yes_playlist": True,
                    }

                    try:
                        with yt_dlp.YoutubeDL(force_check_opts) as ydl:
                            force_info = ydl.extract_info(original_url, download=False)
                        force_entries = force_info.get("entries", [])
                        force_count = len(force_entries) if force_entries else 1

                        if force_count > count:
                            logger.info(f"🔄 强制检测成功！检测到 {force_count} 个视频")
                            entries = force_entries
                            count = force_count
                            info = force_info
                        elif anthology_detected:
                            # 检测到anthology，但需要进一步确认是否真的是多集
                            logger.info("🔄 anthology检测成功，但需要确认是否真的是多集")
                            # 不强制设置count，保持原有的检测结果
                            if count <= 1:
                                logger.info("🔍 anthology检测到，但实际只有1集，按单集处理")
                            else:
                                logger.info(f"🔍 anthology检测到，确认有{count}集，按合集处理")
                    except Exception as e:
                        logger.warning(f"⚠️ 强制检测失败: {e}")
                        if anthology_detected:
                            # 如果anthology检测成功但强制检测失败，需要谨慎处理
                            logger.info("🔄 anthology检测成功，但强制检测失败，按实际检测结果处理")
                            # 不强制设置count，保持原有的检测结果
                            if count <= 1:
                                logger.info("🔍 anthology检测到但强制检测失败，且实际只有1集，按单集处理")
                            else:
                                logger.info(f"🔍 anthology检测到，实际有{count}集，按合集处理")
            playlist_title = info.get("title", "Unknown Playlist")
            safe_playlist_title = re.sub(r'[\\/:*?"<>|]', "_", playlist_title).strip()

            if count > 1 and auto_playlist:
                final_download_path = Path(download_path) / safe_playlist_title
                final_download_path.mkdir(parents=True, exist_ok=True)
                logger.info(
                    f"📁 为合集 '{safe_playlist_title}' 创建下载目录: {final_download_path}"
                )
            else:
                final_download_path = Path(download_path)
                logger.info(f"📁 使用默认下载目录: {final_download_path}")
            # 移除 os.chdir() 调用，使用绝对路径

            if count == 1:
                video_type = "single"
                logger.info("🎬 检测到单视频")
            else:
                first_id = entries[0].get("id", "") if entries else ""
                all_same_id = all(
                    entry.get("id", "") == first_id for entry in entries if entry
                )
                if all_same_id:
                    video_type = "episodes"
                    logger.info(f"📺 检测到分集视频，共 {count} 集")
                    logger.info("📋 分集详情:")
                    for i, entry in enumerate(entries, 1):
                        if entry:
                            episode_title = entry.get("title", "unknown")
                            episode_id = entry.get("id", "unknown")
                            logger.info(
                                f"  {i:02d}. {episode_title} (ID: {episode_id})"
                            )
                else:
                    video_type = "playlist"
                    logger.info(f"📚 检测到合集，共 {count} 个视频")
                    logger.info("📋 合集详情:")
                    for i, entry in enumerate(entries, 1):
                        if entry:
                            video_title = entry.get("title", "unknown")
                            video_id = entry.get("id", "unknown")
                            logger.info(f"  {i:02d}. {video_title} (ID: {video_id})")

            # 根据视频类型决定下载策略
            if video_type == "single":
                # smart_download_bilibili 专门处理多P和合集，单视频应该由通用下载器处理
                logger.info("⚠️ smart_download_bilibili 检测到单视频")
                if auto_playlist:
                    logger.info("💡 虽然开启了自动下载全集，但这确实是单视频，建议使用通用下载器")
                else:
                    logger.info("💡 这是单视频，建议使用通用下载器")

                # 返回特殊状态，让调用方知道这是单视频
                return {
                    "status": "single_video",
                    "message": "这是单视频，建议使用通用下载器",
                    "video_type": "single"
                }
            elif video_type == "episodes":
                if auto_playlist:
                    # 自动下载全集 - 直接使用完整标题，不做复杂处理
                    output_template = str(
                        final_download_path / "%(title)s.%(ext)s"
                    )
                    # 添加明显的outtmpl日志
                    logger.info(
                        f"🔧 [BILIBILI_EPISODES] outtmpl 使用完整标题: {output_template}"
                    )

                    # 创建简单的进度回调，不需要重命名
                    def enhanced_progress_callback(d):
                        # 执行原有的进度回调逻辑（显示完整标题）
                        if progress_callback:
                            progress_callback(d)

                    ydl_opts = {
                        "outtmpl": output_template,
                        "merge_output_format": "mp4",
                        "quiet": False,
                        "yes_playlist": True,
                        "extract_flat": False,
                        "progress_hooks": [enhanced_progress_callback],
                    }
                    logger.info("🔄 自动下载全集模式：将下载所有分P视频")
                else:
                    # 只下载当前分P
                    output_template = str(final_download_path / "%(title)s.%(ext)s")
                    # 添加明显的outtmpl日志
                    logger.info(
                        f"🔧 [BILIBILI_SINGLE_EPISODE] outtmpl 绝对路径: {output_template}"
                    )
                    ydl_opts = {
                        "outtmpl": output_template,
                        "merge_output_format": "mp4",
                        "quiet": False,
                        "noplaylist": True,
                        "progress_hooks": [
                            lambda d: (
                                progress_callback(d) if progress_callback else None
                            )
                        ],
                    }
                    logger.info("🔄 单P模式：只下载当前分P视频")
            else:  # playlist - 和多P下载一样简单
                # 对于合集，直接使用yt-dlp播放列表功能（和多P下载一样）
                logger.info(f"🔧 检测到合集，使用yt-dlp播放列表功能下载")
                logger.info(f"   - 视频数量: {count}")

                # 使用和多P下载完全相同的逻辑
                output_template = str(
                    final_download_path / "%(playlist_index)s. %(title)s.%(ext)s"
                )
                logger.info(f"🔧 [BILIBILI_PLAYLIST] outtmpl 绝对路径: {output_template}")

                # 使用增强版进度回调来生成详细的进度显示格式
                progress_data = {
                    "final_filename": None,
                    "lock": threading.Lock(),
                    "downloaded_files": [],  # 添加下载文件列表
                    "expected_files": []     # 添加预期文件列表
                }

                # 检查 progress_callback 是否是增强版进度回调函数
                if callable(progress_callback) and progress_callback.__name__ == 'enhanced_progress_callback':
                    # 如果是增强版进度回调，直接使用它返回的 progress_hook
                    progress_hook = progress_callback(progress_data)
                else:
                    # 否则使用标准的 single_video_progress_hook
                    progress_hook = single_video_progress_hook(progress_callback, progress_data)

                ydl_opts = {
                    "outtmpl": output_template,
                    "merge_output_format": "mp4",
                    "quiet": False,
                    "yes_playlist": True,
                    "extract_flat": False,
                    "progress_hooks": [progress_hook],
                }
                logger.info("🔄 合集模式：将下载所有合集视频")

            # 对于单视频和分集视频，使用yt-dlp下载
            if video_type in ["single", "episodes"]:
                # 添加代理和cookies配置
                if self.proxy_host:
                    ydl_opts["proxy"] = self.proxy_host
                if self.b_cookies_path and os.path.exists(self.b_cookies_path):
                    ydl_opts["cookiefile"] = self.b_cookies_path
                logger.info(f"🔧 [BILIBILI_DOWNLOAD] 最终ydl_opts: {ydl_opts}")
                logger.info(f"📝 最终输出模板: {output_template}")
                logger.info(f"📁 下载目录: {final_download_path}")

                # 执行下载
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([original_url])

                logger.info("✅ B站视频下载完成")
                logger.info("🎯 使用postprocessor智能文件名，无需重命名")

                # 简化：B站多P下载完成，直接返回成功，文件查找交给目录遍历
                logger.info("🎯 B站多P下载完成，使用目录遍历查找文件")

                return {
                    "status": "success",
                    "video_type": video_type,
                    "count": count,
                    "playlist_title": safe_playlist_title if count > 1 else None,
                    "download_path": str(final_download_path),
                    # 简化：不传递预期文件信息，使用目录遍历
                }

        except Exception as e:
            logger.error(f"❌ B站视频下载失败: {e}")
            return {"status": "failure", "error": str(e)}
        finally:
            # 恢复原始工作目录
            try:
                os.chdir(original_cwd)
                logger.info(f"📁 已恢复工作目录: {original_cwd}")
            except Exception as e:
                logger.warning(f"⚠️ 恢复工作目录失败: {e}")

    def get_bilibili_list_videos(self, uid: str, list_id: str) -> list:
        """
        通过B站API获取用户自定义列表中的视频

        Args:
            uid: 用户ID (如 477348669)
            list_id: 列表ID (如 2111173)

        Returns:
            list: [(bv, title), ...]
        """
        try:
            # B站用户列表API
            api_url = f"https://api.bilibili.com/x/space/fav/season/list"
            params = {
                "season_id": list_id,
                "pn": 1,
                "ps": 20,  # 每页20个
                "jsonp": "jsonp",
            }

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Referer": f"https://space.bilibili.com/{uid}/lists/{list_id}",
            }

            logger.info(f"🔍 获取B站列表API: {api_url}")
            response = requests.get(api_url, params=params, headers=headers, timeout=10, verify=False)
            response.raise_for_status()

            data = response.json()
            if data.get("code") != 0:
                logger.error(f"❌ API返回错误: {data.get('message', '未知错误')}")
                return []

            # 解析视频列表
            videos = []
            archives = data.get("data", {}).get("medias", [])

            for archive in archives:
                bv = archive.get("bvid", "")
                title = archive.get("title", "")
                if bv and title:
                    videos.append((bv, title))
                    logger.info(f"  📺 {bv}: {title}")

            logger.info(f"📦 从API获取到 {len(videos)} 个视频")
            return videos

        except Exception as e:
            logger.error(f"❌ 获取B站列表失败: {e}")
            return []

    def download_bilibili_list_bv_method(
        self, uid: str, list_id: str, download_path: str
    ) -> bool:
        """
        使用BV号循环法下载B站用户自定义列表

        Args:
            uid: 用户ID
            list_id: 列表ID
            download_path: 下载路径

        Returns:
            bool: 下载是否成功
        """
        import subprocess
        import re

        logger.info(f"🔧 使用BV号循环法下载B站列表:")
        logger.info(f"   - 用户ID: {uid}")
        logger.info(f"   - 列表ID: {list_id}")

        # 1. 通过API获取视频列表
        bv_list = self.get_bilibili_list_videos(uid, list_id)

        if not bv_list:
            logger.error("❌ 未找到任何视频")
            return False

        logger.info(f"📦 找到 {len(bv_list)} 个视频，开始逐个下载")

        # 2. 依次下载每个BV号
        success_count = 0
        for idx, (bv, title) in enumerate(bv_list, 1):
            # 清理标题中的非法字符
            safe_title = re.sub(r'[\\/:*?"<>|]', "", title)[:60]
            outtmpl = f"{idx:02d}. {safe_title}.%(ext)s"
            cmd_dl = [
                "yt-dlp",
                "-o",
                outtmpl,
                "--merge-output-format",
                "mp4",
                f"https://www.bilibili.com/video/{bv}",
            ]
            logger.info(f"🚀 下载第{idx}个: {bv} - {title}")
            logger.info(f"📝 文件名模板: {outtmpl}")

            result = subprocess.run(cmd_dl, cwd=download_path)
            if result.returncode == 0:
                success_count += 1
                logger.info(f"✅ 第{idx}个下载成功")
            else:
                logger.error(f"❌ 第{idx}个下载失败")

        logger.info(f"🎉 BV号循环法下载完成: {success_count}/{len(bv_list)} 个成功")
        return success_count > 0

    async def _download_bilibili_list(
        self, uid: str, list_id: str, download_path: Path, message_updater=None
    ) -> Dict[str, Any]:
        """下载Bilibili播放列表"""
        logger.info(f"🎬 开始下载Bilibili播放列表: UID={uid}, ListID={list_id}")

        try:
            logger.info("🔍 步骤1: 准备获取播放列表信息...")
            # 获取播放列表信息 - 添加超时控制
            info_opts = {
                "quiet": True,
                "extract_flat": True,
                "ignoreerrors": True,
                "socket_timeout": 30,  # 30秒超时
                "retries": 3,  # 减少重试次数
                "fragment_retries": 3,
            }
            if self.proxy_host:
                info_opts["proxy"] = self.proxy_host
                logger.info(f"🌐 使用代理: {self.proxy_host}")

            logger.info("🔍 步骤2: 开始提取播放列表信息（设置30秒超时）...")

            # 使用异步执行器来添加超时控制
            loop = asyncio.get_running_loop()

            def extract_playlist_info():
                with yt_dlp.YoutubeDL(info_opts) as ydl:
                    logger.info("📡 正在从Bilibili获取播放列表数据...")
                    return ydl.extract_info(
                        f"https://www.bilibili.com/medialist/play/{uid}?business=space_series&business_id={list_id}",
                        download=False,
                    )

            # 设置30秒超时
            try:
                info = await asyncio.wait_for(
                    loop.run_in_executor(None, extract_playlist_info), timeout=60.0
                )
                logger.info(f"✅ 播放列表信息获取完成，数据类型: {type(info)}")
            except asyncio.TimeoutError:
                logger.error("❌ 获取播放列表信息超时（30秒）")
                return {
                    "success": False,
                    "error": "获取播放列表信息超时，请检查网络连接或稍后重试。",
                }

            if not info:
                logger.error("❌ 播放列表信息为空")
                return {"success": False, "error": "无法获取播放列表信息"}

            if "entries" not in info:
                logger.error("❌ 播放列表信息中没有找到 'entries' 字段")
                return {"success": False, "error": "无法获取播放列表信息"}

            entries = info.get("entries", [])
            logger.info(f"📊 播放列表包含 {len(entries)} 个视频")

            if not entries:
                logger.warning("⚠️ 播放列表为空")
                return {"success": False, "error": "播放列表为空"}

            logger.info("🔍 步骤3: 创建播放列表目录...")
            playlist_title = re.sub(
                r'[\\/:*?"<>|]', "_", info.get("title", "Bilibili_Playlist")
            ).strip()
            playlist_path = download_path / playlist_title
            playlist_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"📁 播放列表目录: {playlist_path}")

            logger.info("🔍 步骤4: 配置下载选项...")
            # 设置输出模板
            outtmpl = str(
                playlist_path.absolute()
                / "%(playlist_index)02d - %(title)s [%(id)s].%(ext)s"
            )
            # 添加明显的outtmpl日志
            logger.info(f"🔧 [BILIBILI_PLAYLIST] outtmpl 绝对路径: {outtmpl}")

            # 配置下载选项 - 优化性能
            ydl_opts = {
                "outtmpl": outtmpl,
                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "merge_output_format": "mp4",
                "ignoreerrors": True,
                "retries": 5,  # 减少重试次数
                "fragment_retries": 5,
                "skip_unavailable_fragments": True,
                "quiet": True,
                "no_warnings": True,
                "socket_timeout": 30,  # 30秒超时
                "extract_flat": False,  # 完整提取
            }

            if self.proxy_host:
                ydl_opts["proxy"] = self.proxy_host

            if message_updater:
                ydl_opts["progress_hooks"] = [message_updater]

            logger.info("🔍 步骤5: 开始下载播放列表（设置60秒超时）...")

            def download_playlist():
                logger.info(f"🔧 [BILIBILI_PLAYLIST_DOWNLOAD] 最终ydl_opts: {ydl_opts}")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    logger.info("🚀 开始下载Bilibili播放列表视频...")
                    return ydl.download(
                        [
                            f"https://www.bilibili.com/medialist/play/{uid}?business=space_series&business_id={list_id}"
                        ]
                    )

            # 设置60秒超时用于下载
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(None, download_playlist), timeout=120.0
                )
                logger.info("✅ Bilibili播放列表下载完成")
            except asyncio.TimeoutError:
                logger.error("❌ Bilibili播放列表下载超时（60秒）")
                return {
                    "success": False,
                    "error": "Bilibili播放列表下载超时，请检查网络连接或稍后重试。",
                }

            return {
                "success": True,
                "is_playlist": True,
                "playlist_title": playlist_title,
                "download_path": str(playlist_path),
                "video_count": len(entries),
            }

        except Exception as e:
            logger.error(f"❌ Bilibili播放列表下载失败: {e}")
            import traceback

            logger.error(f"详细错误信息: {traceback.format_exc()}")
            return {"success": False, "error": str(e)}

    async def _download_youtube_playlist_with_progress(
        self, playlist_id: str, download_path: Path, progress_callback=None
    ) -> Dict[str, Any]:
        """下载YouTube播放列表（带详细进度）"""
        logger.info(f"🎬 开始下载YouTube播放列表: {playlist_id}")
        logger.info(f"📁 下载路径: {download_path}")

        try:
            # 首先检查播放列表是否已经完整下载
            logger.info("🔍 检查播放列表是否已完整下载...")
            check_result = self._check_playlist_already_downloaded(
                playlist_id, download_path
            )

            if check_result.get("already_downloaded", False):
                logger.info("✅ 播放列表已完整下载，直接返回结果")
                return {
                    "success": True,
                    "already_downloaded": True,
                    "playlist_title": check_result.get("playlist_title", ""),
                    "video_count": check_result.get("video_count", 0),
                    "download_path": check_result.get("download_path", ""),
                    "total_size_mb": check_result.get("total_size_mb", 0),
                    "resolution": check_result.get("resolution", "未知"),
                    "downloaded_files": check_result.get("downloaded_files", []),
                    "completion_rate": check_result.get("completion_rate", 100),
                }
            else:
                logger.info(f"📥 播放列表未完整下载，原因: {check_result.get('reason', '未知')}")
                if check_result.get("completion_rate", 0) > 0:
                    logger.info(
                        f"📊 当前完成度: {check_result.get('completion_rate', 0):.1f}%"
                    )

            # 获取播放列表信息
            info_opts = {"quiet": True, "extract_flat": True, "ignoreerrors": True}
            if self.proxy_host:
                info_opts["proxy"] = self.proxy_host
                logger.info(f"🌐 使用代理: {self.proxy_host}")
            if self.youtube_cookies_path and os.path.exists(self.youtube_cookies_path):
                info_opts["cookiefile"] = self.youtube_cookies_path
                logger.info(
                    f"🍪 使用YouTube cookies: {self.youtube_cookies_path}"
                )

            def extract_playlist_info():
                logger.info("📡 正在从YouTube获取播放列表数据...")
                with yt_dlp.YoutubeDL(info_opts) as ydl:
                    result = ydl.extract_info(
                        f"https://www.youtube.com/playlist?list={playlist_id}",
                        download=False,
                    )
                    return result

            loop = asyncio.get_running_loop()
            info = await loop.run_in_executor(None, extract_playlist_info)

            if not info:
                logger.error("❌ 播放列表信息为空")
                return {"success": False, "error": "无法获取播放列表信息。"}

            entries = info.get("entries", [])
            if not entries:
                logger.warning("❌ 播放列表为空")
                return {"success": False, "error": "播放列表为空。"}

            logger.info(f"📊 播放列表包含 {len(entries)} 个视频")

            # 创建播放列表目录
            playlist_title = re.sub(
                r'[\\/:*?"<>|]', "_", info.get("title", f"Playlist_{playlist_id}")
            ).strip()
            playlist_path = download_path / playlist_title
            playlist_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"📁 播放列表目录: {playlist_path}")

            # 预先记录预期文件信息（像B站多P下载一样）
            expected_files = []
            for i, entry in enumerate(entries, 1):
                title = entry.get("title", f"Video_{i}")
                safe_title = re.sub(r'[\\/:*?"<>|]', "_", title).strip()
                expected_filename = f"{i:02d}. {safe_title}.mp4"
                expected_files.append({
                    'title': title,
                    'filename': expected_filename,
                    'index': i,
                    'id': entry.get('id', ''),
                })

            logger.info(f"📋 预期文件列表: {len(expected_files)} 个文件")

            # 下载播放列表（带进度回调）
            def download_playlist():
                logger.info("🚀 开始下载播放列表...")
                # 使用绝对路径构建outtmpl，使用两位数字格式
                abs_outtmpl = str(
                    playlist_path.absolute() / "%(playlist_index)02d. %(title)s.%(ext)s"
                )
                logger.info(
                    f"🔧 [YT_PLAYLIST_WITH_PROGRESS] outtmpl 绝对路径: {abs_outtmpl}"
                )
                # 使用增强配置，避免PART文件
                base_opts = {
                    "outtmpl": abs_outtmpl,
                    "merge_output_format": "mp4",
                    "ignoreerrors": True,
                    "progress_hooks": [progress_callback] if progress_callback else [],
                }

                ydl_opts = self._get_enhanced_ydl_opts(base_opts)
                logger.info("🛡️ 使用增强配置，避免PART文件产生")
                logger.info(f"🔧 [YT_PLAYLIST_WITH_PROGRESS] 最终ydl_opts关键配置: outtmpl={abs_outtmpl}")

                playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([playlist_url])

                    # 下载完成后检查并处理PART文件
                    logger.info("🔍 检查YouTube播放列表下载完成状态...")
                    resume_success = self._resume_failed_downloads(download_path, playlist_url, max_retries=2)

                    if not resume_success:
                        logger.warning("⚠️ 部分文件下载未完成，但已达到最大重试次数")
                    else:
                        logger.info("✅ YouTube播放列表所有文件下载完成")

                except Exception as e:
                    logger.error(f"❌ YouTube播放列表下载过程中出现错误: {e}")
                    # 即使出错也尝试断点续传PART文件
                    logger.info("🔄 尝试断点续传未完成的文件...")
                    self._resume_part_files(download_path, playlist_url)
                    raise

            await loop.run_in_executor(None, download_playlist)

            logger.info("🎉 播放列表下载完成!")

            # 使用预期文件名精确查找（像B站多P下载一样）
            downloaded_files = []
            total_size_mb = 0
            all_resolutions = set()

            logger.info("🔍 使用预期文件名查找下载的文件")
            for expected_file in expected_files:
                expected_filename = expected_file['filename']
                expected_path = playlist_path / expected_filename

                if expected_path.exists():
                    try:
                        file_size = expected_path.stat().st_size
                        if file_size > 0:
                            file_size_mb = file_size / (1024 * 1024)
                            total_size_mb += file_size_mb

                            # 获取媒体信息
                            media_info = self.get_media_info(str(expected_path))
                            resolution = media_info.get('resolution', '未知')
                            if resolution != '未知':
                                all_resolutions.add(resolution)

                            downloaded_files.append({
                                "filename": expected_filename,
                                "path": str(expected_path),
                                "size_mb": file_size_mb,
                                "video_title": expected_file['title'],
                            })
                            logger.info(f"✅ 找到预期文件: {expected_filename} ({file_size_mb:.2f}MB)")
                        else:
                            logger.warning(f"⚠️ 预期文件为空: {expected_filename}")
                    except Exception as e:
                        logger.warning(f"⚠️ 无法检查预期文件: {expected_filename}, 错误: {e}")
                else:
                    # 尝试使用清理后的文件名匹配（处理格式代码等）
                    def clean_filename_for_matching(filename):
                        """清理文件名用于匹配"""
                        import re
                        if not filename:
                            return ""

                        # 删除yt-dlp的各种格式代码
                        cleaned = re.sub(r'\.[fm]\d+(\+\d+)*', '', filename)
                        cleaned = re.sub(r'\.f\d+', '', cleaned)
                        cleaned = re.sub(r'\.(webm|m4a|mp3)$', '.mp4', cleaned)

                        # 确保以 .mp4 结尾
                        if not cleaned.endswith('.mp4'):
                            cleaned = cleaned.rstrip('.') + '.mp4'

                        return cleaned

                    # 在播放列表目录中查找匹配的文件
                    found = False
                    for video_ext in ["*.mp4", "*.mkv", "*.webm", "*.avi", "*.mov", "*.flv"]:
                        matching_files = list(playlist_path.glob(video_ext))
                        for file_path in matching_files:
                            actual_filename = file_path.name
                            cleaned_actual = clean_filename_for_matching(actual_filename)
                            cleaned_expected = clean_filename_for_matching(expected_filename)

                            if cleaned_actual == cleaned_expected:
                                try:
                                    file_size = file_path.stat().st_size
                                    if file_size > 0:
                                        file_size_mb = file_size / (1024 * 1024)
                                        total_size_mb += file_size_mb

                                        # 获取媒体信息
                                        media_info = self.get_media_info(str(file_path))
                                        resolution = media_info.get('resolution', '未知')
                                        if resolution != '未知':
                                            all_resolutions.add(resolution)

                                        downloaded_files.append({
                                            "filename": actual_filename,
                                            "path": str(file_path),
                                            "size_mb": file_size_mb,
                                            "video_title": expected_file['title'],
                                        })
                                        logger.info(f"✅ 通过智能匹配找到文件: {actual_filename} ({file_size_mb:.2f}MB)")
                                        found = True
                                        break
                                except Exception as e:
                                    continue
                        if found:
                            break

                    if not found:
                        logger.warning(f"⚠️ 未找到预期文件: {expected_filename}")

            # 计算分辨率显示
            resolution = ', '.join(sorted(all_resolutions)) if all_resolutions else '未知'

            logger.info(f"📊 找到文件数量: {len(downloaded_files)}/{len(expected_files)}")
            logger.info(f"📊 总大小: {total_size_mb:.2f}MB")

            return {
                "success": True,
                "playlist_title": playlist_title,
                "video_count": len(downloaded_files),
                "download_path": str(playlist_path),
                "total_size_mb": total_size_mb,
                "size_mb": total_size_mb,  # 添加这个字段以兼容main.py
                "resolution": resolution,
                "downloaded_files": downloaded_files,
            }

        except Exception as e:
            logger.error(f"❌ YouTube播放列表下载失败: {e}")
            import traceback

            logger.error(f"详细错误信息: {traceback.format_exc()}")
            return {"success": False, "error": str(e)}
    
    def _escape_markdown(self, text: str) -> str:
        # 先转义反斜杠
        text = text.replace("\\", "\\\\")
        # 再转义其它所有特殊字符
        for ch in "_*[]()~`>#+-=|{}.!":
            text = text.replace(ch, f"\\{ch}")
        return text

    def _make_progress_bar(self, percent: float) -> str:
        """生成进度条"""
        bar_length = 20
        filled_length = int(bar_length * percent / 100)
        bar = "█" * filled_length + "░" * (bar_length - filled_length)
        return f"[{bar}] {percent:.1f}%"

    def _check_playlist_already_downloaded(
        self, playlist_id: str, download_path: Path
    ) -> Dict[str, Any]:
        """
        检查YouTube播放列表是否已经完整下载（使用预期文件名方式）

        Args:
            playlist_id: 播放列表ID
            download_path: 下载路径

        Returns:
            Dict: 包含检查结果的字典
        """
        logger.info(f"🔍 检查播放列表是否已下载: {playlist_id}")

        try:
            # 获取播放列表信息
            info_opts = {
                "quiet": True,
                "extract_flat": True,
                "ignoreerrors": True,
                "socket_timeout": 10,
                "retries": 2,
            }
            if self.proxy_host:
                info_opts["proxy"] = self.proxy_host
            if self.youtube_cookies_path and os.path.exists(self.youtube_cookies_path):
                info_opts["cookiefile"] = self.youtube_cookies_path

            with yt_dlp.YoutubeDL(info_opts) as ydl:
                info = ydl.extract_info(
                    f"https://www.youtube.com/playlist?list={playlist_id}",
                    download=False,
                )

            if not info:
                logger.warning("❌ 无法获取播放列表信息")
                return {"already_downloaded": False, "reason": "无法获取播放列表信息"}

            entries = info.get("entries", [])
            if not entries:
                logger.warning("❌ 播放列表为空")
                return {"already_downloaded": False, "reason": "播放列表为空"}

            # 构建预期文件列表（和下载时一致）
            expected_files = []
            for i, entry in enumerate(entries, 1):
                title = entry.get("title", f"Video_{i}")
                safe_title = re.sub(r'[\\/:*?"<>|]', "_", title).strip()
                expected_filename = f"{i:02d}. {safe_title}.mp4"
                expected_files.append({
                    'title': title,
                    'filename': expected_filename,
                    'index': i,
                    'id': entry.get('id', ''),
                })

            # 创建播放列表目录名
            playlist_title = re.sub(
                r'[\\/:*?"<>|]', "_", info.get("title", f"Playlist_{playlist_id}")
            ).strip()
            playlist_path = download_path / playlist_title

            if not playlist_path.exists():
                logger.info(f"📁 播放列表目录不存在: {playlist_path}")
                return {"already_downloaded": False, "reason": "目录不存在"}

            logger.info(f"📁 检查播放列表目录: {playlist_path}")

            # 使用预期文件名检查文件是否存在（和下载逻辑一致）
            missing_files = []
            existing_files = []
            total_size_mb = 0
            all_resolutions = set()

            def clean_filename_for_matching(filename):
                """清理文件名用于匹配"""
                import re
                if not filename:
                    return ""

                # 删除yt-dlp的各种格式代码
                cleaned = re.sub(r'\.[fm]\d+(\+\d+)*', '', filename)
                cleaned = re.sub(r'\.f\d+', '', cleaned)
                cleaned = re.sub(r'\.(webm|m4a|mp3)$', '.mp4', cleaned)

                # 确保以 .mp4 结尾
                if not cleaned.endswith('.mp4'):
                    cleaned = cleaned.rstrip('.') + '.mp4'

                return cleaned

            for expected_file in expected_files:
                expected_filename = expected_file['filename']
                expected_path = playlist_path / expected_filename
                title = expected_file['title']

                if expected_path.exists():
                    try:
                        file_size = expected_path.stat().st_size
                        if file_size > 0:
                            file_size_mb = file_size / (1024 * 1024)
                            total_size_mb += file_size_mb

                            # 获取媒体信息
                            media_info = self.get_media_info(str(expected_path))
                            resolution = media_info.get('resolution', '未知')
                            if resolution != '未知':
                                all_resolutions.add(resolution)

                            existing_files.append({
                                "filename": expected_filename,
                                "path": str(expected_path),
                                "size_mb": file_size_mb,
                                "video_title": title,
                            })
                            logger.info(f"✅ 找到文件: {expected_filename} ({file_size_mb:.2f}MB)")
                        else:
                            missing_files.append(f"{expected_file['index']}. {title}")
                            logger.warning(f"⚠️ 文件为空: {expected_filename}")
                    except Exception as e:
                        missing_files.append(f"{expected_file['index']}. {title}")
                        logger.warning(f"⚠️ 无法检查文件: {expected_filename}, 错误: {e}")
                else:
                    # 尝试智能匹配（处理格式代码等）
                    found = False
                    for video_ext in ["*.mp4", "*.mkv", "*.webm", "*.avi", "*.mov", "*.flv"]:
                        matching_files = list(playlist_path.glob(video_ext))
                        for file_path in matching_files:
                            actual_filename = file_path.name
                            cleaned_actual = clean_filename_for_matching(actual_filename)
                            cleaned_expected = clean_filename_for_matching(expected_filename)

                            if cleaned_actual == cleaned_expected:
                                try:
                                    file_size = file_path.stat().st_size
                                    if file_size > 0:
                                        file_size_mb = file_size / (1024 * 1024)
                                        total_size_mb += file_size_mb

                                        # 获取媒体信息
                                        media_info = self.get_media_info(str(file_path))
                                        resolution = media_info.get('resolution', '未知')
                                        if resolution != '未知':
                                            all_resolutions.add(resolution)

                                        existing_files.append({
                                            "filename": actual_filename,
                                            "path": str(file_path),
                                            "size_mb": file_size_mb,
                                            "video_title": title,
                                        })
                                        logger.info(f"✅ 通过模糊匹配找到文件: {actual_filename} ({file_size_mb:.2f}MB)")
                                        found = True
                                        break
                                except Exception as e:
                                    continue
                        if found:
                            break

                    if not found:
                        missing_files.append(f"{expected_file['index']}. {title}")
                        logger.warning(f"⚠️ 未找到文件: {expected_filename}")

            # 计算完成度
            total_videos = len(expected_files)
            downloaded_videos = len(existing_files)
            completion_rate = (
                (downloaded_videos / total_videos) * 100 if total_videos > 0 else 0
            )

            logger.info(
                f"📊 下载完成度: {downloaded_videos}/{total_videos} ({completion_rate:.1f}%)"
            )

            # 如果完成度达到95%以上，认为已经下载完成
            if completion_rate >= 95:
                logger.info(f"✅ 播放列表已完整下载 ({completion_rate:.1f}%)")

                # 计算分辨率信息
                resolution = ', '.join(sorted(all_resolutions)) if all_resolutions else '未知'
                if existing_files:
                    try:
                        import subprocess

                        first_file_path = existing_files[0]["path"]
                        result = subprocess.run(
                            [
                                "ffprobe",
                                "-v",
                                "quiet",
                                "-print_format",
                                "json",
                                "-show_streams",
                                first_file_path,
                            ],
                            capture_output=True,
                            text=True,
                        )
                        if result.returncode == 0:
                            import json

                            data = json.loads(result.stdout)
                            for stream in data.get("streams", []):
                                if stream.get("codec_type") == "video":
                                    width = stream.get("width", 0)
                                    height = stream.get("height", 0)
                                    if width and height:
                                        resolution = f"{width}x{height}"
                                        break
                    except Exception as e:
                        logger.warning(f"无法获取视频分辨率: {e}")

                return {
                    "already_downloaded": True,
                    "playlist_title": playlist_title,
                    "video_count": downloaded_videos,
                    "total_videos": total_videos,
                    "completion_rate": completion_rate,
                    "download_path": str(playlist_path),
                    "total_size_mb": total_size_mb,
                    "resolution": resolution,
                    "downloaded_files": existing_files,
                    "missing_files": missing_files,
                }
            else:
                logger.info(f"📥 播放列表未完整下载 ({completion_rate:.1f}%)")
                return {
                    "already_downloaded": False,
                    "reason": f"完成度不足 ({completion_rate:.1f}%)",
                    "downloaded_videos": downloaded_videos,
                    "total_videos": total_videos,
                    "completion_rate": completion_rate,
                    "missing_files": missing_files,
                }

        except Exception as e:
            logger.error(f"❌ 检查播放列表下载状态时出错: {e}")
            return {"already_downloaded": False, "reason": f"检查失败: {str(e)}"}

    def _convert_cookies_to_json(self, cookies_path: str) -> dict:
        """将 Netscape 格式的 cookies 转换为 gallery-dl 支持的 JSON 格式"""
        try:
            import http.cookiejar
            
            # 创建 cookie jar 并加载 cookies
            cookie_jar = http.cookiejar.MozillaCookieJar(cookies_path)
            cookie_jar.load()
            
            # 转换为字典格式
            cookies_dict = {}
            for cookie in cookie_jar:
                cookies_dict[cookie.name] = cookie.value
            
            logger.info(f"✅ 成功转换 cookies，共 {len(cookies_dict)} 个")
            return cookies_dict
            
        except Exception as e:
            logger.error(f"❌ cookies 转换失败: {e}")
            return {}

    async def download_with_gallery_dl(
        self, url: str, download_path: Path, message_updater=None
    ) -> Dict[str, Any]:
        """使用 gallery-dl 下载图片"""
        if not GALLERY_DL_AVAILABLE:
            return {
                "success": False,
                "error": "gallery-dl 未安装，无法下载图片。请运行: pip install gallery-dl"
            }
        
        try:
            # 确保下载目录存在
            download_path.mkdir(parents=True, exist_ok=True)
            download_path_str = str(download_path)
            
            # 使用我们创建的 gallery-dl.conf 配置文件 - 与容器中完全一致
            config_path = Path(self.download_path / "gallery-dl.conf")
            if config_path.exists():
                logger.info(f"📄 使用 gallery-dl.conf 配置文件: {config_path}")
                # 加载配置文件 - 与容器中完全一致
                gallery_dl.config.load([str(config_path)])
            else:
                logger.warning(f"⚠️ gallery-dl.conf 配置文件不存在: {config_path}")
                return {
                    "success": False,
                    "error": "gallery-dl.conf 配置文件不存在"
                }
            
            # 获取 gallery-dl 实际使用的下载目录
            try:
                # 直接从配置文件中读取 base-directory
                import json
                if config_path.exists():
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                    actual_download_dir = config_data.get("base-directory", str(download_path))
                else:
                    actual_download_dir = str(download_path)
                logger.info(f"🎯 gallery-dl 实际下载目录: {actual_download_dir}")
            except Exception as e:
                logger.warning(f"⚠️ 无法从配置文件读取下载目录: {e}")
                actual_download_dir = str(download_path)
                logger.info(f"🎯 使用默认下载目录: {actual_download_dir}")
            
            # 记录下载前的文件
            actual_download_path = Path(actual_download_dir)
            before_files = set()
            if actual_download_path.exists():
                for file_path in actual_download_path.rglob("*"):
                    if file_path.is_file():
                        relative_path = str(file_path.relative_to(actual_download_path))
                        before_files.add(relative_path)
            
            logger.info(f"📊 下载前文件数量: {len(before_files)}")
            if before_files:
                logger.info(f"📊 下载前文件示例: {list(before_files)[:5]}")
            
            # 发送开始下载消息
            if message_updater:
                try:
                    if asyncio.iscoroutinefunction(message_updater):
                        await message_updater("🖼️ **图片下载中**\n📝 当前下载：准备中...\n🖼️ 已完成：0 张")
                    else:
                        message_updater("🖼️ **图片下载中**\n📝 当前下载：准备中...\n🖼️ 已完成：0 张")
                except Exception as e:
                    logger.warning(f"⚠️ 发送开始消息失败: {e}")
            
            # 创建进度监控任务
            progress_task = None
            if message_updater:
                progress_task = asyncio.create_task(self._monitor_gallery_dl_progress(
                    actual_download_path, before_files, message_updater
                ))
            
            # 使用正确的 gallery-dl API - 与容器中完全一致
            job = gallery_dl.job.DownloadJob(url, None)
            
            logger.info("📸 gallery-dl 开始下载...")
            
            # 添加重试机制
            max_retries = 3
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    # 在异步执行器中运行同步的 job.run()，让进度监控能够持续运行
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, job.run)
                    
                    logger.info("📸 gallery-dl 下载任务完成")
                    break  # 成功完成，跳出重试循环
                    
                except Exception as e:
                    retry_count += 1
                    error_str = str(e).lower()
                    
                    if ("403" in error_str or "forbidden" in error_str) and retry_count < max_retries:
                        logger.warning(f"⚠️ 遇到 403 错误，第 {retry_count} 次重试...")
                        await asyncio.sleep(10)  # 等待10秒后重试
                        continue
                    else:
                        # 其他错误或重试次数用完，抛出异常
                        raise e
            
            # 等待一下确保文件写入完成
            await asyncio.sleep(3)
            
            # 取消进度监控任务
            if progress_task:
                progress_task.cancel()
                try:
                    await progress_task
                except asyncio.CancelledError:
                    logger.info("📊 进度监控任务已取消")
                    pass
            
            # 查找新下载的文件（在 gallery-dl 实际下载目录中）
            downloaded_files = []
            total_size_bytes = 0
            file_formats = set()
            
            logger.info(f"🔍 开始查找新下载的文件...")
            logger.info(f"🔍 查找目录: {actual_download_dir}")
            logger.info(f"🔍 下载前文件数量: {len(before_files)}")
            
            if actual_download_path.exists():
                # 获取当前所有文件
                current_files = set()
                for file_path in actual_download_path.rglob("*"):
                    if file_path.is_file():
                        relative_path = str(file_path.relative_to(actual_download_path))
                        current_files.add(relative_path)
                
                logger.info(f"🔍 当前文件数量: {len(current_files)}")
                
                # 计算新文件
                new_files = current_files - before_files
                logger.info(f"🔍 新文件数量: {len(new_files)}")
                
                # 记录一些新文件作为示例
                if new_files:
                    sample_files = list(new_files)[:5]  # 前5个文件
                    logger.info(f"🔍 新文件示例: {sample_files}")
                    
                    # 直接处理新文件，不需要额外遍历
                    for relative_path in new_files:
                        file_path = actual_download_path / relative_path
                        if file_path.is_file():
                            # 检查是否为图片或视频文件
                            if file_path.suffix.lower() in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4', '.mov', '.avi', '.mkv']:
                                downloaded_files.append(file_path)
                                try:
                                    file_size = file_path.stat().st_size
                                    total_size_bytes += file_size
                                    file_formats.add(file_path.suffix.lower())
                                    logger.info(f"✅ 找到下载文件: {relative_path} ({file_size} bytes)")
                                except OSError as e:
                                    logger.warning(f"无法获取文件大小: {file_path} - {e}")
                else:
                    # 如果没有找到新文件，尝试查找最近修改的文件
                    logger.warning(f"⚠️ 没有找到新文件，尝试查找最近修改的文件...")
                    try:
                        recent_files = []
                        for file_path in actual_download_path.rglob("*"):
                            if file_path.is_file():
                                # 检查文件修改时间是否在最近5分钟内
                                file_mtime = file_path.stat().st_mtime
                                if time.time() - file_mtime < 300:  # 5分钟
                                    recent_files.append(file_path)
                        
                        logger.info(f"🔍 最近5分钟内修改的文件数量: {len(recent_files)}")
                        if recent_files:
                            logger.info(f"🔍 最近修改的文件示例: {[f.name for f in recent_files[:3]]}")
                            # 将这些最近修改的文件作为下载的文件
                            for file_path in recent_files:
                                if file_path.suffix.lower() in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4', '.mov', '.avi', '.mkv']:
                                    downloaded_files.append(file_path)
                                    try:
                                        file_size = file_path.stat().st_size
                                        total_size_bytes += file_size
                                        file_formats.add(file_path.suffix.lower())
                                        logger.info(f"✅ 找到最近修改的文件: {file_path.name} ({file_size} bytes)")
                                    except OSError as e:
                                        logger.warning(f"无法获取文件大小: {file_path} - {e}")
                    except Exception as e:
                        logger.error(f"❌ 查找最近修改文件时出错: {e}")
            else:
                logger.warning(f"⚠️ 下载目录不存在: {actual_download_dir}")
            
            logger.info(f"🔍 最终找到的下载文件数量: {len(downloaded_files)}")
            
            if downloaded_files:
                # 计算总大小
                size_mb = total_size_bytes / (1024 * 1024)
                
                # 格式化文件格式显示
                format_str = ", ".join(sorted(file_formats)) if file_formats else "未知格式"
                
                # 生成详细的结果信息
                result = {
                    "success": True,
                    "message": f"✅ 图片下载完成！\n\n🖼️ 图片数量：{len(downloaded_files)} 张\n📝 保存位置：{actual_download_dir}\n💾 总大小：{size_mb:.1f} MB\n📄 文件格式：{format_str}",
                    "files_count": len(downloaded_files),
                    "failed_count": 0,
                    "files": [str(f) for f in downloaded_files],
                    "size_mb": size_mb,
                    "filename": downloaded_files[0].name if downloaded_files else "未知文件",
                    "download_path": actual_download_dir,
                    "full_path": str(downloaded_files[0]) if downloaded_files else "",
                    "resolution": "图片",
                    "abr": None,
                    "file_formats": list(file_formats)
                }
                
                logger.info(f"✅ gallery-dl 下载成功: {len(downloaded_files)} 个文件, 总大小: {size_mb:.1f} MB")
                return result
            else:
                logger.warning(f"⚠️ 未找到新下载的文件，查找目录: {actual_download_dir}")
                logger.warning(f"⚠️ 下载前文件数量: {len(before_files)}")
                return {
                    "success": False,
                    "error": "未找到下载的文件"
                }
                
        except Exception as e:
            logger.error(f"gallery-dl 下载失败: {e}")
            
            # 特殊处理不同类型的错误
            error_str = str(e).lower()
            if "403" in error_str or "forbidden" in error_str:
                error_msg = (
                    f"❌ 访问被拒绝 (403 Forbidden)\n\n"
                    f"可能的原因：\n"
                    f"1. 服务器检测到爬虫行为\n"
                    f"2. IP地址被临时封禁\n"
                    f"3. 需要特定的请求头或cookies\n"
                    f"4. 内容需要登录才能访问\n\n"
                    f"建议解决方案：\n"
                    f"1. 等待几分钟后重试\n"
                    f"2. 检查cookies文件是否有效\n"
                    f"3. 尝试使用代理\n"
                    f"4. 联系管理员获取帮助"
                )
            elif "nsfw" in error_str or "authorizationerror" in error_str:
                error_msg = (
                    f"❌ NSFW内容下载失败\n\n"
                    f"请确保：\n"
                    f"1. 已配置有效的X cookies文件路径\n"
                    f"2. X账户允许查看NSFW内容\n"
                    f"3. 账户已完成年龄验证\n"
                    f"4. cookies文件格式正确（Netscape格式）\n"
                    f"5. cookies文件包含有效的认证信息"
                )
            elif "timeout" in error_str or "connection" in error_str:
                error_msg = (
                    f"❌ 网络连接超时\n\n"
                    f"可能的原因：\n"
                    f"1. 网络连接不稳定\n"
                    f"2. 服务器响应慢\n"
                    f"3. 防火墙阻止连接\n\n"
                    f"建议解决方案：\n"
                    f"1. 检查网络连接\n"
                    f"2. 稍后重试\n"
                    f"3. 尝试使用代理"
                )
            else:
                error_msg = f"❌ gallery-dl 下载失败: {str(e)}"
            
            return {
                "success": False,
                "error": error_msg
            }
    
    async def _monitor_gallery_dl_progress(self, download_path: Path, before_files: set, message_updater):
        """监控 gallery-dl 下载进度"""
        try:
            last_count = 0
            last_update_time = time.time()
            update_interval = 3  # 每3秒更新一次进度
            
            logger.info(f"📊 开始监控 gallery-dl 进度")
            logger.info(f"📊 监控目录: {download_path}")
            logger.info(f"📊 下载前文件数量: {len(before_files)}")
            if before_files:
                logger.info(f"📊 下载前文件示例: {list(before_files)[:3]}")
            
            while True:
                await asyncio.sleep(2)  # 每2秒检查一次
                
                # 计算当前文件数量
                current_files = set()
                if download_path.exists():
                    for file_path in download_path.rglob("*"):
                        if file_path.is_file():
                            relative_path = str(file_path.relative_to(download_path))
                            current_files.add(relative_path)
                
                # 计算新文件数量
                new_files = current_files - before_files
                current_count = len(new_files)
                
                logger.info(f"📊 当前文件数量: {len(current_files)}, 新文件数量: {current_count}")
                if new_files:
                    logger.info(f"📊 新文件示例: {list(new_files)[:3]}")
                
                # 如果文件数量有变化或时间间隔到了，更新进度
                if current_count != last_count or time.time() - last_update_time > update_interval:
                    last_count = current_count
                    last_update_time = time.time()
                    
                    # 获取当前正在下载的文件路径
                    current_file_path = "准备中..."
                    if new_files:
                        # 获取最新的文件
                        latest_file = sorted(new_files)[-1]
                        # 显示完整的相对路径
                        current_file_path = latest_file
                    
                    progress_text = (
                        f"🖼️ **图片下载中**\n"
                        f"📝 当前下载：`{current_file_path}`\n"
                        f"🖼️ 已完成：{current_count} 张"
                    )
                    
                    try:
                        # 检查message_updater是否为None
                        if message_updater is None:
                            logger.warning(f"⚠️ message_updater为None，跳过进度更新")
                            continue
                        
                        # 检查message_updater的类型并安全调用
                        if asyncio.iscoroutinefunction(message_updater):
                            await message_updater(progress_text)
                        else:
                            message_updater(progress_text)
                        logger.info(f"📊 gallery-dl 进度更新: {current_count} 张图片, 当前文件: {current_file_path}")
                    except Exception as e:
                        logger.warning(f"⚠️ 更新进度消息失败: {e}")
                        # 不退出循环，继续监控
                        continue
                
        except asyncio.CancelledError:
            logger.info("📊 进度监控任务已取消")
        except Exception as e:
            logger.error(f"❌ 进度监控任务错误: {e}")

    async def download_x_content(self, url: str, message: types.Message) -> dict:
        """下载 X 内容（图片或视频）"""
        logger.info(f"🚀 开始下载 X 内容: {url}")
        
        # 检测内容类型
        content_type = self._detect_x_content_type(url)
        logger.info(f"📊 检测到内容类型: {content_type}")
        
        if content_type == "video":
            # 视频使用 yt-dlp 下载
            logger.info("🎬 使用 yt-dlp 下载 X 视频")
            
            # 创建 message_updater 函数
            async def message_updater(text_or_dict):
                try:
                    if isinstance(text_or_dict, dict):
                        await message.reply(str(text_or_dict))
                    else:
                        await message.reply(text_or_dict)
                except Exception as e:
                    logger.warning(f"⚠️ 更新进度消息失败: {e}")
            
            return await self._download_x_video_with_ytdlp(url, message_updater)
        else:
            # 图片使用 gallery-dl 下载
            logger.info("📸 使用 gallery-dl 下载 X 图片")
            return await self._download_x_image_with_gallerydl(url, message)

    async def _download_x_video_with_ytdlp(self, url: str, message_updater=None) -> dict:
        """使用 yt-dlp 下载 X 视频"""
        return await self._download_with_ytdlp_unified(
            url=url,
            download_path=self.x_download_path,
            message_updater=message_updater,
            platform_name="X",
            content_type="video",
            format_spec="best[height<=1080]",
            cookies_path=self.x_cookies_path
        )



    async def _download_x_playlist(self, url: str, download_path: Path, message_updater=None, playlist_info: dict = None) -> Dict[str, Any]:
        """下载X播放列表中的所有视频"""
        import os
        import time
        from pathlib import Path
        import asyncio
        
        logger.info(f"🎬 开始下载X播放列表: {url}")
        logger.info(f"📊 播放列表信息: {playlist_info}")
        
        if not playlist_info:
            return {'success': False, 'error': '播放列表信息为空'}
        
        total_videos = playlist_info.get('total_videos', 0)
        if total_videos == 0:
            return {'success': False, 'error': '播放列表中没有视频'}
        
        # 记录下载开始时间
        download_start_time = time.time()
        logger.info(f"⏰ 下载开始时间: {download_start_time}")
        
        # 创建进度跟踪
        progress_data = {
            'current': 0,
            'total': total_videos,
            'start_time': download_start_time,
            'downloaded_files': []
        }
        
        # 记录下载开始时间
        download_start_time = time.time()
        logger.info(f"⏰ 下载开始时间: {download_start_time}")
        
        def create_playlist_progress_callback(progress_data):
            def escape_num(text):
                # 只转义MarkdownV2特殊字符，不转义小数点
                special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
                for char in special_chars:
                    text = text.replace(char, f'\\{char}')
                return text
            
            def calculate_overall_progress():
                if progress_data['total'] == 0:
                    return 0
                return (progress_data['current'] / progress_data['total']) * 100
            
            def progress_callback(d):
                try:
                    current = progress_data['current']
                    total = progress_data['total']
                    overall_percent = calculate_overall_progress()
                    
                    if d.get('status') == 'finished':
                        progress_data['current'] += 1
                        current = progress_data['current']
                        overall_percent = calculate_overall_progress()

                        # 记录下载的文件并监控合并状态
                        if 'filename' in d:
                            filename = d['filename']
                            progress_data['downloaded_files'].append(filename)

                            # 监控文件合并状态
                            if filename.endswith('.part'):
                                logger.warning(f"⚠️ 文件合并可能失败: {filename}")
                            else:
                                logger.info(f"✅ 文件下载并合并成功: {filename}")
                    
                    # 创建进度消息
                    progress_bar = self._make_progress_bar(overall_percent)
                    elapsed_time = time.time() - progress_data['start_time']
                    
                    status_text = f"🎬 X播放列表下载进度\n"
                    status_text += f"📊 总体进度: {progress_bar} {overall_percent:.1f}%\n"
                    status_text += f"📹 当前: {current}/{total} 个视频\n"
                    status_text += f"⏱️ 已用时: {elapsed_time:.0f}秒\n"
                    
                    if d.get('status') == 'downloading':
                        if '_percent_str' in d:
                            status_text += f"📥 当前视频: {d.get('_percent_str', '0%')}\n"
                        if '_speed_str' in d:
                            status_text += f"🚀 速度: {d.get('_speed_str', 'N/A')}\n"
                    
                    # 转义Markdown特殊字符
                    escaped_text = escape_num(status_text)
                    
                    # 使用asyncio.run_coroutine_threadsafe来更新进度
                    try:
                        if message_updater:
                            # 检查message_updater的类型
                            if asyncio.iscoroutinefunction(message_updater):
                                # 安全地获取事件循环
                                try:
                                    loop = asyncio.get_running_loop()
                                except RuntimeError:
                                    try:
                                        loop = asyncio.get_event_loop()
                                    except RuntimeError:
                                        loop = asyncio.new_event_loop()
                                        asyncio.set_event_loop(loop)
                                
                                # 调用异步函数并获取协程对象
                                coro = message_updater(escaped_text)
                                asyncio.run_coroutine_threadsafe(coro, loop)
                            else:
                                # 如果是同步函数，直接调用
                                message_updater(escaped_text)
                    except Exception as e:
                        if "Message is not modified" not in str(e):
                            logger.warning(f"⚠️ 更新播放列表进度失败: {e}")
                        # 如果message_updater失败，记录日志
                        logger.info(f"进度更新: {escaped_text}")
                        
                except Exception as e:
                    logger.warning(f"⚠️ 更新播放列表进度失败: {e}")
            
            return progress_callback
        
        try:
            # 使用增强的yt-dlp配置下载整个播放列表
            base_opts = {
                'outtmpl': str(download_path / '%(title)s.%(ext)s'),
                'format': 'best[height<=1080]',
                'progress_hooks': [create_playlist_progress_callback(progress_data)],
            }

            # 获取增强配置，避免PART文件
            ydl_opts = self._get_enhanced_ydl_opts(base_opts)
            logger.info("🛡️ 使用增强配置，避免PART文件产生")

            # 下载播放列表
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).download([url]))

                # 下载完成后检查并处理PART文件
                logger.info("🔍 检查下载完成状态...")
                resume_success = self._resume_failed_downloads(download_path, url, max_retries=2)

                if not resume_success:
                    logger.warning("⚠️ 部分文件下载未完成，但已达到最大重试次数")
                else:
                    logger.info("✅ 所有文件下载完成")

            except Exception as e:
                logger.error(f"❌ 下载过程中出现错误: {e}")
                # 即使出错也尝试断点续传PART文件
                logger.info("🔄 尝试断点续传未完成的文件...")
                self._resume_part_files(download_path, url)
            
            await asyncio.sleep(1)
            
            # 使用progress_data中记录的文件列表来检测下载的文件
            video_files = []
            downloaded_files = progress_data.get('downloaded_files', [])
            logger.info(f"📊 progress_data中记录的文件: {downloaded_files}")
            
            # 首先尝试使用progress_data中记录的文件
            if downloaded_files:
                for filename in downloaded_files:
                    file_path = download_path / filename
                    if file_path.exists():
                        video_files.append((file_path, os.path.getmtime(file_path)))
                        logger.info(f"✅ 找到本次下载文件: {filename}")
                    else:
                        logger.warning(f"⚠️ 文件不存在: {filename}")
            
            # 如果progress_data中没有记录，则使用时间检测
            if not video_files:
                logger.info("🔄 使用时间检测方法查找下载文件")
                for file in download_path.glob("*.mp4"):
                    try:
                        mtime = os.path.getmtime(file)
                        # 如果文件修改时间在下载开始时间之后，认为是本次下载的文件
                        if mtime >= download_start_time:
                            video_files.append((file, mtime))
                            logger.info(f"✅ 找到本次下载文件: {file.name}, 修改时间: {mtime}")
                    except OSError:
                        continue
            
            video_files.sort(key=lambda x: x[0].name)

            # 检测PART文件
            part_files = self._detect_part_files(download_path)
            success_count = len(video_files)
            part_count = len(part_files)

            # 在日志中显示详细统计
            logger.info(f"📊 下载完成统计：")
            logger.info(f"✅ 成功文件：{success_count} 个")
            if part_count > 0:
                logger.warning(f"⚠️ 未完成文件：{part_count} 个")
                self._log_part_files_details(part_files)
            else:
                logger.info("✅ 未发现PART文件，所有下载都已完成")

            if video_files:
                total_size_mb = 0
                file_info_list = []
                all_resolutions = set()
                
                for file_path, mtime in video_files:
                    size_mb = os.path.getsize(file_path) / (1024 * 1024)
                    total_size_mb += size_mb
                    media_info = self.get_media_info(str(file_path))
                    resolution = media_info.get('resolution', '未知')
                    if resolution != '未知':
                        all_resolutions.add(resolution)
                    file_info_list.append({
                        'filename': os.path.basename(file_path),
                        'size_mb': size_mb,
                        'resolution': resolution,
                        'abr': media_info.get('bit_rate')
                    })
                
                filename_list = [info['filename'] for info in file_info_list]
                filename_display = '\n'.join([f"  {i+1:02d}. {name}" for i, name in enumerate(filename_list)])
                resolution_display = ', '.join(sorted(all_resolutions)) if all_resolutions else '未知'
                
                return {
                    'success': True,
                    'is_playlist': True,
                    'file_count': len(video_files),
                    'total_size_mb': total_size_mb,
                    'files': file_info_list,
                    'platform': 'X',
                    'download_path': str(download_path),
                    'filename': filename_display,
                    'size_mb': total_size_mb,
                    'resolution': resolution_display,
                    'episode_count': len(video_files),
                    # 添加PART文件统计信息
                    'success_count': success_count,
                    'part_count': part_count,
                    'part_files': [str(pf) for pf in part_files] if part_files else []
                }
            else:
                return {'success': False, 'error': 'X播放列表下载完成但未找到本次下载的文件'}
                
        except Exception as e:
            logger.error(f"❌ X播放列表下载失败: {e}")
            return {"success": False, "error": str(e)}
        finally:
            # 记录下载完成时间
            download_end_time = time.time()
            total_time = download_end_time - download_start_time
            logger.info(f"⏰ 下载完成时间: {download_end_time}, 总用时: {total_time:.1f}秒")

    async def _download_x_image_with_gallerydl(self, url: str, message: types.Message) -> dict:
        """使用 gallery-dl 下载 X 图片，遇到NSFW错误时fallback到yt-dlp"""
        try:
            # 创建 message_updater 函数
            async def message_updater(text_or_dict):
                try:
                    if isinstance(text_or_dict, dict):
                        await message.reply(str(text_or_dict))
                    else:
                        await message.reply(text_or_dict)
                except Exception as e:
                    logger.warning(f"⚠️ 更新进度消息失败: {e}")
            
            # 使用现有的 download_with_gallery_dl 函数，传递 message_updater
            download_path = self.x_download_path
            result = await self.download_with_gallery_dl(url, download_path, message_updater)
            
            if result.get("success"):
                return {
                    "success": True,
                    "platform": "X",
                    "content_type": "image",
                    "download_path": result.get("download_path", ""),
                    "full_path": result.get("full_path", ""),
                    "filename": result.get("filename", ""),
                    "size_mb": result.get("size_mb", 0),
                    "title": f"X图片 ({result.get('files_count', 0)}张)",
                    "resolution": "图片",  # 添加 resolution 字段，确保识别为图片
                    "files_count": result.get("files_count", 0),
                    "file_formats": result.get("file_formats", []),
                }
            else:
                # 检查是否为NSFW错误，如果是则返回错误信息
                error_msg = result.get("error", "")
                if "NSFW" in error_msg or "AuthorizationError" in error_msg:
                    logger.info("🔄 检测到NSFW错误，gallery-dl无法下载此内容")
                    return {
                        "success": False,
                        "error": "此内容包含NSFW内容，无法下载",
                        "platform": "X",
                        "content_type": "image"
                    }
                else:
                    return result
                    
        except Exception as e:
            logger.error(f"❌ gallery-dl 下载 X 图片失败: {e}")
            return {
                "success": False,
                "error": f"gallery-dl 下载失败: {str(e)}",
                "platform": "X",
                "content_type": "image"
            }



    async def _download_xiaohongshu_with_playwright(self, url: str, message: types.Message, message_updater=None) -> dict:
        """使用 Playwright 下载小红书视频"""
        # 自动提取小红书链接
        real_url = extract_xiaohongshu_url(url)
        if real_url:
            url = real_url
        else:
            logger.warning('未检测到小红书链接，原样使用参数')
        if not PLAYWRIGHT_AVAILABLE:
            return {
                "success": False,
                "error": "Playwright 未安装，无法下载小红书视频",
                "platform": "Xiaohongshu",
                "content_type": "video"
            }
        
        try:
            from playwright.async_api import async_playwright
            import httpx
            from dataclasses import dataclass
            from typing import Optional
            from enum import Enum
            import re
            import time
            
            # 数据类定义
            @dataclass
            class VideoInfo:
                video_id: str
                platform: str
                share_url: str
                download_url: Optional[str] = None
                title: Optional[str] = None
                author: Optional[str] = None
                create_time: Optional[str] = None
                quality: Optional[str] = None
                thumbnail_url: Optional[str] = None
            
            # 使用类级别的 Platform 枚举
            
            # 检测平台
            def detect_platform(url: str) -> VideoDownloader.Platform:
                if any(domain in url.lower() for domain in ['douyin.com', 'iesdouyin.com']):
                    return VideoDownloader.Platform.DOUYIN
                elif any(domain in url.lower() for domain in ['kuaishou.com']):
                    return VideoDownloader.Platform.KUAISHOU
                elif any(domain in url.lower() for domain in ['xiaohongshu.com', 'xhslink.com']):
                    return VideoDownloader.Platform.XIAOHONGSHU
                else:
                    return VideoDownloader.Platform.UNKNOWN
            
            platform = VideoDownloader.Platform.XIAOHONGSHU
            
            # 发送开始下载消息（如果bot可用）
            start_message = None
            if hasattr(self, 'bot') and self.bot:
                try:
                    start_message = await self.bot.send_message(
                        message.chat.id,
                        f"🎬 开始下载{platform.value}视频..."
                    )
                except Exception as e:
                    logger.warning(f"⚠️ 发送开始消息失败: {e}")
            else:
                logger.info(f"🎬 开始下载{platform.value}视频...")
            
            # 小红书下载目录
            download_dir = str(self.xiaohongshu_download_path)
            
            os.makedirs(download_dir, exist_ok=True)
            
            # 使用 Playwright 提取视频信息
            async with async_playwright() as p:
                # 小红书不需要 cookies
                
                # 小红书浏览器配置 - 参考douyin.py
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080},
                    device_scale_factor=1,
                    locale='zh-CN',
                    timezone_id='Asia/Shanghai',
                    is_mobile=False,
                    has_touch=False,
                    color_scheme='light',
                    extra_http_headers={
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,video/mp4,*/*;q=0.8',
                        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                    }
                )
                
                # 小红书不需要 cookies
                
                page = await context.new_page()
                
                # 设置平台特定的请求头
                await self._set_platform_headers(page, platform)
                
                # 监听网络请求，捕获小红书视频URL
                video_url_holder = {'url': None}
                def handle_request(request):
                    req_url = request.url
                    if any(ext in req_url.lower() for ext in ['.mp4', '.m3u8']):
                        if 'xhscdn.com' in req_url or 'xiaohongshu.com' in req_url:
                            # 只保存第一个捕获到的视频URL，避免被后续请求覆盖
                            if not video_url_holder['url']:
                                video_url_holder['url'] = req_url
                                logger.info(f"[cat-catch] 嗅探到小红书视频流: {req_url}")
                page.on("request", handle_request)
                
                # 访问页面 - 参考douyin.py的实现
                logger.info("[extract] goto 前")
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                logger.info("[extract] goto 后，开始极速嗅探")

                # 极速嗅探：只监听network，不做任何交互 - 参考douyin.py
                for _ in range(5):  # 1.5秒内监听
                    if video_url_holder['url']:
                        logger.info(f"[cat-catch][fast] 极速嗅探到小红书视频流: {video_url_holder['url']}")
                        # 立即获取标题和作者，参考douyin.py
                        title = await self._get_video_title(page, platform)
                        author = await self._get_video_author(page, platform)
                        # 直接返回结果，不继续后续逻辑
                        video_info = VideoInfo(
                            video_id=str(int(time.time())),
                            platform=platform.value,
                            share_url=url,
                            download_url=video_url_holder['url'],
                            title=title,
                            author=author
                        )
                        logger.info("[cat-catch][fast] 极速嗅探流程完成")
                        # 关闭浏览器
                        await page.close()
                        await context.close()
                        await browser.close()
                        
                        # 下载视频
                        return await self._download_video_file(video_info, download_dir, message_updater, start_message)
                    await asyncio.sleep(0.3)
                # 兜底：未捕获到流，直接进入正则/其它逻辑（不再做自动交互）
                
                # 检查是否捕获到视频URL
                if not video_url_holder['url']:
                    logger.warning(f"⚠️ 网络嗅探未捕获到小红书视频流")
                else:
                    logger.info(f"✅ 网络嗅探成功捕获到小红书视频流: {video_url_holder['url']}")
                
                # 如果网络嗅探失败，尝试从页面提取
                if not video_url_holder['url']:
                    html = await page.content()
                    logger.info(f"🔍 开始从HTML提取小红书视频直链...")
                    
                    # 小红书HTML正则提取 - 参考douyin.py的简化模式
                    patterns = [
                        r'(https://sns-[^"\']+\.xhscdn\.com/stream/[^"\']+\.mp4)',
                        r'(https://ci[^"\']+\.xhscdn\.com/[^"\']+\.mp4)',
                        r'(https://[^"\']+\.xhscdn\.com/[^"\']+\.mp4)',
                        r'"videoUrl":"(https://[^"\\]+)"',
                        r'"video_url":"(https://[^"\\]+)"',
                        r'"url":"(https://[^"\\]+\.mp4)"'
                    ]
                    
                    # 直接使用HTML正则提取 - 参考douyin.py的简单方法
                    for i, pattern in enumerate(patterns):
                        m = re.search(pattern, html)
                        if m:
                            url = m.group(1).replace('\\u002F', '/').replace('\\u0026', '&')
                            # 验证URL是否有效，并且网络嗅探没有捕获到URL时才使用
                            if self._is_valid_xiaohongshu_url(url) and not video_url_holder['url']:
                                video_url_holder['url'] = url
                                logger.info(f"✅ 使用模式{i+1}提取到小红书视频URL: {url}")
                                break
                            elif self._is_valid_xiaohongshu_url(url) and video_url_holder['url']:
                                logger.info(f"⚠️ 网络嗅探已捕获到URL，跳过HTML提取的URL: {url}")
                                break
                
                # 如果HTML提取成功，获取标题和作者
                title = None
                author = None
                if video_url_holder['url']:
                    try:
                        title = await self._get_video_title(page, platform)
                        author = await self._get_video_author(page, platform)
                        logger.info(f"📝 获取到标题: {title}")
                        logger.info(f"👤 获取到作者: {author}")
                    except Exception as e:
                        logger.warning(f"⚠️ 获取标题和作者失败: {e}")
                
                # 关闭浏览器
                await page.close()
                await context.close()
                await browser.close()
                
                if not video_url_holder['url']:
                    # 如果仍然没有获取到视频URL，保存调试信息
                    debug_html_path = f"/tmp/xiaohongshu_debug_{int(time.time())}.html"
                    try:
                        with open(debug_html_path, 'w', encoding='utf-8') as f:
                            f.write(html)
                        logger.error(f"❌ 无法提取小红书视频直链，已保存调试HTML到: {debug_html_path}")
                    except Exception as e:
                        logger.error(f"❌ 无法提取小红书视频直链，保存调试文件失败: {e}")
                    
                    raise Exception(f"无法提取小红书视频直链，请检查链接有效性")
                
                # 创建VideoInfo对象
                video_info = VideoInfo(
                    video_id=str(int(time.time())),
                    platform=platform.value,
                    share_url=url,
                    download_url=video_url_holder['url'],
                    title=title,
                    author=author
                )
                
                # 使用统一的下载方法
                result = await self._download_video_file(video_info, download_dir, message_updater, start_message)
                
                if not result.get("success"):
                    raise Exception(result.get("error", "下载失败"))
                
                # 删除开始消息（如果存在）
                if start_message and hasattr(self, 'bot') and self.bot:
                    try:
                        await start_message.delete()
                    except Exception as e:
                        logger.warning(f"⚠️ 删除开始消息失败: {e}")
                
                # 文件信息现在在 _download_video_file 方法中处理
                logger.info(f"✅ {platform.value}视频下载成功")
                
                # 返回下载结果
                return result
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Playwright 下载小红书视频失败: {error_msg}")
            
            # 删除开始消息（如果存在）
            if 'start_message' in locals() and start_message and hasattr(self, 'bot') and self.bot:
                try:
                    await self.bot.delete_message(message.chat.id, start_message.message_id)
                except Exception as del_e:
                    logger.warning(f"⚠️ 删除开始消息失败: {del_e}")
            
            return {
                "success": False,
                "error": f"Playwright 下载失败: {error_msg}",
                "platform": "Xiaohongshu",
                "content_type": "video"
            }
    
    async def _extract_douyin_url_from_html(self, html: str) -> Optional[str]:
        """从抖音HTML源码中提取视频直链 - 使用简单有效的逻辑"""
        try:
            logger.info(f"[extract] HTML长度: {len(html)} 字符")
            
            # 查找包含视频数据的script标签
            script_matches = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
            
            for script_content in script_matches:
                if 'aweme_id' in script_content and 'status_code' in script_content:
                    # 尝试提取JSON部分
                    json_matches = re.findall(r'({.*?"errors":\s*null\s*})', script_content, re.DOTALL)
                    for json_str in json_matches:
                        try:
                            # 清理JSON
                            brace_count = 0
                            json_end = -1
                            for i, char in enumerate(json_str):
                                if char == '{':
                                    brace_count += 1
                                elif char == '}':
                                    brace_count -= 1
                                    if brace_count == 0:
                                        json_end = i + 1
                                        break
                            
                            if json_end > 0:
                                clean_json = json_str[:json_end]
                                data = json.loads(clean_json)
                                
                                # 专门查找video字段中的无水印视频URL
                                def find_video_url(obj):
                                    if isinstance(obj, dict):
                                        for key, value in obj.items():
                                            # 专门查找video字段
                                            if key == "video" and isinstance(value, dict):
                                                logger.info(f"[extract] 找到video字段: {list(value.keys())}")
                                                
                                                # 优先查找play_url字段（无水印）
                                                if "play_url" in value:
                                                    play_url = value["play_url"]
                                                    logger.info(f"[extract] play_url字段内容: {play_url}")
                                                    logger.info(f"[extract] play_url类型: {type(play_url)}")
                                                    # 处理play_url字典格式
                                                    if isinstance(play_url, dict) and "url_list" in play_url:
                                                        url_list = play_url["url_list"]
                                                        if isinstance(url_list, list) and url_list:
                                                            video_url = url_list[0]
                                                            if video_url.startswith("http"):
                                                                logger.info(f"[extract] 从play_url.url_list找到无水印视频URL: {video_url}")
                                                                return video_url
                                                    # 处理play_url字符串格式
                                                    elif isinstance(play_url, str) and play_url.startswith("http"):
                                                        if any(ext in play_url.lower() for ext in [".mp4", ".m3u8", ".ts", "douyinvod.com", "snssdk.com"]):
                                                            logger.info(f"[extract] 找到无水印视频URL: {play_url}")
                                                            return play_url
                                                
                                                # 兜底：如果没有play_url，再查找play_addr字段（有水印）
                                                if "play_addr" in value:
                                                    play_addr = value["play_addr"]
                                                    logger.info(f"[extract] play_addr字段内容: {play_addr}")
                                                    logger.info(f"[extract] play_addr类型: {type(play_addr)}")
                                                    # 处理play_addr字典格式
                                                    if isinstance(play_addr, dict) and "url_list" in play_addr:
                                                        url_list = play_addr["url_list"]
                                                        if isinstance(url_list, list) and url_list:
                                                            video_url = url_list[0]
                                                            if video_url.startswith("http"):
                                                                logger.info(f"[extract] 从play_addr.url_list找到有水印视频URL: {video_url}")
                                                                return video_url
                                                    # 查找playAddr
                                                    if isinstance(play_addr, list) and play_addr:
                                                        video_url = play_addr[0]
                                                        if video_url.startswith("http") and any(ext in video_url.lower() for ext in [".mp4", ".m3u8", ".ts", "douyinvod.com", "snssdk.com"]):
                                                            logger.info(f"[extract] 找到有水印视频URL: {video_url}")
                                                            return video_url
                                                    elif isinstance(play_addr, str) and play_addr.startswith("http"):
                                                        if any(ext in play_addr.lower() for ext in [".mp4", ".m3u8", ".ts", "douyinvod.com", "snssdk.com"]):
                                                            logger.info(f"[extract] 找到有水印视频URL: {play_addr}")
                                                            return play_addr
                                            elif isinstance(value, (dict, list)):
                                                result = find_video_url(value)
                                                if result:
                                                    return result
                                    elif isinstance(obj, list):
                                        for item in obj:
                                            result = find_video_url(item)
                                            if result:
                                                return result
                                    return None
                                
                                video_url = find_video_url(data)
                                if video_url:
                                    return video_url
                                    
                        except json.JSONDecodeError:
                            continue
            
            return None
            
        except Exception as e:
            logger.warning(f"抖音HTML正则提取失败: {str(e)}")
        return None

    async def _get_douyin_no_watermark_url(self, video_id: str) -> str:
        """通过抖音官方接口获取无水印视频直链"""
        try:
            # 抖音官方API列表
            apis = [
                f'https://aweme.snssdk.com/aweme/v1/play/?video_id={video_id}&ratio=1080p&line=1',
                f'https://aweme.snssdk.com/aweme/v1/play/?video_id={video_id}&ratio=720p&line=0',
                f'https://aweme.snssdk.com/aweme/v1/play/?video_id={video_id}&ratio=540p&line=2',
                f'https://aweme.snssdk.com/aweme/v1/play/?video_id={video_id}&ratio=1080p&line=0',
                f'https://aweme.snssdk.com/aweme/v1/play/?video_id={video_id}&ratio=720p&line=1',
            ]
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
                'Accept': '*/*',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Referer': 'https://www.douyin.com/',
                'Connection': 'keep-alive',
                'Range': 'bytes=0-1',  # 只请求开头1个字节，验证可访问性
            }

            async def validate_url(api_url: str) -> Optional[str]:
                """验证单个API URL的可用性，检查content-length"""
                try:
                    async with httpx.AsyncClient(follow_redirects=True, timeout=5.0) as client:
                        # 先用 HEAD 请求快速验证
                        try:
                            head_resp = await client.head(
                                api_url,
                                headers=headers,
                                timeout=3.0
                            )
                            if head_resp.status_code in [200, 206]:
                                # 检查content-length，如果为0则认为API失效
                                content_length = int(head_resp.headers.get("content-length", 0))
                                if content_length > 0:
                                    logger.info(f"[douyin_api] HEAD请求成功: {api_url} (大小: {content_length})")
                                    return api_url
                                else:
                                    logger.warning(f"[douyin_api] HEAD请求成功但content-length为0: {api_url}")
                                    return None
                        except Exception:
                            pass  # HEAD 失败就用 GET 试试

                        # HEAD 失败的话用 GET 请求重试
                        resp = await client.get(
                            api_url,
                            headers=headers,
                            timeout=3.0
                        )
                        if resp.status_code in [200, 206]:
                            content_length = int(resp.headers.get("content-length", 0))
                            if content_length > 0:
                                logger.info(f"[douyin_api] GET请求成功: {api_url} (大小: {content_length})")
                                return api_url
                            else:
                                logger.warning(f"[douyin_api] GET请求成功但content-length为0: {api_url}")
                                return None
                        
                except Exception as e:
                    logger.warning(f"[douyin_api] 验证失败: {api_url} - {str(e)}")
                return None

            # 最多重试2次
            for attempt in range(2):
                try:
                    logger.info(f"[douyin_api] 第{attempt + 1}次尝试验证API")
                    # 并发验证所有API
                    tasks = [validate_url(api) for api in apis]
                    results = await asyncio.gather(*tasks)
                    
                    # 返回第一个可用的URL
                    for url in results:
                        if url:
                            logger.info(f"[douyin_api] 找到可用API: {url}")
                            return url
                            
                    logger.warning(f"[douyin_api] 第{attempt + 1}次尝试所有API都返回0字节")
                    if attempt < 1:  # 如果不是最后一次重试
                        await asyncio.sleep(1)  # 等待1秒后重试
                        
                except Exception as e:
                    logger.error(f"[douyin_api] 第{attempt + 1}次尝试发生错误: {str(e)}")
                    if attempt < 1:
                        await asyncio.sleep(1)
                        
            logger.warning("[douyin_api] 所有API都返回0字节，API可能已失效")
            return None
            
        except Exception as e:
            logger.error(f"[douyin_api] 获取无水印直链异常: {str(e)}")
            return None
    
    async def _get_video_title(self, page, platform: 'VideoDownloader.Platform') -> str:
        """获取视频标题 - 针对不同平台优化"""
        try:
            # 快手特殊处理
            if platform == VideoDownloader.Platform.KUAISHOU:
                return await self._get_kuaishou_video_title(page)

            # 其他平台使用通用方法
            page_title = await page.title()
            if page_title and page_title.strip():
                logger.info(f"📝 通过<title>标签获取标题成功")
                logger.info(f"📝 原始<title> repr: {repr(page_title)}")
                clean_title = page_title.strip()
                return re.sub(r'[<>:"/\\|?*]', '_', clean_title)[:100]
        except Exception as e:
            logger.warning(f"获取标题失败: {str(e)}")
        return None

    async def _get_kuaishou_video_title(self, page) -> str:
        """专门获取快手视频标题"""
        try:
            # 方法1: 尝试从页面的JSON数据中提取标题
            html = await page.content()

            # 查找包含视频信息的script标签
            script_matches = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
            for script_content in script_matches:
                if 'caption' in script_content or 'title' in script_content:
                    # 尝试提取JSON中的标题字段
                    title_patterns = [
                        r'"caption":"([^"]+)"',
                        r'"title":"([^"]+)"',
                        r'"content":"([^"]+)"',
                        r'"text":"([^"]+)"',
                        r'"description":"([^"]+)"'
                    ]

                    for pattern in title_patterns:
                        matches = re.findall(pattern, script_content)
                        for match in matches:
                            # 清理和验证标题
                            title = match.replace('\\u002F', '/').replace('\\u0026', '&').replace('\\n', ' ').replace('\\', '')
                            title = title.strip()
                            # 过滤掉明显不是标题的内容
                            if (len(title) > 5 and len(title) < 200 and
                                not title.startswith('http') and
                                not all(c.isdigit() or c in '.-_' for c in title) and
                                '快手' not in title and 'kuaishou' not in title.lower()):
                                logger.info(f"📝 从JSON提取到快手标题: {title}")
                                return re.sub(r'[<>:"/\\|?*]', '_', title)[:100]

            # 方法2: 尝试从页面元素中提取标题
            title_selectors = [
                '.video-info-title',
                '.content-text',
                '.video-title',
                '.caption',
                '[data-testid="video-title"]',
                '.description',
                'h1', 'h2', 'h3'
            ]

            for selector in title_selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    for element in elements:
                        text = await element.text_content()
                        if text and len(text.strip()) > 5 and len(text.strip()) < 200:
                            title = text.strip()
                            if (not title.startswith('http') and
                                not all(c.isdigit() or c in '.-_' for c in title)):
                                logger.info(f"📝 从元素{selector}提取到快手标题: {title}")
                                return re.sub(r'[<>:"/\\|?*]', '_', title)[:100]
                except:
                    continue

            # 方法3: 从页面title中提取，去除快手相关后缀
            page_title = await page.title()
            if page_title and page_title.strip():
                title = page_title.strip()
                # 去除快手相关的后缀
                title = re.sub(r'[-_\s]*快手[-_\s]*', '', title)
                title = re.sub(r'[-_\s]*kuaishou[-_\s]*', '', title, flags=re.IGNORECASE)
                title = re.sub(r'[-_\s]*短视频[-_\s]*', '', title)
                title = title.strip()
                if len(title) > 3:
                    logger.info(f"📝 从页面title提取快手标题: {title}")
                    return re.sub(r'[<>:"/\\|?*]', '_', title)[:100]

            logger.warning("📝 未能提取到快手视频标题")
            return None

        except Exception as e:
            logger.warning(f"获取快手标题失败: {str(e)}")
            return None
    
    async def _get_video_author(self, page, platform: 'VideoDownloader.Platform') -> str:
        """获取视频作者"""
        try:
            # 快手特殊处理
            if platform == VideoDownloader.Platform.KUAISHOU:
                return await self._get_kuaishou_video_author(page)

            # 其他平台使用通用方法
            selectors = {
                VideoDownloader.Platform.DOUYIN: '[data-e2e="user-name"]',
                VideoDownloader.Platform.XIAOHONGSHU: '.user-name, .author, .nickname, [data-e2e="user-name"], .user-info .name',
            }

            selector = selectors.get(platform, '.author, .username')
            author_element = await page.query_selector(selector)

            if author_element:
                return await author_element.text_content()
        except Exception as e:
            logger.warning(f"获取作者失败: {str(e)}")
        return None

    async def _get_kuaishou_video_author(self, page) -> str:
        """专门获取快手视频作者"""
        try:
            # 方法1: 从页面的JSON数据中提取作者
            html = await page.content()

            # 查找包含用户信息的script标签
            script_matches = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
            for script_content in script_matches:
                if 'user' in script_content or 'author' in script_content:
                    # 尝试提取JSON中的作者字段
                    author_patterns = [
                        r'"userName":"([^"]+)"',
                        r'"user_name":"([^"]+)"',
                        r'"nickname":"([^"]+)"',
                        r'"name":"([^"]+)"',
                        r'"author":"([^"]+)"',
                        r'"performer":"([^"]+)"'
                    ]

                    for pattern in author_patterns:
                        matches = re.findall(pattern, script_content)
                        for match in matches:
                            # 清理和验证作者名
                            author = match.replace('\\u002F', '/').replace('\\u0026', '&').replace('\\', '')
                            author = author.strip()
                            # 过滤掉明显不是作者名的内容
                            if (len(author) > 1 and len(author) < 50 and
                                not author.startswith('http') and
                                not all(c.isdigit() or c in '.-_' for c in author) and
                                author not in ['null', 'undefined', 'true', 'false']):
                                logger.info(f"👤 从JSON提取到快手作者: {author}")
                                return re.sub(r'[<>:"/\\|?*]', '_', author)[:30]

            # 方法2: 从页面元素中提取作者
            author_selectors = [
                '.user-name',
                '.author-name',
                '.nickname',
                '.username',
                '.user-info .name',
                '.profile-name',
                '[data-testid="user-name"]',
                '.creator-name'
            ]

            for selector in author_selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    for element in elements:
                        text = await element.text_content()
                        if text and len(text.strip()) > 1 and len(text.strip()) < 50:
                            author = text.strip()
                            if (not author.startswith('http') and
                                not all(c.isdigit() or c in '.-_' for c in author)):
                                logger.info(f"👤 从元素{selector}提取到快手作者: {author}")
                                return re.sub(r'[<>:"/\\|?*]', '_', author)[:30]
                except:
                    continue

            logger.warning("👤 未能提取到快手视频作者")
            return None

        except Exception as e:
            logger.warning(f"获取快手作者失败: {str(e)}")
            return None
    
    def _is_valid_xiaohongshu_url(self, url: str) -> bool:
        """验证小红书视频URL是否有效"""
        if not url:
            return False
            
        url_lower = url.lower()
        
        # 检查是否是视频文件
        if not any(ext in url_lower for ext in ['.mp4', '.m3u8', '.ts', '.flv', '.webm']):
            return False
            
        # 检查是否是来自小红书的CDN
        if not any(cdn in url_lower for cdn in ['xhscdn.com', 'xiaohongshu.com']):
            return False
            
        # 排除一些无效的URL
        if any(x in url_lower for x in ['static', 'avatar', 'icon', 'logo', 'banner']):
            return False
            
        return True

    async def _set_platform_headers(self, page, platform: 'VideoDownloader.Platform'):
        """设置平台特定的请求头"""
        headers = {
            self.Platform.DOUYIN: {'Referer': 'https://www.douyin.com/'},
            self.Platform.KUAISHOU: {'Referer': 'https://www.kuaishou.com/'},
            self.Platform.XIAOHONGSHU: {'Referer': 'https://www.xiaohongshu.com/'},
        }
        
        if platform in headers:
            await page.set_extra_http_headers(headers[platform])
            logger.info(f"🎬 已设置 {platform.value} 平台请求头")

    async def _download_douyin_with_playwright(self, url: str, message: types.Message, message_updater=None) -> dict:
        """使用Playwright下载抖音视频 - 完全复制douyin.py的extract逻辑"""
        if not PLAYWRIGHT_AVAILABLE:
            return {
                "success": False,
                "error": "Playwright 未安装，无法下载抖音视频",
                "platform": "Douyin",
                "content_type": "video"
            }
        
        try:
            from playwright.async_api import async_playwright
            import httpx
            from dataclasses import dataclass
            from typing import Optional
            import re
            import time
            
            @dataclass
            class VideoInfo:
                video_id: str
                platform: str
                share_url: str
                download_url: Optional[str] = None
                title: Optional[str] = None
                author: Optional[str] = None
                create_time: Optional[str] = None
                quality: Optional[str] = None
                thumbnail_url: Optional[str] = None
            
            class Platform(str, Enum):
                DOUYIN = "douyin"
                XIAOHONGSHU = "xiaohongshu"
                UNKNOWN = "unknown"
            
            logger.info(f"🎬 开始下载抖音视频: {url}")
            
            total_start = time.time()
            platform = Platform.DOUYIN
            
            async with async_playwright() as p:
                # 按照douyin.py启动浏览器（无特殊参数）
                browser = await p.chromium.launch(headless=True)
                
                # 按照douyin.py的context配置（抖音用手机版）
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
                    viewport={'width': 375, 'height': 667},
                    device_scale_factor=2,
                    locale='zh-CN',
                    timezone_id='Asia/Shanghai',
                    is_mobile=True,
                    has_touch=True,
                    color_scheme='light',
                    extra_http_headers={
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,video/mp4,*/*;q=0.8',
                        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                    }
                )
                
                page = await context.new_page()
                
                # 尝试加载cookies（如果存在）
                if self.douyin_cookies_path and os.path.exists(self.douyin_cookies_path):
                    try:
                        cookies_dict = self._parse_douyin_cookies_file(self.douyin_cookies_path)
                        cookies = []
                        for name, value in cookies_dict.items():
                            cookies.append({
                                'name': name,
                                'value': value,
                                'domain': '.douyin.com',
                                'path': '/'
                            })
                        await context.add_cookies(cookies)
                        logger.info(f"[extract] 成功加载{len(cookies)}个cookies")
                    except Exception as e:
                        logger.warning(f"[extract] cookies加载失败: {e}")

                # 准备video_id监听
                video_id_holder = {'id': None}
                
                # 备用：监听网络请求中的video_id
                def handle_video_id(request):
                    request_url = request.url
                    if 'video_id=' in request_url:
                        m = re.search(r'video_id=([a-zA-Z0-9]+)', request_url)
                        if m:
                            video_id_holder['id'] = m.group(1)
                            logger.info(f"[extract] 网络请求中捕获到 video_id: {m.group(1)}")
                page.on("request", handle_video_id)

                try:
                    # 按照douyin.py设置headers
                    await self._set_platform_headers(page, platform)
                    
                    # 处理短链接重定向（关键修复）
                    if 'v.douyin.com' in url:
                        logger.info(f"[extract] 检测到短链接，先获取重定向: {url}")
                        response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        real_url = page.url
                        logger.info(f"[extract] 短链接重定向到: {real_url}")
                        
                        # 提取video_id并构造标准douyin.com链接
                        import re
                        video_id_match = re.search(r'/video/(\d+)', real_url)
                        if video_id_match:
                            video_id = video_id_match.group(1)
                            standard_url = f"https://www.douyin.com/video/{video_id}"
                            logger.info(f"[extract] 转换为标准链接: {standard_url}")
                            await page.goto(standard_url, wait_until="domcontentloaded", timeout=30000)
                            logger.info(f"[extract] 访问标准链接完成")
                        else:
                            # 如果提取不到video_id，直接用重定向的URL
                            if real_url != url:
                                await page.goto(real_url, wait_until="domcontentloaded", timeout=30000)
                                logger.info(f"[extract] 重新访问真实URL完成")
                    else:
                        logger.info("[extract] goto 前")
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        logger.info("[extract] goto 后，等待 video_id")
                    
                    # 调试：检查页面是否正确加载
                    page_title = await page.title()
                    current_url = page.url
                    logger.info(f"[debug] 页面标题: {repr(page_title)}")
                    logger.info(f"[debug] 当前URL: {current_url}")
                    
                    # 直接从URL提取video_id（最关键的修复）
                    video_id_match = re.search(r'/video/(\d+)', current_url)
                    if video_id_match:
                        video_id_holder['id'] = video_id_match.group(1)
                        logger.info(f"[extract] 从当前URL直接提取到 video_id: {video_id_holder['id']}")
                    else:
                        # 如果当前URL提取失败，从原始URL提取
                        video_id_match = re.search(r'/video/(\d+)', url)
                        if video_id_match:
                            video_id_holder['id'] = video_id_match.group(1)
                            logger.info(f"[extract] 从原始URL提取到 video_id: {video_id_holder['id']}")

                    # 按照douyin.py：抖音先等2秒
                    await asyncio.sleep(2)

                    # 按照douyin.py：等待video_id出现，最多等3秒
                    wait_start = time.time()
                    max_wait = 3  # 最多等3秒
                    while time.time() - wait_start < max_wait:
                        if video_id_holder['id']:
                            break
                        await asyncio.sleep(0.1)
                    logger.info(f"[extract] video_id 等待用时: {time.time() - wait_start:.2f}s")
                    
                    # 如果还没有video_id，最后一次尝试从URL提取
                    if not video_id_holder['id']:
                        logger.info("[extract] 网络监听未捕获到video_id，尝试从URL直接提取")
                        # 尝试从各种可能的URL格式中提取
                        for test_url in [current_url, url]:
                            video_id_match = re.search(r'/video/(\d+)', test_url)
                            if video_id_match:
                                video_id_holder['id'] = video_id_match.group(1)
                                logger.info(f"[extract] 从URL直接提取到 video_id: {video_id_holder['id']} (来源: {test_url})")
                                break

                    video_url = None
                    # 直接使用HTML提取方式（抖音官方API已失效）
                    logger.info("[extract] 进入HTML提取流程")
                    html = await page.content()
                    
                    # 根据平台选择不同的提取方法
                    if platform == Platform.DOUYIN:
                        video_url = await self._extract_douyin_url_from_html(html)
                    else:
                        # 通用提取方法
                        video_url = await self._extract_douyin_url_from_html(html)
                    
                    logger.info(f"[extract] 正则提取结果: {video_url}")
                    
                    if video_url:
                        # 如果是带水印的URL，尝试转换为无水印URL
                        if 'playwm' in video_url:
                            logger.info("[extract] 检测到带水印URL，尝试转换为无水印URL")
                            no_watermark_url = video_url.replace('playwm', 'play')
                            logger.info(f"[extract] 转换后的无水印URL: {no_watermark_url}")
                            video_url = no_watermark_url
                        # 验证URL有效性
                        is_valid = False
                        if platform == Platform.DOUYIN:
                            def is_valid_video_url(u):
                                u = u.lower()
                                # 抖音视频URL通常不包含文件扩展名，而是通过参数指定
                                # 检查是否是抖音的CDN域名
                                if any(domain in u for domain in ['aweme.snssdk.com', 'douyinvod.com', 'snssdk.com']):
                                    return True
                                # 检查是否包含视频相关参数
                                if any(param in u for param in ['video_id', 'play', 'aweme']):
                                    return True
                                # 排除一些无效的URL
                                if any(x in u for x in ['client.mp4', 'static', 'eden-cn', 'download/douyin_pc_client', 'douyin_pc_client.mp4']):
                                    return False
                                return True
                            is_valid = is_valid_video_url(video_url)
                        else:
                            # 通用验证
                            is_valid = any(ext in video_url.lower() for ext in ['.mp4', '.m3u8', '.ts', '.flv', '.webm'])
                        
                        if is_valid:
                            logger.info(f"[extract] 正则流程命中: {video_url}")
                            title = await self._get_video_title(page, platform)
                            author = await self._get_video_author(page, platform)
                            video_info = VideoInfo(
                                video_id=str(int(time.time())),
                                platform=platform,
                                share_url=url,
                                download_url=video_url,
                                title=title,
                                author=author,
                                thumbnail_url=None
                            )
                            logger.info("[extract] 正则流程完成")
                            
                            # 下载视频
                            download_result = await self._download_video_file(
                                video_info, 
                                str(self.douyin_download_path),
                                message_updater,
                                None
                            )
                            
                            await page.close()
                            await context.close()
                            await browser.close()
                            return download_result
                        else:
                            logger.warning(f"[extract] 提取的URL无效: {video_url}")
                            video_url = None

                    if not video_url:
                        logger.info("[extract] 所有流程均未捕获到视频数据，抛出 TimeoutError")
                        raise TimeoutError("未能捕获到视频数据")

                finally:
                    logger.info("[extract] 关闭 page/context 前")
                    await page.close()
                    await context.close()
                    logger.info("[extract] 关闭 page/context 后")
                    
                await browser.close()
                    
        except Exception as e:
            logger.error(f"抖音下载异常: {str(e)}")
            return {
                "success": False,
                "error": f"下载失败: {str(e)}",
                "platform": "Douyin",
                "content_type": "video"
            }

    async def _download_kuaishou_with_playwright(self, url: str, message, message_updater=None) -> dict:
        """使用Playwright下载快手视频 - 参考抖音实现"""
        if not PLAYWRIGHT_AVAILABLE:
            return {
                "success": False,
                "error": "Playwright 未安装，无法下载快手视频",
                "platform": "Kuaishou",
                "content_type": "video"
            }

        try:
            from playwright.async_api import async_playwright
            import httpx
            from dataclasses import dataclass
            from typing import Optional
            from enum import Enum
            import time
            import re

            @dataclass
            class VideoInfo:
                video_id: str
                title: str
                author: str
                download_url: str
                platform: str = "kuaishou"
                create_time: Optional[str] = None
                quality: Optional[str] = None
                thumbnail_url: Optional[str] = None

            class Platform(str, Enum):
                KUAISHOU = "kuaishou"
                DOUYIN = "douyin"
                XIAOHONGSHU = "xiaohongshu"
                UNKNOWN = "unknown"

            # 首先清理URL，提取纯链接
            clean_url = self._extract_clean_url_from_text(url)
            if not clean_url:
                return {
                    "success": False,
                    "error": "无法从文本中提取有效的快手链接",
                    "platform": "Kuaishou",
                    "content_type": "video"
                }

            logger.info(f"⚡ 开始下载快手视频: {clean_url}")
            if clean_url != url:
                logger.info(f"🔧 URL已清理: {url} -> {clean_url}")

            url = clean_url  # 使用清理后的URL

            total_start = time.time()
            platform = Platform.KUAISHOU

            async with async_playwright() as p:
                # 启动浏览器（参考抖音配置）
                browser = await p.chromium.launch(headless=True)

                # 快手使用手机版配置
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
                    viewport={'width': 375, 'height': 667},
                    device_scale_factor=2,
                    locale='zh-CN',
                    timezone_id='Asia/Shanghai',
                    permissions=['geolocation'],
                    geolocation={'latitude': 39.9042, 'longitude': 116.4074},
                    extra_http_headers={
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'DNT': '1',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                    }
                )

                page = await context.new_page()

                # 尝试加载cookies（如果存在）
                if self.kuaishou_cookies_path and os.path.exists(self.kuaishou_cookies_path):
                    try:
                        cookies_dict = self._parse_kuaishou_cookies_file(self.kuaishou_cookies_path)
                        cookies = []
                        for name, value in cookies_dict.items():
                            cookies.append({
                                'name': name,
                                'value': value,
                                'domain': '.kuaishou.com',
                                'path': '/'
                            })
                        await context.add_cookies(cookies)
                        logger.info(f"[extract] 成功加载{len(cookies)}个快手cookies")
                    except Exception as e:
                        logger.warning(f"[extract] 加载快手cookies失败: {e}")

                # 监听网络请求，捕获视频ID和视频URL
                video_id_holder = {'id': None}
                video_url_holder = {'url': None}

                def handle_video_id(request):
                    req_url = request.url
                    # 快手视频ID模式
                    m = re.search(r'photoId[=:]([a-zA-Z0-9_-]+)', req_url)
                    if m and not video_id_holder['id']:
                        video_id_holder['id'] = m.group(1)
                        logger.info(f"[extract] 网络请求中捕获到快手 photo_id: {m.group(1)}")

                    # 监听视频文件请求 - 改进过滤逻辑
                    if not video_url_holder['url']:
                        # 排除日志、统计、API等非视频请求
                        exclude_patterns = [
                            'log', 'collect', 'radar', 'stat', 'track', 'analytics',
                            'api', 'rest', 'sdk', 'report', 'beacon', 'ping'
                        ]

                        # 检查是否为视频文件请求
                        is_video_request = False
                        if '.mp4' in req_url and any(domain in req_url for domain in ['kwaicdn.com', 'ksapisrv.com', 'kuaishou.com']):
                            # 确保不是日志或API请求
                            if not any(pattern in req_url.lower() for pattern in exclude_patterns):
                                is_video_request = True

                        # 或者检查是否为快手CDN的视频流
                        elif any(domain in req_url for domain in ['kwaicdn.com']) and any(ext in req_url for ext in ['.mp4', '.m3u8', '.ts']):
                            if not any(pattern in req_url.lower() for pattern in exclude_patterns):
                                is_video_request = True

                        if is_video_request:
                            video_url_holder['url'] = req_url
                            logger.info(f"[extract] 网络请求中捕获到快手视频URL: {req_url}")
                        elif any(pattern in req_url.lower() for pattern in exclude_patterns):
                            logger.debug(f"[extract] 跳过非视频请求: {req_url}")

                page.on("request", handle_video_id)

                try:
                    # 设置快手平台headers
                    await self._set_platform_headers(page, platform)

                    # 访问页面
                    logger.info(f"[extract] 开始访问快手页面: {url}")
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    logger.info(f"[extract] 页面访问完成")

                    # 等待页面加载更长时间，让JavaScript执行
                    logger.info(f"[extract] 等待页面JavaScript执行...")
                    await asyncio.sleep(5)

                    # 尝试等待视频元素出现
                    try:
                        await page.wait_for_selector('video, [data-testid*="video"], .video-player', timeout=10000)
                        logger.info(f"[extract] 检测到视频元素")
                    except:
                        logger.warning(f"[extract] 未检测到视频元素，继续处理")

                    # 尝试一些页面交互来触发视频加载
                    try:
                        # 滚动页面
                        await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                        await asyncio.sleep(1)
                        await page.evaluate('window.scrollTo(0, 0)')
                        await asyncio.sleep(1)

                        # 尝试点击播放按钮（如果存在）
                        play_selectors = [
                            '.play-button', '.video-play', '[data-testid="play"]',
                            '.player-play', 'button[aria-label*="play"]', '.play-icon'
                        ]
                        for selector in play_selectors:
                            try:
                                play_button = await page.query_selector(selector)
                                if play_button:
                                    await play_button.click()
                                    logger.info(f"[extract] 点击了播放按钮: {selector}")
                                    await asyncio.sleep(2)
                                    break
                            except:
                                continue

                        # 尝试鼠标悬停在视频区域
                        try:
                            video_area = await page.query_selector('video, .video-container, .player-container')
                            if video_area:
                                await video_area.hover()
                                await asyncio.sleep(1)
                        except:
                            pass

                    except Exception as e:
                        logger.warning(f"[extract] 页面交互失败: {e}")

                    # 再等待一段时间确保内容加载完成
                    await asyncio.sleep(3)

                    # 尝试从URL中提取photo_id
                    if not video_id_holder['id']:
                        photo_id_match = re.search(r'/short-video/([a-zA-Z0-9_-]+)', url)
                        if photo_id_match:
                            video_id_holder['id'] = photo_id_match.group(1)
                            logger.info(f"[extract] 从URL提取到快手 photo_id: {video_id_holder['id']}")

                    # 优先使用网络监听捕获的视频URL
                    video_url = video_url_holder['url']

                    if not video_url:
                        # 如果网络监听没有捕获到，从HTML中提取视频直链
                        logger.info(f"[extract] 网络监听未捕获到视频URL，尝试从HTML提取")
                        html = await page.content()
                        video_url = await self._extract_kuaishou_url_from_html(html)
                        logger.info(f"[extract] 快手HTML提取结果: {video_url}")
                    else:
                        logger.info(f"[extract] 使用网络监听捕获的视频URL: {video_url}")

                    if video_url:
                        # 获取标题和作者
                        title = await self._get_video_title(page, platform)
                        author = await self._get_video_author(page, platform)

                        # 创建视频信息对象
                        video_info = VideoInfo(
                            video_id=video_id_holder['id'] or str(int(time.time())),
                            title=title or f"快手视频_{int(time.time())}",
                            author=author or "未知作者",
                            download_url=video_url,
                            platform="kuaishou"
                        )

                        logger.info(f"[extract] 快手视频信息: 标题={video_info.title}, 作者={video_info.author}")
                        logger.info("[extract] 正则流程完成")

                        # 下载视频
                        download_result = await self._download_video_file(
                            video_info,
                            str(self.kuaishou_download_path),
                            message_updater,
                            None
                        )

                        await page.close()
                        await context.close()
                        return download_result
                    else:
                        logger.error("[extract] 未能提取到快手视频直链")
                        await page.close()
                        await context.close()
                        return {
                            "success": False,
                            "error": "未能提取到快手视频直链",
                            "platform": "Kuaishou",
                            "content_type": "video"
                        }

                except Exception as e:
                    logger.error(f"[extract] 快手页面处理异常: {str(e)}")
                    try:
                        await page.close()
                        await context.close()
                    except:
                        pass
                    logger.info("[extract] 关闭 page/context 后")

                await browser.close()

        except Exception as e:
            logger.error(f"快手下载异常: {str(e)}")
            return {
                "success": False,
                "error": f"下载失败: {str(e)}",
                "platform": "Kuaishou",
                "content_type": "video"
            }

    async def _extract_kuaishou_url_from_html(self, html: str) -> Optional[str]:
        """从快手HTML源码中提取视频直链"""
        try:
            logger.info(f"[extract] 快手HTML长度: {len(html)} 字符")

            # 先保存HTML到文件用于调试
            try:
                debug_path = '/tmp/kuaishou_debug.html'
                with open(debug_path, 'w', encoding='utf-8') as f:
                    f.write(html)
                logger.info(f"[extract] 已保存HTML到 {debug_path} 用于调试")

                # 输出HTML的前500个字符用于快速分析
                logger.info(f"[extract] HTML开头内容: {html[:500]}")

                # 检查HTML中是否包含关键词
                keywords = ['video', 'mp4', 'src', 'url', 'play', 'kwai']
                for keyword in keywords:
                    count = html.lower().count(keyword)
                    if count > 0:
                        logger.info(f"[extract] HTML中包含 '{keyword}': {count} 次")

            except Exception as e:
                logger.warning(f"[extract] 保存HTML调试文件失败: {e}")

            # 快手视频URL的正则模式 - 扩展更多模式
            patterns = [
                # 快手视频直链模式
                r'"srcNoMark":"(https://[^"]+\.mp4[^"]*)"',
                r'"playUrl":"(https://[^"]+\.mp4[^"]*)"',
                r'"videoUrl":"(https://[^"]+\.mp4[^"]*)"',
                r'"src":"(https://[^"]+\.mp4[^"]*)"',
                r'"url":"(https://[^"]+\.mp4[^"]*)"',
                # 快手CDN模式
                r'(https://[^"\']+\.kwaicdn\.com/[^"\']+\.mp4[^"\']*)',
                r'(https://[^"\']+\.kuaishou\.com/[^"\']+\.mp4[^"\']*)',
                r'(https://[^"\']+\.ksapisrv\.com/[^"\']+\.mp4[^"\']*)',
                # JSON中的视频URL
                r'"photoUrl":"(https://[^"]+\.mp4[^"]*)"',
                r'"manifest":"(https://[^"]+\.mp4[^"]*)"',
                # 通用视频URL模式
                r'(https://[^"\'>\s]+\.mp4[^"\'>\s]*)',
                # 查找包含video的JSON字段
                r'"[^"]*[Vv]ideo[^"]*":"(https://[^"]+)"',
                r'"[^"]*[Pp]lay[^"]*":"(https://[^"]+\.mp4[^"]*)"',
            ]

            for i, pattern in enumerate(patterns):
                matches = re.findall(pattern, html)
                if matches:
                    for match in matches:
                        # 清理URL
                        video_url = match.replace('\\u002F', '/').replace('\\u0026', '&').replace('\\/', '/').replace('\\', '')
                        # 验证URL格式
                        if (video_url.startswith('http') and
                            ('.mp4' in video_url or 'kwaicdn.com' in video_url or 'kuaishou.com' in video_url) and
                            len(video_url) > 20):  # 基本长度检查
                            logger.info(f"[extract] 快手模式{i+1}找到视频URL: {video_url}")
                            return video_url

            # 如果正则都失败，尝试查找script标签中的JSON数据
            logger.info("[extract] 正则模式失败，尝试解析script标签中的JSON")
            script_matches = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
            for script_content in script_matches:
                if 'mp4' in script_content or 'video' in script_content.lower():
                    # 尝试从script中提取视频URL
                    video_patterns = [
                        r'"(https://[^"]+\.mp4[^"]*)"',
                        r"'(https://[^']+\.mp4[^']*)'",
                        r'(https://[^\s"\']+\.mp4[^\s"\']*)',
                    ]
                    for pattern in video_patterns:
                        matches = re.findall(pattern, script_content)
                        for match in matches:
                            video_url = match.replace('\\u002F', '/').replace('\\u0026', '&').replace('\\/', '/').replace('\\', '')
                            if (video_url.startswith('http') and
                                ('.mp4' in video_url or 'kwaicdn.com' in video_url) and
                                len(video_url) > 20):
                                logger.info(f"[extract] 从script标签找到视频URL: {video_url}")
                                return video_url

            logger.warning("[extract] 所有快手正则模式都未匹配到视频URL")

            # 输出一些HTML片段用于调试
            if 'mp4' in html:
                mp4_contexts = []
                for match in re.finditer(r'.{0,50}mp4.{0,50}', html, re.IGNORECASE):
                    mp4_contexts.append(match.group())
                logger.info(f"[extract] HTML中包含mp4的上下文: {mp4_contexts[:3]}")  # 只显示前3个

            return None

        except Exception as e:
            logger.warning(f"快手HTML正则提取失败: {str(e)}")
        return None

    async def _download_video_file(self, video_info, download_dir, message_updater=None, start_message=None):
        """下载视频文件"""
        try:
            # 生成文件名
            if video_info.title:
                # 清理标题，去除特殊字符和平台后缀
                clean_title = self._sanitize_filename(video_info.title)
                # 小红书、抖音和快手的特殊命名逻辑
                if video_info.platform in ["xiaohongshu", "douyin", "kuaishou"]:
                    # 去掉开头的#和空格
                    clean_title = clean_title.lstrip('#').strip()
                    # 用#分割，取第一个分割后的内容（即第2个#前的内容）
                    clean_title = clean_title.split('#')[0].strip()
                    # 如果处理后标题为空，使用平台+时间戳
                    if not clean_title:
                        clean_title = f"{video_info.platform}_{int(time.time())}"
                else:
                    # 其他平台保持原有逻辑
                    clean_title = re.split(r'#', clean_title)[0].strip()
                # 去除平台后缀
                clean_title = re.sub(r'[-_ ]*(抖音|快手|小红书|YouTube|youtube)$', '', clean_title, flags=re.IGNORECASE).strip()
                filename = f"{clean_title}.mp4"
            else:
                # 如果获取标题失败，使用时间戳
                filename = f"{video_info.platform}_{int(time.time())}.mp4"
            
            file_path = os.path.join(download_dir, filename)
            
            # 小红书使用简单下载逻辑，抖音保持现有逻辑
            if video_info.platform == 'xiaohongshu':
                # 小红书：简单下载逻辑，参考douyin.py
                async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                        'Referer': 'https://www.xiaohongshu.com/'
                    }
                    
                    logger.info(f"🎬 开始下载小红书视频: {video_info.download_url}")
                    
                    # 先检查响应状态和头信息
                    try:
                        async with client.stream("GET", video_info.download_url, headers=headers) as resp:
                            logger.info(f"📊 HTTP状态码: {resp.status_code}")
                            logger.info(f"📊 响应头: {dict(resp.headers)}")
                            
                            total = int(resp.headers.get("content-length", 0))
                            logger.info(f"📊 文件大小: {total} bytes")
                            
                            if resp.status_code != 200:
                                logger.error(f"❌ HTTP状态码错误: {resp.status_code}")
                                # 读取错误响应内容
                                error_content = await resp.aread()
                                logger.error(f"❌ 错误响应内容: {error_content[:500]}")
                                raise Exception(f"HTTP状态码错误: {resp.status_code}")
                            
                            with open(file_path, "wb") as f:
                                downloaded = 0
                                chunk_size = 1024 * 256
                                
                                async for chunk in resp.aiter_bytes(chunk_size=chunk_size):
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    
                                    # 更新进度 - 使用与 YouTube 相同的格式
                                    if total > 0:
                                        progress = downloaded / total * 100
                                    else:
                                        # 如果没有content-length，使用下载的字节数作为进度指示
                                        progress = min(downloaded / (1024 * 1024), 99)  # 假设至少1MB
                                    
                                    # 计算速度（每秒更新一次）
                                    current_time = time.time()
                                    if not hasattr(self, '_last_update_time'):
                                        self._last_update_time = current_time
                                        self._last_downloaded = 0
                                    
                                    if current_time - self._last_update_time >= 1.0:
                                        speed = (downloaded - self._last_downloaded) / (current_time - self._last_update_time)
                                        self._last_update_time = current_time
                                        self._last_downloaded = downloaded
                                    else:
                                        speed = 0
                                    
                                    # 计算ETA
                                    if speed > 0 and total > 0:
                                        remaining_bytes = total - downloaded
                                        eta_seconds = remaining_bytes / speed
                                    else:
                                        eta_seconds = 0
                                    
                                    # 构建进度数据，格式与 yt-dlp 一致
                                    progress_data = {
                                        'status': 'downloading',
                                        'downloaded_bytes': downloaded,
                                        'total_bytes': total,
                                        'speed': speed,
                                        'eta': eta_seconds,
                                        'filename': filename
                                    }
                                    
                                    # 使用 message_updater 更新进度
                                    if message_updater:
                                        try:
                                            import asyncio
                                            if asyncio.iscoroutinefunction(message_updater):
                                                # 如果是协程函数，需要在事件循环中运行
                                                try:
                                                    loop = asyncio.get_running_loop()
                                                except RuntimeError:
                                                    try:
                                                        loop = asyncio.get_event_loop()
                                                    except RuntimeError:
                                                        loop = asyncio.new_event_loop()
                                                        asyncio.set_event_loop(loop)
                                                asyncio.run_coroutine_threadsafe(message_updater(progress_data), loop)
                                            else:
                                                # 同步函数，直接调用
                                                message_updater(progress_data)
                                        except Exception as e:
                                            logger.warning(f"⚠️ 更新进度失败: {e}")
                                
                                # 下载完成后的最终更新
                                logger.info(f"✅ 小红书视频下载完成: {downloaded} bytes @{video_info.download_url}")
                                if message_updater:
                                    try:
                                        final_progress_data = {
                                            'status': 'finished',
                                            'downloaded_bytes': downloaded,
                                            'total_bytes': total,
                                            'filename': filename
                                        }
                                        message_updater(final_progress_data)
                                    except Exception as e:
                                        logger.warning(f"⚠️ 更新完成状态失败: {e}")
                    except Exception as e:
                        logger.error(f"❌ 小红书下载异常: {e}")
                        raise
            else:
                # 抖音等其他平台：处理API重定向
                # 准备cookies（如果有）
                cookies_dict = {}
                if video_info.platform == 'douyin' and self.douyin_cookies_path and os.path.exists(self.douyin_cookies_path):
                    try:
                        cookies_dict = self._parse_douyin_cookies_file(self.douyin_cookies_path)
                        logger.info(f"📊 加载了{len(cookies_dict)}个cookies用于下载")
                    except Exception as e:
                        logger.warning(f"⚠️ 加载cookies失败: {e}")
                
                async with httpx.AsyncClient(follow_redirects=True, timeout=60, cookies=cookies_dict) as client:
                    # 使用手机版User-Agent（按照原始douyin.py）
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
                        'Accept': '*/*',
                        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                        'Referer': 'https://www.douyin.com/' if video_info.platform == 'douyin' else 'https://www.xiaohongshu.com/',
                        'Connection': 'keep-alive',
                    }
                    
                    # 对于抖音API链接，直接使用stream下载（按照原始douyin.py的方式）
                    logger.info(f"🎬 开始下载抖音视频: {video_info.download_url}")
                    
                    with open(file_path, "wb") as f:
                        async with client.stream("GET", video_info.download_url, headers=headers) as resp:
                            total = int(resp.headers.get("content-length", 0))
                            downloaded = 0
                            chunk_size = 1024 * 256
                            last_update_time = time.time()
                            last_downloaded = 0
                            
                            logger.info(f"📊 Stream响应状态码: {resp.status_code}")
                            logger.info(f"📊 Stream文件大小: {total} bytes")
                            logger.info(f"📊 实际请求URL: {resp.url}")
                            logger.info(f"📊 响应头: {dict(resp.headers)}")
                            
                            if resp.status_code != 200:
                                raise Exception(f"HTTP状态码错误: {resp.status_code}")
                            
                            async for chunk in resp.aiter_bytes(chunk_size=chunk_size):
                                if not chunk:
                                    break
                                f.write(chunk)
                                downloaded += len(chunk)
                                current_time = time.time()
                                
                                # 更新进度 - 使用与 YouTube 相同的格式
                                if total > 0:
                                    progress = downloaded / total * 100
                                else:
                                    # 如果没有content-length，使用下载的字节数作为进度指示
                                    progress = min(downloaded / (1024 * 1024), 99)  # 假设至少1MB
                                
                                # 计算速度（每秒更新一次）
                                if current_time - last_update_time >= 1.0:
                                    speed = (downloaded - last_downloaded) / (current_time - last_update_time)
                                    last_update_time = current_time
                                    last_downloaded = downloaded
                                    
                                    # 计算ETA
                                    if speed > 0 and total > 0:
                                        remaining_bytes = total - downloaded
                                        eta_seconds = remaining_bytes / speed
                                    else:
                                        eta_seconds = 0
                                    
                                    # 构建进度数据，格式与 yt-dlp 一致
                                    progress_data = {
                                        'status': 'downloading',
                                        'downloaded_bytes': downloaded,
                                        'total_bytes': total,
                                        'speed': speed,
                                        'eta': eta_seconds,
                                        'filename': filename
                                    }
                                    
                                    # 使用 message_updater 更新进度
                                    if message_updater:
                                        try:
                                            import asyncio
                                            if asyncio.iscoroutinefunction(message_updater):
                                                # 如果是协程函数，需要在事件循环中运行
                                                try:
                                                    loop = asyncio.get_running_loop()
                                                except RuntimeError:
                                                    try:
                                                        loop = asyncio.get_event_loop()
                                                    except RuntimeError:
                                                        loop = asyncio.new_event_loop()
                                                        asyncio.set_event_loop(loop)
                                                asyncio.run_coroutine_threadsafe(message_updater(progress_data), loop)
                                            else:
                                                # 同步函数，直接调用
                                                message_updater(progress_data)
                                        except Exception as e:
                                            logger.warning(f"⚠️ 更新进度失败: {e}")
                                    else:
                                        # 如果没有 message_updater，使用原来的简单更新
                                        if start_message and hasattr(self, 'bot') and self.bot:
                                            try:
                                                await start_message.edit_text(
                                                    f"📥 下载中... {progress:.1f}% ({downloaded/(1024*1024):.1f}MB)"
                                                )
                                            except Exception as e:
                                                logger.warning(f"⚠️ 更新进度消息失败: {e}")
                                        else:
                                            logger.info(f"📥 下载中... {progress:.1f}% ({downloaded/(1024*1024):.1f}MB)")
                            
                            # 下载完成后的最终更新
                            logger.info(f"✅ 下载完成: {downloaded} bytes")
                            if message_updater:
                                try:
                                    final_progress_data = {
                                        'status': 'finished',
                                        'downloaded_bytes': downloaded,
                                        'total_bytes': total,
                                        'filename': filename
                                    }
                                    import asyncio
                                    if asyncio.iscoroutinefunction(message_updater):
                                        # 如果是协程函数，需要在事件循环中运行
                                        try:
                                            loop = asyncio.get_running_loop()
                                        except RuntimeError:
                                            try:
                                                loop = asyncio.get_event_loop()
                                            except RuntimeError:
                                                loop = asyncio.new_event_loop()
                                                asyncio.set_event_loop(loop)
                                        asyncio.run_coroutine_threadsafe(message_updater(final_progress_data), loop)
                                    else:
                                        # 同步函数，直接调用
                                        message_updater(final_progress_data)
                                except Exception as e:
                                    logger.warning(f"⚠️ 更新完成状态失败: {e}")
            
            # 删除开始消息（如果存在）
            if start_message and hasattr(self, 'bot') and self.bot:
                try:
                    await start_message.delete()
                except Exception as e:
                    logger.warning(f"⚠️ 删除开始消息失败: {e}")
            
            # 获取文件信息
            file_size = os.path.getsize(file_path)
            size_mb = file_size / (1024 * 1024)
            
            # 使用 ffprobe 获取视频分辨率信息
            resolution = "未知"
            try:
                media_info = self.get_media_info(file_path)
                if media_info.get("resolution"):
                    resolution = media_info["resolution"]
                    logger.info(f"📺 获取到视频分辨率: {resolution}")
            except Exception as e:
                logger.warning(f"⚠️ 获取视频分辨率失败: {e}")
            
            logger.info(f"✅ {video_info.platform}视频下载成功: {filename} ({size_mb:.1f} MB, 分辨率: {resolution})")
            
            return {
                "success": True,
                "file_path": file_path,
                "filename": filename,
                "title": video_info.title,
                "author": video_info.author,
                "platform": video_info.platform,
                "content_type": "video",
                "size_mb": size_mb,
                "resolution": resolution,
                "download_path": download_dir,
                "full_path": file_path,
                "file_count": 1,
                "files": [file_path]
            }
            
        except Exception as e:
            logger.error(f"❌ 下载视频文件失败: {e}")
            # 确保在异常情况下也能返回有效的结果
            return {
                "success": False,
                "error": f"下载视频文件失败: {e}",
                "platform": video_info.platform,
                "content_type": "video",
                "downloaded_bytes": 0,
                "total_bytes": 0,
                "filename": video_info.title or f"{video_info.platform}_{int(time.time())}.mp4"
            }



    def _build_bilibili_rename_script(self):
        """
        构建B站多P视频智能重命名脚本

        基于您的优秀建议：使用yt-dlp的--exec功能在下载完成后立即重命名
        避免了下载完成后的批量重命名操作，更高效更准确

        Returns:
            str: 重命名脚本命令
        """
        import shlex

        # 构建重命名脚本
        # 1. 获取当前文件的URL（从文件名推导）
        # 2. 使用yt-dlp --get-title获取完整标题
        # 3. 使用grep提取pxx部分
        # 4. 重命名文件

        script = '''
        # 获取文件信息
        file_path="{}"
        file_dir=$(dirname "$file_path")
        file_name=$(basename "$file_path")
        file_ext="${file_name##*.}"
        video_id="${file_name%.*}"

        # 构建URL（假设是B站视频）
        if [[ $video_id == *"_p"* ]]; then
            # 多P视频格式：BV1Jgf6YvE8e_p1
            bv_id="${video_id%_p*}"
            part_num="${video_id#*_p}"
            video_url="https://www.bilibili.com/video/${bv_id}?p=${part_num}"
        else
            # 单P视频格式：BV1Jgf6YvE8e
            video_url="https://www.bilibili.com/video/${video_id}"
        fi

        # 获取完整标题并提取pxx部分
        full_title=$(yt-dlp --get-title --skip-download "$video_url" 2>/dev/null)
        if [[ $? -eq 0 && -n "$full_title" ]]; then
            # 提取pxx及后续内容
            new_name=$(echo "$full_title" | grep -o "p[0-9]\\{1,3\\}.*" | head -1)
            if [[ -n "$new_name" ]]; then
                # 清理文件名中的特殊字符
                new_name=$(echo "$new_name" | sed 's/[\\/:*?"<>|【】｜]/\\_/g' | sed 's/\\s\\+/ /g')
                new_file_path="$file_dir/${new_name}.${file_ext}"

                # 执行重命名
                if [[ "$file_path" != "$new_file_path" ]]; then
                    mv "$file_path" "$new_file_path"
                    echo "✅ 智能重命名: $(basename "$file_path") -> ${new_name}.${file_ext}"
                else
                    echo "📝 文件名已正确: ${new_name}.${file_ext}"
                fi
            else
                echo "⚠️ 未找到pxx模式，保持原文件名: $file_name"
            fi
        else
            echo "⚠️ 无法获取标题，保持原文件名: $file_name"
        fi
        '''

        return script.strip()

    def _is_temp_format_file(self, filename):
        """
        检查是否是临时格式文件（包含yt-dlp格式代码）

        Args:
            filename: 文件路径

        Returns:
            bool: 如果是临时格式文件返回True
        """
        import re
        from pathlib import Path

        file_name = Path(filename).name

        # 检查是否包含yt-dlp的格式代码
        # 例如：.f100026, .f137+140, .m4a, .webm 等
        temp_patterns = [
            r'\.f\d+',           # .f100026
            r'\.f\d+\+\d+',      # .f137+140
            r'\.m4a$',           # .m4a
            r'\.webm$',          # .webm
        ]

        for pattern in temp_patterns:
            if re.search(pattern, file_name):
                return True

        return False

    def _get_final_filename_from_mapping(self, filename, title_mapping):
        """
        从标题映射表中获取最终文件名

        Args:
            filename: 当前下载的文件名
            title_mapping: 视频ID到最终文件名的映射表

        Returns:
            str: 最终文件名，如果找不到则返回None
        """
        import re
        from pathlib import Path

        try:
            file_path = Path(filename)

            # 从文件名中提取视频ID
            # 例如：BV1aDMezREUj_p1.f100026.mp4 -> BV1aDMezREUj_p1
            raw_video_id = file_path.stem
            video_id = re.sub(r'\.f\d+.*$', '', raw_video_id)

            # 从映射表中查找最终文件名
            final_filename = title_mapping.get(video_id)
            if final_filename:
                logger.debug(f"📋 映射查找: {video_id} -> {final_filename}")
                return final_filename
            else:
                logger.debug(f"⚠️ 未找到映射: {video_id}")
                return None

        except Exception as e:
            logger.debug(f"映射查找失败: {e}")
            return None

    def _optimize_filename_display_for_telegram(self, filename_display, file_count, total_size_mb, resolution_display, download_path):
        """
        动态优化文件名显示，最大化利用TG消息空间

        Args:
            filename_display: 原始文件名显示字符串
            file_count: 文件数量
            total_size_mb: 总文件大小
            resolution_display: 分辨率显示
            download_path: 下载路径

        Returns:
            str: 优化后的文件名显示字符串
        """
        # TG消息最大长度限制
        MAX_MESSAGE_LENGTH = 4096

        # 构建消息的其他部分（不包括文件名列表）
        other_parts = (
            f"🎬 **视频下载完成**\n\n"
            f"📝 **文件名**:\n"
            f"FILENAME_PLACEHOLDER\n\n"
            f"💾 **文件大小**: `{total_size_mb:.2f} MB`\n"
            f"📊 **集数**: `{file_count} 集`\n"
            f"🖼️ **分辨率**: `{resolution_display}`\n"
            f"📂 **保存位置**: `{download_path}`"
        )

        # 计算除文件名列表外的消息长度
        other_parts_length = len(other_parts) - len("FILENAME_PLACEHOLDER")

        # 可用于文件名列表的最大长度
        available_length = MAX_MESSAGE_LENGTH - other_parts_length - 100  # 留100字符缓冲

        lines = filename_display.split('\n')

        # 如果原始文件名列表不超过可用长度，直接返回
        if len(filename_display) <= available_length:
            return filename_display

        # 需要截断，找到能显示的最大文件数量
        result_lines = []
        current_length = 0

        # 省略提示的模板
        omit_template = "  ... (省略 {} 个文件，受限于TG消息限制，完整文件列表请到下载目录查看) ..."

        for i, line in enumerate(lines):
            # 计算加上这一行和可能的省略提示后的总长度
            remaining_files = len(lines) - i - 1
            if remaining_files > 0:
                omit_text = omit_template.format(remaining_files)
                projected_length = current_length + len(line) + 1 + len(omit_text)  # +1 for newline
            else:
                projected_length = current_length + len(line)

            # 如果加上这一行会超过限制
            if projected_length > available_length:
                # 如果还有剩余文件，添加省略提示
                if remaining_files > 0:
                    omit_text = omit_template.format(remaining_files)
                    result_lines.append(omit_text)
                break
            else:
                # 可以添加这一行
                result_lines.append(line)
                current_length = projected_length

        return '\n'.join(result_lines)

    def _rename_bilibili_file_from_full_title(self, filename):
        """
        从完整标题文件名重命名为简洁的pxx格式

        例如：
        输入: 尚硅谷Cursor使用教程，2小时玩转cursor p01 01-Cursor教程简介.mp4
        输出: p01 01-Cursor教程简介.mp4

        Args:
            filename: 下载完成的文件路径（包含完整标题）
        """
        import re
        from pathlib import Path

        try:
            file_path = Path(filename)
            if not file_path.exists():
                logger.warning(f"⚠️ 文件不存在: {filename}")
                return

            file_name = file_path.name
            file_ext = file_path.suffix
            title_without_ext = file_path.stem

            logger.info(f"🔍 处理完整标题文件: {file_name}")

            # 使用智能处理逻辑提取pxx部分
            processed_title = self._process_bilibili_multipart_title(title_without_ext)

            if processed_title != title_without_ext:
                # 标题被处理了，说明找到了pxx部分
                safe_title = self._sanitize_filename(processed_title)
                new_file_path = file_path.parent / f"{safe_title}{file_ext}"

                logger.info(f"🎯 简洁文件名: {safe_title}{file_ext}")

                # 执行重命名
                if file_path != new_file_path:
                    try:
                        file_path.rename(new_file_path)
                        logger.info(f"✅ 智能重命名成功: {file_name} -> {safe_title}{file_ext}")
                    except Exception as e:
                        logger.warning(f"⚠️ 重命名失败: {e}")
                else:
                    logger.info(f"📝 文件名已是简洁格式: {safe_title}{file_ext}")
            else:
                logger.info(f"📝 未找到pxx模式，保持原文件名: {file_name}")

        except Exception as e:
            logger.error(f"❌ 处理文件名失败: {e}")

    def _get_processed_filename_for_display(self, filename):
        """
        获取用于显示的处理后文件名

        这个函数用于在下载进度中显示用户友好的文件名，
        而不是技术性的临时文件名

        Args:
            filename: 原始文件名

        Returns:
            str: 处理后的显示文件名
        """
        import re
        from pathlib import Path

        try:
            file_path = Path(filename)
            file_name = file_path.name
            file_ext = file_path.suffix

            # 如果是临时格式文件，尝试推导最终文件名
            if self._is_temp_format_file(filename):
                # 从临时文件名推导视频ID
                # 例如：BV1aDMezREUj_p1.f100026.mp4 -> BV1aDMezREUj_p1
                raw_video_id = file_path.stem
                video_id = re.sub(r'\.f\d+.*$', '', raw_video_id)

                # 尝试从缓存的标题信息获取处理后的文件名
                # 这里我们使用一个简化的方法：直接显示视频ID
                if "_p" in video_id:
                    # 多P视频：显示分集信息
                    parts = video_id.split("_p")
                    part_num = parts[1]
                    return f"p{part_num.zfill(2)} 下载中...{file_ext}"
                else:
                    # 单P视频
                    return f"视频下载中...{file_ext}"
            else:
                # 如果是最终文件，检查是否需要处理标题
                # 这里我们假设文件名可能包含完整的标题
                if any(keyword in file_name for keyword in ["尚硅谷", "教程", "课程"]):
                    # 尝试提取pxx部分
                    pattern = r'p(\d{1,3})\s+'
                    match = re.search(pattern, file_name, re.IGNORECASE)
                    if match:
                        # 找到pxx，尝试提取后续内容
                        start_pos = match.start()
                        remaining = file_name[start_pos:]
                        # 简化处理：只取前50个字符
                        if len(remaining) > 50:
                            remaining = remaining[:47] + "..."
                        return remaining

                # 默认返回原文件名
                return file_name

        except Exception as e:
            logger.debug(f"处理显示文件名失败: {e}")
            return Path(filename).name

    def _rename_bilibili_file_immediately(self, filename):
        """
        立即重命名B站多P文件（基于您的优秀建议的Python实现）

        在每个文件下载完成时立即执行重命名，避免批量处理

        Args:
            filename: 下载完成的文件路径
        """
        import re
        import os
        from pathlib import Path

        try:
            file_path = Path(filename)
            if not file_path.exists():
                logger.warning(f"⚠️ 文件不存在: {filename}")
                return

            file_name = file_path.name
            file_ext = file_path.suffix
            raw_video_id = file_path.stem

            logger.info(f"🔍 分析文件: {file_name}")
            logger.info(f"📝 原始视频ID: {raw_video_id}")

            # 清理视频ID，去除格式代码
            # 例如：BV1aDMezREUj_p2.f100026 -> BV1aDMezREUj_p2
            video_id = re.sub(r'\.f\d+.*$', '', raw_video_id)
            logger.info(f"🧹 清理后视频ID: {video_id}")

            # 构建URL（从文件名推导）
            if "_p" in video_id:
                # 多P视频格式：BV1aDMezREUj_p1
                parts = video_id.split("_p")
                bv_id = parts[0]
                part_num = parts[1]
                video_url = f"https://www.bilibili.com/video/{bv_id}?p={part_num}"
            else:
                # 单P视频格式：BV1aDMezREUj
                video_url = f"https://www.bilibili.com/video/{video_id}"

            logger.info(f"🔗 构建URL: {video_url}")

            # 使用yt-dlp获取完整标题
            try:
                import subprocess
                result = subprocess.run(
                    ["yt-dlp", "--get-title", "--skip-download", video_url],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.returncode == 0 and result.stdout.strip():
                    full_title = result.stdout.strip()
                    logger.info(f"📋 获取标题: {full_title}")

                    # 提取pxx及后续内容
                    pattern = r'p(\d{1,3}).*'
                    match = re.search(pattern, full_title, re.IGNORECASE)

                    if match:
                        # 从pxx开始截取
                        start_pos = match.start()
                        new_name = full_title[start_pos:]

                        # 清理文件名中的特殊字符
                        new_name = re.sub(r'[\\/:*?"<>|【】｜]', '_', new_name)
                        new_name = re.sub(r'\s+', ' ', new_name).strip()

                        new_file_path = file_path.parent / f"{new_name}{file_ext}"

                        logger.info(f"🎯 新文件名: {new_name}{file_ext}")

                        # 执行重命名
                        if file_path != new_file_path:
                            file_path.rename(new_file_path)
                            logger.info(f"✅ 智能重命名成功: {file_name} -> {new_name}{file_ext}")
                        else:
                            logger.info(f"📝 文件名已正确: {new_name}{file_ext}")
                    else:
                        logger.warning(f"⚠️ 未找到pxx模式，保持原文件名: {file_name}")
                else:
                    logger.warning(f"⚠️ 无法获取标题，保持原文件名: {file_name}")
                    logger.warning(f"yt-dlp错误: {result.stderr}")

            except subprocess.TimeoutExpired:
                logger.warning(f"⚠️ 获取标题超时，保持原文件名: {file_name}")
            except Exception as e:
                logger.warning(f"⚠️ 获取标题失败: {e}，保持原文件名: {file_name}")

        except Exception as e:
            logger.error(f"❌ 重命名文件失败: {e}")

    def _rename_bilibili_multipart_files(self, download_path, expected_files):
        """
        重命名B站多P下载的文件，使其匹配预期文件名

        Args:
            download_path: 下载目录路径
            expected_files: 预期文件列表
        """
        import os
        from pathlib import Path

        logger.info(f"🔄 开始重命名B站多P文件，目录: {download_path}")
        logger.info(f"📋 预期文件数量: {len(expected_files)}")

        # 获取目录中所有视频文件
        video_extensions = ["*.mp4", "*.mkv", "*.webm", "*.avi", "*.mov", "*.flv"]
        all_video_files = []
        for ext in video_extensions:
            all_video_files.extend(list(Path(download_path).glob(ext)))

        logger.info(f"📁 找到视频文件数量: {len(all_video_files)}")

        renamed_count = 0
        for expected_file in expected_files:
            expected_filename = expected_file['filename']
            original_title = expected_file['title']

            # 查找匹配的实际文件
            for actual_file in all_video_files:
                actual_filename = actual_file.name

                # 使用智能匹配逻辑检查是否匹配
                def clean_filename_for_matching(filename):
                    """清理文件名用于匹配"""
                    import re
                    if not filename:
                        return ""

                    # 删除yt-dlp的各种格式代码
                    cleaned = re.sub(r'\.[fm]\d+(\+\d+)*', '', filename)
                    cleaned = re.sub(r'\.f\d+', '', cleaned)
                    cleaned = re.sub(r'\.(webm|m4a|mp3)$', '.mp4', cleaned)
                    cleaned = re.sub(r'\.(webm|m4a|mp3)\.mp4$', '.mp4', cleaned)

                    # 删除序号前缀
                    cleaned = re.sub(r'^\d+\.\s*', '', cleaned)

                    # 对B站多P标题进行智能处理
                    pattern = r'\s+[pP](\d{1,3})\s+'
                    match = re.search(pattern, cleaned)
                    if match:
                        start_pos = match.start() + 1
                        cleaned = cleaned[start_pos:]

                    # 统一特殊字符（解决全角/半角差异）
                    # 将各种竖线统一为下划线，与_sanitize_filename保持一致
                    cleaned = re.sub(r'[|｜]', '_', cleaned)
                    # 统一其他特殊字符
                    cleaned = re.sub(r'[【】]', '_', cleaned)

                    # 确保以 .mp4 结尾
                    if not cleaned.endswith('.mp4'):
                        cleaned = cleaned.rstrip('.') + '.mp4'

                    return cleaned

                cleaned_actual = clean_filename_for_matching(actual_filename)
                cleaned_expected = clean_filename_for_matching(expected_filename)

                if cleaned_actual == cleaned_expected:
                    # 找到匹配的文件，进行重命名
                    new_file_path = actual_file.parent / expected_filename

                    if actual_file != new_file_path:  # 避免重命名为相同名称
                        try:
                            actual_file.rename(new_file_path)
                            logger.info(f"✅ 重命名成功: {actual_filename} -> {expected_filename}")
                            renamed_count += 1
                        except Exception as e:
                            logger.warning(f"⚠️ 重命名失败: {actual_filename} -> {expected_filename}, 错误: {e}")
                    else:
                        logger.info(f"📝 文件名已正确: {expected_filename}")
                        renamed_count += 1
                    break
            else:
                logger.warning(f"⚠️ 未找到匹配文件: {expected_filename}")

        logger.info(f"🎉 重命名完成: {renamed_count}/{len(expected_files)} 个文件")

    def _process_bilibili_multipart_title(self, title):
        """
        智能处理B站多P视频标题，去除pxx前面的冗长内容

        例如：
        输入: "3小时超快速入门Python | 动画教学【2025新版】【自学Python教程】【零基础Python】【计算机二级Python】【Python期末速成】 p01 先导篇 | 为什么做这个教程"
        输出: "p01 先导篇 | 为什么做这个教程"
        """
        if not title:
            return title

        import re

        # 查找 pxx 模式（p + 数字）
        # 支持 p01, p1, P01, P1 等格式
        pattern = r'\s+[pP](\d{1,3})\s+'
        match = re.search(pattern, title)

        if match:
            # 找到 pxx，从 pxx 开始截取
            start_pos = match.start() + 1  # +1 是为了跳过前面的空格
            processed_title = title[start_pos:]
            logger.info(f"🔧 B站多P标题处理: '{title}' -> '{processed_title}'")
            return processed_title
        else:
            # 没有找到 pxx 模式，返回原标题
            return title

    def _basic_sanitize_filename(self, filename):
        """
        基本的文件名清理，与yt-dlp保持一致
        只替换文件系统不支持的字符，保留其他字符

        注意：这个函数需要完全模拟yt-dlp的字符处理行为
        """
        if not filename:
            return "video"

        # yt-dlp的字符处理规则（基于观察到的实际行为）：
        # 1. 半角 | 转换为全角 ｜
        filename = filename.replace('|', '｜')

        # 2. 斜杠 / 转换为大斜杠符号 ⧸ （这是yt-dlp的实际行为）
        filename = filename.replace('/', '⧸')

        # 3. 只替换文件系统绝对不支持的字符
        # 保留 ｜ 【】 ⧸ 等字符，因为yt-dlp也会保留它们
        filename = re.sub(r'[\\:*?"<>]', '_', filename)

        # 3. 去除多余空格
        filename = re.sub(r'\s+', ' ', filename).strip()

        # 4. 去除开头和结尾的下划线和空格
        filename = re.sub(r'^[_\s]+|[_\s]+$', '', filename)

        # 确保文件名不为空
        if not filename or filename.isspace():
            filename = "video"

        return filename

    def _detect_part_files(self, download_path):
        """检测PART文件"""
        from pathlib import Path
        part_files = list(Path(download_path).rglob("*.part"))
        return part_files

    def _analyze_failure_reason(self, part_file):
        """分析PART文件失败原因"""
        try:
            file_size = part_file.stat().st_size
            if file_size == 0:
                return "下载未开始或立即失败"
            elif file_size < 1024 * 1024:  # < 1MB
                return "下载刚开始就中断，可能是网络问题"
            elif file_size < 10 * 1024 * 1024:  # < 10MB
                return "下载进行中被中断，可能是网络问题"
            else:
                return "下载进行中被中断，可能是网络或磁盘问题"
        except Exception:
            return "无法分析失败原因"

    def _log_part_files_details(self, part_files):
        """在日志中记录PART文件详细信息"""
        if part_files:
            logger.warning(f"⚠️ 发现 {len(part_files)} 个未完成的PART文件")
            logger.warning("⚠️ 未完成的文件列表：")
            for part_file in part_files:
                reason = self._analyze_failure_reason(part_file)
                logger.warning(f"   - {part_file.name} ({reason})")
        else:
            logger.info("✅ 未发现PART文件，所有下载都已完成")

    def _get_enhanced_ydl_opts(self, base_opts=None):
        """获取增强的yt-dlp配置，避免PART文件产生"""
        enhanced_opts = {
            # 基础配置
            'quiet': False,
            'no_warnings': False,

            # 网络和重试配置 - 避免网络中断导致的PART文件
            'socket_timeout': 60,           # 增加超时时间到60秒
            'retries': 10,                  # 增加重试次数
            'fragment_retries': 10,         # 分片重试次数
            'retry_sleep_functions': {      # 重试间隔配置
                'http': lambda n: min(5 * (2 ** n), 60),  # 指数退避，最大60秒
                'fragment': lambda n: min(2 * (2 ** n), 30),  # 分片重试间隔
            },

            # 下载配置 - 确保文件完整性和断点续传
            'skip_unavailable_fragments': False,  # 不跳过不可用分片，确保完整性
            'abort_on_unavailable_fragment': False,  # 允许部分分片失败，支持断点续传
            'keep_fragments': False,        # 不保留分片，避免临时文件堆积
            'continue_dl': True,            # 启用断点续传
            'part': True,                   # 允许生成.part文件用于断点续传
            'mtime': True,                  # 保持文件修改时间，有助于断点续传

            # 合并配置 - 确保合并成功
            'merge_output_format': 'mp4',   # 强制合并为mp4
            'postprocessor_args': {         # 后处理参数
                'ffmpeg': ['-y']            # ffmpeg强制覆盖输出文件
            },

            # 错误处理配置
            'ignoreerrors': False,          # 不忽略错误，确保问题被发现
            'abort_on_error': False,        # 单个文件错误时不中止整个下载

            # 临时文件配置
            'writeinfojson': False,         # 不写入info.json，减少临时文件
            'writesubtitles': False,        # 不下载字幕，减少复杂性
            'writeautomaticsub': False,     # 不下载自动字幕
        }

        # 合并基础配置
        if base_opts:
            enhanced_opts.update(base_opts)

        # 添加代理配置
        if self.proxy_host:
            enhanced_opts['proxy'] = self.proxy_host

        # 添加cookies配置
        if hasattr(self, 'youtube_cookies_path') and self.youtube_cookies_path and os.path.exists(self.youtube_cookies_path):
            enhanced_opts['cookiefile'] = self.youtube_cookies_path
        elif hasattr(self, 'x_cookies_path') and self.x_cookies_path and os.path.exists(self.x_cookies_path):
            enhanced_opts['cookiefile'] = self.x_cookies_path

        return enhanced_opts

    def _resume_part_files(self, download_path, original_url):
        """断点续传PART文件"""
        from pathlib import Path
        part_files = self._detect_part_files(download_path)
        resumed_count = 0

        if not part_files:
            return 0

        logger.info(f"🔄 发现 {len(part_files)} 个PART文件，尝试断点续传")

        for part_file in part_files:
            try:
                # 获取PART文件信息
                file_size = part_file.stat().st_size
                logger.info(f"📥 断点续传: {part_file.name} (已下载: {file_size / (1024*1024):.1f}MB)")

                # 使用yt-dlp的断点续传功能
                resume_opts = self._get_enhanced_ydl_opts({
                    'outtmpl': str(download_path / '%(title)s.%(ext)s'),
                    'format': 'best[height<=1080]',
                    'continue_dl': True,  # 启用断点续传
                    'part': True,         # 允许PART文件
                })

                import yt_dlp
                with yt_dlp.YoutubeDL(resume_opts) as ydl:
                    ydl.download([original_url])

                resumed_count += 1
                logger.info(f"✅ 断点续传成功: {part_file.name}")

            except Exception as e:
                logger.warning(f"⚠️ 断点续传失败: {part_file.name}, 错误: {e}")
                # 如果断点续传失败，可以选择删除PART文件重新下载
                try:
                    logger.info(f"🗑️ 删除损坏的PART文件: {part_file.name}")
                    part_file.unlink()
                except Exception as del_e:
                    logger.warning(f"⚠️ 删除PART文件失败: {del_e}")

        if resumed_count > 0:
            logger.info(f"✅ 成功断点续传 {resumed_count} 个文件")

        return resumed_count

    def _resume_failed_downloads(self, download_path, original_url, max_retries=2):
        """检测并断点续传失败的下载"""
        part_files = self._detect_part_files(download_path)

        if not part_files:
            return True  # 没有PART文件，下载成功

        if max_retries <= 0:
            logger.warning(f"⚠️ 重试次数已用完，仍有 {len(part_files)} 个未完成文件")
            return False

        logger.info(f"🔄 检测到 {len(part_files)} 个未完成文件，尝试断点续传 (剩余重试: {max_retries})")

        # 尝试断点续传PART文件
        resumed_count = self._resume_part_files(download_path, original_url)

        # 等待一段时间再检查
        import time
        time.sleep(1)

        # 递归检查是否还有PART文件
        remaining_part_files = self._detect_part_files(download_path)

        if not remaining_part_files:
            logger.info("✅ 所有PART文件已成功续传完成")
            return True
        elif len(remaining_part_files) < len(part_files):
            logger.info(f"📈 部分文件续传成功，剩余 {len(remaining_part_files)} 个文件")
            # 继续尝试剩余文件
            return self._resume_failed_downloads(download_path, original_url, max_retries - 1)
        else:
            logger.warning(f"⚠️ 断点续传未能减少PART文件数量，剩余重试: {max_retries - 1}")
            if max_retries > 1:
                return self._resume_failed_downloads(download_path, original_url, max_retries - 1)
            else:
                return False

    def _sanitize_filename(self, filename, max_length=200):
        """清理文件名，去除特殊字符，限制长度"""
        if not filename:
            return "video"

        # 去除特殊字符
        filename = re.sub(r'[\\/:*?"<>|【】]', '_', filename)
        # 去除多余空格
        filename = re.sub(r'\s+', ' ', filename).strip()
        # 去除开头和结尾的特殊字符
        filename = re.sub(r'^[_\s]+|[_\s]+$', '', filename)

        # 如果文件名太长，进行智能截断
        if len(filename) > max_length:
            # 保留扩展名（如果有）
            name, ext = os.path.splitext(filename)
            if ext:
                # 如果有扩展名，保留扩展名，截断主文件名
                max_name_length = max_length - len(ext) - 3  # 3是"..."的长度
                if max_name_length > 0:
                    filename = name[:max_name_length] + "..." + ext
                else:
                    # 如果扩展名太长，只保留扩展名
                    filename = "..." + ext
            else:
                # 没有扩展名，直接截断
                filename = filename[:max_length-3] + "..."

        # 确保文件名不为空
        if not filename or filename.isspace():
            filename = "video"

        return filename

    def _create_gallery_dl_config(self):
        """创建 gallery-dl.conf 配置文件"""
        import json

        config_path = Path(self.download_path / "gallery-dl.conf")

        # 使用 GALLERY_DL_DOWNLOAD_PATH 环境变量，如果没有设置则使用默认值
        gallery_dl_download_path = os.environ.get("GALLERY_DL_DOWNLOAD_PATH")
        if not gallery_dl_download_path:
            # 本地开发环境默认值
            gallery_dl_download_path = str(self.download_path / "gallery")
            logger.info(f"⚠️ 未设置 GALLERY_DL_DOWNLOAD_PATH 环境变量，使用默认值: {gallery_dl_download_path}")
        else:
            logger.info(f"✅ 使用 GALLERY_DL_DOWNLOAD_PATH 环境变量: {gallery_dl_download_path}")
        
        logger.info(f"🎯 使用 GALLERY_DL_DOWNLOAD_PATH: {gallery_dl_download_path}")

        # 从环境变量获取X_COOKIES路径
        x_cookies_env = os.environ.get("X_COOKIES")
        if x_cookies_env:
            cookies_path = x_cookies_env
            logger.info(f"🍪 从环境变量获取X_COOKIES: {cookies_path}")
        else:
            cookies_path = str(self.x_cookies_path) if self.x_cookies_path else None
            logger.info(f"🍪 使用初始化参数中的X cookies: {cookies_path}")

        config = {
            "base-directory": gallery_dl_download_path,
            "extractor": {
                "twitter": {
                    "cookies": cookies_path
                }
            },
            "downloader": {
                "http": {
                    "timeout": 120,
                    "retries": 15,
                    "sleep": 5,
                    "verify": False,
                    "headers": {
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                        "Accept-Encoding": "gzip, deflate, br",
                        "DNT": "1",
                        "Connection": "keep-alive",
                        "Upgrade-Insecure-Requests": "1",
                        "Sec-Fetch-Dest": "document",
                        "Sec-Fetch-Mode": "navigate",
                        "Sec-Fetch-Site": "cross-site",
                        "Sec-Fetch-User": "?1",
                        "Cache-Control": "max-age=0",
                        "Referer": "https://telegra.ph/",
                        "Origin": "https://telegra.ph"
                    },
                    "max_retries": 15,
                    "retry_delay": 5,
                    "connection_timeout": 60,
                    "read_timeout": 120,
                    "chunk_size": 8192,
                    "stream": True,
                    "allow_redirects": True,
                    "max_redirects": 10
                }
            }
        }

        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        logger.info(f"已成功创建 gallery-dl.conf 配置文件: {config_path}")
        logger.info(f"配置文件内容:\n{json.dumps(config, indent=2, ensure_ascii=False)}")


class TelegramBot:
    def __init__(self, token: str, downloader: VideoDownloader):
        self.token = token
        self.downloader = downloader
        self.application = None
        self.bot_id = None
        self.qb_client = None
        
        # 新增：配置持久化 - 在_load_config之前设置
        self.config_path = Path(os.getenv("CONFIG_PATH", "config/settings.json"))
        
        # 加载配置
        self.config = self._load_config()
        self.auto_download_enabled = self.config.get("auto_download_enabled", True)
        self.download_tasks = (
            {}
        )  # 存储下载任务 {task_id: {'task': asyncio.Task, 'cancelled': bool}}
        self.task_lock = asyncio.Lock()  # 用于保护任务字典的锁
        self.user_client: TelegramClient | None = None

        # 新增：B站自动下载全集配置
        self.bilibili_auto_playlist = self.config.get("bilibili_auto_playlist", False)  # 默认关闭自动下载全集

        # qBittorrent 配置 - 只在有配置时才启用
        self.qb_config = {
            "host": os.getenv("QB_HOST"),
            "port": os.getenv("QB_PORT"),
            "username": os.getenv("QB_USERNAME"),
            "password": os.getenv("QB_PASSWORD"),
            "enabled": False,  # 默认禁用
        }

        # 检查是否有完整的 qBittorrent 配置
        if all(
            [
                self.qb_config["host"],
                self.qb_config["port"],
                self.qb_config["username"],
                self.qb_config["password"],
            ]
        ):
            try:
                self.qb_config["port"] = int(self.qb_config["port"])
                self.qb_config["enabled"] = True
                logger.info(f"已配置 qBittorrent: {self.qb_config['host']}:{self.qb_config['port']}")
            except (ValueError, TypeError):
                logger.warning("qBittorrent 端口配置无效，跳过连接")
        else:
            logger.info("未配置 qBittorrent")

        # 新增：权限管理
        self.allowed_user_ids = self._parse_user_ids(os.getenv("TELEGRAM_BOT_ALLOWED_USER_IDS", ""))
        logger.info(f"🔐 允许的用户: {self.allowed_user_ids}")

    def _parse_user_ids(self, user_ids_str: str) -> list:
        """解析用户ID字符串为列表"""
        if not user_ids_str:
            return []
        
        try:
            # 支持逗号、分号、空格分隔的用户ID
            user_ids = []
            for user_id_str in re.split(r"[,;\s]+", user_ids_str.strip()):
                if user_id_str.strip():
                    user_ids.append(int(user_id_str.strip()))
            return user_ids
        except ValueError as e:
            logger.error(f"解析用户ID失败: {e}")
            return []

    def _check_user_permission(self, user_id: int) -> bool:
        """检查用户是否有权限使用机器人"""
        # 如果没有配置允许的用户，则允许所有用户（向后兼容）
        if not self.allowed_user_ids:
            return True
        
        # 检查是否在允许的用户列表中
        return user_id in self.allowed_user_ids

    def _load_config(self):
        """从文件加载配置"""
        try:
            if self.config_path.exists():
                config_data = json.loads(self.config_path.read_text())
                logger.info(
                    f"从 {self.config_path} 加载配置, B站多P自动下载模式: {config_data.get('bilibili_auto_playlist', False)}"
                )
                return config_data
            else:
                # 如果配置文件不存在，创建默认配置
                default_config = {
                    "auto_download_enabled": True,
                    "bilibili_auto_playlist": False
                }
                self._save_config_sync(default_config)
                return default_config
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            # 返回默认配置
            return {
                "auto_download_enabled": True,
                "bilibili_auto_playlist": False
            }

    def _save_config_sync(self, config_data=None):
        """同步保存配置到文件"""
        try:
            if config_data is None:
                config_data = {
                    "auto_download_enabled": self.auto_download_enabled,
                    "bilibili_auto_playlist": self.bilibili_auto_playlist
                }
            
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(json.dumps(config_data, indent=4))
            logger.info(f"配置已保存到 {self.config_path}")
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")

    async def _save_config_async(self):
        """异步保存配置到文件"""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._save_config_sync)

    def _make_progress_bar(self, percent: float) -> str:
        """生成进度条"""
        bar_length = 20
        # 确保percent在0-100范围内
        percent = max(0, min(percent, 100))
        filled_length = int(bar_length * percent / 100)
        bar = "█" * filled_length + "░" * (bar_length - filled_length)
        return bar

    def _escape_markdown(self, text: str) -> str:
        """转义Markdown特殊字符"""
        if not text:
            return text

        # 需要转义的特殊字符
        special_chars = [
            "_",
            "*",
            "[",
            "]",
            "(",
            ")",
            "~",
            "`",
            ">",
            "#",
            "+",
            "-",
            "=",
            "|",
            "{",
            "}",
            ".",
            "!",
        ]

        escaped_text = text
        for char in special_chars:
            escaped_text = escaped_text.replace(char, f"\\{char}")

        return escaped_text

    async def post_init(self, application: Application):
        """在应用启动后运行的初始化任务, 获取机器人自身 ID"""
        bot_info = await application.bot.get_me()
        self.bot_id = bot_info.id
        logger.info(f"机器人已启动，用户名为: @{bot_info.username} (ID: {self.bot_id})")

    def _connect_qbittorrent(self):
        """连接到 qBittorrent 客户端"""
        try:
            # 检查是否启用了 qBittorrent
            if not self.qb_config["enabled"]:
                return

            logger.info(
                f"正在连接 qBittorrent: {self.qb_config['host']}:{self.qb_config['port']}"
            )

            # 创建客户端
            self.qbit_client = qbittorrentapi.Client(
                host=self.qb_config["host"],
                port=self.qb_config["port"],
                username=self.qb_config["username"],
                password=self.qb_config["password"],
                VERIFY_WEBUI_CERTIFICATE=False,  # 禁用SSL证书验证
                REQUESTS_ARGS={"timeout": 10},  # 设置10秒超时
            )

            # 尝试登录
            self.qbit_client.auth_log_in()

            # 检查连接状态
            if not self.qbit_client.is_logged_in:
                logger.error("qBittorrent 连接失败")
                self.qbit_client = None
                return

            # 获取 qBittorrent 版本信息
            try:
                version_info = self.qbit_client.app.version
                logger.info(f"qBittorrent 连接成功 (版本: {version_info})")
            except Exception as e:
                logger.info("qBittorrent 连接成功")

            # 创建标签
            try:
                self.qbit_client.torrents_create_tags(tags="savextube")
            except Exception:
                pass

        except qbittorrentapi.LoginFailed as e:
            logger.error("qBittorrent 连接失败: 用户名或密码错误")
            self.qbit_client = None
        except qbittorrentapi.APIConnectionError as e:
            logger.error("qBittorrent 连接失败: 无法连接到服务器")
            self.qbit_client = None
        except Exception as e:
            logger.error(f"qBittorrent 连接失败: {e}")
            self.qbit_client = None

    def _is_magnet_link(self, text: str) -> bool:
        magnet_pattern = r"magnet:\?xt=urn:btih:[a-fA-F0-9]{32,40}"
        return bool(re.search(magnet_pattern, text))

    def _extract_magnet_links(self, text: str):
        # 支持多条磁力链接，忽略前后其它文字
        magnet_pattern = r"(magnet:\?xt=urn:btih:[a-fA-F0-9]{32,40}[^\s]*)"
        return re.findall(magnet_pattern, text)

    async def add_magnet_to_qb(self, magnet_link: str) -> bool:
        """添加磁力链接到 qBittorrent"""
        try:
            # 检查 qBittorrent 客户端是否可用
            if not self.qbit_client:
                logger.error("qBittorrent 客户端未连接")
                return False

            # 检查登录状态
            if not self.qbit_client.is_logged_in:
                logger.error("qBittorrent 未登录")
                return False

            # 验证磁力链接格式
            if not self._is_magnet_link(magnet_link):
                logger.error(f"无效的磁力链接格式: {magnet_link}")
                return False

            logger.info(f"正在添加磁力链接到 qBittorrent: {magnet_link[:50]}...")

            # 添加磁力链接
            self.qbit_client.torrents_add(urls=magnet_link, tags="savextube")

            logger.info("✅ 成功添加磁力链接到 qBittorrent")
            return True

        except qbittorrentapi.APIConnectionError as e:
            logger.error(f"qBittorrent API 连接错误: {e}")
            return False
        except qbittorrentapi.LoginFailed as e:
            logger.error(f"qBittorrent 登录失败: {e}")
            return False
        except Exception as e:
            logger.error(f"添加磁力链接失败: {e}")
            logger.error(f"错误类型: {type(e).__name__}")
            return False

    async def add_torrent_file_to_qb(self, torrent_data: bytes, filename: str) -> bool:
        """添加种子文件到 qBittorrent"""
        try:
            # 检查 qBittorrent 客户端是否可用
            if not self.qbit_client:
                logger.error("qBittorrent 客户端未连接")
                return False

            # 检查登录状态
            if not self.qbit_client.is_logged_in:
                logger.error("qBittorrent 未登录")
                return False

            logger.info(f"正在添加种子文件到 qBittorrent: {filename}")

            # 将字节数据写入临时文件
            import tempfile
            import os
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.torrent') as temp_file:
                temp_file.write(torrent_data)
                temp_file_path = temp_file.name

            try:
                # 使用临时文件路径添加种子
                self.qbit_client.torrents_add(torrent_files=temp_file_path, tags="savextube")
                logger.info("✅ 成功添加种子文件到 qBittorrent")
                return True
            finally:
                # 清理临时文件
                try:
                    os.unlink(temp_file_path)
                except Exception as e:
                    logger.warning(f"清理临时文件失败: {e}")

        except qbittorrentapi.APIConnectionError as e:
            logger.error(f"qBittorrent API 连接错误: {e}")
            return False
        except qbittorrentapi.LoginFailed as e:
            logger.error(f"qBittorrent 登录失败: {e}")
            return False
        except Exception as e:
            logger.error(f"添加种子文件失败: {e}")
            logger.error(f"错误类型: {type(e).__name__}")
            return False

    def _clean_filename_for_display(self, filename):
        """清理文件名用于显示"""
        try:
            # 移除时间戳前缀如果存在
            import re

            if re.match(r"^\d{10}_", filename):
                display_name = filename[11:]
            else:
                display_name = filename

            # 如果文件名太长，进行智能截断
            if len(display_name) > 35:
                name, ext = os.path.splitext(display_name)
                display_name = name[:30] + "..." + ext

            return display_name
        except BaseException:
            return filename if len(filename) <= 35 else filename[:32] + "..."

    def _get_resolution_quality(self, resolution):
        """根据分辨率生成质量标识"""
        if not resolution or resolution == '未知':
            return ''
        
        # 提取分辨率数字
        import re
        match = re.search(r'(\d+)x(\d+)', resolution)
        if not match:
            return ''
        
        width = int(match.group(1))
        height = int(match.group(2))
        
        # 根据高度判断质量
        if height >= 4320:
            return ' (8K)'
        elif height >= 2160:
            return ' (4K)'
        elif height >= 1440:
            return ' (2K)'
        elif height >= 1080:
            return ' (1080p)'
        elif height >= 720:
            return ' (720p)'
        elif height >= 480:
            return ' (480p)'
        elif height >= 360:
            return ' (360p)'
        else:
            return ' (低画质)'

    def _create_progress_bar(self, percent: float, length: int = 20) -> str:
        """创建进度条"""
        filled_length = int(length * percent / 100)
        bar = "█" * filled_length + "░" * (length - filled_length)
        return bar

    def _signal_handler(self, signum, frame):
        """处理系统信号"""
        logger.info(f"收到信号 {signum}，正在优雅关闭...")
        if self.user_client:
            asyncio.create_task(self.user_client.disconnect())
        self.executor.shutdown(wait=True)
        sys.exit(0)

    def _setup_handlers(self):
        """设置所有的命令和消息处理器"""
        if not self.application:
            return

        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("version", self.version_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        # self.application.add_handler(CommandHandler("sxt", self.sxt_command))
        # # 已删除：sxt命令处理器
        self.application.add_handler(CommandHandler("settings", self.settings_command))
        self.application.add_handler(
            CallbackQueryHandler(self.settings_button_handler, pattern="toggle_autop")
        )
        self.application.add_handler(
            CallbackQueryHandler(self.cancel_task_callback, pattern="cancel:")
        )
        # 统一的媒体处理器，明确指向新函数
        media_filter = (
            filters.AUDIO | filters.VIDEO | filters.Document.ALL
        ) & ~filters.COMMAND
        # self.application.add_handler(MessageHandler(media_filter,
        # self.handle_media)) # 禁用旧的处理器
        self.application.add_handler(
            MessageHandler(media_filter, self.download_user_media)
        )  # 启用新处理器

        # 文本消息处理器 - 保持不变
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

        # 错误处理器
        self.application.add_error_handler(self.error_handler)
        logger.info("所有处理器已设置。")

    async def run(self):
        """启动机器人和所有客户端"""
        # 1. 连接 qBittorrent
        self._connect_qbittorrent()
        # 2. 初始化并连接 Telethon 客户端
        api_id = os.getenv("TELEGRAM_BOT_API_ID")
        api_hash = os.getenv("TELEGRAM_BOT_API_HASH")
        session_string = os.getenv("TELEGRAM_SESSION_STRING")
        logger.info("--- Telethon 配置诊断 ---")
        logger.info(f"读取 TELEGRAM_BOT_API_ID: {'已找到' if api_id else '未找到'}")
        logger.info(
            f"读取 TELEGRAM_BOT_API_HASH: {'已找到' if api_hash else '未找到'}"
        )
        logger.info(
            f"读取 TELEGRAM_SESSION_STRING: {'已找到' if session_string else '未找到'}"
        )
        logger.info("--------------------------")
        if all([api_id, api_hash, session_string]):
            try:
                self.user_client = TelegramClient(
                    StringSession(session_string), int(api_id), api_hash
                )
                if self.downloader.proxy_host:
                    p_url = urlparse(self.downloader.proxy_host)
                    proxy_config = (p_url.scheme, p_url.hostname, p_url.port)
                    self.user_client.set_proxy(proxy_config)
                    logger.info(
                        f"Telethon 客户端使用代理: {self.downloader.proxy_host}"
                    )
                logger.info("正在连接 Telethon 客户端...")
                await self.user_client.start()
                logger.info("Telethon 客户端连接成功。")
            except Exception as e:
                logger.error(f"Telethon 客户端启动失败: {e}", exc_info=True)
                self.user_client = None
        else:
            logger.warning("Telethon 未完整配置，媒体转存功能将不可用。")
        # 3. 设置并启动 PTB Application
        if self.downloader.proxy_host:
            logger.info(f"Telegram Bot 使用代理: {self.downloader.proxy_host}")
            self.application = (
                Application.builder().token(self.token).proxy(self.downloader.proxy_host).post_init(self.post_init).build()
            )
        else:
            logger.info("Telegram Bot 直接连接")
            self.application = (
                Application.builder().token(self.token).post_init(self.post_init).build()
            )
        self._setup_handlers()

        logger.info("启动 Telegram Bot (PTB)...")

        # 增强的网络重试机制
        max_retries = int(os.getenv("TELEGRAM_MAX_RETRIES", "10"))
        base_delay = float(os.getenv("TELEGRAM_BASE_DELAY", "5.0"))
        max_delay = float(os.getenv("TELEGRAM_MAX_DELAY", "300.0"))

        retry_count = 0
        while retry_count <= max_retries:
            try:
                async with self.application:
                    await self.application.initialize()
                    await self.application.start()

                    # 配置更强的网络参数
                    await self.application.updater.start_polling(
                        timeout=30,  # 增加超时时间
                        read_timeout=30,
                        write_timeout=30,
                        connect_timeout=30,
                        pool_timeout=30
                    )

                    logger.info("机器人已成功启动并正在运行。")

                    # 添加定期健康检查和网络监控
                    if os.getenv("ENABLE_HEALTH_CHECK", "true").lower() == "true":
                        asyncio.create_task(self._periodic_health_check())
                        asyncio.create_task(self._network_monitor())
                        asyncio.create_task(self._keep_alive_heartbeat())

                    await asyncio.Event().wait()
                    break  # 成功启动，退出重试循环

            except (NetworkError, TimedOut, RetryAfter, httpx.RemoteProtocolError,
                   httpx.ConnectError, httpx.TimeoutException, ConnectionError) as e:
                retry_count += 1
                if retry_count <= max_retries:
                    # 计算指数退避延迟
                    delay = min(base_delay * (2 ** (retry_count - 1)), max_delay)
                    logger.warning(f"🌐 Telegram Bot网络错误: {e}")
                    logger.warning(f"🔄 {delay:.1f}秒后重试 ({retry_count}/{max_retries})")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"❌ Telegram Bot网络连接失败，已达到最大重试次数")
                    raise e
            except Exception as e:
                logger.error(f"❌ Telegram Bot启动失败: {e}")
                raise e

    async def _periodic_health_check(self):
        """定期健康检查，监控网络连接状态并自动恢复"""
        check_interval = int(os.getenv("HEALTH_CHECK_INTERVAL", "30"))  # 缩短到30秒检查一次
        max_failures = int(os.getenv("HEALTH_CHECK_MAX_FAILURES", "3"))  # 最大失败次数
        failure_count = 0
        last_success_time = time.time()

        while True:
            try:
                await asyncio.sleep(check_interval)

                # 检查 Telegram API 连接
                try:
                    await self.application.bot.get_me()
                    if failure_count > 0:
                        logger.info(f"🟢 网络连接已恢复！连续失败 {failure_count} 次后恢复正常")
                    failure_count = 0  # 重置失败计数
                    last_success_time = time.time()
                    logger.debug("🟢 健康检查通过 - Telegram API 连接正常")

                except Exception as e:
                    failure_count += 1
                    current_time = time.time()
                    offline_duration = current_time - last_success_time

                    logger.warning(f"🟡 健康检查失败 ({failure_count}/{max_failures}): {e}")
                    logger.warning(f"⏱️ 离线时长: {offline_duration:.0f}秒")

                    if failure_count >= max_failures:
                        logger.error(f"🔴 健康检查连续失败 {max_failures} 次，尝试重启Bot连接")

                        # 尝试重启Bot连接
                        try:
                            await self._restart_bot_connection()
                            logger.info("✅ Bot连接重启成功")
                            failure_count = 0  # 重置计数器
                        except Exception as restart_error:
                            logger.error(f"❌ Bot连接重启失败: {restart_error}")
                            # 继续监控，不要停止健康检查

            except Exception as e:
                logger.error(f"❌ 健康检查异常: {e}")
                await asyncio.sleep(10)  # 异常时短暂等待后继续

    async def _restart_bot_connection(self):
        """重启Bot连接"""
        logger.info("🔄 开始重启Bot连接...")

        try:
            # 停止当前的polling
            if self.application.updater.running:
                await self.application.updater.stop()
                logger.info("📴 已停止当前polling")

            # 等待一段时间
            await asyncio.sleep(5)

            # 重新启动polling
            await self.application.updater.start_polling(
                timeout=30,
                read_timeout=30,
                write_timeout=30,
                connect_timeout=30,
                pool_timeout=30
            )
            logger.info("📡 已重新启动polling")

        except Exception as e:
            logger.error(f"❌ 重启Bot连接失败: {e}")
            raise e

    async def _network_monitor(self):
        """网络状态监控，检测长时间的网络中断"""
        monitor_interval = int(os.getenv("NETWORK_MONITOR_INTERVAL", "120"))  # 2分钟检查一次
        max_offline_time = int(os.getenv("MAX_OFFLINE_TIME", "600"))  # 最大离线时间10分钟

        last_successful_check = time.time()
        consecutive_failures = 0

        while True:
            try:
                await asyncio.sleep(monitor_interval)

                # 测试网络连接
                network_ok = await test_network_connectivity()
                current_time = time.time()

                if network_ok:
                    if consecutive_failures > 0:
                        offline_duration = current_time - last_successful_check
                        logger.info(f"🟢 网络连接已恢复！离线时长: {offline_duration:.0f}秒")
                    consecutive_failures = 0
                    last_successful_check = current_time
                else:
                    consecutive_failures += 1
                    offline_duration = current_time - last_successful_check

                    logger.warning(f"🔴 网络监控检测到连接问题 (连续失败 {consecutive_failures} 次)")
                    logger.warning(f"⏱️ 离线时长: {offline_duration:.0f}秒")

                    # 如果离线时间过长，尝试重启整个应用
                    if offline_duration > max_offline_time:
                        logger.error(f"💀 网络离线时间超过 {max_offline_time} 秒，考虑重启应用")
                        # 这里可以添加重启逻辑，但要谨慎

            except Exception as e:
                logger.error(f"❌ 网络监控异常: {e}")
                await asyncio.sleep(30)  # 异常时短暂等待

    async def _keep_alive_heartbeat(self):
        """保持连接活跃的心跳机制"""
        heartbeat_interval = int(os.getenv("HEARTBEAT_INTERVAL", "300"))  # 5分钟发送一次心跳

        while True:
            try:
                await asyncio.sleep(heartbeat_interval)

                # 发送一个轻量级的API调用来保持连接活跃
                try:
                    await self.application.bot.get_me()
                    logger.debug("💓 心跳保持连接活跃")
                except Exception as e:
                    logger.warning(f"💔 心跳失败: {e}")
                    # 心跳失败不需要特殊处理，健康检查会处理

            except Exception as e:
                logger.error(f"❌ 心跳机制异常: {e}")
                await asyncio.sleep(60)  # 异常时等待1分钟

    async def version_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /version 命令 - 显示版本信息"""
        user_id = update.message.from_user.id
        
        # 权限检查
        if not self._check_user_permission(user_id):
            await update.message.reply_text("❌ 您没有权限使用此机器人")
            return
        
        update_heartbeat()
        try:
            version_text = (
                f"⚙️ <b>系统版本信息</b>\n\n"
                f"  - <b>机器人</b>: <code>{BOT_VERSION}</code>"
            )
            await update.message.reply_text(version_text, parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"❌ 获取版本信息失败: {e}")

    async def formats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /formats 命令 - 检查视频格式"""
        user_id = update.message.from_user.id
        
        # 权限检查
        if not self._check_user_permission(user_id):
            await update.message.reply_text("❌ 您没有权限使用此机器人")
            return
        
        update_heartbeat()

        try:
            # 获取用户发送的URL
            if not context.args:
                await update.message.reply_text(
                    """格式检查命令
使用方法：
/formats <视频链接>
示例：
/formats https://www.youtube.com/watch?v=xxx
此命令会显示视频的可用格式，帮助调试下载问题。"""
                )
                return

            url = context.args[0]

            # 验证URL
            if not url.startswith(("http://", "https://")):
                await update.message.reply_text("请提供有效的视频链接")
                return

            check_message = await update.message.reply_text("正在检查视频格式...")

            # 检查格式
            result = self.downloader.check_video_formats(url)

            if result["success"]:
                formats_text = f"""视频格式信息
标题：{result['title']}
可用格式（前10个）：
"""
                for i, fmt in enumerate(result["video_formats"], 1):
                    size_info = ""
                    if fmt["filesize"] and fmt["filesize"] > 0:
                        size_mb = fmt["filesize"] / (1024 * 1024)
                        size_info = f" ({size_mb:.1f}MB)"

                    formats_text += f"{i}. ID: {fmt['id']} | {fmt['ext']} | {fmt['quality']}{size_info}\n"

                formats_text += "\n音频格式（前5个）：\n"
                for i, fmt in enumerate(result["audio_formats"], 1):
                    size_info = ""
                    if fmt["filesize"] and fmt["filesize"] > 0:
                        size_mb = fmt["filesize"] / (1024 * 1024)
                        size_info = f" ({size_mb:.1f}MB)"

                    formats_text += f"{i}. ID: {fmt['id']} | {fmt['ext']} | {fmt['quality']}{size_info}\n"

                formats_text += "\n如果下载失败，可以尝试其他视频或报告此信息。"

                await check_message.edit_text(formats_text)
            else:
                await check_message.edit_text(f"格式检查失败: {result['error']}")

        except Exception as e:
            await update.message.reply_text(f"格式检查出错: {str(e)}")

    async def cleanup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /cleanup 命令"""
        user_id = update.message.from_user.id
        
        # 权限检查
        if not self._check_user_permission(user_id):
            await update.message.reply_text("❌ 您没有权限使用此机器人")
            return
        
        update_heartbeat()

        cleanup_message = await update.message.reply_text("开始清理重复文件...")

        try:
            cleaned_count = self.downloader.cleanup_duplicates()
            if cleaned_count > 0:
                completion_text = f"""清理完成!
删除了 {cleaned_count} 个重复文件
释放了存储空间"""
            else:
                completion_text = "清理完成! 未发现重复文件"

            await cleanup_message.edit_text(completion_text)
        except Exception as e:
            await cleanup_message.edit_text(f"清理失败: {str(e)}")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /status 命令"""
        user_id = update.message.from_user.id
        
        # 权限检查
        if not self._check_user_permission(user_id):
            await update.message.reply_text("❌ 您没有权限使用此机器人")
            return
        
        update_heartbeat()
        try:
            # 统计文件
            video_extensions = ["*.mp4", "*.mkv", "*.webm", "*.mov", "*.avi"]
            x_files = []
            if self.downloader.x_download_path.exists():
                for ext in video_extensions:
                    x_files.extend(self.downloader.x_download_path.glob(ext))
            youtube_files = []
            if self.downloader.youtube_download_path.exists():
                for ext in video_extensions:
                    youtube_files.extend(
                        self.downloader.youtube_download_path.glob(ext)
                    )
            bilibili_files = []
            if self.downloader.bilibili_download_path.exists():
                for ext in video_extensions:
                    bilibili_files.extend(
                        self.downloader.bilibili_download_path.glob(ext)
                    )
            douyin_files = []
            if self.downloader.douyin_download_path.exists():
                for ext in video_extensions:
                    douyin_files.extend(
                        self.downloader.douyin_download_path.glob(ext)
                    )
            total_files = len(x_files) + len(youtube_files) + len(bilibili_files) + len(douyin_files)
            status_text = (
                f"📊 <b>下载状态</b>\n\n"
                f"  - <b>X (Twitter)</b>: {len(x_files)} 个文件\n"
                f"  - <b>YouTube</b>: {len(youtube_files)} 个文件\n"
                f"  - <b>Bilibili</b>: {len(bilibili_files)} 个文件\n"
                f"  - <b>总计</b>: {total_files} 个文件\n\n"
            )
            # qBittorrent 状态
            if self.qbit_client and self.qbit_client.is_logged_in:
                torrents = self.qbit_client.torrents_info(tag="savextube")
                active_torrents = [
                    t for t in torrents if t.state not in ["completed", "pausedUP"]
                ]
                status_text += f"<b>qBittorrent 任务</b>: {len(torrents)} (活动: {len(active_torrents)})"
            else:
                status_text += "<b>qBittorrent</b>: 未连接"
            await update.message.reply_text(status_text, parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"❌ 获取状态失败: {str(e)}")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理文本消息，主要是视频链接"""
        user_id = update.message.from_user.id
        
        # 权限检查
        if not self._check_user_permission(user_id):
            await update.message.reply_text("❌ 您没有权限使用此机器人")
            return
        
        # 更新心跳
        update_heartbeat()

        message = update.message
        url = None
        
        # 检查消息类型并提取URL
        if message.text and message.text.startswith("http"):
            # 普通文本链接
            url = message.text
        elif message.text and (message.text.startswith("magnet:") or message.text.endswith(".torrent")):
            # 磁力链接或种子文件 - 新增支持
            url = message.text
        elif message.text and "magnet:" in message.text:
            # 从混合文本中提取磁力链接
            import re
            magnet_match = re.search(r'magnet:\?xt=urn:btih:[a-fA-F0-9]{32,40}[^\s]*', message.text)
            if magnet_match:
                url = magnet_match.group(0)
                logger.info(f"🔧 从混合文本中提取磁力链接: {message.text} -> {url}")
        elif message.text and ".torrent" in message.text:
            # 从混合文本中提取种子文件链接
            import re
            torrent_match = re.search(r'https?://[^\s]*\.torrent[^\s]*', message.text)
            if torrent_match:
                url = torrent_match.group(0)
                logger.info(f"🔧 从混合文本中提取种子文件链接: {message.text} -> {url}")
        elif message.entities:
            # 检查是否有链接实体
            for entity in message.entities:
                if entity.type == "url":
                    url = message.text[entity.offset:entity.offset + entity.length]
                    break
                elif entity.type == "text_link":
                    url = entity.url
                    break
        elif message.text and ("http" in message.text or "tp://" in message.text or "kuaishou.com" in message.text or "douyin.com" in message.text):
            # 尝试从文本中提取URL，包括修复错误的协议和智能提取
            import re

            # 首先使用智能提取方法
            extracted_urls = self.downloader.extract_urls_from_text(message.text)
            if extracted_urls:
                url = extracted_urls[0]  # 使用第一个找到的URL
                logger.info(f"🔧 智能提取URL: {message.text} -> {url}")
            else:
                # 备选方案：修复错误的协议
                fixed_text = message.text.replace("tp://", "http://")
                url_match = re.search(r'https?://[^\s]+', fixed_text)
                if url_match:
                    url = url_match.group(0)
                    logger.info(f"🔧 修复了错误的URL协议: {message.text} -> {url}")
        
        # 检查转发消息
        if not url and message.forward_from_chat:
            # 处理转发的频道/群组消息
            if message.text and ("http" in message.text or "tp://" in message.text or "magnet:" in message.text):
                import re
                # 首先尝试提取磁力链接
                magnet_match = re.search(r'magnet:\?xt=urn:btih:[a-fA-F0-9]{32,40}[^\s]*', message.text)
                if magnet_match:
                    url = magnet_match.group(0)
                    logger.info(f"🔧 转发消息中提取磁力链接: {message.text} -> {url}")
                else:
                    # 尝试提取种子文件链接
                    torrent_match = re.search(r'https?://[^\s]*\.torrent[^\s]*', message.text)
                    if torrent_match:
                        url = torrent_match.group(0)
                        logger.info(f"🔧 转发消息中提取种子文件链接: {message.text} -> {url}")
                    else:
                        # 修复错误的协议
                        fixed_text = message.text.replace("tp://", "http://")
                        url_match = re.search(r'https?://[^\s]+', fixed_text)
                        if url_match:
                            url = url_match.group(0)
                            logger.info(f"🔧 转发消息中修复了错误的URL协议: {message.text} -> {url}")
        
        # 检查回复的消息
        if not url and message.reply_to_message:
            reply_msg = message.reply_to_message
            if reply_msg.text and ("http" in reply_msg.text or "tp://" in reply_msg.text or "magnet:" in reply_msg.text):
                import re
                # 首先尝试提取磁力链接
                magnet_match = re.search(r'magnet:\?xt=urn:btih:[a-fA-F0-9]{32,40}[^\s]*', reply_msg.text)
                if magnet_match:
                    url = magnet_match.group(0)
                    logger.info(f"🔧 回复消息中提取磁力链接: {reply_msg.text} -> {url}")
                else:
                    # 尝试提取种子文件链接
                    torrent_match = re.search(r'https?://[^\s]*\.torrent[^\s]*', reply_msg.text)
                    if torrent_match:
                        url = torrent_match.group(0)
                        logger.info(f"🔧 回复消息中提取种子文件链接: {reply_msg.text} -> {url}")
                    else:
                        # 修复错误的协议
                        fixed_text = reply_msg.text.replace("tp://", "http://")
                        url_match = re.search(r'https?://[^\s]+', fixed_text)
                        if url_match:
                            url = url_match.group(0)
                            logger.info(f"🔧 回复消息中修复了错误的URL协议: {reply_msg.text} -> {url}")
            elif reply_msg.entities:
                for entity in reply_msg.entities:
                    if entity.type == "url":
                        url = reply_msg.text[entity.offset:entity.offset + entity.length]
                        break
                    elif entity.type == "text_link":
                        url = entity.url
                        break
        
        if not url:
            await message.reply_text("🤔 请发送一个有效的链接或包含链接的消息。\n\n💡 提示：\n• 直接发送链接\n• 转发包含链接的消息\n• 回复包含链接的消息")
            return
            
        # 添加调试日志
        logger.info(f"收到消息: {url}")

        # 立即发送快速响应
        status_message = await message.reply_text("🚀 正在处理您的请求...")

        # 异步处理下载任务，不阻塞响应
        asyncio.create_task(
            self._process_download_async(update, context, url, status_message)
        )

    async def handle_qbittorrent_links(self, update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, status_message):
        """专门处理qBittorrent相关的链接（磁力链接和种子文件）"""
        try:
            # 检查是否为磁力链接或种子文件
            if self._is_magnet_link(url) or url.endswith(".torrent"):
                logger.info(f"🔗 检测到磁力链接或种子文件: {url[:50]}...")
                await status_message.edit_text("🔗 正在添加到 qBittorrent...")
                
                # 尝试添加到 qBittorrent
                success = await self.add_magnet_to_qb(url)
                
                if success:
                    await status_message.edit_text(
                        "✅ **磁力链接/种子文件已成功添加到 qBittorrent！**\n\n"
                        "📝 任务已添加到下载队列\n"
                        "🔍 您可以在 qBittorrent 中查看下载进度\n"
                        "💡 提示：下载完成后文件会保存到配置的下载目录"
                    )
                else:
                    await status_message.edit_text(
                        "❌ **添加磁力链接/种子文件失败**\n\n"
                        "可能的原因：\n"
                        "• qBittorrent 未连接或未配置\n"
                        "• 链接格式无效\n"
                        "• qBittorrent 服务异常\n\n"
                        "请检查 qBittorrent 配置和连接状态"
                    )
                return True  # 表示已处理
            
            # 检查是否为媒体消息，从媒体消息文本中提取磁力链接
            message = update.message
            if message.photo or message.video or message.document or message.audio:
                if message.caption:
                    caption_text = message.caption
                    logger.info(f"🔍 检测到媒体消息，文本内容: {caption_text}")
                    
                    # 从媒体消息文本中提取磁力链接
                    import re
                    magnet_match = re.search(r'magnet:\?xt=urn:btih:[a-fA-F0-9]{32,40}[^\s]*', caption_text)
                    if magnet_match:
                        magnet_url = magnet_match.group(0)
                        logger.info(f"🔧 从媒体消息文本中提取磁力链接: {caption_text} -> {magnet_url}")
                        await status_message.edit_text("🔗 正在添加到 qBittorrent...")
                        
                        # 尝试添加到 qBittorrent
                        success = await self.add_magnet_to_qb(magnet_url)
                        
                        if success:
                            await status_message.edit_text(
                                "✅ **磁力链接已成功添加到 qBittorrent！**\n\n"
                                "📝 任务已添加到下载队列\n"
                                "🔍 您可以在 qBittorrent 中查看下载进度\n"
                                "💡 提示：下载完成后文件会保存到配置的下载目录"
                            )
                        else:
                            await status_message.edit_text(
                                "❌ **添加磁力链接失败**\n\n"
                                "可能的原因：\n"
                                "• qBittorrent 未连接或未配置\n"
                                "• 链接格式无效\n"
                                "• qBittorrent 服务异常\n\n"
                                "请检查 qBittorrent 配置和连接状态"
                            )
                        return True  # 表示已处理
                    
                    # 尝试提取种子文件链接
                    torrent_match = re.search(r'https?://[^\s]*\.torrent[^\s]*', caption_text)
                    if torrent_match:
                        torrent_url = torrent_match.group(0)
                        logger.info(f"🔧 从媒体消息文本中提取种子文件链接: {caption_text} -> {torrent_url}")
                        await status_message.edit_text("🔗 正在添加到 qBittorrent...")
                        
                        # 尝试添加到 qBittorrent
                        success = await self.add_magnet_to_qb(torrent_url)
                        
                        if success:
                            await status_message.edit_text(
                                "✅ **种子文件已成功添加到 qBittorrent！**\n\n"
                                "📝 任务已添加到下载队列\n"
                                "🔍 您可以在 qBittorrent 中查看下载进度\n"
                                "💡 提示：下载完成后文件会保存到配置的下载目录"
                            )
                        else:
                            await status_message.edit_text(
                                "❌ **添加种子文件失败**\n\n"
                                "可能的原因：\n"
                                "• qBittorrent 未连接或未配置\n"
                                "• 链接格式无效\n"
                                "• qBittorrent 服务异常\n\n"
                                "请检查 qBittorrent 配置和连接状态"
                            )
                        return True  # 表示已处理
            
            return False  # 表示未处理，继续其他流程
        except Exception as e:
            logger.error(f"处理qBittorrent链接时发生错误: {e}", exc_info=True)
            await status_message.edit_text(f"❌ 处理qBittorrent链接时发生错误: {str(e)}")
            return True  # 表示已处理（出错也算处理了）

    async def _process_download_async(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        url: str,
        status_message,
    ):
        """异步处理下载任务"""
        # 在方法开始时定义chat_id，确保在所有异常处理路径中都可访问
        chat_id = status_message.chat_id
        
        try:
            # 首先尝试处理qBittorrent相关链接
            if await self.handle_qbittorrent_links(update, context, url, status_message):
                return  # 如果是qB相关链接，处理完就返回
            
            # 检查是否为B站自定义列表URL
            is_list, uid, list_id = self.downloader.is_bilibili_list_url(url)
            if is_list:
                logger.info(f"🔧 检测到B站用户列表URL: 用户{uid}, 列表{list_id}")
            # 链接有效性检查
            platform_name = self.downloader.get_platform_name(url)
            if platform_name == "未知":
                await status_message.edit_text("🙁 抱歉，暂不支持您发送的网站。")
                return
            
            # 获取平台信息用于后续判断
            platform = platform_name.lower()
        except Exception as e:
            logger.error(f"处理下载时发生意外错误: {e}", exc_info=True)
            await context.bot.edit_message_text(
                text=f"❌ 处理下载时发生内部错误：\n`{self._escape_markdown(str(e))}`",
                chat_id=chat_id,
                message_id=status_message.message_id,
                parse_mode="MarkdownV2",
            )
            return

        # 缓存上次发送的内容，避免重复发送
        last_progress_text = {"text": None}
        
        # --- 进度回调 ---
        last_update_time = {"time": time.time()}
        last_progress_percent = {"value": 0}
        progress_state = {"last_stage": None, "last_percent": 0, "finished_shown": False}  # 跟踪上一次的状态和是否已显示完成
        last_progress_text = {"text": ""}  # 跟踪上一次的文本内容
        
        # 创建增强版的消息更新器函数，支持传递 status_message 和 context 给 single_video_progress_hook
        # 增加对B站多P下载的支持，但保持YouTube功能完全不变
        async def message_updater(text_or_dict, bilibili_progress_data=None):
            try:
                logger.info(f"🔍 message_updater 被调用，参数类型: {type(text_or_dict)}")
                logger.info(f"🔍 message_updater 参数内容: {text_or_dict}")
                
                # 如果已经显示完成状态，忽略所有后续调用
                if progress_state["finished_shown"]:
                    logger.info("下载已完成，忽略message_updater后续调用")
                    return
                
                # 处理字符串类型，避免重复发送相同内容
                if isinstance(text_or_dict, str):
                    if text_or_dict == last_progress_text["text"]:
                        logger.info("🔍 跳过重复内容")
                        return  # 跳过重复内容
                    last_progress_text["text"] = text_or_dict
                    await status_message.edit_text(text_or_dict)
                    return
                
                # 检查是否为字典类型（来自progress_hook的进度数据）
                if isinstance(text_or_dict, dict):
                    logger.info(f"🔍 检测到字典类型，状态: {text_or_dict.get('status')}")
                    
                    # 记录文件名（用于文件查找）
                    if text_or_dict.get("status") == "finished":
                        filename = text_or_dict.get('filename', '')
                        if filename:
                            # 如果提供了bilibili_progress_data，记录B站下载的文件
                            if bilibili_progress_data is not None:
                                if 'downloaded_files' not in bilibili_progress_data:
                                    bilibili_progress_data['downloaded_files'] = []
                                bilibili_progress_data['downloaded_files'].append(filename)
                                logger.info(f"📝 B站文件记录: {filename}")
                            else:
                                # YouTube或其他平台的处理保持不变
                                logger.info(f"📝 检测到finished状态，文件名: {filename}")
                    
                    if text_or_dict.get("status") == "finished":
                        # 对于finished状态，不调用update_progress，避免显示错误的进度信息
                        logger.info("🔍 检测到finished状态，跳过update_progress调用")
                        return
                    elif text_or_dict.get("status") == "downloading":
                        # 这是来自progress_hook的下载进度数据
                        logger.info("🔍 检测到下载进度数据，准备调用 update_progress...")
                        # 直接调用update_progress函数处理
                        update_progress(text_or_dict)
                        logger.info("✅ update_progress 调用完成")
                    else:
                        # 其他字典状态，转换为文本
                        logger.info(f"🔍 其他字典状态: {text_or_dict}")
                        dict_text = str(text_or_dict)
                        if dict_text == last_progress_text["text"]:
                            logger.info("🔍 跳过重复字典内容")
                            return  # 跳过重复内容
                        last_progress_text["text"] = dict_text
                        await status_message.edit_text(dict_text)
                else:
                    # 普通文本消息
                    logger.info(f"🔍 普通文本消息: {text_or_dict}")
                    text_str = str(text_or_dict)
                    if text_str == last_progress_text["text"]:
                        logger.info("🔍 跳过重复文本内容")
                        return  # 跳过重复内容
                    last_progress_text["text"] = text_str
                    await status_message.edit_text(text_str)
            except Exception as e:
                logger.error(f"❌ message_updater 处理错误: {e}")
                logger.error(f"❌ 异常类型: {type(e)}")
                import traceback
                logger.error(f"❌ 异常堆栈: {traceback.format_exc()}")
                if "Message is not modified" not in str(e):
                    logger.warning(f"更新状态消息失败: {e}")
        
        # 创建增强版的进度回调函数，支持传递 status_message 和 context
        def enhanced_progress_callback(progress_data_dict):
            """增强版进度回调，支持传递 status_message 和 context 给 single_video_progress_hook"""
            # 创建 single_video_progress_hook 的增强版本
            progress_hook = single_video_progress_hook(
                message_updater=None,  # 不使用简单的 message_updater
                progress_data=progress_data_dict,
                status_message=status_message,
                context=context
            )
            return progress_hook

        # 更新状态消息
        try:
            if message_updater:
                logger.debug(f'message_updater type: {type(message_updater)}, value: {message_updater}')
                if asyncio.iscoroutinefunction(message_updater):
                    await message_updater("🔍 正在分析链接...")
                else:
                    message_updater("🔍 正在分析链接...")
        except Exception as e:
            logger.warning(f"更新状态消息失败: {e}")
        # 直接开始下载，跳过预先获取信息（避免用户等待）
        try:
            if message_updater:
                logger.debug(f'message_updater type: {type(message_updater)}, value: {message_updater}')
                if asyncio.iscoroutinefunction(message_updater):
                    await message_updater("🚀 正在启动下载...")
                else:
                    message_updater("🚀 正在启动下载...")
        except Exception as e:
            logger.warning(f"更新状态消息失败: {e}")
        # 获取当前事件循环
        loop = asyncio.get_running_loop()
        
        # 生成任务ID
        task_id = f"{update.effective_user.id}_{int(time.time())}"
        
        # 添加 progress_data 支持（参考 main.v0.3.py）
        progress_data = {
            'filename': '',
            'total_bytes': 0,
            'downloaded_bytes': 0,
            'speed': 0,
            'status': 'downloading',
            'final_filename': '',
            'last_update': 0,
            'progress': 0.0
        }

        # --- 使用全局进度管理器 ---
        await global_progress_manager.update_progress(task_id, {}, context, status_message)
        def update_progress(d):
            import os
            logger.debug(f"update_progress 被调用: {type(d)}, 内容: {d}")
            # 支持字符串类型，直接发到Telegram
            if isinstance(d, str):
                try:
                    asyncio.run_coroutine_threadsafe(
                        status_message.edit_text(d, parse_mode="MarkdownV2"),
                        loop
                    )
                except Exception as e:
                    logger.warning(f"发送字符串进度到TG失败: {e}")
                return
            # 添加类型检查，确保d是字典类型
            if not isinstance(d, dict):
                logger.warning(f"update_progress接收到非字典类型参数: {type(d)}, 内容: {d}")
                return
            
            # 更新 progress_data（参考 main.v0.3.py）
            try:
                if d['status'] == 'downloading':
                    raw_filename = d.get('filename', '')
                    display_filename = os.path.basename(raw_filename) if raw_filename else 'video.mp4'
                    progress_data.update({
                        'filename': display_filename,
                        'total_bytes': d.get('total_bytes') or d.get('total_bytes_estimate', 0),
                        'downloaded_bytes': d.get('downloaded_bytes', 0),
                        'speed': d.get('speed', 0),
                        'status': 'downloading',
                        'progress': (d.get('downloaded_bytes', 0) / (d.get('total_bytes') or d.get('total_bytes_estimate', 1))) * 100 if (d.get('total_bytes') or d.get('total_bytes_estimate', 0)) > 0 else 0.0
                    })
                elif d['status'] == 'finished':
                    final_filename = d.get('filename', '')
                    display_filename = os.path.basename(final_filename) if final_filename else 'video.mp4'
                    progress_data.update({
                        'filename': display_filename,
                        'status': 'finished',
                        'final_filename': final_filename,
                        'progress': 100.0
                    })
            except Exception as e:
                logger.error(f"更新 progress_data 错误: {str(e)}")
                
            now = time.time()
            # 使用 main.v0.3.py 的方式：每1秒更新一次
            if now - last_update_time['time'] < 1.0:
                return
            # 处理B站合集下载进度
            if d.get('status') == 'downloading' and d.get('bv'):
                # B站合集下载进度
                last_update_time['time'] = now
                bv = d.get('bv', '')
                filename = d.get('filename', '')
                template = d.get('template', '')
                index = d.get('index', 0)
                total = d.get('total', 0)
                
                progress_text = (
                    f"🚀 **正在下载第{index}个**: `{bv}` - `{filename}`\n"
                    f"📝 **文件名模板**: `{template}`\n"
                    f"📊 **进度**: {index}/{total}"
                )
                
                async def do_update():
                    try:
                        await asyncio.wait_for(
                            context.bot.edit_message_text(
                                text=progress_text,
                                chat_id=status_message.chat_id,
                                message_id=status_message.message_id,
                                parse_mode=ParseMode.MARKDOWN_V2
                            ),
                            timeout=10.0  # 增加到10秒超时，减少超时错误
                        )
                        logger.info(f"B站合集进度更新: 第{index}/{total}个")
                    except asyncio.TimeoutError:
                        logger.warning(f"B站合集进度更新超时: 第{index}/{total}个")
                    except Exception as e:
                        if "Message is not modified" not in str(e):
                            logger.warning(f"更新B站合集进度失败: {e}")
                
                asyncio.run_coroutine_threadsafe(do_update(), loop)
                return
            
            # 处理B站合集下载完成/失败
            if d.get('status') in ['finished', 'error'] and d.get('bv'):
                # B站合集下载完成/失败
                last_update_time['time'] = now
                bv = d.get('bv', '')
                filename = d.get('filename', '')
                index = d.get('index', 0)
                total = d.get('total', 0)
                status_emoji = "✅" if d.get('status') == 'finished' else "❌"
                status_text = "下载成功" if d.get('status') == 'finished' else "下载失败"
                
                progress_text = (
                    f"{status_emoji} **第{index}个{status_text}**: `{filename}`\n"
                    f"📊 **进度**: {index}/{total}"
                )
                
                async def do_update():
                    try:
                        await asyncio.wait_for(
                            context.bot.edit_message_text(
                                text=progress_text,
                                chat_id=status_message.chat_id,
                                message_id=status_message.message_id,
                                parse_mode=ParseMode.MARKDOWN_V2
                            ),
                            timeout=10.0  # 增加到10秒超时，减少超时错误
                        )
                        logger.info(f"B站合集状态更新: 第{index}个{status_text}")
                    except asyncio.TimeoutError:
                        logger.warning(f"B站合集状态更新超时: 第{index}个{status_text}")
                    except Exception as e:
                        if "Message is not modified" not in str(e):
                            logger.warning(f"更新B站合集状态失败: {e}")
                
                asyncio.run_coroutine_threadsafe(do_update(), loop)
                return

            # 处理下载完成状态 - 直接显示完成信息并返回（参考 main.v0.3.py）
            elif d.get('status') == 'finished':
                logger.info("yt-dlp下载完成，显示完成信息")

                # 获取进度信息
                filename = progress_data.get('filename', 'video.mp4')
                total_bytes = progress_data.get('total_bytes', 0)
                downloaded_bytes = progress_data.get('downloaded_bytes', 0)

                # 监控文件合并状态
                actual_filename = d.get('filename', filename)
                if actual_filename.endswith('.part'):
                    logger.warning(f"⚠️ 文件合并可能失败: {actual_filename}")
                else:
                    logger.info(f"✅ 文件下载并合并成功: {actual_filename}")
                
                # 显示完成信息
                display_filename = self._clean_filename_for_display(filename)
                progress_bar = self._create_progress_bar(100.0)
                size_mb = total_bytes / (1024 * 1024) if total_bytes > 0 else downloaded_bytes / (1024 * 1024)
                
                completion_text = (
                    f"📝 文件：{display_filename}\n"
                    f"💾 大小：{size_mb:.2f}MB\n"
                    f"⚡ 速度：完成\n"
                    f"⏳ 预计剩余：0秒\n"
                    f"📊 进度：{progress_bar} (100.0%)"
                )
                
                async def do_update():
                    try:
                        await status_message.edit_text(completion_text)
                        logger.info("显示下载完成进度信息")
                    except Exception as e:
                        logger.warning(f"显示完成进度信息失败: {e}")
                
                asyncio.run_coroutine_threadsafe(do_update(), loop)
                return
                
            if d.get('status') == 'downloading':
                logger.debug(f"收到下载进度回调: {d}")
                last_update_time['time'] = now
                
                total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                downloaded_bytes = d.get('downloaded_bytes', 0)
                speed_bytes_s = d.get('speed', 0)
                eta_seconds = d.get('eta', 0)
                filename = d.get('filename', '') or "正在下载..."
                
                # 使用 main.v0.3.py 的简单逻辑
                if total_bytes > 0:
                    progress = (downloaded_bytes / total_bytes) * 100
                    progress_bar = self._create_progress_bar(progress)
                    size_mb = total_bytes / (1024 * 1024)
                    speed_mb = (speed_bytes_s or 0) / (1024 * 1024)
                    
                    # 计算预计剩余时间
                    eta_text = ""
                    if speed_bytes_s and total_bytes and downloaded_bytes < total_bytes:
                        remaining = total_bytes - downloaded_bytes
                        eta = int(remaining / speed_bytes_s)
                        mins, secs = divmod(eta, 60)
                        if mins > 0:
                            eta_text = f"{mins}分{secs}秒"
                        else:
                            eta_text = f"{secs}秒"
                    elif speed_bytes_s:
                        eta_text = "计算中"
                    else:
                        eta_text = "未知"
                    
                    # 确保文件名不包含路径
                    display_filename = os.path.basename(filename) if filename else 'video.mp4'
                    display_filename = self._clean_filename_for_display(display_filename)
                    downloaded_mb = downloaded_bytes / (1024 * 1024)
                    progress_text = (
                        f"📥 下载中\n"
                        f"📝 文件名：{display_filename}\n"
                        f"💾 大小：{downloaded_mb:.2f}MB / {size_mb:.2f}MB\n"
                        f"⚡ 速度：{speed_mb:.2f}MB/s\n"
                        f"⏳ 预计剩余：{eta_text}\n"
                        f"📊 进度：{progress_bar} {progress:.1f}%"
                    )
                    
                    async def do_update():
                        try:
                            await status_message.edit_text(progress_text)
                        except Exception as e:
                            if "Message is not modified" not in str(e):
                                logger.warning(f"更新进度失败: {e}")
                    
                    asyncio.run_coroutine_threadsafe(do_update(), loop)
                else:
                    # 没有总大小信息时的处理
                    downloaded_mb = downloaded_bytes / (1024 * 1024) if downloaded_bytes > 0 else 0
                    speed_mb = (speed_bytes_s or 0) / (1024 * 1024)
                    # 确保文件名不包含路径
                    display_filename = os.path.basename(filename) if filename else 'video.mp4'
                    display_filename = self._clean_filename_for_display(display_filename)
                    progress_text = (
                        f"📥 下载中\n"
                        f"📝 文件名：{display_filename}\n"
                        f"💾 大小：{downloaded_mb:.2f}MB\n"
                        f"⚡ 速度：{speed_mb:.2f}MB/s\n"
                        f"⏳ 预计剩余：未知\n"
                        f"📊 进度：下载中..."
                    )
                    
                    async def do_update():
                        try:
                            await status_message.edit_text(progress_text)
                        except Exception as e:
                            if "Message is not modified" not in str(e):
                                logger.warning(f"更新进度失败: {e}")
                    
                    asyncio.run_coroutine_threadsafe(do_update(), loop)

        # --- 执行下载 ---
        # 创建下载任务，使用增强版的进度回调
        download_task = asyncio.create_task(
            self.downloader.download_video(
                url, update_progress, self.bilibili_auto_playlist
            )
        )

        # 添加到任务管理器
        await self.add_download_task(task_id, download_task)

        try:
            # 等待下载完成
            result = await download_task
        except asyncio.CancelledError:
            logger.info(f"🚫 下载任务被取消: {task_id}")
            await status_message.edit_text("🚫 下载任务已取消")
            return
        except Exception as e:
            logger.error(f"❌ 下载任务执行异常: {e}")
            await status_message.edit_text(f"❌ 下载失败: `{self._escape_markdown(str(e))}`")
            return
        finally:
            # 从任务管理器中移除任务
            await self.remove_download_task(task_id)
            # 🔥 关键修复：下载完成后立即锁死进度回调，防止后续回调覆盖完成信息
            progress_state["finished_shown"] = True
            logger.info("🔒 下载任务完成，锁死进度回调")
        
        # 检查result是否为None
        if not result:
            logger.error("❌ 下载任务返回None结果")
            await status_message.edit_text("❌ 下载失败: 未知错误")
            return
            
        # 兼容不同的返回格式：有些返回"success"，有些返回"status"
        if result.get("success") or result.get("status") == "success":
            # 添加调试日志
            logger.info(f"下载完成，结果: {result}")
            logger.info(f"is_playlist: {result.get('is_playlist')}")
            logger.info(f"platform: {result.get('platform')}")
            logger.info(f"video_type: {result.get('video_type')}")
            
            # 检查是否为B站合集下载
            platform_value = result.get("platform", "")
            logger.info(f"Platform值: '{platform_value}'")
            logger.info(f"是否包含Bilibili: {'Bilibili' in platform_value}")
            
            if (result.get("is_playlist") and "bilibili" in platform_value.lower()) or (result.get("video_type") == "playlist" and "bilibili" in platform_value.lower()):
                # B站自定义列表下载完成，直接使用返回的结果，不进行目录遍历
                # 参考 main.mp.py 的逻辑
                file_count = result.get("file_count", 0)
                total_size_mb = result.get("total_size_mb", 0)
                filename_display = result.get("filename", "")
                resolution_display = result.get("resolution", "未知")
                episode_count = result.get("episode_count", 0)
                download_path = result.get("download_path", "")

                title = "🎬 **视频下载完成**"
                escaped_title = self._escape_markdown(title)

                # 动态处理文件名显示，最大化利用TG消息空间
                filename_display = self.downloader._optimize_filename_display_for_telegram(
                    filename_display, file_count, total_size_mb, resolution_display, download_path
                )

                # 转义各个字段
                escaped_filename = self._escape_markdown(filename_display)
                escaped_resolution = self._escape_markdown(resolution_display)
                escaped_download_path = self._escape_markdown(download_path)
                
                # 为 MarkdownV2 转义数字中的小数点
                total_size_str = f"{total_size_mb:.2f}".replace('.', r'\.')
                episode_count_str = str(episode_count)

                # 获取PART文件统计信息
                success_count = result.get("success_count", episode_count)
                part_count = result.get("part_count", 0)

                # 构建统计信息
                stats_text = f"✅ **成功**: `{success_count} 个`"
                if part_count > 0:
                    stats_text += f"\n⚠️ **未完成**: `{part_count} 个`"
                    stats_text += f"\n💡 **提示**: 发现未完成文件，可能需要重新下载"

                success_text = (
                    f"{escaped_title}\n\n"
                    f"📝 **文件名**:\n{escaped_filename}\n\n"
                    f"💾 **文件大小**: `{total_size_str} MB`\n"
                    f"📊 **下载统计**:\n{stats_text}\n"
                    f"🖼️ **分辨率**: `{escaped_resolution}`\n"
                    f"📂 **保存位置**: `{escaped_download_path}`"
                )

                try:
                    await status_message.edit_text(
                        text=success_text, parse_mode="MarkdownV2"
                    )
                except Exception as e:
                    if "Flood control" in str(e):
                        logger.warning(
                            "B站合集下载完成消息遇到Flood control，等待5秒后重试..."
                        )
                        await asyncio.sleep(5)
                        try:
                            await status_message.edit_text(
                                text=success_text, parse_mode="MarkdownV2"
                            )
                        except Exception as retry_error:
                            logger.error(
                                f"重试发送B站合集完成消息失败: {retry_error}"
                            )
                    else:
                        logger.error(f"发送B站合集完成消息失败: {e}")
            # 检查是否为播放列表或频道下载
            elif result.get("is_playlist") or result.get("is_channel") or result.get("downloaded_files"):
                # 播放列表或频道下载完成
                if result.get("is_channel"):
                    title = "📺 YouTube频道播放列表下载完成"
                    channel_title = result.get("channel_title", "未知频道")
                    playlists = result.get("playlists_downloaded", [])
                    playlist_stats = result.get("playlist_stats", [])
                    download_path = result.get("download_path", "")

                    # 计算总文件大小和PART文件统计
                    total_size_mb = sum(stat.get('total_size_mb', 0) for stat in playlist_stats)
                    total_size_gb = total_size_mb / 1024

                    # 计算总的成功和未完成文件数量
                    total_success_count = sum(stat.get('success_count', stat.get('video_count', 0)) for stat in playlist_stats)
                    total_part_count = sum(stat.get('part_count', 0) for stat in playlist_stats)

                    # 格式化总大小显示 - 只显示一个单位
                    if total_size_gb >= 1.0:
                        total_size_str = f"{total_size_gb:.2f}GB"
                    else:
                        total_size_str = f"{total_size_mb:.2f}MB"

                    success_text = (
                        f"{self._escape_markdown(title)}\n\n"
                        f"📺 频道: `{self._escape_markdown(channel_title)}`\n"
                        f"📊 播放列表数量: `{self._escape_markdown(str(len(playlists)))}`\n\n"
                        f"已下载的播放列表:\n"
                    )

                    # 使用playlist_stats来显示集数信息
                    for i, stat in enumerate(playlist_stats, 1):
                        playlist_title = stat.get("title", f"播放列表{i}")
                        video_count = stat.get("video_count", 0)
                        success_text += f"  {self._escape_markdown(str(i))}\\. {self._escape_markdown(playlist_title)} \\({self._escape_markdown(str(video_count))} 集\\)\n"

                    # 构建下载统计信息
                    stats_text = f"✅ 成功: `{total_success_count} 个`"
                    if total_part_count > 0:
                        stats_text += f"\n⚠️ 未完成: `{total_part_count} 个`"
                        stats_text += f"\n💡 提示: 发现未完成文件，可能需要重新下载"

                    # 添加统计信息、总大小和保存位置（放在最后）
                    success_text += (
                        f"\n📊 下载统计:\n{stats_text}\n"
                        f"💾 文件总大小: `{self._escape_markdown(total_size_str)}`\n"
                        f"📂 保存位置: `{self._escape_markdown(download_path)}`"
                    )
                else:
                    # 检查是否为X播放列表
                    platform = result.get("platform", "")
                    if platform == "X" and result.get("is_playlist"):
                        # X播放列表下载完成
                        title = "🎬 **X播放列表下载完成**"
                        file_count = result.get("file_count", 0)
                        episode_count = result.get("episode_count", 0)
                        total_size_mb = result.get("total_size_mb", 0)
                        resolution = result.get("resolution", "未知")
                        download_path = result.get("download_path", "")
                        filename_display = result.get("filename", "")
                        
                        success_text = (
                            f"{self._escape_markdown(title)}\n\n"
                            f"📝 **文件名**:\n{self._escape_markdown(filename_display)}\n\n"
                            f"💾 **文件大小**: `{self._escape_markdown(f'{total_size_mb:.2f}')} MB`\n"
                            f"📊 **集数**: `{self._escape_markdown(str(episode_count))} 集`\n"
                            f"🖼️ **分辨率**: `{self._escape_markdown(resolution)}`\n"
                            f"📂 **保存位置**: `{self._escape_markdown(download_path)}`"
                        )
                    else:
                        # YouTube播放列表下载完成
                        # 检查是否有详细的文件信息
                        downloaded_files = result.get("downloaded_files", [])
                        if downloaded_files:
                            # 有详细文件信息，使用增强显示
                            title = "🎬 **视频下载完成**"
                            playlist_title = result.get("playlist_title", "YouTube播放列表")
                            video_count = result.get("video_count", len(downloaded_files))
                            total_size_mb = result.get("total_size_mb", 0)
                            resolution = result.get("resolution", "未知")
                            download_path = result.get("download_path", "")

                            # 构建文件名显示列表
                            filename_lines = []
                            for i, file_info in enumerate(downloaded_files, 1):
                                filename = file_info.get("filename", f"文件{i}")
                                filename_lines.append(f"  {i:02d}. {filename}")
                            filename_display = '\n'.join(filename_lines)

                            # 动态处理文件名显示，最大化利用TG消息空间
                            filename_display = self.downloader._optimize_filename_display_for_telegram(
                                filename_display, video_count, total_size_mb, resolution, download_path
                            )

                            # 获取PART文件统计信息
                            success_count = result.get("success_count", video_count)
                            part_count = result.get("part_count", 0)

                            # 构建统计信息
                            stats_text = f"✅ **成功**: `{success_count} 个`"
                            if part_count > 0:
                                stats_text += f"\n⚠️ **未完成**: `{part_count} 个`"
                                stats_text += f"\n💡 **提示**: 发现未完成文件，可能需要重新下载"

                            # 转义各个字段
                            escaped_title = self._escape_markdown(title)
                            escaped_filename = self._escape_markdown(filename_display)
                            escaped_resolution = self._escape_markdown(resolution)
                            escaped_download_path = self._escape_markdown(download_path)
                            size_str = f"{total_size_mb:.2f}".replace('.', r'\.')

                            success_text = (
                                f"{escaped_title}\n\n"
                                f"📝 **文件名**:\n{escaped_filename}\n\n"
                                f"💾 **文件大小**: `{size_str} MB`\n"
                                f"📊 **下载统计**:\n{stats_text}\n"
                                f"🖼️ **分辨率**: `{escaped_resolution}`\n"
                                f"📂 **保存位置**: `{escaped_download_path}`"
                            )
                        else:
                            # 没有详细文件信息，使用简单显示
                            title = "📋 **YouTube播放列表下载完成**"
                            playlist_title = result.get("playlist_title", "未知播放列表")
                            video_count = result.get("video_count", 0)
                            download_path = result.get("download_path", "")

                            # 检查是否已经下载过
                            if result.get("already_downloaded", False):
                                title = "📋 **YouTube播放列表已存在**"
                                completion_rate = result.get("completion_rate", 100)
                                completion_str = f"{completion_rate:.1f}".replace('.', r'\.')

                                success_text = (
                                    f"{self._escape_markdown(title)}\n\n"
                                    f"📋 **播放列表**: `{self._escape_markdown(playlist_title)}`\n"
                                    f"📂 **保存位置**: `{self._escape_markdown(download_path)}`\n"
                                    f"📊 **视频数量**: `{self._escape_markdown(str(video_count))}`\n"
                                    f"✅ **完成度**: `{completion_str}%`\n"
                                    f"💡 **状态**: 本地文件已存在，无需重复下载"
                                )
                            else:
                                # 检查是否为零文件情况（所有视频不可用）
                                if video_count == 0:
                                    title = "⚠️ **YouTube播放列表无可用视频**"
                                    success_text = (
                                        f"{self._escape_markdown(title)}\n\n"
                                        f"📋 **播放列表**: `{self._escape_markdown(playlist_title)}`\n"
                                        f"📂 **保存位置**: `{self._escape_markdown(download_path)}`\n"
                                        f"❌ **状态**: 播放列表中的所有视频都不可用\n"
                                        f"💡 **可能原因**: 视频被删除、账号被终止或地区限制"
                                    )
                                else:
                                    success_text = (
                                        f"{self._escape_markdown(title)}\n\n"
                                        f"📋 **播放列表**: `{self._escape_markdown(playlist_title)}`\n"
                                        f"📂 **保存位置**: `{self._escape_markdown(download_path)}`\n"
                                        f"📊 **视频数量**: `{self._escape_markdown(str(video_count))}`"
                                    )

                try:
                    await status_message.edit_text(
                        text=success_text, parse_mode="MarkdownV2"
                    )
                except Exception as e:
                    if "Flood control" in str(e):
                        logger.warning(
                            "播放列表下载完成消息遇到Flood control，等待5秒后重试..."
                        )
                        await asyncio.sleep(5)
                        try:
                            await status_message.edit_text(
                                text=success_text, parse_mode="MarkdownV2"
                            )
                        except Exception as retry_error:
                            logger.error(
                                f"重试发送播放列表完成消息失败: {retry_error}"
                            )
                    else:
                        logger.error(f"发送播放列表完成消息失败: {e}")
            else:
                # 单文件下载，使用原有逻辑
                # 根据结果构建成功消息
                resolution = result.get("resolution", "未知")
                abr = result.get("abr")

                # 根据分辨率判断是视频还是音频
                if resolution and resolution != "未知" and resolution == "图片":
                    # 图片类型
                    title = "🖼️ **图片下载完成**"
                    size_str = f"{result['size_mb']:.2f}".replace('.', r'\.')
                    files_count = result.get("files_count", 1)
                    file_formats = result.get("file_formats", [])
                    format_str = ", ".join(file_formats) if file_formats else "未知格式"
                    
                    success_text = (
                        f"{self._escape_markdown(title)}\n\n"
                        f"🖼️ **图片数量**: `{files_count} 张`\n"
                        f"💾 **文件大小**: `{size_str} MB`\n"
                        f"📄 **文件格式**: `{self._escape_markdown(format_str)}`\n"
                        f"📂 **保存位置**: `{self._escape_markdown(result['download_path'])}`"
                    )
                    
                    # 直接发送图片完成消息，不进入后续的通用处理逻辑
                    try:
                        await status_message.edit_text(success_text, parse_mode="MarkdownV2")
                        logger.info("显示图片下载完成信息")
                    except Exception as e:
                        if "Flood control" in str(e):
                            logger.warning("图片下载完成消息遇到Flood control，等待5秒后重试...")
                            await asyncio.sleep(5)
                            try:
                                await status_message.edit_text(success_text, parse_mode="MarkdownV2")
                            except Exception as retry_error:
                                logger.error(f"重试发送图片下载完成消息失败: {retry_error}")
                        else:
                            logger.error(f"发送图片下载完成消息失败: {e}")
                    return
                elif resolution and resolution != "未知" and "x" in resolution:
                    # 有分辨率信息，说明是视频
                    # 解析分辨率并添加质量标识
                    try:
                        width, height = resolution.split("x")
                        width, height = int(width), int(height)

                        # 根据高度判断质量
                        if height >= 4320:
                            quality = "8K"
                        elif height >= 2160:
                            quality = "4K"
                        elif height >= 1440:
                            quality = "2K"
                        elif height >= 1080:
                            quality = "1080p"
                        elif height >= 720:
                            quality = "720p"
                        elif height >= 480:
                            quality = "480p"
                        else:
                            quality = f"{height}p"

                        quality_info = f" ({quality})"
                    except (ValueError, TypeError):
                        quality_info = ""

                    # 转义quality_info
                    # escaped_quality_info =
                    # self._escape_markdown(quality_info)

                    # 构建完整的title，然后一次性转义
                    title = "🎬 **视频下载完成**"
                    escaped_title = self._escape_markdown(title)
                    # 将质量标识添加到分辨率后面
                    resolution_with_quality = f"{resolution}{quality_info}"
                    size_str = f"{result['size_mb']:.2f}".replace('.', r'\.')
                    success_text = (
                        f"{escaped_title}\n\n"
                        f"📝 **文件名**: `{self._escape_markdown(result['filename'])}`\n"
                        f"💾 **文件大小**: `{size_str} MB`\n"
                        f"📺 **分辨率**: `{self._escape_markdown(resolution_with_quality)}`\n"
                        f"📂 **保存位置**: `{self._escape_markdown(result['download_path'])}`"
                    )
                # 使用简单格式显示完成信息（只显示一次）
                try:
                    # 获取进度信息用于显示
                    display_filename = self._clean_filename_for_display(result.get('filename', progress_data.get('filename', 'video.mp4')))
                    resolution = result.get('resolution', '未知')
                    platform = result.get('platform', '未知')
                    size_mb = result.get('size_mb', 0)
                    
                    # 获取分辨率质量标识
                    quality_suffix = self._get_resolution_quality(resolution)
                    
                    # 获取下载路径
                    download_path = result.get('download_path', '未知路径')
                    
                    # 检查是否为B站合集下载
                    video_type = result.get('video_type', '')
                    count = result.get('count', 0)
                    playlist_title = result.get('playlist_title', '')
                    
                    if video_type == 'playlist' and count > 1 and 'Bilibili' in platform:
                        # B站合集下载完成，使用特殊格式
                        # 使用result中的文件信息，而不是遍历目录
                        import os

                        try:
                            # 检查result中是否有文件信息
                            if result.get('is_playlist') and result.get('files'):
                                # 使用yt-dlp记录的文件信息
                                file_info_list = result['files']

                                # 构建文件名列表
                                file_list = []
                                for i, file_info in enumerate(file_info_list, 1):
                                    filename = file_info['filename']
                                    file_list.append(f"  {i:02d}. {filename}")

                                # 使用已计算的总文件大小
                                total_size = result.get('total_size_mb', 0)
                            else:
                                # 回退方案：如果result中没有文件信息，使用目录遍历
                                logger.warning("⚠️ result中没有文件信息，使用目录遍历回退方案")
                                download_dir = Path(download_path)
                                video_files = sorted(download_dir.glob("*.mp4"))

                                # 构建文件名列表
                                file_list = []
                                for i, file_path in enumerate(video_files, 1):
                                    filename = file_path.name
                                    file_list.append(f"  {i:02d}. {filename}")

                                # 计算总文件大小
                                total_size = sum(f.stat().st_size for f in video_files) / (1024 * 1024)
                            
                            # 获取分辨率信息
                            if result.get('is_playlist') and result.get('files'):
                                # 使用result中的分辨率信息
                                resolutions = set()
                                for file_info in file_info_list:
                                    resolution = file_info.get('resolution', '未知')
                                    if resolution != '未知':
                                        resolutions.add(resolution)
                                resolution_str = ', '.join(sorted(resolutions)) if resolutions else '未知'
                            else:
                                # 回退方案：使用ffprobe检测分辨率
                                resolutions = set()
                                for file_path in video_files[:3]:  # 只检查前3个文件
                                    try:
                                        import subprocess
                                        result_cmd = subprocess.run([
                                            'ffprobe', '-v', 'quiet', '-select_streams', 'v:0',
                                            '-show_entries', 'stream=width,height', '-of', 'csv=p=0',
                                            str(file_path)
                                        ], capture_output=True, text=True)
                                        if result_cmd.returncode == 0:
                                            width, height = result_cmd.stdout.strip().split(',')
                                            resolutions.add(f"{width}x{height}")
                                    except:
                                        pass
                                resolution_str = ', '.join(sorted(resolutions)) if resolutions else '未知'
                            
                            completion_text = f"""🎬 **视频下载完成**

📝 文件名:
{chr(10).join(file_list)}

💾 文件大小: {total_size:.2f} MB
📊 集数: {count} 集
🖼️ 分辨率: {resolution_str}
📂 保存位置: {download_path}"""
                            
                        except Exception as e:
                            logger.error(f"构建B站合集完成信息时出错: {e}")
                            # 如果出错，使用默认格式
                            completion_text = f"""🎬 **视频下载完成**

📝 文件名: {display_filename}
💾 文件大小: {size_mb:.2f} MB
📊 集数: {count} 集
🖼️ 分辨率: {resolution}{quality_suffix}
📂 保存位置: {download_path}"""
                    else:
                        # 使用新的格式：去掉进度条，添加质量标识
                        completion_text = f"""🎬 **视频下载完成**

📝 文件名: {display_filename}
💾 文件大小: {size_mb:.2f} MB
🎥 分辨率: {resolution}{quality_suffix}
📂 保存位置: {download_path}"""
                    
                    await status_message.edit_text(completion_text)
                    logger.info("显示下载完成信息")
                except Exception as e:
                    if "Flood control" in str(e):
                        logger.warning(
                            "下载完成消息遇到Flood control，等待5秒后重试..."
                        )
                        await asyncio.sleep(5)
                        try:
                            await status_message.edit_text(completion_text)
                        except Exception as retry_error:
                            logger.error(
                                f"重试发送下载完成消息失败: {retry_error}"
                            )
                    else:
                        logger.error(f"发送下载完成消息失败: {e}")
        else:
            # 确保result不为None
            if result:
                error_msg = result.get("error", "未知错误")
            else:
                error_msg = "下载任务返回空结果"
                
            try:
                await status_message.edit_text(
                    f"❌ 下载失败: `{self._escape_markdown(error_msg)}`",
                    parse_mode="MarkdownV2",
                )
            except Exception as retry_error:
                logger.error(f"重试发送下载失败消息失败: {retry_error}")
            return


    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /start 命令 - 显示帮助信息"""
        user_id = update.message.from_user.id
        
        # 权限检查
        if not self._check_user_permission(user_id):
            await update.message.reply_text("❌ 您没有权限使用此机器人")
            return
        
        welcome_message = (
            "🤖 <b>SaveXTube 已启动！</b>\n"
            "<b>支持的平台:</b>\n"
            "• X (Twitter)\n"
            "• YouTube（包括播放列表和频道）\n"
            "• Bilibili\n"
            "• Xvideos\n"
            "• Pornhub\n\n"
            "<b>使用方法：</b>\n"
            "直接发送视频链接即可开始下载\n\n"
            "<b>命令：</b>\n"
            "<b>/start</b> - 🏁 显示此帮助信息\n"
            "<b>/status</b> - 📊 查看下载统计\n"
            "<b>/version</b> - ⚙️ 查看版本信息\n"
            "<b>/settings</b> - 🛠 功能设置（多P自动下载开关）\n\n"
            "<b>特性：</b>\n"
            "✅ 实时下载进度显示\n"
            "✅ 智能格式选择和备用方案\n"
            "✅ 自动格式转换（YouTube webm → mp4）\n"
            "✅ 按平台分类存储\n"
            "✅ 支持 NSFW 内容下载\n"
            "✅ 唯一文件名，避免覆盖\n"
            "✅ YouTube 播放列表和频道下载"
        )
        await update.message.reply_text(welcome_message, parse_mode="HTML")

    async def settings_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """/settings 命令，显示自动下载开关按钮"""
        user_id = update.message.from_user.id
        
        # 权限检查
        if not self._check_user_permission(user_id):
            await update.message.reply_text("❌ 您没有权限使用此机器人")
            return
        
        current = self.bilibili_auto_playlist
        text = "✅ 多P自动下载：开启" if current else "❌  多P自动下载：关闭"
        toggle_button = InlineKeyboardButton(text, callback_data="toggle_autop")
        reply_markup = InlineKeyboardMarkup([[toggle_button]])
        await update.message.reply_text("🛠 功能设置", reply_markup=reply_markup)

    async def settings_button_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        query = update.callback_query
        user_id = query.from_user.id
        
        # 权限检查
        if not self._check_user_permission(user_id):
            await query.answer("❌ 您没有权限使用此机器人")
            return
        
        current = self.bilibili_auto_playlist
        self.bilibili_auto_playlist = not current
        await self._save_config_async()
        new_text = "✅ 自动下载：开启" if not current else "❌ 自动下载：关闭"
        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton(new_text, callback_data="toggle_autop")]]
        )
        await query.edit_message_reply_markup(reply_markup=reply_markup)
        await query.answer("已切换自动下载状态")

    async def cancel_task_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        """处理取消下载任务的按钮点击"""
        query = update.callback_query
        user_id = query.from_user.id
        
        # 权限检查
        if not self._check_user_permission(user_id):
            await query.answer("❌ 您没有权限使用此机器人")
            return
        
        await query.answer()

        # 获取任务 ID
        task_id = query.data.split(":")[1]

        # 取消对应的下载任务
        cancelled = await self.cancel_download_task(task_id)

        if cancelled:
            # 编辑原消息为已取消
            await query.edit_message_text(f"🚫 下载任务已取消（ID: {task_id}）")
        else:
            # 任务不存在或已经被取消
            await query.edit_message_text(f"⚠️ 任务不存在或已被取消（ID: {task_id}）")

    async def add_download_task(self, task_id: str, task: asyncio.Task):
        """添加下载任务到管理器中"""
        async with self.task_lock:
            self.download_tasks[task_id] = {
                "task": task,
                "cancelled": False,
                "start_time": time.time(),
            }
            logger.info(f"📝 添加下载任务: {task_id}")

    async def cancel_download_task(self, task_id: str) -> bool:
        """取消指定的下载任务"""
        async with self.task_lock:
            if task_id in self.download_tasks:
                task_info = self.download_tasks[task_id]
                if not task_info["cancelled"]:
                    task_info["cancelled"] = True
                    task_info["task"].cancel()
                    logger.info(f"🚫 取消下载任务: {task_id}")
                    return True
                else:
                    logger.warning(f"⚠️ 任务 {task_id} 已经被取消")
                    return False
            else:
                logger.warning(f"⚠️ 未找到任务: {task_id}")
                return False

    async def remove_download_task(self, task_id: str):
        """从管理器中移除下载任务"""
        async with self.task_lock:
            if task_id in self.download_tasks:
                del self.download_tasks[task_id]
                logger.info(f"🗑️ 移除下载任务: {task_id}")

    def is_task_cancelled(self, task_id: str) -> bool:
        """检查任务是否已被取消"""
        if task_id in self.download_tasks:
            return self.download_tasks[task_id]["cancelled"]
        return False

    async def download_user_media(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        通过 Telethon 处理用户发送或转发的媒体文件，以支持大文件下载。
        """
        user_id = update.message.from_user.id
        
        # 权限检查
        if not self._check_user_permission(user_id):
            await update.message.reply_text("❌ 您没有权限使用此机器人")
            return
        
        message = update.message
        chat_id = message.chat_id
        
        if not self.user_client:
            await message.reply_text("❌ 媒体下载功能未启用（Telethon 未配置），请联系管理员。")
            return
        
        # --- 紧急修复: 确保 self.bot_id 已设置 ---
        if not self.bot_id:
            try:
                logger.warning("self.bot_id 未设置，正在尝试获取...")
                bot_info = await context.bot.get_me()
                self.bot_id = bot_info.id
                logger.info(f"成功获取到 bot_id: {self.bot_id}")
            except Exception as e:
                logger.error(f"紧急获取 bot_id 失败: {e}", exc_info=True)
                await message.reply_text(f"❌ 内部初始化错误：无法获取机器人自身ID。请稍后重试。")
                return
        # 提取媒体信息
        attachment = message.effective_attachment
        if not attachment:
            await message.reply_text("❓ 请发送或转发一个媒体文件。")
            return
        
        file_name = getattr(attachment, 'file_name', 'unknown_file')
        # 优先处理.torrent文件
        if file_name and file_name.lower().endswith('.torrent'):
            logger.info(f"🔗 检测到种子文件: {file_name}")
            status_message = await message.reply_text("🔗 正在处理种子文件...")
            try:
                file_path = await context.bot.get_file(attachment.file_id)
                torrent_data = await file_path.download_as_bytearray()
                success = await self.add_torrent_file_to_qb(torrent_data, file_name)
                if success:
                    await status_message.edit_text("✅ **磁力链接/种子文件已成功添加到 qBittorrent！**\n\n📝 任务已添加到下载队列\n🔍 您可以在 qBittorrent 中查看下载进度\n💡 提示：下载完成后文件会保存到配置的下载目录")
                else:
                    await status_message.edit_text("❌ 添加到qBittorrent失败！")
            except Exception as e:
                logger.exception(f"添加种子文件到qBittorrent出错: {e}")
                await status_message.edit_text(f"❌ 添加种子文件出错: {e}")
            return
        # 如果 Bot API 没有文件名，尝试从消息文本中提取
        if not file_name or file_name == 'unknown_file':
            logger.info(f"Bot API 消息文本: '{message.text}'")
            if message.text and message.text.strip():
                file_name = message.text.strip()
                logger.info(f"从消息文本中提取文件名: {file_name}")
            else:
                logger.info("Bot API 消息文本为空或只包含空白字符")
        
        # 文件名处理：首行去#，空格变_；正文空格变_；末行全#标签则去#拼接，所有部分用_拼接
        if file_name and file_name != 'unknown_file':
            lines = file_name.splitlines()
            parts = []
            # 处理首行
            if lines:
                first = lines[0].lstrip('#').strip().replace(' ', '_')
                if first:
                    parts.append(first)
            # 处理正文
            for l in lines[1:-1]:
                l = l.strip().replace(' ', '_')
                if l:
                    parts.append(l)
            # 处理末行（全是#标签）
            if len(lines) > 1 and all(x.startswith('#') for x in lines[-1].split()):
                tags = [x.lstrip('#').strip().replace(' ', '_') for x in lines[-1].split() if x.lstrip('#').strip()]
                if tags:
                    parts.extend(tags)
            else:
                # 末行不是全#标签，也当正文处理
                if len(lines) > 1:
                    last = lines[-1].strip().replace(' ', '_')
                    if last:
                        parts.append(last)
            file_name = '_'.join(parts)
        if not file_name:
            file_name = 'unknown_file'
        file_size = getattr(attachment, 'file_size', 0)
        file_unique_id = getattr(attachment, 'file_unique_id', 'unknown_id')
        total_mb = file_size / (1024 * 1024) if file_size else 0
        
        # 记录 bot 端收到的消息信息
        bot_message_timestamp = message.date
        logger.info(
            f"Bot API 收到媒体: name='{file_name}', size={file_size}, "
            f"time={bot_message_timestamp.isoformat()}, unique_id='{file_unique_id}'"
        )
        status_message = await message.reply_text("正在分析消息，请稍候...")
        try:
            # 在用户客户端（user_client）中查找匹配的消息
            telethon_message = None
            audio_bitrate = None
            audio_duration = None
            video_width = None
            video_height = None
            video_duration = None
            time_window_seconds = 5 # 允许5秒的时间误差
            
            # 目标是与机器人的私聊
            try:
                # 首先尝试使用bot_id获取实体
                target_entity = await self.user_client.get_entity(self.bot_id)
            except ValueError as e:
                logger.warning(f"无法通过bot_id获取实体: {e}")
                try:
                    # 备用方案1: 尝试使用bot用户名
                    bot_info = await context.bot.get_me()
                    bot_username = bot_info.username
                    if bot_username:
                        logger.info(f"尝试使用bot用户名获取实体: @{bot_username}")
                        target_entity = await self.user_client.get_entity(bot_username)
                    else:
                        raise ValueError("Bot没有用户名")
                except Exception as e2:
                    logger.warning(f"无法通过用户名获取实体: {e2}")
                    try:
                        # 备用方案2: 使用 "me" 获取与自己的对话
                        logger.info("尝试使用 'me' 获取对话")
                        target_entity = await self.user_client.get_entity("me")
                    except Exception as e3:
                        logger.error(f"所有获取实体的方法都失败了: {e3}")
                        await status_message.edit_text(
                            "❌ 无法访问消息历史，可能是Telethon会话问题。请联系管理员。"
                        )
                        return
            
            async for msg in self.user_client.iter_messages(target_entity, limit=20):
                # 兼容两种媒体类型: document (视频/文件) 和 audio (作为音频发送)
                media_to_check = msg.media.document if hasattr(msg.media, 'document') else msg.media
                
                if media_to_check and hasattr(media_to_check, 'size') and media_to_check.size == file_size:
                    if abs((msg.date - bot_message_timestamp).total_seconds()) < time_window_seconds:
                        telethon_message = msg
                        logger.info(f"找到匹配消息，开始提取媒体属性...")
                        logger.info(f"Telethon 消息完整信息: {telethon_message}")
                        logger.info(f"Telethon 消息文本属性: '{telethon_message.text}'")
                        logger.info(f"Telethon 消息原始文本: '{telethon_message.raw_text}'")
                        
                        # 检查是否为音频并提取元数据
                        if hasattr(media_to_check, 'attributes'):
                            logger.info(f"媒体属性列表: {[type(attr).__name__ for attr in media_to_check.attributes]}")
                            
                            for attr in media_to_check.attributes:
                                logger.info(f"检查属性: {type(attr).__name__} - {attr}")
                                
                                # 音频属性
                                if isinstance(attr, types.DocumentAttributeAudio):
                                    if hasattr(attr, 'bitrate'):
                                        audio_bitrate = attr.bitrate
                                    if hasattr(attr, 'duration'):
                                        audio_duration = attr.duration
                                    logger.info(f"提取到音频元数据: 码率={audio_bitrate}, 时长={audio_duration}")
                                
                                # 视频属性
                                elif isinstance(attr, types.DocumentAttributeVideo):
                                    if hasattr(attr, 'w') and hasattr(attr, 'h'):
                                        video_width = attr.w
                                        video_height = attr.h
                                        logger.info(f"提取到视频元数据: 分辨率={video_width}x{video_height}")

                                    if hasattr(attr, 'duration'):
                                        video_duration = attr.duration
                                        logger.info(f"提取到视频时长: {video_duration}秒")
                                
                                # 文档属性（可能包含文件名等信息）
                                elif isinstance(attr, types.DocumentAttributeFilename):
                                    logger.info(f"提取到文件名: {attr.file_name}")
                                    # 使用从 Telethon 提取的文件名，如果之前没有获取到文件名
                                    if not file_name or file_name == 'unknown_file':
                                        file_name = attr.file_name
                                        logger.info(f"使用 Telethon 文件名: {file_name}")
                                
                                # 音频属性
                                if isinstance(attr, types.DocumentAttributeAudio):
                                    if hasattr(attr, 'bitrate'):
                                        audio_bitrate = attr.bitrate
                                    if hasattr(attr, 'duration'):
                                        audio_duration = attr.duration
                                    logger.info(f"提取到音频元数据: 码率={audio_bitrate}, 时长={audio_duration}")
                                
                                # 视频属性
                                elif isinstance(attr, types.DocumentAttributeVideo):
                                    if hasattr(attr, 'w') and hasattr(attr, 'h'):
                                        video_width = attr.w
                                        video_height = attr.h
                                        logger.info(f"提取到视频元数据: 分辨率={video_width}x{video_height}")

                                    if hasattr(attr, 'duration'):
                                        video_duration = attr.duration
                                        logger.info(f"提取到视频时长: {video_duration}秒")
                        
                        break # 找到匹配项，跳出循环
            
            # 如果还没有文件名，尝试从 Telethon 消息文本中提取
            if (not file_name or file_name == 'unknown_file') and telethon_message:
                logger.info(f"Telethon 消息文本: '{telethon_message.text}'")
                if telethon_message.text and telethon_message.text.strip():
                    file_name = telethon_message.text.strip()
                    logger.info(f"从 Telethon 消息文本中提取文件名: {file_name}")
                    # 对从 Telethon 获取的文件名也应用 # 号处理
                    if file_name:
                        lines = file_name.splitlines()
                        parts = []
                        # 处理首行
                        if lines:
                            first = lines[0].lstrip('#').strip().replace(' ', '_')
                            if first:
                                parts.append(first)
                        # 处理正文
                        for l in lines[1:-1]:
                            l = l.strip().replace(' ', '_')
                            if l:
                                parts.append(l)
                        # 处理末行（全是#标签）
                        if len(lines) > 1 and all(x.startswith('#') for x in lines[-1].split()):
                            tags = [x.lstrip('#').strip().replace(' ', '_') for x in lines[-1].split() if x.lstrip('#').strip()]
                            if tags:
                                parts.extend(tags)
                        else:
                            # 末行不是全#标签，也当正文处理
                            if len(lines) > 1:
                                last = lines[-1].strip().replace(' ', '_')
                                if last:
                                    parts.append(last)
                        file_name = '_'.join(parts)
                    if not file_name:
                        file_name = 'unknown_file'
                    logger.info(f"处理后的文件名: {file_name}")
                else:
                    logger.info("Telethon 消息文本为空或只包含空白字符")
            
            # 兜底机制：如果还是没有文件名，使用视频文件 ID
            if not file_name or file_name == 'unknown_file':
                if telethon_message and hasattr(telethon_message.media, 'document'):
                    # 使用文档 ID 作为文件名
                    doc_id = telethon_message.media.document.id
                    logger.info(f"兜底机制触发 - 文件大小: {file_size} bytes, 视频分辨率: {video_width}x{video_height}, 音频时长: {audio_duration}")
                    # 根据检测到的文件类型添加扩展名
                    if video_width is not None and video_height is not None:
                        file_name = f"video_{doc_id}.mp4"
                        logger.info(f"检测到视频属性，使用 .mp4 扩展名")
                    elif audio_duration is not None and audio_bitrate is not None:
                        file_name = f"audio_{doc_id}.mp3"
                        logger.info(f"检测到音频属性，使用 .mp3 扩展名")
                    else:
                        # 如果无法确定类型，但文件大小较大，很可能是视频文件
                        if file_size > 1024 * 1024:  # 大于1MB
                            file_name = f"video_{doc_id}.mp4"
                            logger.info(f"文件大小较大({file_size} bytes)，推测为视频文件，使用 .mp4 扩展名")
                        else:
                            file_name = f"file_{doc_id}.bin"
                            logger.info(f"文件大小较小({file_size} bytes)，使用 .bin 扩展名")
                    logger.info(f"使用文件 ID 作为文件名: {file_name}")
            
            # 根据媒体类型确定下载路径
            # 改进音频检测：不仅检查DocumentAttributeAudio，也检查文件扩展名
            is_audio_file = False
            if audio_duration is not None and audio_bitrate is not None:
                is_audio_file = True
            elif file_name and any(file_name.lower().endswith(ext) for ext in ['.mp3', '.m4a', '.flac', '.wav', '.ogg', '.aac', '.wma', '.opus']):
                is_audio_file = True
                logger.info(f"通过文件扩展名检测到音频文件: {file_name}")
            
            # 改进视频检测：不仅检查DocumentAttributeVideo，也检查文件扩展名
            is_video_file = False
            if video_width is not None and video_height is not None:
                is_video_file = True
            elif file_name and any(file_name.lower().endswith(ext) for ext in ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.3gp', '.ts']):
                is_video_file = True
                logger.info(f"通过文件扩展名检测到视频文件: {file_name}")
            
            if is_audio_file:
                # 音频文件放在telegram/music文件夹
                download_path = os.path.join(self.downloader.download_path, "telegram", "music")
                logger.info(f"检测到音频文件，下载路径: {download_path}")
            elif is_video_file:
                # 视频文件放在telegram/videos文件夹
                download_path = os.path.join(self.downloader.download_path, "telegram", "videos")
                logger.info(f"检测到视频文件，下载路径: {download_path}")
            else:
                # 其他文件放在telegram文件夹
                download_path = os.path.join(self.downloader.download_path, "telegram")
                logger.info(f"检测到其他媒体文件，下载路径: {download_path}")
            
            os.makedirs(download_path, exist_ok=True)
            if telethon_message:
                logger.info(f"找到匹配的Telethon消息: {telethon_message.id}，开始下载...")
                
                # 添加详细的调试信息
                logger.info(f"消息类型: {type(telethon_message)}")
                logger.info(f"消息媒体: {type(telethon_message.media) if telethon_message.media else 'None'}")
                if telethon_message.media:
                    logger.info(f"媒体属性: {dir(telethon_message.media)}")
                    if hasattr(telethon_message.media, 'document'):
                        logger.info(f"Document: {telethon_message.media.document}")
                    else:
                        logger.info(f"直接媒体: {telethon_message.media}")
                
                # --- 下载回调 (统一为详细样式) ---
                last_update_time = time.time()
                last_downloaded = 0
                async def progress(current, total):
                    nonlocal last_update_time, last_downloaded
                    now = time.time()
                    
                    if now - last_update_time < 5 and current != total:
                        return
                    
                    diff_time = now - last_update_time
                    diff_bytes = current - last_downloaded
                    last_update_time = now
                    last_downloaded = current
                    
                    speed_bytes_s = diff_bytes / diff_time if diff_time > 0 else 0
                    speed_mb_s = speed_bytes_s / (1024 * 1024)
                    eta_str = "未知"
                    if speed_bytes_s > 0:
                        remaining_bytes = total - current
                        try:
                            eta_seconds = remaining_bytes / speed_bytes_s
                            minutes, seconds = divmod(int(eta_seconds), 60)
                            eta_str = f"{minutes:02d}:{seconds:02d}"
                        except (OverflowError, ValueError):
                            eta_str = "未知"
                    
                    downloaded_mb = current / (1024 * 1024)
                    total_mb = total / (1024 * 1024)
                    # 修复：检查file_name是否为None
                    display_filename = file_name if file_name else "未知文件"
                    safe_filename = self._escape_markdown(display_filename)
                    percent = current * 100 / total if total > 0 else 0
                    bar = self._make_progress_bar(percent)
                    # 为 MarkdownV2 转义数字中的小数点
                    downloaded_mb_str = f"{downloaded_mb:.2f}".replace('.', r'\.')
                    total_mb_str = f"{total_mb:.2f}".replace('.', r'\.')
                    speed_mb_s_str = f"{speed_mb_s:.2f}".replace('.', r'\.')
                    percent_str = f"{percent:.1f}".replace('.', r'\.')
                    
                    # 转义eta_str
                    escaped_eta_str = self._escape_markdown(eta_str)
                    progress_text = (
                        f"📝 文件：`{safe_filename}`\n"
                        f"💾 大小：{downloaded_mb_str}MB / {total_mb_str}MB\n"
                        f"⚡ 速度：{speed_mb_s_str}MB/s\n"
                        f"⏳ 预计剩余：{escaped_eta_str}\n"
                        f"📊 进度：{bar} {percent_str}%"
                    )
                    try:
                        if current != total:
                            await context.bot.edit_message_text(
                                text=progress_text,
                                chat_id=chat_id,
                                message_id=status_message.message_id,
                                parse_mode=ParseMode.MARKDOWN_V2
                            )
                    except Exception as e:
                        if "Message is not modified" not in str(e):
                            logger.warning(f"更新TG下载进度时出错: {e}")
                
                try:
                    # 生成唯一文件名，防止覆盖
                    def get_unique_filename(base_path, filename):
                        name, ext = os.path.splitext(filename)
                        counter = 1
                        unique_filename = filename
                        while os.path.exists(os.path.join(base_path, unique_filename)):
                            unique_filename = f"{name}_{counter}{ext}"
                            counter += 1
                        return unique_filename
                
                    unique_file_name = get_unique_filename(download_path, file_name)
                    downloaded_file = await self.user_client.download_media(
                        telethon_message,
                        file=os.path.join(download_path, unique_file_name),
                        progress_callback=progress
                    )
                    if downloaded_file:
                        # 下载成功，获取文件信息
                        file_size_mb = os.path.getsize(downloaded_file) / (1024 * 1024)

                        # 检查是否为音频文件
                        file_extension = os.path.splitext(downloaded_file)[1].lower()
                        is_audio_file = file_extension in ['.mp3', '.flac', '.wav', '.aac', '.ogg', '.m4a', '.wma']

                        logger.info(f"🎵 音频文件检测: 文件扩展名={file_extension}, 是否为音频文件={is_audio_file}")
                        logger.info(f"🎵 Telegram元数据: 码率={audio_bitrate}, 时长={audio_duration}")

                        # 对于音频文件，强制尝试获取音频信息
                        if is_audio_file:
                            try:
                                logger.info(f"🎵 开始提取音频文件信息: {downloaded_file}")
                                media_info = self.downloader.get_media_info(downloaded_file)
                                logger.info(f"🎵 get_media_info返回: {media_info}")

                                # 如果没有码率信息，从文件中提取
                                if not audio_bitrate and media_info.get('bit_rate'):
                                    # 从字符串中提取数字，如 "320 kbps" -> 320
                                    bit_rate_str = str(media_info.get('bit_rate', ''))
                                    import re
                                    match = re.search(r'(\d+)', bit_rate_str)
                                    if match:
                                        audio_bitrate = int(match.group(1))
                                        logger.info(f"✅ 从文件提取到音频码率: {audio_bitrate}kbps")
                                    else:
                                        logger.warning(f"⚠️ 无法从码率字符串提取数字: {bit_rate_str}")

                                # 如果没有时长信息，从文件中提取
                                if not audio_duration and media_info.get('duration'):
                                    duration_from_file = media_info.get('duration')
                                    # 检查是否为格式化的时间字符串（如 "03:47"）
                                    if isinstance(duration_from_file, str) and ':' in duration_from_file:
                                        # 解析时间字符串为秒数
                                        try:
                                            time_parts = duration_from_file.split(':')
                                            if len(time_parts) == 2:  # MM:SS
                                                minutes, seconds = map(int, time_parts)
                                                audio_duration = minutes * 60 + seconds
                                            elif len(time_parts) == 3:  # HH:MM:SS
                                                hours, minutes, seconds = map(int, time_parts)
                                                audio_duration = hours * 3600 + minutes * 60 + seconds
                                            else:
                                                audio_duration = float(duration_from_file)
                                        except ValueError:
                                            logger.warning(f"⚠️ 无法解析时长字符串: {duration_from_file}")
                                    else:
                                        # 直接使用数字时长
                                        audio_duration = float(duration_from_file)
                                    logger.info(f"✅ 从文件提取到音频时长: {audio_duration}秒")

                                # 如果仍然没有获取到信息，尝试使用ffprobe
                                if not audio_bitrate or not audio_duration:
                                    logger.info(f"🔍 尝试使用ffprobe获取音频信息")
                                    try:
                                        import subprocess
                                        import json

                                        cmd = [
                                            'ffprobe', '-v', 'quiet', '-print_format', 'json',
                                            '-show_format', '-show_streams', downloaded_file
                                        ]
                                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

                                        if result.returncode == 0:
                                            probe_data = json.loads(result.stdout)
                                            logger.info(f"🔍 ffprobe返回数据: {probe_data}")

                                            # 从streams中获取音频信息
                                            for stream in probe_data.get('streams', []):
                                                if stream.get('codec_type') == 'audio':
                                                    if not audio_bitrate and 'bit_rate' in stream:
                                                        audio_bitrate = int(int(stream['bit_rate']) / 1000)  # 转换为kbps
                                                        logger.info(f"✅ ffprobe从streams获取到码率: {audio_bitrate}kbps")
                                                    break

                                            # 从format中获取码率和时长信息
                                            if 'format' in probe_data:
                                                format_info = probe_data['format']

                                                # 如果streams中没有码率信息，尝试从format中获取
                                                if not audio_bitrate and 'bit_rate' in format_info:
                                                    audio_bitrate = int(int(format_info['bit_rate']) / 1000)  # 转换为kbps
                                                    logger.info(f"✅ ffprobe从format获取到码率: {audio_bitrate}kbps")

                                                # 获取时长信息
                                                if (not audio_duration or not isinstance(audio_duration, (int, float))) and 'duration' in format_info:
                                                    audio_duration = float(format_info['duration'])
                                                    logger.info(f"✅ ffprobe获取到时长: {audio_duration}秒")
                                        else:
                                            logger.warning(f"⚠️ ffprobe执行失败: {result.stderr}")
                                    except Exception as ffprobe_error:
                                        logger.warning(f"⚠️ ffprobe执行异常: {ffprobe_error}")

                            except Exception as e:
                                logger.warning(f"❌ 无法从文件提取音频信息: {e}")

                        # 确保 audio_duration 是数字类型
                        if audio_duration and isinstance(audio_duration, str) and ':' in audio_duration:
                            # 如果是时间字符串格式，解析为秒数
                            try:
                                time_parts = audio_duration.split(':')
                                if len(time_parts) == 2:  # MM:SS
                                    minutes, seconds = map(int, time_parts)
                                    audio_duration = minutes * 60 + seconds
                                elif len(time_parts) == 3:  # HH:MM:SS
                                    hours, minutes, seconds = map(int, time_parts)
                                    audio_duration = hours * 3600 + minutes * 60 + seconds
                                logger.info(f"🔧 解析时长字符串 '{':'.join(time_parts)}' 为 {audio_duration} 秒")
                            except ValueError as e:
                                logger.warning(f"⚠️ 无法解析时长字符串 '{audio_duration}': {e}")

                        logger.info(f"🎵 最终音频信息: 码率={audio_bitrate}, 时长={audio_duration}")

                        # 构建成功消息
                        success_text = f"✅ **文件下载完成**\n\n"
                        success_text += f"📝 **文件名**: `{self._escape_markdown(file_name)}`\n"
                        success_text += f"💾 **文件大小**: `{file_size_mb:.2f}MB`\n"

                        # 如果有视频分辨率信息，显示在文件大小下面
                        if video_width and video_height:
                            # 判断分辨率等级
                            resolution_label = ""
                            max_dimension = max(video_width, video_height)
                            if max_dimension >= 3840:  # 4K
                                resolution_label = " (4K)"
                            elif max_dimension >= 2560:  # 2K
                                resolution_label = " (2K)"
                            elif max_dimension >= 1920:  # 1080p
                                resolution_label = " (1080p)"
                            elif max_dimension >= 1280:  # 720p
                                resolution_label = " (720p)"
                            elif max_dimension >= 854:   # 480p
                                resolution_label = " (480p)"

                            success_text += f"🎥 **分辨率**: `{video_width}x{video_height}{resolution_label}`\n"

                        # 如果是音频文件，显示码率信息
                        if is_audio_file and audio_bitrate:
                            success_text += f"🎵 **码率**: `{self._escape_markdown(str(audio_bitrate))}kbps`\n"

                        # 显示时长信息（音频或视频）
                        duration_to_show = audio_duration if is_audio_file else video_duration
                        if duration_to_show:
                            minutes, seconds = divmod(int(duration_to_show), 60)
                            duration_str = f"{minutes:02d}:{seconds:02d}"
                            success_text += f"⏱️ **时长**: `{self._escape_markdown(duration_str)}`\n"

                        success_text += f"📁 **保存路径**: `{self._escape_markdown(os.path.dirname(downloaded_file))}`"
                        
                        await context.bot.edit_message_text(
                            text=success_text,
                            chat_id=chat_id,
                            message_id=status_message.message_id,
                            parse_mode=ParseMode.MARKDOWN_V2
                        )
                        logger.info(f"✅ 媒体文件下载完成: {downloaded_file}")
                    else:
                        await context.bot.edit_message_text(
                            text="❌ 下载失败：无法获取文件",
                            chat_id=chat_id,
                            message_id=status_message.message_id
                        )
                        logger.error("❌ 媒体文件下载失败：无法获取文件")
                        
                except Exception as e:
                    logger.error(f"❌ 媒体文件下载失败: {e}", exc_info=True)
                    await context.bot.edit_message_text(
                        text=f"❌ 下载失败: {str(e)}",
                        chat_id=chat_id,
                        message_id=status_message.message_id
                    )
            else:
                await context.bot.edit_message_text(
                    text="❌ 无法找到匹配的媒体消息，请重试",
                    chat_id=chat_id,
                    message_id=status_message.message_id
                )
                logger.error("❌ 无法找到匹配的Telethon消息")
                
        except Exception as e:
            logger.error(f"❌ 处理媒体消息时出错: {e}", exc_info=True)
            await context.bot.edit_message_text(
                text=f"❌ 处理失败: {str(e)}",
                chat_id=chat_id,
                message_id=status_message.message_id
            )

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """记录所有 PTB 抛出的错误并处理网络错误"""
        error = context.error
        error_msg = str(error)
        error_type = type(error).__name__

        # 检查是否为网络相关错误
        is_network_error = any(keyword in error_msg.lower() for keyword in [
            'connection', 'timeout', 'network', 'remote', 'protocol',
            'httpx', 'telegram', 'api', 'server', 'unavailable',
            'connecterror', 'timeoutexception', 'httperror', 'ssl',
            'dns', 'resolve', 'unreachable', 'refused', 'reset',
            'broken pipe', 'connection reset', 'connection aborted',
            'read timeout', 'write timeout', 'connect timeout',
            'pool timeout', 'proxy', 'gateway', 'service unavailable'
        ])

        if is_network_error:
            logger.warning(f"🌐 检测到网络错误: {error_type}: {error_msg}")
            logger.info("🔄 网络错误将由健康检查机制自动处理")
        else:
            logger.error(f"❌ PTB 错误: {error_type}: {error_msg}", exc_info=error)

        # 对于严重的网络错误，触发立即健康检查
        if is_network_error and any(critical in error_msg.lower() for critical in [
            'connection reset', 'connection aborted', 'broken pipe', 'ssl'
        ]):
            logger.warning("🚨 检测到严重网络错误，触发立即健康检查")
            # 这里可以触发立即的健康检查，但要避免递归调用


class GlobalProgressManager:
    """全局进度管理器，统一管理所有下载任务的进度更新"""

    def __init__(self):
        self.last_update_time = time.time()
        self.update_interval = 15  # 全局更新间隔15秒
        self.active_downloads = {}  # 存储活跃下载任务
        self.lock = asyncio.Lock()

    async def update_progress(
        self, task_id: str, progress_data: dict, context, status_message
    ):
        """更新单个任务的进度"""
        async with self.lock:
            self.active_downloads[task_id] = progress_data

            now = time.time()
            if now - self.last_update_time < self.update_interval:
                return  # 未到更新时间

            # 构建汇总进度消息
            await self._send_summary_progress(context, status_message)
            self.last_update_time = now

    async def _send_summary_progress(self, context, status_message):
        """发送汇总进度消息"""
        if not self.active_downloads:
            return

        total_tasks = len(self.active_downloads)
        completed_tasks = sum(
            1
            for data in self.active_downloads.values()
            if data.get("status") == "finished"
        )

        # 构建进度消息
        progress_lines = []
        progress_lines.append(f"📦 **批量下载进度** ({completed_tasks}/{total_tasks})")

        # 显示前3个活跃任务
        active_tasks = [
            data
            for data in self.active_downloads.values()
            if data.get("status") == "downloading"
        ][:3]

        for i, data in enumerate(active_tasks, 1):
            filename = os.path.basename(data.get("filename", "未知文件"))
            progress = data.get("progress", 0)
            speed = data.get("speed", 0)

            if speed and speed > 0:
                speed_mb = speed / (1024 * 1024)
                speed_str = f"{speed_mb:.1f}MB/s"
            else:
                speed_str = "未知"

            progress_lines.append(f"{i}. `{filename}` - {progress:.1f}% ({speed_str})")

        if len(active_tasks) < total_tasks - completed_tasks:
            remaining = total_tasks - completed_tasks - len(active_tasks)
            progress_lines.append(f"... 还有 {remaining} 个任务进行中")

        progress_text = "\n".join(progress_lines)

        try:
            await context.bot.edit_message_text(
                text=progress_text,
                chat_id=status_message.chat_id,
                message_id=status_message.message_id,
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception as e:
            if "Message is not modified" not in str(e) and "Flood control" not in str(
                e
            ):
                logger.warning(f"更新汇总进度失败: {e}")

    def remove_task(self, task_id: str):
        """移除完成的任务"""
        if task_id in self.active_downloads:
            del self.active_downloads[task_id]


# 全局进度管理器实例
global_progress_manager = GlobalProgressManager()


async def test_network_connectivity():
    """测试网络连接性"""
    import httpx
    test_urls = [
        "https://api.telegram.org",
        "https://www.google.com",
        "https://1.1.1.1"
    ]

    for url in test_urls:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    logger.info(f"🟢 网络连接测试成功: {url}")
                    return True
        except Exception as e:
            logger.warning(f"🟡 网络连接测试失败: {url} - {e}")
            continue

    logger.error(f"🔴 所有网络连接测试都失败")
    return False

async def main():
    """主函数 (异步)"""
    # 启动时环境检查
    logger.info("🔍 开始启动前环境检查...")

    # 检查关键环境变量
    required_env_vars = ["TELEGRAM_BOT_TOKEN"]
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        logger.error(f"❌ 缺少必需的环境变量: {missing_vars}")
        return

    # 显示网络重试配置
    max_retries = int(os.getenv("TELEGRAM_MAX_RETRIES", "10"))
    base_delay = float(os.getenv("TELEGRAM_BASE_DELAY", "5.0"))
    max_delay = float(os.getenv("TELEGRAM_MAX_DELAY", "300.0"))
    logger.info(f"📊 网络重试配置: 最大重试={max_retries}, 基础延迟={base_delay}s, 最大延迟={max_delay}s")

    # 测试网络连接
    logger.info("🔍 开始网络连接测试...")
    if not await test_network_connectivity():
        logger.warning("⚠️ 网络连接测试失败，但将继续尝试启动")
        # 不要直接退出，继续尝试启动，可能是测试URL的问题

    # 检查是否启用健康检查服务器
    enable_health_check = os.getenv("ENABLE_HEALTH_CHECK", "true").lower() == "true"

    if enable_health_check:
        # 启动 Flask health check server in a background thread
        health_thread = threading.Thread(target=run_health_check_server, daemon=True)
        health_thread.start()
        logger.info(
            f"❤️ 健康检查和登录服务器已在后台线程启动，端口 {os.getenv('HEALTHCHECK_PORT', 8080)}"
        )
    else:
        logger.info("健康检查服务器已禁用")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    download_path = os.getenv("DOWNLOAD_PATH", "/downloads")
    x_cookies_path = os.getenv("X_COOKIES")
    b_cookies_path = os.getenv("BILIBILI_COOKIES")
    youtube_cookies_path = os.getenv("YOUTUBE_COOKIES")
    douyin_cookies_path = os.getenv("DOUYIN_COOKIES")
    kuaishou_cookies_path = os.getenv("KUAISHOU_COOKIES")

    if not bot_token:
        logger.error("请设置 TELEGRAM_BOT_TOKEN 环境变量")
        sys.exit(1)

    logger.info(f"下载路径: {download_path}")
    if x_cookies_path:
        logger.info(f"X Cookies 路径: {x_cookies_path}")
    if b_cookies_path:
        logger.info(f"Bilibili Cookies 路径: {b_cookies_path}")
    if youtube_cookies_path:
        logger.info(f"🍪 使用YouTube cookies: {youtube_cookies_path}")
    if douyin_cookies_path:
        logger.info(f"🎬 使用抖音 cookies: {douyin_cookies_path}")
        # 检查文件是否存在
        if os.path.exists(douyin_cookies_path):
            file_size = os.path.getsize(douyin_cookies_path)
            logger.info(f"✅ 抖音 cookies 文件存在，大小: {file_size} 字节")
            
            # 读取并显示前几行内容
            try:
                with open(douyin_cookies_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    logger.info(f"📄 抖音 cookies 文件包含 {len(lines)} 行")
                    if lines:
                        logger.info(f"📝 第一行内容: {lines[0].strip()}")
                        if len(lines) > 1:
                            logger.info(f"📝 第二行内容: {lines[1].strip()}")
            except Exception as e:
                logger.error(f"❌ 读取抖音 cookies 文件失败: {e}")
        else:
            logger.warning(f"⚠️ 抖音 cookies 文件不存在: {douyin_cookies_path}")
    else:
        logger.warning("⚠️ 未设置 DOUYIN_COOKIES 环境变量")

    # 检查快手cookies
    if kuaishou_cookies_path:
        logger.info(f"⚡ 使用快手 cookies: {kuaishou_cookies_path}")
        # 检查文件是否存在
        if os.path.exists(kuaishou_cookies_path):
            file_size = os.path.getsize(kuaishou_cookies_path)
            logger.info(f"✅ 快手 cookies 文件存在，大小: {file_size} 字节")

            # 读取并显示前几行内容
            try:
                with open(kuaishou_cookies_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    logger.info(f"📄 快手 cookies 文件包含 {len(lines)} 行")
                    if lines:
                        logger.info(f"📝 第一行内容: {lines[0].strip()}")
                        if len(lines) > 1:
                            logger.info(f"📝 第二行内容: {lines[1].strip()}")
            except Exception as e:
                logger.error(f"❌ 读取快手 cookies 文件失败: {e}")
        else:
            logger.warning(f"⚠️ 快手 cookies 文件不存在: {kuaishou_cookies_path}")
    else:
        logger.warning("⚠️ 未设置 KUAISHOU_COOKIES 环境变量")

    # 创建下载器和机器人
    downloader = VideoDownloader(
        download_path, x_cookies_path, b_cookies_path, youtube_cookies_path, douyin_cookies_path, kuaishou_cookies_path
    )
    bot = TelegramBot(bot_token, downloader)

    # 网络错误重试机制 - 使用您的配置参数
    max_retries = int(os.getenv("TELEGRAM_MAX_RETRIES", "10"))  # 增加重试次数
    base_delay = float(os.getenv("TELEGRAM_BASE_DELAY", "5.0"))  # 使用您的基础延迟
    max_delay = float(os.getenv("TELEGRAM_MAX_DELAY", "300.0"))  # 使用您的最大延迟
    
    retry_count = 0
    while retry_count < max_retries:
        try:
            logger.info(f"🔄 尝试启动Telegram Bot (第 {retry_count + 1}/{max_retries} 次)")

            # 在重试前测试网络连接
            if retry_count > 0:
                logger.info("🔍 重试前测试网络连接...")
                await test_network_connectivity()

            await bot.run()
            logger.info("✅ Telegram Bot启动成功！")
            break  # 成功启动，退出重试循环

        except Exception as e:
            retry_count += 1
            error_msg = str(e)
            error_type = type(e).__name__

            logger.error(f"❌ Telegram Bot启动失败 (第 {retry_count} 次): {error_type}: {error_msg}")

            # 检查是否为网络相关错误 - 增强错误检测
            is_network_error = any(keyword in error_msg.lower() for keyword in [
                'connection', 'timeout', 'network', 'remote', 'protocol',
                'httpx', 'telegram', 'api', 'server', 'unavailable',
                'connecterror', 'timeoutexception', 'httperror', 'ssl',
                'dns', 'resolve', 'unreachable', 'refused', 'reset',
                'broken pipe', 'connection reset', 'connection aborted',
                'read timeout', 'write timeout', 'connect timeout',
                'pool timeout', 'proxy', 'gateway', 'service unavailable'
            ])

            if is_network_error and retry_count < max_retries:
                # 计算指数退避延迟
                delay = min(base_delay * (2 ** (retry_count - 1)), max_delay)
                logger.warning(f"🌐 检测到网络错误，{delay:.1f}秒后重试 ({retry_count}/{max_retries})")
                logger.info(f"📊 重试策略: 基础延迟={base_delay}s, 最大延迟={max_delay}s, 当前延迟={delay:.1f}s")
                await asyncio.sleep(delay)
            else:
                # 非网络错误或已达到最大重试次数
                if retry_count >= max_retries:
                    logger.error(f"💀 网络连接失败，已达到最大重试次数 ({max_retries})")
                    logger.error(f"💡 建议检查: 1) 网络连接 2) Telegram API访问 3) 代理设置 4) 防火墙配置")
                else:
                    logger.error(f"💀 Telegram Bot启动失败，非网络错误: {error_type}")
                raise e


if __name__ == "__main__":
    try:
        update_heartbeat()  # 初始化心跳
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("机器人已停止。")


















