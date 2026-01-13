[app]

# 应用标题
title = HF下载工具

# 包名（唯一标识）
package.name = hfdownloader

# 包域名
package.domain = com.hfmirror

# 源代码目录
source.dir = .

# 源代码包含的文件
source.include_exts = py,png,jpg,kv,atlas

# 应用版本（兼容 ColorOS 15）
version = 2.1

# 应用需求（Python包）
requirements = python3,kivy,requests,pyjnius

# 应用图标（可选，建议提供）
#icon.filename = %(source.dir)s/icon.png

# 启动屏幕（可选）
#presplash.filename = %(source.dir)s/presplash.png

# Android 权限（兼容 Android 15 / ColorOS 15）
android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,ACCESS_NETWORK_STATE,WAKE_LOCK,READ_MEDIA_IMAGES,READ_MEDIA_VIDEO,READ_MEDIA_AUDIO,MANAGE_EXTERNAL_STORAGE,POST_NOTIFICATIONS

# Android API 级别（Android 15 = API 35）
android.api = 35

# 最低 API 级别（支持 Android 5.0+）
android.minapi = 21

# Android NDK 版本
android.ndk = 25b

# Android 架构（一加 ACE 2 Pro 使用骁龙8 Gen2，支持 ARM64）
android.archs = arm64-v8a

# 应用方向
orientation = portrait

# 全屏模式
fullscreen = 0

# Android 入口点
android.entrypoint = org.kivy.android.PythonActivity

# Android 应用主题
#android.apptheme = "@android:style/Theme.NoTitleBar"

# 添加Java源码目录（可选）
#android.add_src = 

# 添加资源目录（可选）
#android.add_resources = 

# 添加权限（已在上面定义）
#android.add_permissions = 

# Gradle 依赖
#android.gradle_dependencies = 

# 签名配置（发布版本需要）
#android.release_artifact = aab
#android.logcat_filters = *:S python:D

# Android 备份规则
android.allow_backup = True

[buildozer]

# 日志级别 (0 = error only, 1 = info, 2 = debug)
log_level = 2

# 警告级别
warn_on_root = 1

# 构建目录
build_dir = ./.buildozer

# 构建缓存目录  
bin_dir = ./bin
