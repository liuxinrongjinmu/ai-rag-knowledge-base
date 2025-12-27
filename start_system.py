#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
RAG系统一键启动脚本
自动检查环境、启动系统
"""

import os
import sys
import subprocess
import time
import webbrowser
from pathlib import Path

def check_python_version():
    """检查Python版本"""
    print("🐍 检查Python版本...")
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print("❌ 需要Python 3.8或更高版本")
        return False
    print(f"✅ Python版本: {version.major}.{version.minor}.{version.micro}")
    return True

def check_dependencies():
    """检查依赖包"""
    print("\n📦 检查依赖包...")
    required_packages = [
        "flask",
        "langchain", 
        "langchain_community",
        "pypdf",
        "dashscope",
        "faiss-cpu"
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package.replace("-", "_"))
            print(f"✅ {package}")
        except ImportError:
            print(f"❌ {package}")
            missing_packages.append(package)
    
    if missing_packages:
        print(f"\n⚠️ 缺少依赖包: {', '.join(missing_packages)}")
        print("正在自动安装...")
        
        try:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", 
                "flask", "langchain", "langchain_community", 
                "pypdf2", "dashscope", "faiss-cpu"
            ])
            print("✅ 依赖包安装完成")
            return True
        except subprocess.CalledProcessError:
            print("❌ 自动安装失败，请手动安装:")
            print(f"pip install {' '.join(missing_packages)}")
            return False
    
    return True

def check_api_key():
    """检查API密钥"""
    print("\n🔑 检查API密钥...")
    api_key = os.getenv("DASHSCOPE_API_KEY")
    
    if not api_key:
        print("❌ 未设置 DASHSCOPE_API_KEY 环境变量")
        print("\n请按以下步骤设置:")
        print("1. 访问 https://dashscope.console.aliyun.com/")
        print("2. 注册/登录阿里云账号")
        print("3. 获取API密钥")
        print("4. 设置环境变量:")
        
        if os.name == 'nt':  # Windows
            print("   set DASHSCOPE_API_KEY=your_api_key_here")
            print("   或在系统环境变量中设置")
        else:  # Unix/Linux/Mac
            print("   export DASHSCOPE_API_KEY=your_api_key_here")
            print("   或在 ~/.bashrc 中添加")
        
        return False
    
    print("✅ API密钥已设置")
    return True

def check_knowledge_base():
    """检查知识库"""
    print("\n📚 检查知识库...")
    vector_db_path = Path("./vector_db")
    
    if vector_db_path.exists() and any(vector_db_path.iterdir()):
        print("✅ 知识库存在")
        return True
    else:
        print("⚠️ 知识库不存在或为空")
        print("请先上传PDF文档到管理界面: http://localhost:5000/admin")
        return True  # 不阻止启动，但提示用户

def start_server():
    """启动服务器"""
    print("\n🚀 启动RAG系统服务器...")
    
    try:
        # 在新进程中启动app.py
        process = subprocess.Popen([
            sys.executable, "app.py"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        # 等待服务器启动
        print("⏳ 等待服务器启动...")
        for i in range(30):  # 等待最多30秒
            time.sleep(1)
            if process.poll() is not None:  # 进程已退出
                stdout, stderr = process.communicate()
                print(f"❌ 服务器启动失败:")
                print(f"标准输出: {stdout}")
                print(f"错误输出: {stderr}")
                return None
            
            print(f"   启动中... {i+1}/30秒")
        
        # 检查服务器是否真的在运行
        try:
            import requests
            response = requests.get("http://localhost:5000", timeout=5)
            if response.status_code == 200:
                print("✅ 服务器启动成功!")
                return process
        except:
            pass
        
        print("⚠️ 服务器可能未完全启动，请检查日志")
        return process
        
    except Exception as e:
        print(f"❌ 启动服务器失败: {e}")
        return None

def open_browser():
    """打开浏览器"""
    print("\n🌐 打开浏览器...")
    try:
        # 等待一秒确保服务器就绪
        time.sleep(1)
        webbrowser.open("http://localhost:5000")
        print("✅ 浏览器已打开")
    except Exception as e:
        print(f"⚠️ 无法自动打开浏览器: {e}")
        print("请手动访问: http://localhost:5000")

def show_usage_info():
    """显示使用说明"""
    print("\n" + "="*60)
    print("🎉 RAG系统启动成功!")
    print("="*60)
    print("📱 用户界面: http://localhost:5000")
    print("⚙️ 管理界面: http://localhost:5000/admin")
    print("   用户名: admin")
    print("   密码: admin123")
    print("\n💡 使用说明:")
    print("1. 首次使用请先访问管理界面上传PDF文档")
    print("2. 用户界面支持智能问答，自动缓存常用问题")
    print("3. 相同问题再次询问将大幅加速响应")
    print("\n🛠️ 管理功能:")
    print("- 上传/更新PDF文档")
    print("- 查看缓存统计")
    print("- 清空缓存")
    print("- 重建知识库")
    print("\n🧪 性能测试:")
    print("运行 python performance_test.py 测试系统性能")
    print("\n按 Ctrl+C 停止服务器")
    print("="*60)

def main():
    """主函数"""
    print("🚀 RAG企业文档知识库系统 - 一键启动")
    print("="*60)
    
    # 检查环境
    if not check_python_version():
        return
    
    if not check_dependencies():
        return
    
    if not check_api_key():
        return
    
    check_knowledge_base()
    
    # 启动服务器
    process = start_server()
    if process is None:
        return
    
    # 打开浏览器
    open_browser()
    
    # 显示使用说明
    show_usage_info()
    
    try:
        # 等待进程结束
        process.wait()
    except KeyboardInterrupt:
        print("\n\n🛑 正在停止服务器...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        print("✅ 服务器已停止")

if __name__ == "__main__":
    main()