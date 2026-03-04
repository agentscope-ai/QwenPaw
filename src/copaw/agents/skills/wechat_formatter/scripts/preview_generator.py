#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Live Preview Generator for WeChat Articles
实时预览生成器，支持边写边看效果
"""

import argparse
import sys
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from markdown_to_html import WeChatHTMLConverter
import webbrowser
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
import os


class MarkdownChangeHandler(FileSystemEventHandler):
    """监听Markdown文件变化的处理器"""

    def __init__(self, input_file: str, output_file: str, theme: str, auto_refresh: bool = True):
        self.input_file = Path(input_file).absolute()
        self.output_file = Path(output_file).absolute()
        self.theme = theme
        self.auto_refresh = auto_refresh
        self.converter = WeChatHTMLConverter(theme=theme)
        self.last_modified = 0

        # 初次转换
        self._convert()

    def _convert(self):
        """执行转换"""
        try:
            # 检查文件修改时间，避免重复转换
            current_modified = self.input_file.stat().st_mtime
            if current_modified == self.last_modified:
                return

            self.last_modified = current_modified

            # 转换文件
            self.converter.convert_file(str(self.input_file), str(self.output_file))

            timestamp = time.strftime('%H:%M:%S')
            print(f'[{timestamp}] ✅ 已更新预览: {self.output_file.name}')

        except Exception as e:
            timestamp = time.strftime('%H:%M:%S')
            print(f'[{timestamp}] ❌ 转换失败: {e}')

    def on_modified(self, event):
        """文件修改时触发"""
        if event.src_path == str(self.input_file):
            self._convert()


class QuietHTTPRequestHandler(SimpleHTTPRequestHandler):
    """静默的HTTP请求处理器（不打印访问日志）"""

    def log_message(self, format, *args):
        """覆盖日志方法，静默处理"""
        pass


def start_http_server(directory: Path, port: int = 8000):
    """启动HTTP服务器"""
    import functools

    handler = functools.partial(QuietHTTPRequestHandler, directory=str(directory))
    server = HTTPServer(('localhost', port), handler)
    print(f'🌐 本地服务器已启动: http://localhost:{port}')
    server.serve_forever()


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description='实时预览Markdown文章的微信公众号效果',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例用法:
  # 实时预览，自动监听文件变化
  python preview_generator.py --input article.md

  # 指定主题
  python preview_generator.py --input article.md --theme minimal

  # 指定输出目录和端口
  python preview_generator.py --input article.md --output preview/ --port 8080

工作原理:
  1. 首次运行时转换Markdown为HTML
  2. 在浏览器中打开预览
  3. 启动文件监听，当Markdown文件修改时自动重新转换
  4. 刷新浏览器即可看到最新效果

使用技巧:
  - 使用支持自动刷新的浏览器扩展（如Live Server）
  - 或手动刷新浏览器查看最新效果
  - 按Ctrl+C停止预览服务
        '''
    )

    parser.add_argument('-i', '--input', required=True, help='输入的Markdown文件路径')
    parser.add_argument('-o', '--output', help='输出目录（默认：./preview/）')
    parser.add_argument('-t', '--theme', default='tech',
                        choices=['tech', 'minimal', 'business'],
                        help='选择主题样式（默认：tech）')
    parser.add_argument('-p', '--port', type=int, default=8000,
                        help='HTTP服务器端口（默认：8000）')
    parser.add_argument('--no-browser', action='store_true',
                        help='不自动打开浏览器')

    args = parser.parse_args()

    try:
        # 确定输出路径
        input_path = Path(args.input).absolute()
        if not input_path.exists():
            raise FileNotFoundError(f'输入文件不存在: {args.input}')

        output_dir = Path(args.output) if args.output else Path('./preview')
        output_dir.mkdir(parents=True, exist_ok=True)

        output_file = output_dir / f'{input_path.stem}.html'

        print('🚀 启动实时预览服务...')
        print(f'📄 监听文件: {input_path}')
        print(f'📁 输出目录: {output_dir}')
        print(f'🎨 使用主题: {args.theme}')
        print()

        # 创建文件监听处理器
        event_handler = MarkdownChangeHandler(
            input_file=str(input_path),
            output_file=str(output_file),
            theme=args.theme
        )

        # 启动HTTP服务器（在后台线程）
        server_thread = threading.Thread(
            target=start_http_server,
            args=(output_dir, args.port),
            daemon=True
        )
        server_thread.start()

        # 在浏览器中打开预览
        if not args.no_browser:
            time.sleep(0.5)  # 等待服务器启动
            preview_url = f'http://localhost:{args.port}/{output_file.name}'
            webbrowser.open(preview_url)
            print(f'🌐 已在浏览器中打开预览: {preview_url}')

        print()
        print('👀 正在监听文件变化...')
        print('💡 提示：修改Markdown文件后，刷新浏览器即可看到最新效果')
        print('⏹️  按Ctrl+C停止服务')
        print()

        # 启动文件监听
        observer = Observer()
        observer.schedule(event_handler, path=str(input_path.parent), recursive=False)
        observer.start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
            print('\n👋 预览服务已停止')

        observer.join()

    except Exception as e:
        print(f'❌ 启动失败: {e}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
