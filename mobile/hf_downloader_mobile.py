#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HuggingFace 下载工具 - 移动端版本 (Android)
基于 Kivy 框架开发
"""

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.progressbar import ProgressBar
from kivy.uix.checkbox import CheckBox
from kivy.uix.popup import Popup
from kivy.clock import Clock
from kivy.utils import platform
from kivy.core.window import Window
from kivy.core.text import LabelBase
from kivy.resources import resource_add_path

import os
import requests
import threading
import re
import json
import time
from urllib.parse import urlparse, unquote
from functools import partial

# Android 特定导入
if platform == 'android':
    from android.permissions import request_permissions, Permission
    from jnius import autoclass, cast
    
    # Java 类引用 - 只保留必要的
    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    Context = autoclass('android.content.Context')
    PowerManager = autoclass('android.os.PowerManager')
    
    # 注册中文字体（使用 Android 系统字体）
    try:
        LabelBase.register('Roboto', '/system/fonts/DroidSansFallback.ttf')
    except:
        try:
            LabelBase.register('Roboto', '/system/fonts/NotoSansCJK-Regular.ttc')
        except:
            pass

# 设置窗口大小（开发时使用，打包后自动适配手机屏幕）
if platform != 'android':
    Window.size = (360, 640)


class HFDownloader:
    """HuggingFace 文件下载器核心类"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36'
        })
        self.cancel_flag = False
        self.pause_flag = False
        
    def parse_hf_url(self, url):
        """解析 HuggingFace URL"""
        url = url.split('?')[0]
        
        # 检查是否是目录URL
        tree_patterns = [
            r'hf-mirror\.com/([^/]+)/([^/]+)/tree/([^/]+)(?:/(.*))?',
            r'huggingface\.co/([^/]+)/([^/]+)/tree/([^/]+)(?:/(.*))?',
        ]
        
        for pattern in tree_patterns:
            match = re.search(pattern, url)
            if match:
                username, model, branch = match.groups()[:3]
                subpath = match.groups()[3] if len(match.groups()) > 3 else ''
                repo_info = {
                    'username': username,
                    'model': model,
                    'branch': branch,
                    'subpath': subpath or ''
                }
                return None, None, True, repo_info
        
        # 检查单文件URL
        file_patterns = [
            r'hf-mirror\.com/([^/]+)/([^/]+)/resolve/([^/]+)/(.+)',
            r'hf-mirror\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)',
            r'huggingface\.co/([^/]+)/([^/]+)/resolve/([^/]+)/(.+)',
            r'huggingface\.co/([^/]+)/([^/]+)/blob/([^/]+)/(.+)',
        ]
        
        for pattern in file_patterns:
            match = re.search(pattern, url)
            if match:
                username, model, branch, filepath = match.groups()
                download_url = f"https://hf-mirror.com/{username}/{model}/resolve/{branch}/{filepath}"
                filename = os.path.basename(unquote(filepath))
                return download_url, filename, False, None
        
        if url.startswith('http'):
            filename = os.path.basename(unquote(urlparse(url).path))
            if not filename:
                filename = 'downloaded_file'
            return url, filename, False, None
            
        return None, None, False, None
    
    def get_file_size(self, url):
        """获取远程文件大小"""
        try:
            response = self.session.head(url, allow_redirects=True, timeout=10)
            if response.status_code == 200:
                return int(response.headers.get('Content-Length', 0))
        except:
            pass
        return 0
    
    def format_size(self, size):
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"
    
    def download_file(self, url, save_path, progress_callback=None, status_callback=None):
        """下载文件，支持断点续传，网络异常安全处理"""
        self.cancel_flag = False
        self.pause_flag = False
        
        try:
            os.makedirs(os.path.dirname(save_path) if os.path.dirname(save_path) else '.', exist_ok=True)
        except Exception as e:
            if status_callback:
                Clock.schedule_once(lambda dt: status_callback(f"Path error: {e}"), 0)
            return False
        
        downloaded_size = 0
        if os.path.exists(save_path):
            downloaded_size = os.path.getsize(save_path)
        
        try:
            total_size = self.get_file_size(url)
        except:
            total_size = 0
        
        if downloaded_size > 0 and total_size > 0 and downloaded_size == total_size:
            if status_callback:
                Clock.schedule_once(lambda dt: status_callback("File exists"), 0)
            if progress_callback:
                Clock.schedule_once(lambda dt: progress_callback(100.0, total_size, total_size), 0)
            return True
        
        headers = self.session.headers.copy()
        if downloaded_size > 0:
            headers['Range'] = f'bytes={downloaded_size}-'
            if status_callback:
                Clock.schedule_once(lambda dt: status_callback("Resuming..."), 0)
        
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                response = self.session.get(url, headers=headers, stream=True, timeout=60)
                
                if downloaded_size > 0 and response.status_code != 206:
                    downloaded_size = 0
                    response = self.session.get(url, stream=True, timeout=60)
                
                if response.status_code not in [200, 206]:
                    if status_callback:
                        Clock.schedule_once(lambda dt: status_callback(f"HTTP {response.status_code}"), 0)
                    return False
                
                mode = 'ab' if downloaded_size > 0 else 'wb'
                chunk_size = 8192
                
                with open(save_path, mode) as f:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        # 暂停处理
                        while self.pause_flag and not self.cancel_flag:
                            time.sleep(0.1)
                        
                        if self.cancel_flag:
                            if status_callback:
                                Clock.schedule_once(lambda dt: status_callback("Cancelled"), 0)
                            return False
                        
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            
                            if progress_callback and total_size > 0:
                                percentage = (downloaded_size / total_size * 100)
                                Clock.schedule_once(lambda dt, p=percentage, d=downloaded_size, t=total_size: 
                                                  progress_callback(p, d, t), 0)
                
                if status_callback:
                    Clock.schedule_once(lambda dt: status_callback("Done!"), 0)
                return True
                
            except (requests.exceptions.ConnectionError, 
                    requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError) as e:
                retry_count += 1
                if retry_count < max_retries:
                    if status_callback:
                        Clock.schedule_once(lambda dt, r=retry_count: 
                            status_callback(f"Network error, retry {r}/{max_retries}..."), 0)
                    time.sleep(2)  # 等待2秒后重试
                    # 重新获取已下载大小
                    if os.path.exists(save_path):
                        downloaded_size = os.path.getsize(save_path)
                        headers['Range'] = f'bytes={downloaded_size}-'
                else:
                    if status_callback:
                        Clock.schedule_once(lambda dt: status_callback("Network failed"), 0)
                    return False
            except Exception as e:
                if status_callback:
                    Clock.schedule_once(lambda dt: status_callback(f"Error: {str(e)[:30]}"), 0)
                return False
        
        return False
    
    def get_repo_files(self, username, model, branch='main', subpath=''):
        """获取仓库文件列表"""
        try:
            api_url = f"https://hf-mirror.com/api/models/{username}/{model}/tree/{branch}"
            if subpath:
                api_url += f"/{subpath}"
            
            response = self.session.get(api_url, timeout=30)
            if response.status_code != 200:
                return None
            
            files_info = []
            data = response.json()
            
            for item in data:
                if item['type'] == 'file':
                    relative_path = item['path']
                    file_size = item.get('size', 0)
                    download_url = f"https://hf-mirror.com/{username}/{model}/resolve/{branch}/{relative_path}"
                    files_info.append((relative_path, download_url, file_size))
            
            return files_info
        except:
            return None


class HFDownloaderApp(App):
    """移动端下载器应用主类"""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.wake_lock = None
        self.window_flags_set = False
        self.file_checkboxes = []
        self.files_data = []
        self.file_selection_popup = None
        self.is_paused = False
        self.notification_id = 1001
        self.channel_id = 'hf_download_channel'
        self.state_file = None  # 状态保存文件路径
        self.pending_files = []  # 待下载文件列表
        self.current_save_dir = ''
    
    def build(self):
        self.title = 'HF下载工具'
        self.downloader = HFDownloader()
        self.download_thread = None
        self.is_downloading = False
        self.log_label = None  # 先初始化为 None
        
        # 主布局
        layout = BoxLayout(orientation='vertical', padding=10, spacing=10)
        
        # 标题
        title = Label(text='[b]HF Download Tool[/b]', 
                     markup=True, size_hint_y=0.08, font_size='20sp')
        layout.add_widget(title)
        
        # URL输入
        url_layout = BoxLayout(orientation='vertical', size_hint_y=0.15, spacing=5)
        url_layout.add_widget(Label(text='URL:', size_hint_y=0.3, halign='left'))
        self.url_input = TextInput(hint_text='Paste HuggingFace URL', 
                                   multiline=False, size_hint_y=0.7)
        url_layout.add_widget(self.url_input)
        layout.add_widget(url_layout)
        
        # 保存路径（Android）
        if platform == 'android':
            # Android 15 / ColorOS 15 需要的权限
            permissions_to_request = [
                Permission.INTERNET,
                Permission.WRITE_EXTERNAL_STORAGE, 
                Permission.READ_EXTERNAL_STORAGE,
                Permission.WAKE_LOCK,
            ]
            
            # Android 13+ 需要新的媒体权限
            try:
                permissions_to_request.extend([
                    Permission.READ_MEDIA_IMAGES,
                    Permission.READ_MEDIA_VIDEO,
                    Permission.READ_MEDIA_AUDIO,
                ])
            except:
                pass  # 旧版本 Android 不支持这些权限
            
            request_permissions(permissions_to_request)
            
            # ColorOS 15 推荐使用 Documents 目录
            default_path = '/storage/emulated/0/Documents/HF_Models'
        else:
            default_path = os.path.expanduser('~/Downloads/HF_Models')
        
        path_layout = BoxLayout(orientation='vertical', size_hint_y=0.12, spacing=5)
        path_layout.add_widget(Label(text='Save Path:', size_hint_y=0.3, halign='left'))
        self.path_input = TextInput(text=default_path, multiline=False, size_hint_y=0.7)
        path_layout.add_widget(self.path_input)
        layout.add_widget(path_layout)
        
        # 下载模式选择
        mode_layout = BoxLayout(orientation='horizontal', size_hint_y=0.08, spacing=10)
        mode_layout.add_widget(Label(text='Mode:', size_hint_x=0.25))
        self.mode_single_btn = Button(text='Single', size_hint_x=0.375)
        self.mode_batch_btn = Button(text='Batch', size_hint_x=0.375)
        self.mode_single_btn.bind(on_press=lambda x: self.set_mode('single'))
        self.mode_batch_btn.bind(on_press=lambda x: self.set_mode('batch'))
        mode_layout.add_widget(self.mode_single_btn)
        mode_layout.add_widget(self.mode_batch_btn)
        layout.add_widget(mode_layout)
        
        self.batch_mode = False
        self.mode_single_btn.background_color = (0.2, 0.6, 1, 1)
        
        # 按钮区第一行：下载/暂停/取消
        btn_layout1 = BoxLayout(orientation='horizontal', size_hint_y=0.07, spacing=5)
        self.download_btn = Button(text='Start', font_size='14sp',
                                   background_color=(0.2, 0.8, 0.2, 1))
        self.download_btn.bind(on_press=self.start_download)
        
        self.pause_btn = Button(text='Pause', font_size='14sp', disabled=True,
                               background_color=(1, 0.6, 0, 1))
        self.pause_btn.bind(on_press=self.toggle_pause)
        
        self.cancel_btn = Button(text='Cancel', font_size='14sp', disabled=True,
                                background_color=(0.8, 0.2, 0.2, 1))
        self.cancel_btn.bind(on_press=self.cancel_download)
        
        btn_layout1.add_widget(self.download_btn)
        btn_layout1.add_widget(self.pause_btn)
        btn_layout1.add_widget(self.cancel_btn)
        layout.add_widget(btn_layout1)
        
        # 按钮区第二行：设置按钮（ColorOS 省电优化引导）
        btn_layout2 = BoxLayout(orientation='horizontal', size_hint_y=0.06, spacing=5)
        self.settings_btn = Button(text='[!] Battery Settings (Important)', font_size='12sp',
                                   background_color=(0.8, 0.4, 0.1, 1))
        self.settings_btn.bind(on_press=self.show_battery_settings)
        btn_layout2.add_widget(self.settings_btn)
        layout.add_widget(btn_layout2)
        
        # 进度条
        progress_layout = BoxLayout(orientation='vertical', size_hint_y=0.12, spacing=5)
        self.progress_bar = ProgressBar(max=100, value=0)
        self.progress_label = Label(text='Ready...', size_hint_y=0.4)
        progress_layout.add_widget(self.progress_bar)
        progress_layout.add_widget(self.progress_label)
        layout.add_widget(progress_layout)
        
        # 日志区域
        log_layout = BoxLayout(orientation='vertical', size_hint_y=0.30)
        log_layout.add_widget(Label(text='Log:', size_hint_y=0.1, halign='left'))
        
        self.log_scroll = ScrollView(size_hint_y=0.9)
        self.log_label = Label(text='', size_hint_y=None, markup=True)
        self.log_label.bind(texture_size=self.log_label.setter('size'))
        self.log_scroll.add_widget(self.log_label)
        log_layout.add_widget(self.log_scroll)
        layout.add_widget(log_layout)
        
        # 初始化保持屏幕常亮和防止后台杀死（在 UI 创建完成后）
        Clock.schedule_once(lambda dt: self.init_android_features(), 0.5)
        
        return layout
    
    def init_android_features(self):
        """初始化 Android 特性"""
        self.acquire_wake_lock()
        self.log_message('Ready')
    
    def init_state_file(self):
        """初始化状态文件路径"""
        try:
            save_dir = self.path_input.text.strip() if self.path_input else ''
            if save_dir:
                os.makedirs(save_dir, exist_ok=True)
                self.state_file = os.path.join(save_dir, '.hf_download_state.json')
        except Exception:
            self.state_file = None
    
    def save_download_state(self, files, save_dir):
        """保存下载状态"""
        if not self.state_file:
            return
        try:
            state = {
                'files': files,
                'save_dir': save_dir,
                'url': self.url_input.text.strip() if self.url_input else ''
            }
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f)
        except Exception:
            pass
    
    def load_download_state(self):
        """加载下载状态"""
        try:
            if not self.state_file or not os.path.exists(self.state_file):
                return None
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None
    
    def clear_download_state(self):
        """清除下载状态"""
        try:
            if self.state_file and os.path.exists(self.state_file):
                os.remove(self.state_file)
        except Exception:
            pass
    
    def check_pending_downloads(self):
        """检查是否有未完成的下载"""
        try:
            state = self.load_download_state()
            if not state or not state.get('files'):
                return
            
            files = state['files']
            save_dir = state.get('save_dir', '')
            url = state.get('url', '')
            
            if not save_dir:
                return
            
            pending = []
            for f in files:
                try:
                    path, file_url, size = f
                    save_path = os.path.join(save_dir, path)
                    if os.path.exists(save_path):
                        if os.path.getsize(save_path) < size:
                            pending.append(f)
                    else:
                        pending.append(f)
                except Exception:
                    continue
            
            if pending:
                self.pending_files = pending
                self.current_save_dir = save_dir
                if url and self.url_input:
                    self.url_input.text = url
                self.log_message(f'Found {len(pending)} pending')
                self.log_message('Click Start to resume')
        except Exception:
            pass
    
    def create_notification_channel(self):
        """创建通知通道"""
        pass  # 简化版本不使用通知
    
    def show_download_notification(self, title, text, progress=-1):
        """显示下载通知"""
        pass  # 简化版本不使用通知
    
    def cancel_notification(self):
        """取消通知"""
        pass  # 简化版本不使用通知
    
    def check_battery_optimization(self):
        """检查电池优化状态"""
        pass  # 简化版本
    
    def request_high_priority(self):
        """请求高优先级"""
        pass  # 简化版本
    
    def show_battery_settings(self, instance):
        """显示电池设置引导"""
        self.show_manual_settings_guide()
    
    def show_manual_settings_guide(self):
        """显示手动设置指引"""
        guide_text = '''To enable background download:

1. Settings > Apps > App Management
2. Find "HF Download" app
3. Battery Usage > Allow background

4. Settings > Battery > Power Saving
5. Add this app to whitelist

6. In Recent Apps, swipe down on
   this app to LOCK it'''
        
        content = BoxLayout(orientation='vertical', padding=10)
        label = Label(text=guide_text, halign='left', valign='top', color=(1,1,1,1))
        label.bind(size=label.setter('text_size'))
        content.add_widget(label)
        
        popup = Popup(title='Manual Settings Guide', content=content,
                     size_hint=(0.9, 0.8))
        popup.open()
    
    def toggle_pause(self, instance):
        """切换暂停/继续"""
        if self.is_paused:
            # 继续下载
            self.is_paused = False
            self.downloader.pause_flag = False
            self.pause_btn.text = 'Pause'
            self.pause_btn.background_color = (1, 0.6, 0, 1)
            self.log_message('>> Download resumed')
        else:
            # 暂停下载
            self.is_paused = True
            self.downloader.pause_flag = True
            self.pause_btn.text = 'Resume'
            self.pause_btn.background_color = (0.2, 0.8, 0.2, 1)
            self.log_message('|| Download paused')
    
    def acquire_wake_lock(self):
        """获取唤醒锁，防止CPU睡眠和后台杀死（兼容 ColorOS 15）"""
        if platform == 'android' and not self.wake_lock:
            try:
                activity = PythonActivity.mActivity
                power_manager = cast(PowerManager, activity.getSystemService(Context.POWER_SERVICE))
                
                # 创建唤醒锁（PARTIAL_WAKE_LOCK 保持CPU运行）
                # ColorOS 15 优化了电池管理，使用 ON_AFTER_RELEASE 确保可靠性
                self.wake_lock = power_manager.newWakeLock(
                    PowerManager.PARTIAL_WAKE_LOCK | PowerManager.ON_AFTER_RELEASE,
                    'HFDownloader::DownloadWakeLock'
                )
                
                # 获取唤醒锁（设置超时防止永久持有）
                if self.wake_lock and not self.wake_lock.isHeld():
                    # 10小时超时（足够下载大文件）
                    self.wake_lock.acquire(10 * 60 * 60 * 1000)
                    self.log_message('OK 防止后台杀死已启用')
            except Exception as e:
                self.log_message(f'! 唤醒锁失败: {e}')
    
    def release_wake_lock(self):
        """释放唤醒锁"""
        if platform == 'android' and self.wake_lock:
            try:
                if self.wake_lock.isHeld():
                    self.wake_lock.release()
                    self.log_message('X 唤醒锁已释放')
            except Exception as e:
                self.log_message(f'! 释放唤醒锁失败: {e}')
    
    def keep_screen_on(self):
        """保持屏幕常亮，防止黑屏"""
        if platform == 'android' and not self.window_flags_set:
            try:
                activity = PythonActivity.mActivity
                window = activity.getWindow()
                
                # 直接使用常量值 FLAG_KEEP_SCREEN_ON = 128 (0x00000080)
                window.addFlags(128)
                self.window_flags_set = True
                self.log_message('OK 屏幕常亮已启用')
            except Exception as e:
                self.log_message(f'! 屏幕常亮设置失败: {e}')
    
    def clear_screen_on(self):
        """清除屏幕常亮设置"""
        if platform == 'android' and self.window_flags_set:
            try:
                activity = PythonActivity.mActivity
                window = activity.getWindow()
                # 直接使用常量值 FLAG_KEEP_SCREEN_ON = 128
                window.clearFlags(128)
                self.window_flags_set = False
                self.log_message('X 屏幕常亮已取消')
            except Exception as e:
                self.log_message(f'! 清除屏幕常亮失败: {e}')
    
    def set_mode(self, mode):
        """设置下载模式"""
        if mode == 'single':
            self.batch_mode = False
            self.mode_single_btn.background_color = (0.2, 0.6, 1, 1)
            self.mode_batch_btn.background_color = (0.5, 0.5, 0.5, 1)
        else:
            self.batch_mode = True
            self.mode_single_btn.background_color = (0.5, 0.5, 0.5, 1)
            self.mode_batch_btn.background_color = (0.2, 0.6, 1, 1)
    
    def log_message(self, message):
        """添加日志"""
        if self.log_label is None:
            return  # UI 未创建时忽略日志
        current = self.log_label.text
        self.log_label.text = f"{current}\n{message}" if current else message
        self.log_scroll.scroll_y = 0
    
    def update_progress(self, percentage, downloaded, total):
        """更新进度"""
        self.progress_bar.value = percentage
        self.progress_label.text = f"{self.downloader.format_size(downloaded)} / {self.downloader.format_size(total)} ({percentage:.1f}%)"
        # 更新通知栏进度
        self.show_download_notification('Downloading...', f'{percentage:.1f}%', percentage)
    
    def start_download(self, instance):
        """开始下载"""
        try:
            url = self.url_input.text.strip() if self.url_input else ''
            save_dir = self.path_input.text.strip() if self.path_input else ''
            
            if not url:
                self.show_popup('Warning', 'Please enter URL')
                return
            
            if not save_dir:
                self.show_popup('Warning', 'Please enter save path')
                return
            
            try:
                download_url, filename, is_directory, repo_info = self.downloader.parse_hf_url(url)
            except Exception as e:
                self.log_message(f'URL parse error: {e}')
                return
            
            if is_directory and not self.batch_mode:
                self.show_popup('Info', 'Directory URL, switch to Batch mode')
                return
            
            if not is_directory and self.batch_mode:
                self.show_popup('Info', 'Single file URL, switch to Single mode')
                return
            
            if not download_url and not is_directory:
                self.show_popup('Error', 'Cannot parse URL')
                return
            
            self.download_btn.disabled = True
            self.cancel_btn.disabled = False
            self.pause_btn.disabled = False
            self.is_downloading = True
            self.is_paused = False
            self.downloader.pause_flag = False
            
            if is_directory:
                self.log_message('Batch mode: Getting file list...')
                if repo_info:
                    self.log_message(f"Model: {repo_info.get('username', '')}/{repo_info.get('model', '')}")
                thread = threading.Thread(target=self._fetch_files_and_show_selection, 
                                           args=(repo_info, save_dir), daemon=True)
                thread.start()
            else:
                try:
                    save_path = os.path.join(save_dir, filename) if filename else save_dir
                except:
                    save_path = save_dir
                self.log_message(f'Downloading: {filename}')
                thread = threading.Thread(target=self._single_download, args=(download_url, save_path), daemon=True)
                thread.start()
        except Exception as e:
            self.log_message(f'Error: {str(e)[:50]}')
            self.download_btn.disabled = False
    
    def _fetch_files_and_show_selection(self, repo_info, save_dir):
        """获取文件列表并显示选择界面"""
        try:
            files = self.downloader.get_repo_files(
                repo_info['username'],
                repo_info['model'],
                repo_info['branch'],
                repo_info['subpath']
            )
            
            if not files:
                Clock.schedule_once(lambda dt: self.log_message('Failed to get file list'), 0)
                Clock.schedule_once(lambda dt: self._download_finished(False), 0)
                return
            
            self.files_data = files
            self.current_save_dir = save_dir
            Clock.schedule_once(lambda dt: self._show_file_selection(files), 0)
        except Exception as e:
            Clock.schedule_once(lambda dt: self.log_message(f'Error: {str(e)[:30]}'), 0)
            Clock.schedule_once(lambda dt: self._download_finished(False), 0)
    
    def _show_file_selection(self, files):
        """显示文件选择界面"""
        self.file_checkboxes = []
        
        # 创建内容布局
        content = BoxLayout(orientation='vertical', spacing=5, padding=10)
        
        # 标题
        header = BoxLayout(size_hint_y=None, height=40)
        header.add_widget(Label(text=f'Found {len(files)} files:', color=(1, 1, 1, 1)))
        content.add_widget(header)
        
        # 全选/取消全选按钮
        btn_layout = BoxLayout(size_hint_y=None, height=50, spacing=10)
        select_all_btn = Button(text='Select All', font_size='14sp')
        select_all_btn.bind(on_press=lambda x: self._toggle_all_files(True))
        deselect_all_btn = Button(text='Deselect All', font_size='14sp')
        deselect_all_btn.bind(on_press=lambda x: self._toggle_all_files(False))
        btn_layout.add_widget(select_all_btn)
        btn_layout.add_widget(deselect_all_btn)
        content.add_widget(btn_layout)
        
        # 文件列表（可滚动）
        scroll = ScrollView(size_hint_y=0.65)
        file_grid = GridLayout(cols=1, spacing=8, size_hint_y=None, padding=[5, 5])
        file_grid.bind(minimum_height=file_grid.setter('height'))
        
        for path, url, size in files:
            # 每个文件一行 - 增加行高
            row = BoxLayout(size_hint_y=None, height=80, spacing=5)
            
            # 复选框
            cb = CheckBox(active=True, size_hint_x=0.1)
            self.file_checkboxes.append((cb, path, url, size))
            row.add_widget(cb)
            
            # 文件名和大小 - 分开显示
            filename = os.path.basename(path)
            size_str = self.downloader.format_size(size)
            
            # 使用垂直布局显示文件名和大小
            info_layout = BoxLayout(orientation='vertical', size_hint_x=0.9)
            
            # 文件名 Label
            name_label = Label(
                text=filename,
                halign='left',
                valign='bottom',
                color=(1, 1, 1, 1),
                font_size='12sp',
                size_hint_y=0.6
            )
            name_label.bind(size=name_label.setter('text_size'))
            info_layout.add_widget(name_label)
            
            # 大小 Label
            size_label = Label(
                text=f'[{size_str}]',
                halign='left',
                valign='top',
                color=(0.7, 0.7, 0.7, 1),
                font_size='11sp',
                size_hint_y=0.4
            )
            size_label.bind(size=size_label.setter('text_size'))
            info_layout.add_widget(size_label)
            
            row.add_widget(info_layout)
            file_grid.add_widget(row)
        
        scroll.add_widget(file_grid)
        content.add_widget(scroll)
        
        # 下载按钮
        download_btn = Button(
            text='Download Selected', 
            size_hint_y=None, 
            height=60,
            font_size='16sp',
            background_color=(0.2, 0.8, 0.2, 1)
        )
        download_btn.bind(on_press=self._start_selected_download)
        content.add_widget(download_btn)
        
        # 显示弹窗
        self.file_selection_popup = Popup(
            title='Select Files', 
            content=content,
            size_hint=(0.95, 0.9)
        )
        self.file_selection_popup.open()
        
        # 恢复按钮状态
        self.download_btn.disabled = False
        self.cancel_btn.disabled = True
    
    def _toggle_all_files(self, select):
        """全选/取消全选"""
        for cb, path, url, size in self.file_checkboxes:
            cb.active = select
    
    def _start_selected_download(self, instance):
        """开始下载选中的文件"""
        try:
            selected_files = [(path, url, size) for cb, path, url, size in self.file_checkboxes if cb.active]
            
            if not selected_files:
                self.show_popup('Notice', 'Please select at least one file')
                return
            
            if self.file_selection_popup:
                self.file_selection_popup.dismiss()
            
            self.log_message(f'\nDownloading {len(selected_files)} files...')
            
            self.download_btn.disabled = True
            self.cancel_btn.disabled = False
            self.pause_btn.disabled = False
            self.is_downloading = True
            self.is_paused = False
            self.downloader.pause_flag = False
            
            thread = threading.Thread(target=self._download_selected_files, 
                                      args=(selected_files, self.current_save_dir), daemon=True)
            thread.start()
        except Exception as e:
            self.log_message(f'Error: {str(e)[:30]}')
    
    def _download_selected_files(self, files, save_dir):
        """下载选中的文件"""
        total = len(files)
        for i, (path, url, size) in enumerate(files, 1):
            if not self.is_downloading:
                break
            
            filename = os.path.basename(path)
            try:
                save_path = os.path.join(save_dir, path)
                os.makedirs(os.path.dirname(save_path) if os.path.dirname(save_path) else save_dir, exist_ok=True)
            except Exception as e:
                Clock.schedule_once(lambda dt: self.log_message(f'Path error: {e}'), 0)
                continue
            
            # 检查是否有旧文件（断点续传）
            existing_size = 0
            if os.path.exists(save_path):
                existing_size = os.path.getsize(save_path)
            
            if existing_size > 0 and existing_size < size:
                Clock.schedule_once(lambda dt, p=path, e=existing_size, s=size, idx=i, t=total: 
                    self.log_message(f'\n[{idx}/{t}] {os.path.basename(p)}\n  -> RESUME: {self.downloader.format_size(e)}/{self.downloader.format_size(s)}'), 0)
            elif existing_size >= size and size > 0:
                Clock.schedule_once(lambda dt, p=path, idx=i, t=total: 
                    self.log_message(f'\n[{idx}/{t}] {os.path.basename(p)} (done)'), 0)
                continue
            else:
                Clock.schedule_once(lambda dt, p=path, idx=i, t=total: 
                    self.log_message(f'\n[{idx}/{t}] {os.path.basename(p)}'), 0)
            
            self.downloader.download_file(
                url, save_path,
                progress_callback=self.update_progress,
                status_callback=self.log_message
            )
        
        # 下载完成
        Clock.schedule_once(lambda dt: self._download_finished(True), 0)

    def _single_download(self, url, save_path):
        """单文件下载工作线程"""
        # 检查断点续传
        filename = os.path.basename(save_path)
        if os.path.exists(save_path):
            existing_size = os.path.getsize(save_path)
            total_size = self.downloader.get_file_size(url)
            if existing_size > 0 and existing_size < total_size:
                Clock.schedule_once(lambda dt: 
                    self.log_message(f'RESUME: {self.downloader.format_size(existing_size)}/{self.downloader.format_size(total_size)}'), 0)
        
        success = self.downloader.download_file(
            url, save_path,
            progress_callback=self.update_progress,
            status_callback=self.log_message
        )
        Clock.schedule_once(lambda dt: self._download_finished(success), 0)
    
    def _download_finished(self, success):
        """下载完成"""
        self.download_btn.disabled = False
        self.cancel_btn.disabled = True
        self.pause_btn.disabled = True
        self.is_downloading = False
        self.is_paused = False
        
        # 取消通知
        self.cancel_notification()
        
        if success:
            self.show_popup('Done', 'Download completed!')
    
    def cancel_download(self, instance):
        """取消下载"""
        self.downloader.cancel_flag = True
        self.is_downloading = False
        self.is_paused = False
        self.pause_btn.disabled = True
        self.cancel_notification()
        self.log_message('Cancelling...')
    
    def show_popup(self, title, message):
        """显示弹窗"""
        popup = Popup(title=title, content=Label(text=message),
                     size_hint=(0.8, 0.3))
        popup.open()


    def on_stop(self):
        """应用关闭时释放资源"""
        self.release_wake_lock()
        self.clear_screen_on()
        return True


if __name__ == '__main__':
    HFDownloaderApp().run()
