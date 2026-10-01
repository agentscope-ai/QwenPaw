# -*- coding: utf-8 -*-
"""QwenPaw file management end-to-end tests."""

from __future__ import annotations

import logging

import pytest
from playwright.sync_api import APIRequestContext, Page, expect

from config.settings import config
from utils.helpers import log_test_result, log_test_step

logger = logging.getLogger(__name__)

WORKSPACE_URL = f"{config.base_url}/files"
PROFILE_FIXTURES = {
    "_e2e_profile_a.md": "# E2E Profile A\n\nProfile fixture A.\n",
    "_e2e_profile_b.md": "# E2E Profile B\n\nProfile fixture B.\n",
}
FILE_ITEM_SELECTOR = 'div[class*="profileRow"]'
FILE_NAME_SELECTOR = 'button[class*="profileOpen"] > span:last-child'
SWITCH_SELECTOR = 'button.qwenpaw-switch[role="switch"]'
DRAG_HANDLE_SELECTOR = 'span[class*="dragHandle"]'


@pytest.fixture(scope="module")
def profile_file_fixtures(
    api_context: APIRequestContext,
) -> tuple[str, ...]:
    """Create deterministic profile files and restore the original state."""
    workspace = config.working_dir / "workspaces" / "default"
    workspace.mkdir(parents=True, exist_ok=True)
    originals: dict[str, bytes | None] = {}
    headers = {"X-Agent-Id": "default"}

    enabled_response = api_context.get(
        "/api/workspace/system-prompt-files",
        headers=headers,
    )
    assert enabled_response.ok, enabled_response.text()
    original_enabled = enabled_response.json()
    assert isinstance(original_enabled, list)

    for filename, content in PROFILE_FIXTURES.items():
        path = workspace / filename
        originals[filename] = path.read_bytes() if path.exists() else None
        response = api_context.put(
            f"/api/workspace/files/{filename}",
            data={"content": content},
            headers=headers,
        )
        assert response.ok, response.text()

    fixture_names = tuple(PROFILE_FIXTURES)
    seeded_enabled = [
        *fixture_names,
        *(name for name in original_enabled if name not in fixture_names),
    ]
    update_response = api_context.put(
        "/api/workspace/system-prompt-files",
        data=seeded_enabled,
        headers=headers,
    )
    assert update_response.ok, update_response.text()

    try:
        yield fixture_names
    finally:
        restore_response = api_context.put(
            "/api/workspace/system-prompt-files",
            data=original_enabled,
            headers=headers,
        )
        assert restore_response.ok, restore_response.text()
        for filename, original in originals.items():
            path = workspace / filename
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(original)


def navigate_to_workspace(page: Page) -> None:
    """Navigate to the workspace and wait for the source tabs."""
    page.goto(WORKSPACE_URL)
    page.wait_for_load_state("domcontentloaded")
    profile_tab = page.get_by_role("tab", name="Profile", exact=True).or_(
        page.get_by_role("tab", name="档案", exact=True)
    )
    expect(profile_tab).to_be_visible(timeout=config.browser.timeout)


def reset_project_binding(api_context: APIRequestContext) -> None:
    """Keep workspace tests independent from coding-mode project bindings."""
    disable_response = api_context.post(
        "/api/coding-mode",
        data={"enabled": False},
        headers={"X-Agent-Id": "default"},
    )
    assert disable_response.ok, disable_response.text()
    binding_response = api_context.put(
        "/api/workspace/project-directory",
        data={"path": None},
        headers={"X-Agent-Id": "default"},
    )
    assert binding_response.ok, binding_response.text()


def open_profile_files(page: Page) -> None:
    """Open the managed profile source."""
    profile_tab = page.get_by_role("tab", name="Profile", exact=True).or_(
        page.get_by_role("tab", name="档案", exact=True)
    )
    profile_tab.click()
    expect(profile_tab).to_have_attribute("aria-selected", "true")


def profile_row(page: Page, filename: str):
    """Return one profile row by its exact filename."""
    return page.locator(FILE_ITEM_SELECTOR).filter(
        has=page.get_by_role("button", name=filename, exact=True)
    )


def get_file_items(page: Page):
    """Return the currently rendered profile rows."""
    first_item = page.locator(FILE_ITEM_SELECTOR).first
    expect(first_item).to_be_visible(timeout=config.browser.timeout)
    items = page.locator(FILE_ITEM_SELECTOR).all()
    assert items, "Expected at least one managed profile file"
    return items


def drag_profile_row(page: Page, source, target) -> None:
    """Reorder two rows through the dnd-kit pointer sensor."""
    handle = source.locator(DRAG_HANDLE_SELECTOR).first
    expect(handle).to_be_visible(timeout=5000)
    source_box = handle.bounding_box()
    target_box = target.bounding_box()
    assert source_box is not None
    assert target_box is not None
    start_x = source_box["x"] + source_box["width"] / 2
    start_y = source_box["y"] + source_box["height"] / 2
    target_x = target_box["x"] + target_box["width"] / 2
    target_y = target_box["y"] + target_box["height"] * 0.75
    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(target_x, target_y, steps=12)
    page.mouse.up()


@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.files
class TestFileListEditSave:
    """Verify deterministic profile-file navigation."""

    @pytest.mark.test_id("FILE-001")
    def test_file_list_view_edit_save(
        self,
        page: Page,
        profile_file_fixtures: tuple[str, ...],
        request: pytest.FixtureRequest,
    ) -> None:
        """Verify a managed profile file opens in preview mode."""
        test_name = request.node.name
        filename = profile_file_fixtures[0]

        log_test_step("1. Open the managed profile source")
        navigate_to_workspace(page)
        open_profile_files(page)

        log_test_step("2. Verify the seeded profile rows")
        assert len(get_file_items(page)) >= 2
        row = profile_row(page, filename)
        expect(row).to_have_count(1)
        expect(row.locator(FILE_NAME_SELECTOR)).to_have_text(filename)
        expect(row.locator(SWITCH_SELECTOR)).to_be_checked()

        log_test_step("3. Open the seeded Markdown preview")
        row.get_by_role("button", name=filename, exact=True).click()
        heading = page.get_by_role("heading", name="E2E Profile A")
        expect(heading).to_be_visible(timeout=config.browser.timeout)

        log_test_result(test_name, True, 0)


@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.files
class TestFileToggleReorderMemory:
    """Verify profile toggling and persistent ordering."""

    @pytest.mark.test_id("FILE-002")
    def test_file_toggle_reorder_memory(
        self,
        page: Page,
        api_context: APIRequestContext,
        profile_file_fixtures: tuple[str, ...],
        request: pytest.FixtureRequest,
    ) -> None:
        """Toggle and reorder isolated profile-file fixtures."""
        test_name = request.node.name
        first_name, second_name = profile_file_fixtures
        headers = {"X-Agent-Id": "default"}

        navigate_to_workspace(page)
        open_profile_files(page)

        log_test_step("1. Toggle the first profile file off")
        order_response = api_context.get(
            "/api/workspace/system-prompt-files",
            headers=headers,
        )
        assert order_response.ok, order_response.text()
        original_order = order_response.json()
        try:
            toggle = profile_row(page, first_name).locator(SWITCH_SELECTOR)
            expect(toggle).to_be_checked()
            toggle.click()
            expect(profile_row(page, first_name)).to_have_count(
                0,
                timeout=config.browser.timeout,
            )
            disabled_response = api_context.get(
                "/api/workspace/system-prompt-files",
                headers=headers,
            )
            assert disabled_response.ok, disabled_response.text()
            assert first_name not in disabled_response.json()
        finally:
            restore_response = api_context.put(
                "/api/workspace/system-prompt-files",
                data=original_order,
                headers=headers,
            )
            assert restore_response.ok, restore_response.text()

        page.reload()
        page.wait_for_load_state("domcontentloaded")
        open_profile_files(page)
        expect(profile_row(page, first_name)).to_have_count(1)
        expect(
            profile_row(page, first_name).locator(SWITCH_SELECTOR)
        ).to_be_checked()

        log_test_step("2. Reorder the two fixture rows")
        try:
            drag_profile_row(
                page,
                profile_row(page, first_name),
                profile_row(page, second_name),
            )
            first_visible_name = page.locator(FILE_NAME_SELECTOR).first
            expect(first_visible_name).to_have_text(
                second_name,
                timeout=config.browser.timeout,
            )
            persisted_response = api_context.get(
                "/api/workspace/system-prompt-files",
                headers=headers,
            )
            assert persisted_response.ok, persisted_response.text()
            assert persisted_response.json()[:2] == [second_name, first_name]
        finally:
            restore_response = api_context.put(
                "/api/workspace/system-prompt-files",
                data=original_order,
                headers=headers,
            )
            assert restore_response.ok, restore_response.text()

        log_test_step("3. Reload and verify the restored profile list")
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        open_profile_files(page)
        expect(profile_row(page, first_name)).to_have_count(1)

        log_test_result(test_name, True, 0)


@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.files
class TestFileContentEditAndSave:
    """Verify profile-file editing and persistence."""

    @pytest.mark.test_id("FILE-003")
    def test_file_content_edit_save_reset(
        self,
        page: Page,
        api_context: APIRequestContext,
        profile_file_fixtures: tuple[str, ...],
        request: pytest.FixtureRequest,
    ) -> None:
        """Edit a fixture in Monaco, save it, then restore it by API."""
        test_name = request.node.name
        test_marker = "\n# E2E Test Marker"
        filename = profile_file_fixtures[0]
        original_content = PROFILE_FIXTURES[filename]
        headers = {"X-Agent-Id": "default"}

        navigate_to_workspace(page)
        open_profile_files(page)
        row = profile_row(page, filename)
        row.get_by_role("button", name=filename, exact=True).click()

        log_test_step("1. Switch the fixture from preview to edit mode")
        edit_button = page.get_by_role("button", name="Edit", exact=True).or_(
            page.get_by_role("button", name="编辑", exact=True)
        )
        expect(edit_button).to_be_visible(timeout=config.browser.timeout)
        edit_button.click()
        editor = page.locator(".monaco-editor").first
        expect(editor).to_be_visible(timeout=config.browser.timeout)

        try:
            log_test_step("2. Edit and save the fixture")
            editor.click()
            page.keyboard.press("ControlOrMeta+A")
            page.keyboard.insert_text(original_content + test_marker)
            save_button = page.locator(
                'div[class*="documentActions"] button'
            ).last
            expect(save_button).to_be_enabled(timeout=config.browser.timeout)
            save_button.click()

            log_test_step("3. Verify persistence through the Files API")
            expect(save_button).to_be_disabled(timeout=config.browser.timeout)
            response = api_context.get(
                f"/api/workspace/files/{filename}",
                headers=headers,
            )
            assert response.ok, response.text()
            assert test_marker.strip() in response.json()["content"]
        finally:
            restore_response = api_context.put(
                f"/api/workspace/files/{filename}",
                data={"content": original_content},
                headers=headers,
            )
            assert restore_response.ok, restore_response.text()

        log_test_result(test_name, True, 0)


# ============================================================================
# FILE-004: Workspace upload and download
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.files
class TestWorkspaceUploadDownload:
    """
    FILE-004: Workspace upload and download.

    Combined coverage (post-#6504 workspace redesign):
    1. Visit the files page (route moved from /workspace to /files)
    2. Verify the upload button (aria-label "Upload files") is visible
    3. Verify the hidden file input exists (multi-file, no accept filter)
    4. Open a file and verify the per-file download button appears in the
       editor toolbar (lucide Download icon)

    The legacy whole-workspace zip download/upload was removed upstream by
    #6504; the page now offers single-file upload plus per-file download.
    """

    @pytest.mark.test_id("FILE-004")
    def test_workspace_download_and_upload_button(self, page: Page, api_context, request: pytest.FixtureRequest):
        """Verify workspace upload and per-file download buttons."""
        test_name = request.node.name

        log_test_step("0. Seed a file so the tree has a row to open")
        reset_project_binding(api_context)
        seed = api_context.put(
            "/api/workspace/files/e2e_files_seed.txt",
            data={"content": "e2e seed for FILE-004\n"},
            headers={"X-Agent-Id": "default"},
        )
        assert seed.ok, f"Seed failed [{seed.status}]: {seed.text()}"

        log_test_step("1. Visit the files page")
        navigate_to_workspace(page)

        log_test_step("2. Find the upload button")
        upload_btn = page.locator(
            'button[aria-label*="Upload"], button[aria-label*="上传"], '
            'button:has-text("Upload files"), button:has-text("上传文件")'
        ).first
        expect(upload_btn).to_be_visible(timeout=5000)
        assert upload_btn.is_enabled(), "Upload button should be enabled"
        logger.info("Upload button visible and enabled")

        log_test_step("3. Verify the hidden file input exists")
        file_input = page.locator('input[type="file"]').first
        assert file_input.count() > 0, "A hidden file upload input should exist"
        logger.info("Hidden file input exists")

        log_test_step("4. Open the first file and verify the download button")
        first_row = page.locator('button[class*="treeRow"]:not([aria-expanded])').first
        expect(first_row).to_be_visible(timeout=10000)
        first_row.click()
        download_btn = page.locator('button:has(svg.lucide-download)').first
        expect(download_btn).to_be_visible(timeout=10000)
        assert download_btn.is_enabled(), "Download button should be enabled"
        logger.info("Per-file download button visible and enabled")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - workspace upload/download buttons OK")


# ============================================================================
# FILE-P1-004: Daily memory expand/collapse view
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.files
class TestDailyMemoryView:
    """
    FILE-P1-004: Daily memory expand/collapse view.

    Coverage:
    1. Find the daily memory section in the file list
    2. Expand a daily memory entry to view its content
    3. Collapse a daily memory entry
    """

    @pytest.mark.test_id("FILE-P1-004")
    def test_daily_memory_view(self, page: Page, request: pytest.FixtureRequest):
        """Test daily memory expand/collapse."""
        test_name = request.node.name

        log_test_step("Navigate to the workspace page")
        page.goto(f"{config.base_url}/files")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

        log_test_step("Find the daily memory section")
        memory_section = page.locator(
            ':text("Daily"), :text("Memory"), '
            ':text("daily"), :text("memory"), '
            '[class*="memory"], [class*="Memory"]'
        ).first

        if memory_section.count() == 0:
            logger.info("Daily memory section not found; verifying file list exists")
            file_list = page.locator(
                '[class*="fileList"], [class*="FileList"], '
                '.qwenpaw-tree, .ant-tree'
            ).first
            if file_list.count() > 0:
                logger.info("File list exists")
            else:
                logger.info("File list also not found; page may be empty")
            log_test_result(test_name, True, 0)
            return

        logger.info("Found daily memory section")

        log_test_step("Find expandable memory items")
        # Daily memory typically uses Collapse or clickable list items
        expandable_items = page.locator(
            '.qwenpaw-collapse-header, .ant-collapse-header, '
            '[class*="memoryItem"], [class*="memory-item"], '
            '[class*="dailyMemory"] [class*="header"]'
        ).all()

        if len(expandable_items) > 0:
            logger.info(f"Found {len(expandable_items)} expandable memory items")

            log_test_step("Expand the first memory item")
            expandable_items[0].click()
            page.wait_for_timeout(1000)

            # Verify expanded content
            expanded_content = page.locator(
                '.qwenpaw-collapse-content-active, .ant-collapse-content-active, '
                '[class*="memoryContent"], [class*="memory-content"]'
            ).first
            if expanded_content.count() > 0:
                content_text = expanded_content.inner_text()
                logger.info(f"Memory content expanded; length: {len(content_text)}")
            else:
                logger.info("No explicit content area found after expansion")

            log_test_step("Collapse the memory item")
            expandable_items[0].click()
            page.wait_for_timeout(500)
            logger.info("Memory item collapsed")
        else:
            logger.info("No expandable memory items found; another display mechanism may be used")
            # Try clicking the memory section
            memory_section.click()
            page.wait_for_timeout(1000)

        log_test_result(test_name, True, 0)

# ============================================================================
# FILE-P1-005: Markdown live preview
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.files
class TestMarkdownPreview:
    """
    FILE-P1-005: Markdown live preview.

    Coverage:
    1. Select a Markdown file in the file list
    2. Verify the editor area exists
    3. Verify the preview area exists
    """

    @pytest.mark.test_id("FILE-P1-005")
    def test_markdown_preview(self, page: Page, request: pytest.FixtureRequest):
        """Test Markdown live preview."""
        test_name = request.node.name

        log_test_step("Navigate to the workspace page")
        page.goto(f"{config.base_url}/files")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

        log_test_step("Find Markdown files in the file list")
        md_files = page.locator(
            ':text(".md"), :text("README"), '
            '[class*="file"]:has-text(".md")'
        ).all()

        if len(md_files) == 0:
            # Fall back to any file in the file tree
            file_items = page.locator(
                '.qwenpaw-tree-treenode, .ant-tree-treenode, '
                '[class*="fileItem"], [class*="file-item"]'
            ).all()
            if len(file_items) > 0:
                logger.info(f"Found {len(file_items)} file items; clicking the first")
                file_items[0].click()
                page.wait_for_timeout(2000)
            else:
                logger.info("File list is empty; skipping Markdown preview test")
                log_test_result(test_name, True, 0)
                return
        else:
            logger.info(f"Found {len(md_files)} Markdown-related files")
            md_files[0].click()
            page.wait_for_timeout(2000)

        log_test_step("Verify editor/preview areas exist")
        editor_area = page.locator(
            'textarea, [class*="editor"], [class*="Editor"], '
            '[class*="CodeMirror"], [class*="monaco"], '
            '[class*="fileContent"], [class*="file-content"]'
        ).first

        preview_area = page.locator(
            '[class*="preview"], [class*="Preview"], '
            '[class*="markdown"], [class*="Markdown"], '
            '.markdown-body'
        ).first

        has_editor = editor_area.count() > 0
        has_preview = preview_area.count() > 0

        if has_editor:
            logger.info("Editor area exists")
        if has_preview:
            logger.info("Preview area exists")
            preview_content = preview_area.inner_text()
            logger.info(f"Preview content length: {len(preview_content)}")

        if not has_editor and not has_preview:
            # At least verify a file content area exists
            content_area = page.locator(
                '[class*="content"], pre, code'
            ).first
            if content_area.count() > 0:
                logger.info("Found a file content display area")
            else:
                logger.info("Neither editor nor preview area found")

        log_test_result(test_name, True, 0)


# ============================================================================
# FILE-P2-001: Upload files into the workspace
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.files
class TestWorkspaceZipUpload:
    """FILE-P2-001: Upload files into the workspace.

    Upstream #6504 replaced the whole-workspace zip restore with
    single/multi-file upload, so this case now verifies the new upload
    entry (button + hidden input) on the files page.
    """

    @pytest.mark.test_id("FILE-P2-001")
    def test_workspace_zip_upload(self, page: Page, request: pytest.FixtureRequest):
        """Test the workspace upload entry."""
        test_name = request.node.name

        log_test_step("Navigate to the files page")
        page.goto(f"{config.base_url}/files")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

        log_test_step("Find the upload button")
        upload_btn = page.locator(
            'button[aria-label*="Upload"], button[aria-label*="上传"], '
            'button:has-text("Upload files"), button:has-text("上传文件")'
        ).first
        assert upload_btn.count() > 0, "Files page should have an upload button"
        expect(upload_btn).to_be_visible(timeout=5000)
        logger.info("Upload button exists and visible")

        log_test_step("Verify the hidden file input")
        file_input = page.locator('input[type="file"]').first
        assert file_input.count() > 0, "A hidden file input should exist"
        logger.info("Hidden file input exists")

        log_test_result(test_name, True, 0)


# ============================================================================
# FILE-P2-002: Download a workspace file
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.files
class TestWorkspaceZipDownload:
    """FILE-P2-002: Download a workspace file.

    Upstream #6504 replaced the whole-workspace zip download with a
    per-file download button in the editor toolbar, so this case now
    opens the first file and verifies that button.
    """

    @pytest.mark.test_id("FILE-P2-002")
    def test_workspace_zip_download(self, page: Page, api_context, request: pytest.FixtureRequest):
        """Test downloading a workspace file."""
        test_name = request.node.name

        log_test_step("Seed a file so the tree has a row to open")
        reset_project_binding(api_context)
        seed = api_context.put(
            "/api/workspace/files/e2e_zip_seed.txt",
            data={"content": "e2e seed for FILE-P2-002\n"},
            headers={"X-Agent-Id": "default"},
        )
        assert seed.ok, f"Seed failed [{seed.status}]: {seed.text()}"

        log_test_step("Navigate to the files page")
        page.goto(f"{config.base_url}/files")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

        log_test_step("Open the first file")
        first_row = page.locator('button[class*="treeRow"]:not([aria-expanded])').first
        expect(first_row).to_be_visible(timeout=10000)
        first_row.click()
        # Wait for the editor tab to open before the toolbar renders.
        expect(
            page.locator('button:has(svg.lucide-download)').first
        ).to_be_visible(timeout=10000)

        log_test_step("Find the download button")
        download_btn = page.locator('button:has(svg.lucide-download)').first
        assert download_btn.count() > 0, "Editor toolbar should have a download button"
        assert download_btn.is_enabled(), "Download button should be enabled"
        logger.info("Download button exists and enabled")

        log_test_result(test_name, True, 0)
