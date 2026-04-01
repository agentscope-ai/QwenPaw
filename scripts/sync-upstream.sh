#!/bin/bash
# CoPaw Fork Sync Script
# 用于同步上游仓库并解决冲突的交互式脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 确认函数
confirm() {
    read -p "$(echo -e ${YELLOW}$1${NC}) [y/N]: " response
    case "$response" in
        [yY][eE][sS]|[yY]) 
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

# 检查 git 状态
check_git_status() {
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        log_error "当前目录不是 Git 仓库"
        exit 1
    fi
}

# Phase 1: 准备和安全备份
phase1_preparation() {
    log_info "========== Phase 1: 准备和安全备份 =========="
    
    # 检查当前分支
    current_branch=$(git branch --show-current)
    log_info "当前分支: $current_branch"
    
    if [ "$current_branch" != "main" ]; then
        log_warning "当前不在 main 分支"
        if confirm "是否切换到 main 分支?"; then
            git checkout main
        else
            log_error "请先切换到 main 分支"
            exit 1
        fi
    fi
    
    # 创建备份分支
    backup_branch="backup-before-sync-$(date +%Y%m%d-%H%M%S)"
    log_info "创建备份分支: $backup_branch"
    git branch "$backup_branch"
    log_success "备份分支已创建"
    
    # 推送备份到远程
    if confirm "是否推送备份分支到远程?"; then
        git push origin "$backup_branch"
        log_success "备份分支已推送到远程"
    fi
    
    # 检查未提交的更改
    if ! git diff-index --quiet HEAD --; then
        log_warning "检测到未提交的更改"
        git status --short
        
        if confirm "是否提交所有更改为 WIP commit?"; then
            git add -A
            git commit -m "🚧 WIP: Local development changes before upstream sync

- Supabase authentication integration (console + website)
- Docker Compose microservices architecture with nginx
- Claude Code control tool
- Development scripts and documentation

This commit preserves work-in-progress before syncing commits from upstream."
            log_success "更改已提交"
        else
            log_error "请先处理未提交的更改"
            exit 1
        fi
    fi
    
    # 验证干净状态
    if git diff-index --quiet HEAD --; then
        log_success "工作区干净，可以继续"
    else
        log_error "工作区仍有未提交的更改"
        exit 1
    fi
    
    echo ""
}

# Phase 2: 配置上游远程
phase2_configure_upstream() {
    log_info "========== Phase 2: 配置上游远程 =========="
    
    # 检查是否已有 upstream
    if git remote | grep -q "^upstream$"; then
        log_warning "upstream 远程已存在"
        upstream_url=$(git remote get-url upstream)
        log_info "当前 upstream URL: $upstream_url"
        
        if confirm "是否更新 upstream URL?"; then
            git remote set-url upstream https://github.com/agentscope-ai/CoPaw.git
            log_success "upstream URL 已更新"
        fi
    else
        log_info "添加 upstream 远程"
        git remote add upstream https://github.com/agentscope-ai/CoPaw.git
        log_success "upstream 远程已添加"
    fi
    
    # 显示所有远程
    log_info "当前配置的远程:"
    git remote -v
    
    # 获取上游更新
    log_info "正在获取上游更新..."
    git fetch upstream
    git fetch upstream --tags
    log_success "上游更新已获取"
    
    # 显示分支差异
    log_info "查看分支差异:"
    commits_behind=$(git rev-list --count HEAD..upstream/main)
    commits_ahead=$(git rev-list --count upstream/main..HEAD)
    log_info "本地分支落后上游 $commits_behind 个提交"
    log_info "本地分支领先上游 $commits_ahead 个提交"
    
    # 预览上游最新提交
    log_info "上游最新 10 个提交:"
    git log --oneline upstream/main -10
    
    echo ""
}

# Phase 3: 执行 Rebase 策略
phase3_rebase() {
    log_info "========== Phase 3: 执行 Rebase 策略 =========="
    
    log_warning "即将开始 rebase，这将重写提交历史"
    log_info "如果遇到复杂冲突，可以使用 'git rebase --abort' 中止"
    
    if ! confirm "是否继续执行 rebase?"; then
        log_info "已取消 rebase"
        exit 0
    fi
    
    # 开始 rebase
    log_info "开始 rebase 到 upstream/main..."
    if git rebase upstream/main; then
        log_success "Rebase 成功完成，没有冲突！"
    else
        log_warning "Rebase 遇到冲突，需要手动解决"
        show_conflict_resolution_guide
        exit 1
    fi
    
    echo ""
}

# 显示冲突解决指南
show_conflict_resolution_guide() {
    cat << 'CONFLICT_GUIDE'

========== 冲突解决指南 ==========

1. 查看冲突文件:
   git status
   git diff --name-only --diff-filter=U

2. 解决冲突策略:

   A. 保留本地版本（适用于自定义文件）:
      git checkout --ours <file>

   B. 保留上游版本（适用于上游文件）:
      git checkout --theirs <file>

   C. 手动合并（适用于共享文件）:
      编辑文件，解决 <<<< ==== >>>> 之间的冲突

3. 关键文件冲突解决建议:

   docker-compose.yml:
   - 手动合并：保留上游基础 + 本地服务（nginx, console, website）

   console/package.json:
   - 手动合并：合并两边的依赖
   - 解决后运行: cd console && npm install

   console/src/App.tsx:
   - 保留本地版本: git checkout --ours console/src/App.tsx

   website/src/**:
   - 保留本地版本: git checkout --ours website/src/

   src/copaw/agents/tools/claude_code_control.py:
   - 保留本地版本（新工具）

   pyproject.toml:
   - 手动合并：合并依赖项

4. 解决冲突后继续:
   git add <resolved-files>
   git rebase --continue

5. 如果太复杂，中止并切换到 merge 策略:
   git rebase --abort
   ./scripts/sync-upstream.sh --merge

========================================
CONFLICT_GUIDE
}

# Phase 3 替代方案: Merge 策略
phase3_merge() {
    log_info "========== Phase 3: 执行 Merge 策略 =========="
    
    log_info "使用 merge 策略同步上游"
    
    if ! confirm "是否继续执行 merge?"; then
        log_info "已取消 merge"
        exit 0
    fi
    
    # 开始 merge
    log_info "开始 merge upstream/main..."
    if git merge upstream/main -m "Merge upstream changes from agentscope-ai/CoPaw"; then
        log_success "Merge 成功完成，没有冲突！"
    else
        log_warning "Merge 遇到冲突，需要手动解决"
        show_conflict_resolution_guide
        log_info "解决冲突后运行: git commit"
        exit 1
    fi
    
    echo ""
}

# Phase 4: 验证和测试
phase4_verification() {
    log_info "========== Phase 4: 验证和测试 =========="
    
    # 检查提交历史
    log_info "检查提交历史:"
    git log --oneline --graph -20
    
    # 检查是否有冲突标记
    log_info "检查是否有遗留的冲突标记..."
    if git grep -n "<<<<<<< HEAD" 2>/dev/null; then
        log_error "发现冲突标记，请检查并解决"
        exit 1
    else
        log_success "没有发现冲突标记"
    fi
    
    # 验证关键文件
    log_info "验证关键文件存在:"
    
    files_to_check=(
        "src/copaw/agents/tools/claude_code_control.py"
        "src/copaw/app/routers/supabase_auth.py"
        "console/src/contexts/AuthContext.tsx"
        "website/src/contexts/AuthContext.tsx"
        "scripts/dev-start.sh"
        "nginx/nginx.conf"
    )
    
    for file in "${files_to_check[@]}"; do
        if [ -f "$file" ]; then
            log_success "✓ $file"
        else
            log_warning "✗ $file (不存在)"
        fi
    done
    
    # 测试构建
    if confirm "是否运行构建测试?"; then
        log_info "测试 Docker Compose 配置..."
        if docker-compose config > /dev/null 2>&1; then
            log_success "Docker Compose 配置有效"
        else
            log_error "Docker Compose 配置无效"
        fi
        
        log_info "测试 console 构建..."
        if [ -d "console" ]; then
            cd console
            if npm install && npm run build; then
                log_success "Console 构建成功"
            else
                log_error "Console 构建失败"
            fi
            cd ..
        fi
        
        log_info "测试 website 构建..."
        if [ -d "website" ]; then
            cd website
            if npm install && npm run build; then
                log_success "Website 构建成功"
            else
                log_error "Website 构建失败"
            fi
            cd ..
        fi
    fi
    
    echo ""
}

# Phase 5: 推送到远程
phase5_push() {
    log_info "========== Phase 5: 推送到远程 =========="
    
    log_warning "即将使用 --force-with-lease 推送到远程"
    log_info "这将重写远程历史"
    
    if ! confirm "是否推送到远程?"; then
        log_info "已取消推送"
        log_info "稍后可以手动推送: git push origin main --force-with-lease"
        exit 0
    fi
    
    # 推送到远程
    log_info "推送到 origin/main..."
    if git push origin main --force-with-lease; then
        log_success "成功推送到远程"
    else
        log_error "推送失败"
        log_info "可能原因: 远程有新的提交"
        log_info "请先 git fetch origin 检查远程状态"
        exit 1
    fi
    
    echo ""
}

# Phase 6: 清理和文档
phase6_cleanup() {
    log_info "========== Phase 6: 清理和文档 =========="
    
    # 创建同步标签
    if confirm "是否创建同步标签?"; then
        tag_name="sync-upstream-$(date +%Y%m%d)"
        git tag -a "$tag_name" -m "Synced commits from upstream agentscope-ai/CoPaw"
        log_success "标签 $tag_name 已创建"
        
        if confirm "是否推送标签到远程?"; then
            git push origin "$tag_name"
            log_success "标签已推送到远程"
        fi
    fi
    
    # 显示最终状态
    log_info "最终状态:"
    commits_behind=$(git rev-list --count HEAD..upstream/main 2>/dev/null || echo "0")
    commits_ahead=$(git rev-list --count upstream/main..HEAD 2>/dev/null || echo "0")
    log_success "本地分支落后上游 $commits_behind 个提交"
    log_success "本地分支领先上游 $commits_ahead 个提交"
    
    log_success "========== 同步完成！ =========="
    
    echo ""
}

# 主函数
main() {
    log_info "CoPaw Fork 上游同步脚本"
    log_info "================================"
    echo ""
    
    # 检查 git 状态
    check_git_status
    
    # 解析参数
    USE_MERGE=false
    SKIP_PHASES=""
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --merge)
                USE_MERGE=true
                shift
                ;;
            --skip-phase1)
                SKIP_PHASES="$SKIP_PHASES 1"
                shift
                ;;
            --skip-phase2)
                SKIP_PHASES="$SKIP_PHASES 2"
                shift
                ;;
            --continue-rebase)
                log_info "继续 rebase..."
                git rebase --continue
                exit $?
                ;;
            --abort)
                log_warning "中止同步..."
                if git rebase --abort 2>/dev/null; then
                    log_success "Rebase 已中止"
                fi
                exit 0
                ;;
            --help)
                cat << 'HELP'
用法: ./sync-upstream.sh [选项]

选项:
  --merge              使用 merge 策略而不是 rebase
  --skip-phase1        跳过 Phase 1 (准备和备份)
  --skip-phase2        跳过 Phase 2 (配置上游)
  --continue-rebase    继续被中断的 rebase
  --abort              中止当前的 rebase
  --help               显示此帮助信息

示例:
  ./sync-upstream.sh                    # 完整执行 (rebase 策略)
  ./sync-upstream.sh --merge            # 使用 merge 策略
  ./sync-upstream.sh --skip-phase1      # 跳过准备阶段
  ./sync-upstream.sh --continue-rebase  # 解决冲突后继续
HELP
                exit 0
                ;;
            *)
                log_error "未知选项: $1"
                log_info "使用 --help 查看帮助"
                exit 1
                ;;
        esac
    done
    
    # 执行各阶段
    if [[ ! "$SKIP_PHASES" =~ "1" ]]; then
        phase1_preparation
    fi
    
    if [[ ! "$SKIP_PHASES" =~ "2" ]]; then
        phase2_configure_upstream
    fi
    
    if [ "$USE_MERGE" = true ]; then
        phase3_merge
    else
        phase3_rebase
    fi
    
    phase4_verification
    phase5_push
    phase6_cleanup
}

# 运行主函数
main "$@"
