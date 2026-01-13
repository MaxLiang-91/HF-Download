#!/bin/bash
# APK 构建脚本（需要在 Linux 或 WSL 环境中运行）

echo "======================================"
echo "HF下载工具 - Android APK 构建"
echo "======================================"
echo ""

# 检查 buildozer
if ! command -v buildozer &> /dev/null; then
    echo "正在安装 buildozer..."
    pip3 install --user buildozer
    pip3 install --user cython
fi

# 检查依赖
echo "检查系统依赖..."
sudo apt-get update
sudo apt-get install -y git zip unzip openjdk-17-jdk python3-pip autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev

# 清理旧构建
echo ""
echo "清理旧构建文件..."
rm -rf .buildozer
rm -rf bin

# 开始构建
echo ""
echo "开始构建 APK..."
buildozer android debug

# 检查结果
if [ -f "bin/*.apk" ]; then
    echo ""
    echo "======================================"
    echo "✅ APK 构建成功！"
    echo "======================================"
    echo ""
    echo "APK 文件位置: bin/"
    ls -lh bin/*.apk
    echo ""
    echo "安装到手机："
    echo "adb install -r bin/hfdownloader-*.apk"
    echo ""
else
    echo ""
    echo "======================================"
    echo "❌ APK 构建失败"
    echo "======================================"
    echo "请检查错误信息"
fi
