# -*- coding: utf-8 -*-
"""
《末日调查员》一键启动器
评委双击 start.exe 后:
1. 启动后端 server.exe
2. 等 2 秒让 WebSocket 服务起来
3. 启动 Godot 前端
4. 当前端关闭时,自动关闭后端
"""
import os
import sys
import time
import subprocess
import atexit


def main():
    # 定位 start.exe 所在目录(也就是 zip 解压后的根目录)
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    # 后端 exe 路径
    backend_exe = os.path.join(base_dir, "后端", "server.exe")
    # 前端 exe 路径
    frontend_exe = os.path.join(base_dir, "末日调查员", "末日调查员.exe")

    # 启动检查
    if not os.path.exists(backend_exe):
        print(f"找不到后端: {backend_exe}")
        input("按回车退出...")
        return
    if not os.path.exists(frontend_exe):
        print(f"找不到前端: {frontend_exe}")
        input("按回车退出...")
        return

    print("=" * 50)
    print("    《末日调查员》Doomsday Investigator")
    print("    腾讯光子工作室首届游戏大赛 · v6.3")
    print("=" * 50)
    print()
    print("启动中,请稍候...")
    print()

    # 启动后端(独立控制台窗口)
    print("[1/2] 启动后端服务器...")
    backend_proc = subprocess.Popen(
        [backend_exe],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        cwd=os.path.dirname(backend_exe),
    )

    # 等后端起来
    print("[2/2] 等待后端就绪(2 秒)...")
    time.sleep(2)

    # 注册退出回调
    def cleanup():
        if backend_proc.poll() is None:
            print("\n清理后端进程...")
            backend_proc.terminate()
            try:
                backend_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                backend_proc.kill()

    atexit.register(cleanup)

    # 启动前端
    print()
    print("准备就绪!正在打开游戏窗口...")
    print()
    print("【提示】关闭游戏窗口后,后端会自动退出。")
    print()
    frontend_proc = subprocess.Popen(
        [frontend_exe],
        cwd=os.path.dirname(frontend_exe),
    )

    # 等前端结束
    frontend_proc.wait()
    cleanup()
    print("\n游戏已退出,谢谢游玩!")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"启动器异常: {e}")
        import traceback
        traceback.print_exc()
        input("\n按回车退出...")