# -*- coding: utf-8 -*-
"""
飞书文档写入模块
"""

import time
from typing import Dict, List, Tuple, Optional, Any

import requests

from .auth import FeishuAuth


class FeishuDocWriter:
    """飞书文档写入模块"""

    BASE_URL = "https://open.feishu.cn/open-apis"
    REQUEST_TIMEOUT = 30  # HTTP 请求超时（秒）

    def __init__(self, auth: FeishuAuth):
        self.auth = auth

    def _headers(self) -> Dict:
        return {
            "Authorization": f"Bearer {self.auth.get_token()}",
            "Content-Type": "application/json"
        }

    def create_document(self, title: str, folder_token: Optional[str] = None) -> Tuple[str, str]:
        """
        创建文档

        Returns:
            (document_id, document_block_id)
        """
        url = f"{self.BASE_URL}/docx/v1/documents"
        data = {"title": title}
        if folder_token:
            data["folder_token"] = folder_token

        resp = requests.post(url, headers=self._headers(), json=data, timeout=self.REQUEST_TIMEOUT)
        resp.raise_for_status()
        result = resp.json()

        if result.get("code") != 0:
            raise Exception(f"创建文档失败: {result.get('msg')}")

        doc = result.get("data", {}).get("document", {})
        return doc.get("document_id"), doc.get("document_id")  # document_id 同时是根 block_id

    def get_document_block_id(self, document_id: str) -> str:
        """获取文档的根 block_id"""
        url = f"{self.BASE_URL}/docx/v1/documents/{document_id}"
        resp = requests.get(url, headers=self._headers(), timeout=self.REQUEST_TIMEOUT)
        resp.raise_for_status()
        result = resp.json()

        if result.get("code") != 0:
            raise Exception(f"获取文档信息失败: {result.get('msg')}")

        return result.get("data", {}).get("document", {}).get("document_id")

    def append_blocks(self, document_id: str, block_id: str, blocks: List[Dict]) -> bool:
        """向文档追加内容块"""
        if not blocks:
            return True

        url = f"{self.BASE_URL}/docx/v1/documents/{document_id}/blocks/{block_id}/children"

        # 飞书 API 限制每次最多 50 个 block
        batch_size = 50
        for i in range(0, len(blocks), batch_size):
            batch = blocks[i:i + batch_size]
            data = {"children": batch}

            resp = requests.post(url, headers=self._headers(), json=data, timeout=self.REQUEST_TIMEOUT)
            resp.raise_for_status()
            result = resp.json()

            if result.get("code") != 0:
                print(f"警告: 写入部分内容失败: {result.get('msg')}")
                return False

        return True

    def list_documents_in_folder(self, folder_token: str) -> List[Dict]:
        """列出文件夹中的文档（支持分页）"""
        url = f"{self.BASE_URL}/drive/v1/files"
        all_files = []
        page_token = None

        while True:
            params = {
                "folder_token": folder_token,
                "page_size": 200
            }
            if page_token:
                params["page_token"] = page_token

            resp = requests.get(url, headers=self._headers(), params=params, timeout=self.REQUEST_TIMEOUT)
            resp.raise_for_status()
            result = resp.json()

            if result.get("code") != 0:
                return all_files

            all_files.extend(result.get("data", {}).get("files", []))

            # 检查是否有下一页
            if result.get("data", {}).get("has_more"):
                page_token = result.get("data", {}).get("page_token")
            else:
                break

        return all_files

    def delete_document_content(self, document_id: str) -> bool:
        """清空文档内容（用于更新）"""
        # 获取文档所有 block
        url = f"{self.BASE_URL}/docx/v1/documents/{document_id}/blocks"
        resp = requests.get(url, headers=self._headers(), timeout=self.REQUEST_TIMEOUT)
        resp.raise_for_status()
        result = resp.json()

        if result.get("code") != 0:
            return False

        blocks = result.get("data", {}).get("items", [])

        # 删除所有子 block（跳过根 block）
        for block in blocks:
            block_id = block.get("block_id")
            if block_id and block_id != document_id:
                delete_url = f"{self.BASE_URL}/docx/v1/documents/{document_id}/blocks/{block_id}"
                del_resp = requests.delete(delete_url, headers=self._headers(), timeout=self.REQUEST_TIMEOUT)
                if del_resp.status_code < 200 or del_resp.status_code >= 300:
                    print(f"警告: 删除 block {block_id} 失败: status={del_resp.status_code}, body={del_resp.text}")
                    return False
                del_result = del_resp.json()
                if del_result.get("code") != 0:
                    print(f"警告: 删除 block {block_id} API 错误: {del_result.get('msg')}")
                    return False

        return True

    def move_to_wiki(self, document_id: str, space_id: str, parent_node_token: Optional[str] = None) -> bool:
        """将文档移动到知识库（已废弃，建议使用 create_wiki_document）

        Args:
            document_id: 文档 ID
            space_id: 知识库 space_id（数字）
            parent_node_token: 父节点 token（可选，用于放到指定节点下）
        """
        url = f"{self.BASE_URL}/wiki/v2/spaces/{space_id}/nodes"
        data = {
            "obj_type": "docx",
            "obj_token": document_id,
            "node_type": "origin"
        }
        if parent_node_token:
            data["parent_node_token"] = parent_node_token

        resp = requests.post(url, headers=self._headers(), json=data, timeout=self.REQUEST_TIMEOUT)
        resp.raise_for_status()
        result = resp.json()

        return result.get("code") == 0

    def create_wiki_document(self, title: str, space_id: str, parent_node_token: Optional[str] = None) -> Tuple[str, str]:
        """直接在知识库中创建文档

        Args:
            title: 文档标题
            space_id: 知识库 space_id
            parent_node_token: 父节点 token（可选）

        Returns:
            (obj_token, node_token) - obj_token 用于写入内容，node_token 用于访问链接
        """
        url = f"{self.BASE_URL}/wiki/v2/spaces/{space_id}/nodes"
        data = {
            "obj_type": "docx",
            "node_type": "origin",
            "title": title
        }
        if parent_node_token:
            data["parent_node_token"] = parent_node_token

        resp = requests.post(url, headers=self._headers(), json=data, timeout=self.REQUEST_TIMEOUT)
        resp.raise_for_status()
        result = resp.json()

        if result.get("code") != 0:
            raise Exception(f"创建知识库文档失败: {result.get('msg')}")

        node = result.get("data", {}).get("node", {})
        obj_token = node.get("obj_token")
        node_token = node.get("node_token")

        return obj_token, node_token

    def get_wiki_space_id(self, node_token: str) -> Optional[str]:
        """通过节点 token 获取知识库 space_id"""
        url = f"{self.BASE_URL}/wiki/v2/spaces/get_node"
        params = {"token": node_token}

        resp = requests.get(url, headers=self._headers(), params=params, timeout=self.REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return None

        result = resp.json()
        if result.get("code") != 0:
            return None

        return result.get("data", {}).get("node", {}).get("space_id")

    def create_image_block(self, document_id: str, block_id: str) -> Optional[str]:
        """
        创建空的图片块占位符

        Args:
            document_id: 文档 ID
            block_id: 父块 ID（通常是文档根 block_id）

        Returns:
            创建的图片块 block_id，失败返回 None
        """
        url = f"{self.BASE_URL}/docx/v1/documents/{document_id}/blocks/{block_id}/children"
        data = {
            "children": [
                {
                    "block_type": 27,
                    "image": {}
                }
            ]
        }

        try:
            resp = requests.post(url, headers=self._headers(), json=data, timeout=self.REQUEST_TIMEOUT)
            resp.raise_for_status()
            result = resp.json()

            if result.get("code") != 0:
                print(f"警告: 创建图片块失败: {result.get('msg')}")
                return None

            # 返回创建的图片块 block_id
            children = result.get("data", {}).get("children", [])
            if children:
                return children[0].get("block_id")
            return None
        except Exception as e:
            print(f"警告: 创建图片块异常: {e}")
            return None

    def replace_image_token(self, document_id: str, block_id: str, file_token: str) -> bool:
        """
        更新图片块的 token（使用 replace_image）

        Args:
            document_id: 文档 ID
            block_id: 图片块 ID
            file_token: 上传图片后获得的 file_token

        Returns:
            是否成功
        """
        url = f"{self.BASE_URL}/docx/v1/documents/{document_id}/blocks/{block_id}"
        data = {
            "replace_image": {
                "token": file_token
            }
        }

        try:
            resp = requests.patch(url, headers=self._headers(), json=data, timeout=self.REQUEST_TIMEOUT)
            resp.raise_for_status()
            result = resp.json()

            if result.get("code") != 0:
                print(f"警告: 更新图片块失败: {result.get('msg')}")
                return False

            return True
        except Exception as e:
            print(f"警告: 更新图片块异常: {e}")
            return False

    def create_table(self, document_id: str, block_id: str, rows: int, cols: int) -> Optional[str]:
        """
        创建表格块

        Args:
            document_id: 文档 ID
            block_id: 父块 ID
            rows: 行数
            cols: 列数

        Returns:
            创建的表格块 block_id，失败返回 None
        """
        url = f"{self.BASE_URL}/docx/v1/documents/{document_id}/blocks/{block_id}/children"
        data = {
            "children": [
                {
                    "block_type": 31,
                    "table": {
                        "property": {
                            "row_size": rows,
                            "column_size": cols
                        }
                    }
                }
            ]
        }

        try:
            resp = requests.post(url, headers=self._headers(), json=data, timeout=self.REQUEST_TIMEOUT)
            resp.raise_for_status()
            result = resp.json()

            if result.get("code") != 0:
                print(f"警告: 创建表格失败: {result.get('msg')}")
                return None

            children = result.get("data", {}).get("children", [])
            if children:
                return children[0].get("block_id")
            return None
        except Exception as e:
            print(f"警告: 创建表格异常: {e}")
            return None

    def get_table_cells(self, document_id: str, table_block_id: str) -> List[Dict[str, Any]]:
        """
        获取表格的所有单元格信息

        Args:
            document_id: 文档 ID
            table_block_id: 表格块 ID

        Returns:
            单元格列表，每个元素包含 block_id 和位置信息
        """
        url = f"{self.BASE_URL}/docx/v1/documents/{document_id}/blocks/{table_block_id}/children"

        try:
            resp = requests.get(url, headers=self._headers(), timeout=self.REQUEST_TIMEOUT)
            resp.raise_for_status()
            result = resp.json()

            if result.get("code") != 0:
                print(f"警告: 获取表格子块失败: {result.get('msg')}")
                return []

            # 获取所有行
            rows = result.get("data", {}).get("items", [])
            cells = []

            # 遍历每一行获取单元格
            for row in rows:
                row_id = row.get("block_id")
                row_children_url = f"{self.BASE_URL}/docx/v1/documents/{document_id}/blocks/{row_id}/children"
                row_resp = requests.get(row_children_url, headers=self._headers(), timeout=self.REQUEST_TIMEOUT)
                row_resp.raise_for_status()
                row_result = row_resp.json()

                if row_result.get("code") == 0:
                    row_cells = row_result.get("data", {}).get("items", [])
                    cells.extend(row_cells)

            return cells
        except Exception as e:
            print(f"警告: 获取表格单元格异常: {e}")
            return []

    def fill_table_cell(self, document_id: str, cell_block_id: str, content: str) -> bool:
        """
        填充表格单元格内容

        Args:
            document_id: 文档 ID
            cell_block_id: 单元格块 ID
            content: 要填充的文本内容

        Returns:
            是否成功
        """
        url = f"{self.BASE_URL}/docx/v1/documents/{document_id}/blocks/{cell_block_id}/children"
        data = {
            "children": [
                {
                    "block_type": 2,
                    "text": {
                        "elements": [
                            {
                                "text_run": {
                                    "content": content
                                }
                            }
                        ]
                    }
                }
            ]
        }

        try:
            resp = requests.post(url, headers=self._headers(), json=data, timeout=self.REQUEST_TIMEOUT)
            resp.raise_for_status()
            result = resp.json()

            if result.get("code") != 0:
                # 输出详细错误信息用于调试
                print(f"填充单元格失败: code={result.get('code')}, msg={result.get('msg')}")
                return False

            return True
        except Exception as e:
            print(f"填充单元格异常: {e}")
            return False

    def fill_table(self, document_id: str, table_block_id: str, table_data: List[List[str]]) -> bool:
        """
        填充整个表格内容

        Args:
            document_id: 文档 ID
            table_block_id: 表格块 ID
            table_data: 二维数组，表格数据

        Returns:
            是否成功
        """
        try:
            # 等待表格创建完成
            time.sleep(0.5)

            # 获取表格的所有单元格（飞书表格的子块直接就是单元格，按行优先顺序排列）
            url = f"{self.BASE_URL}/docx/v1/documents/{document_id}/blocks/{table_block_id}/children"
            resp = requests.get(url, headers=self._headers(), timeout=self.REQUEST_TIMEOUT)
            resp.raise_for_status()
            result = resp.json()

            if result.get("code") != 0:
                print(f"警告: 获取表格单元格失败: {result.get('msg')}")
                return False

            cells = result.get("data", {}).get("items", [])

            # 计算表格尺寸
            rows = len(table_data)
            cols = max(len(row) for row in table_data) if table_data else 0

            # 按行优先顺序填充单元格
            for row_idx in range(rows):
                for col_idx in range(cols):
                    cell_index = row_idx * cols + col_idx

                    if cell_index >= len(cells):
                        break

                    if col_idx >= len(table_data[row_idx]):
                        continue

                    cell_block = cells[cell_index]
                    cell_id = cell_block.get("block_id")
                    content = table_data[row_idx][col_idx]

                    if content:
                        success = self.fill_table_cell(document_id, cell_id, content)
                        if not success:
                            print(f"警告: 填充单元格 [{row_idx}][{col_idx}] 失败")
                        # 添加小延时避免 API 限流
                        time.sleep(0.1)

            return True
        except Exception as e:
            print(f"警告: 填充表格异常: {e}")
            return False
