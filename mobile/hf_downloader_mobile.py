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

import os
import requests
import threading
import re
from urllib.parse import urlparse, unquote
from functools import partial

# Android 特定导入
if platform == 'android':
    from android.permissions import request_permissions, Permission
    from jnius import autoclass, cast
    
    # Java 类引用
    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    Context = autoclass('android.content.Context')
    PowerManager = autoclass('android.os.PowerManager')
    WindowManager = autoclass('android.view.WindowManager')

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
        """下载文件，支持断点续传"""
        self.cancel_flag = False
        self.pause_flag = False
        
        os.makedirs(os.path.dirname(save_path) if os.path.dirname(save_path) else '.', exist_ok=True)
        
        downloaded_size = 0
        if os.path.exists(save_path):
            downloaded_size = os.path.getsize(save_path)
        
        total_size = self.get_file_size(url)
        
        if downloaded_size > 0 and downloaded_size == total_size:
            if status_callback:
                Clock.schedule_once(lambda dt: status_callback("文件已存在"), 0)
            if progress_callback:
                Clock.schedule_once(lambda dt: progress_callback(100.0, total_size, total_size), 0)
            return True
        
        headers = self.session.headers.copy()
        if downloaded_size > 0:
            headers['Range'] = f'bytes={downloaded_size}-'
            if status_callback:
                Clock.schedule_once(lambda dt: status_callback("继续下载..."), 0)
        
        try:
            response = self.session.get(url, headers=headers, stream=True, timeout=30)
            
            if downloaded_size > 0 and response.status_code != 206:
                downloaded_size = 0
                response = self.session.get(url, stream=True, timeout=30)
            
            if response.status_code not in [200, 206]:
                if status_callback:
                    Clock.schedule_once(lambda dt: status_callback(f"下载失败: {response.status_code}"), 0)
                return False
            
            mode = 'ab' if downloaded_size > 0 else 'wb'
            chunk_size = 8192
            
            with open(save_path, mode) as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    while self.pause_flag and not self.cancel_flag:
                        pass
                    
                    if self.cancel_flag:
                        if status_callback:
                            Clock.schedule_once(lambda dt: status_callback("下载已取消"), 0)
                        return False
                    
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        
                        if progress_callback and total_size > 0:
                            percentage = (downloaded_size / total_size * 100)
                            Clock.schedule_once(lambda dt, p=percentage, d=downloaded_size, t=total_size: 
                                              progress_callback(p, d, t), 0)
            
            if status_callback:
                Clock.schedule_once(lambda dt: status_callback("下载完成！"), 0)
            return True
            
        except Exception as e:
            if status_callback:
                Clock.schedule_once(lambda dt: status_callback(f"错误: {str(e)}"), 0)
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
    
    def build(self):
        self.title = 'HF下载工具'
        self.downloader = HFDownloader()
        self.download_thread = None
        self.is_downloading = False
        
        # 初始化保持屏幕常亮和防止后台杀死
        self.acquire_wake_lock()
        self.keep_screen_on()
        
        # 主布局
        layout = BoxLayout(orientation='vertical', padding=10, spacing=10)
        
        # 标题
        title = Label(text='[b]HuggingFace 下载工具[/b]', 
                     markup=True, size_hint_y=0.08, font_size='20sp')
        layout.add_widget(title)
        
        # URL输入
        url_layout = BoxLayout(orientation='vertical', size_hint_y=0.15, spacing=5)
        url_layout.add_widget(Label(text='下载地址:', size_hint_y=0.3, halign='left'))
        self.url_input = TextInput(hint_text='粘贴 HuggingFace URL', 
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
        path_layout.add_widget(Label(text='保存路径:', size_hint_y=0.3, halign='left'))
        self.path_input = TextInput(text=default_path, multiline=False, size_hint_y=0.7)
        path_layout.add_widget(self.path_input)
        layout.add_widget(path_layout)
        
        # 下载模式选择
        mode_layout = BoxLayout(orientation='horizontal', size_hint_y=0.08, spacing=10)
        mode_layout.add_widget(Label(text='模式:', size_hint_x=0.25))
        self.mode_single_btn = Button(text='单文件', size_hint_x=0.375)
        self.mode_batch_btn = Button(text='批量', size_hint_x=0.375)
        self.mode_single_btn.bind(on_press=lambda x: self.set_mode('single'))
        self.mode_batch_btn.bind(on_press=lambda x: self.set_mode('batch'))
        mode_layout.add_widget(self.mode_single_btn)
        mode_layout.add_widget(self.mode_batch_btn)
        layout.add_widget(mode_layout)
        
        self.batch_mode = False
        self.mode_single_btn.background_color = (0.2, 0.6, 1, 1)
        
        # 按钮区
        btn_layout = BoxLayout(orientation='horizontal', size_hint_y=0.08, spacing=10)
        self.download_btn = Button(text='开始下载', 
                                   background_color=(0.2, 0.8, 0.2, 1))
        self.download_btn.bind(on_press=self.start_download)
        
        self.cancel_btn = Button(text='取消', disabled=True,
                                background_color=(0.8, 0.2, 0.2, 1))
        self.cancel_btn.bind(on_press=self.cancel_download)
        
        btn_layout.add_widget(self.download_btn)
        btn_layout.add_widget(self.cancel_btn)
        layout.add_widget(btn_layout)
        
        # 进度条
        progress_layout = BoxLayout(orientation='vertical', size_hint_y=0.15, spacing=5)
        self.progress_bar = ProgressBar(max=100, value=0)
        self.progress_label = Label(text='等待开始...', size_hint_y=0.4)
        progress_layout.add_widget(self.progress_bar)
        progress_layout.add_widget(self.progress_label)
        layout.add_widget(progress_layout)
        
        # 日志区域
        log_layout = BoxLayout(orientation='vertical', size_hint_y=0.34)
        log_layout.add_widget(Label(text='日志:', size_hint_y=0.1, halign='left'))
        
        self.log_scroll = ScrollView(size_hint_y=0.9)
        self.log_label = Label(text='', size_hint_y=None, markup=True)
        self.log_label.bind(texture_size=self.log_label.setter('size'))
        self.log_scroll.add_widget(self.log_label)
        log_layout.add_widget(self.log_scroll)
        layout.add_widget(log_layout)
        
        return layout
    
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
                    self.log_message('✅ 已启用防止后台杀死 (ColorOS 15 优化)')
            except Exception as e:
                self.log_message(f'⚠️ 唤醒锁失败: {e}')
    
    def release_wake_lock(self):
        """释放唤醒锁"""
        if platform == 'android' and self.wake_lock:
            try:
                if self.wake_lock.isHeld():
                    self.wake_lock.release()
                    self.log_message('❌ 已释放唤醒锁')
            except Exception as e:
                self.log_message(f'⚠️ 释放唤醒锁失败: {e}')
    
    def keep_screen_on(self):
        """保持屏幕常亮，防止黑屏"""
        if platform == 'android' and not self.window_flags_set:
            try:
                activity = PythonActivity.mActivity
                window = activity.getWindow()
                
                # 添加 FLAG_KEEP_SCREEN_ON 标志
                window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                self.window_flags_set = True
                self.log_message('✅ 已启用屏幕常亮')
            except Exception as e:
                self.log_message(f'⚠️ 屏幕常亮设置失败: {e}')
    
    def clear_screen_on(self):
        """清除屏幕常亮设置"""
        if platform == 'android' and self.window_flags_set:
            try:
                activity = PythonActivity.mActivity
                window = activity.getWindow()
                window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                self.window_flags_set = False
                self.log_message('❌ 已取消屏幕常亮')
            except Exception as e:
                self.log_message(f'⚠️ 清除屏幕常亮失败: {e}')
    
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
        current = self.log_label.text
        self.log_label.text = f"{current}\n{message}" if current else message
        self.log_scroll.scroll_y = 0
    
    def update_progress(self, percentage, downloaded, total):
        """更新进度"""
        self.progress_bar.value = percentage
        self.progress_label.text = f"{self.downloader.format_size(downloaded)} / {self.downloader.format_size(total)} ({percentage:.1f}%)"
    
    def start_download(self, instance):
        """开始下载"""
        url = self.url_input.text.strip()
        save_dir = self.path_input.text.strip()
        
        if not url:
            self.show_popup('警告', '请输入下载地址')
            return
        
        if not save_dir:
            self.show_popup('警告', '请输入保存路径')
            return
        
        download_url, filename, is_directory, repo_info = self.downloader.parse_hf_url(url)
        
        if is_directory and not self.batch_mode:
            self.show_popup('提示', '检测到目录URL，请切换到批量模式')
            return
        
        if not is_directory and self.batch_mode:
            self.show_popup('提示', '检测到单文件URL，请切换到单文件模式')
            return
        
        if not download_url and not is_directory:
            self.show_popup('错误', '无法解析URL')
            return
        
        self.download_btn.disabled = True
        self.cancel_btn.disabled = False
        self.is_downloading = True
        
        if is_directory:
            self.log_message('批量下载模式...')
            self.log_message(f"模型: {repo_info['username']}/{repo_info['model']}")
            # 简化版：直接下载所有文件（移动端不显示选择界面）
            thread = threading.Thread(target=self._batch_download, args=(repo_info, save_dir), daemon=True)
            thread.start()
        else:
            save_path = os.path.join(save_dir, filename)
            self.log_message(f'开始下载: {filename}')
            thread = threading.Thread(target=self._single_download, args=(download_url, save_path), daemon=True)
            thread.start()
    
    def _single_download(self, url, save_path):
        """单文件下载工作线程"""
        success = self.downloader.download_file(
            url, save_path,
            progress_callback=self.update_progress,
            status_callback=self.log_message
        )
        Clock.schedule_once(lambda dt: self._download_finished(success), 0)
    
    def _batch_download(self, repo_info, save_dir):
        """批量下载工作线程"""
        files = self.downloader.get_repo_files(
            repo_info['username'],
            repo_info['model'],
            repo_info['branch'],
            repo_info['subpath']
        )
        
        if not files:
            Clock.schedule_once(lambda dt: self.log_message('获取文件列表失败'), 0)
            Clock.schedule_once(lambda dt: self._download_finished(False), 0)
            return
        
        Clock.schedule_once(lambda dt: self.log_message(f'找到 {len(files)} 个文件'), 0)
        
        for i, (path, url, size) in enumerate(files, 1):
            if not self.is_downloading:
                break
            
            Clock.schedule_once(lambda dt, p=path: self.log_message(f'\n[{i}/{len(files)}] {p}'), 0)
            save_path = os.path.join(save_dir, path)
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            
            self.downloader.download_file(
                url, save_path,
                progress_callback=self.update_progress,
                status_callback=self.log_message
            )
        
        Clock.schedule_once(lambda dt: self._download_finished(True), 0)
    
    def _download_finished(self, success):
        """下载完成"""
        self.download_btn.disabled = False
        self.cancel_btn.disabled = True
        self.is_downloading = False
        
        # 下载完成后释放唤醒锁（可选，保持唤醒锁也可以）
        # self.release_wake_lock()
        # self.clear_screen_on()
        
        if success:
            self.show_popup('完成', '下载完成！')
    
    def cancel_download(self, instance):
        """取消下载"""
        self.downloader.cancel_flag = True
        self.is_downloading = False
        self.log_message('正在取消...')
    
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
