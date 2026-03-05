# -*- coding: utf-8 -*-
"""
飞书写入主入口类
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional, List

from dotenv import load_dotenv

from .auth import FeishuAuth
from .uploader import FeishuImageUploader
from .parser import MarkdownParser
from .doc_writer import FeishuDocWriter


class FeishuWriter:
    """飞书写入主类"""

    def __init__(self):
        load_dotenv()

        app_id = os.getenv("FEISHU_APP_ID")
        app_secret = os.getenv("FEISHU_APP_SECRET")

        if not app_id or not app_secret:
            raise Exception("请在 .env 文件中配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")

        self.auth = FeishuAuth(app_id, app_secret)
        # uploader 会在写入时初始化，因为需要知道 md_file_path
        self.uploader = None
        self.doc_writer = FeishuDocWriter(self.auth)

    def write_file(
        self,
        md_path: str,
        target: str = "space",
        folder_token: Optional[str] = None,
        wiki_token: Optional[str] = None,
        check_duplicate: bool = True
    ) -> Dict[str, Any]:
        """
        将 MD 文件写入飞书

        Args:
            md_path: MD 文件路径
            target: 目标类型 (space/folder/wiki)
            folder_token: 文件夹 token（target=folder 时必需）
            wiki_token: 知识库 token（target=wiki 时必需）
            check_duplicate: 是否检查重复

        Returns:
            {"success": bool, "document_id": str, "message": str}
        """
        path = Path(md_path)
        if not path.exists():
            return {"success": False, "document_id": None, "message": f"文件不存在: {md_path}"}

        # 读取 MD 文件
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        # 用文件名作为标题（去掉 .md 扩展名）
        title = path.stem

        # 解析 MD 内容（不再传入 uploader）
        parser = MarkdownParser(str(path))
        blocks = parser.parse(content)

        # folder_token 回退到环境变量
        if target == "folder" and not folder_token:
            folder_token = os.getenv("FEISHU_DEFAULT_FOLDER_TOKEN")

        # 检查重复
        existing_doc = None
        if check_duplicate and folder_token:
            docs = self.doc_writer.list_documents_in_folder(folder_token)
            for doc in docs:
                if doc.get("name") == title:
                    existing_doc = doc
                    break

        if existing_doc:
            return {
                "success": False,
                "document_id": None,
                "message": f"duplicate:{existing_doc.get('token')}:{title}",
                "existing_doc": existing_doc
            }

        # 根据目标类型创建文档
        if target == "wiki":
            # 直接在知识库中创建文档
            wiki_space_id = os.getenv("FEISHU_DEFAULT_WIKI_SPACE_ID")
            wiki_node_token = wiki_token or os.getenv("FEISHU_DEFAULT_WIKI_NODE_TOKEN")

            if wiki_node_token and not wiki_space_id:
                wiki_space_id = self.doc_writer.get_wiki_space_id(wiki_node_token)

            if not wiki_space_id:
                return {"success": False, "document_id": None, "message": "未配置知识库 space_id，请在 .env 中配置或通过 --wiki-token 指定"}

            try:
                doc_id, node_token = self.doc_writer.create_wiki_document(
                    title, wiki_space_id, wiki_node_token
                )
            except Exception as e:
                return {"success": False, "document_id": None, "message": f"创建知识库文档失败: {e}"}

            # 写入内容（包含图片和表格处理）
            uploaded_images, write_success = self._write_content_with_images(str(path), doc_id, blocks, parser.pending_images, parser.pending_tables)

            return {
                "success": write_success,
                "document_id": doc_id,
                "node_token": node_token,
                "message": f"成功创建文档: {title}" if write_success else f"文档已创建但部分内容写入失败: {title}",
                "uploaded_images": uploaded_images
            }
        else:
            # 在云文档中创建
            try:
                doc_id, block_id = self.doc_writer.create_document(
                    title,
                    folder_token if target == "folder" else None
                )
            except Exception as e:
                return {"success": False, "document_id": None, "message": f"创建文档失败: {e}"}

            # 写入内容（包含图片和表格处理）
            uploaded_images, write_success = self._write_content_with_images(str(path), doc_id, blocks, parser.pending_images, parser.pending_tables)

            return {
                "success": write_success,
                "document_id": doc_id,
                "message": f"成功创建文档: {title}" if write_success else f"文档已创建但部分内容写入失败: {title}",
                "uploaded_images": uploaded_images
            }

    def _write_content_with_images(self, md_path: str, doc_id: str, blocks: List[Dict], pending_images: List, pending_tables: List) -> tuple:
        """
        写入内容，包含图片和表格处理，保持原始顺序

        Args:
            md_path: Markdown 文件路径（用于解析相对图片路径）
            doc_id: 文档 ID
            blocks: 所有 blocks
            pending_images: 待上传的图片列表 [(block_index, image_path, is_url), ...]
            pending_tables: 待处理的表格列表 [(block_index, table_data), ...]

        Returns:
            (成功上传的图片数量, 是否全部写入成功)
        """
        uploaded_count = 0
        all_success = True

        # 初始化 uploader（传入 md_path 用于处理相对路径）
        if not self.uploader:
            from pathlib import Path
            self.uploader = FeishuImageUploader(self.auth, Path(md_path).parent)
        else:
            from pathlib import Path
            self.uploader.md_dir = Path(md_path).parent

        # 构建图片索引映射（新的三元组格式）
        image_map = {idx: (path, is_url) for idx, path, is_url in pending_images}
        # 构建表格索引映射
        table_map = {idx: data for idx, data in pending_tables}

        # 按顺序处理每个 block
        # 为了保持顺序，需要分批写入：遇到图片或表格时先写入之前的普通块，再处理特殊块
        current_batch = []

        for i, block in enumerate(blocks):
            if i in image_map:
                # 遇到图片，先写入之前积累的普通块
                if current_batch:
                    if not self.doc_writer.append_blocks(doc_id, doc_id, current_batch):
                        all_success = False
                    current_batch = []

                # 处理图片
                image_path, is_url = image_map[i]

                # 1. 创建图片块占位符
                image_block_id = self.doc_writer.create_image_block(doc_id, doc_id)
                if not image_block_id:
                    print(f"警告: 创建图片块失败 - {image_path}")
                    continue

                # 2. 上传图片（uploader 会自动处理本地/网络图片）
                file_token = self.uploader.upload(image_path, image_block_id)
                if not file_token:
                    print(f"警告: 图片上传失败 - {image_path}")
                    continue

                # 3. 更新图片块的 token
                if self.doc_writer.replace_image_token(doc_id, image_block_id, file_token):
                    uploaded_count += 1
                    print(f"  [图片] 上传成功: {image_path[:60]}{'...' if len(image_path) > 60 else ''}")
                else:
                    print(f"警告: 更新图片块失败 - {image_path}")

            elif i in table_map:
                # 遇到表格，先写入之前积累的普通块
                if current_batch:
                    if not self.doc_writer.append_blocks(doc_id, doc_id, current_batch):
                        all_success = False
                    current_batch = []

                # 处理表格
                table_data = table_map[i]
                rows = len(table_data)
                cols = max(len(row) for row in table_data) if table_data else 0

                if rows > 0 and cols > 0:
                    # 1. 创建表格
                    table_block_id = self.doc_writer.create_table(doc_id, doc_id, rows, cols)
                    if table_block_id:
                        # 2. 填充表格内容
                        self.doc_writer.fill_table(doc_id, table_block_id, table_data)
                    else:
                        print(f"警告: 创建表格失败")
            else:
                # 普通块，加入当前批次
                current_batch.append(block)

        # 写入剩余的普通块
        if current_batch:
            if not self.doc_writer.append_blocks(doc_id, doc_id, current_batch):
                all_success = False

        return uploaded_count, all_success

    def update_document(self, document_id: str, md_path: str) -> Dict[str, Any]:
        """更新已有文档"""
        path = Path(md_path)
        if not path.exists():
            return {"success": False, "message": f"文件不存在: {md_path}"}

        # 读取 MD 文件
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        # 解析 MD 内容
        parser = MarkdownParser(str(path))
        blocks = parser.parse(content)

        # 清空原内容
        if not self.doc_writer.delete_document_content(document_id):
            return {"success": False, "message": "清空文档原内容失败，已中止更新操作"}

        # 写入新内容（包含图片和表格处理）
        uploaded_images, write_success = self._write_content_with_images(str(path), document_id, blocks, parser.pending_images, parser.pending_tables)

        return {
            "success": write_success,
            "document_id": document_id,
            "message": "文档更新成功" if write_success else "文档已更新但部分内容写入失败",
            "uploaded_images": uploaded_images
        }
