#!/bin/bash
# 冲突解决辅助脚本
# 用于在 rebase/merge 过程中快速解决常见冲突

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 检查是否在冲突状态
check_conflict_state() {
    if ! git status | grep -q "Unmerged paths\|both modified\|both added"; then
        log_error "当前没有检测到冲突"
        log_info "如果已解决所有冲突，请运行: git rebase --continue"
        exit 1
    fi
}

# 列出冲突文件
list_conflicts() {
    log_info "========== 冲突文件列表 =========="
    git diff --name-only --diff-filter=U | while read file; do
        echo -e "${RED}✗${NC} $file"
    done
    echo ""
}

# 显示文件冲突详情
show_conflict_details() {
    local file=$1
    log_info "========== $file 冲突详情 =========="
    git diff "$file" | head -50
    echo ""
}

# 自动解决策略
auto_resolve_file() {
    local file=$1
    local strategy=$2
    
    case $strategy in
        ours)
            log_info "保留本地版本: $file"
            git checkout --ours "$file"
            git add "$file"
            log_success "已解决: $file (使用本地版本)"
            ;;
        theirs)
            log_info "保留上游版本: $file"
            git checkout --theirs "$file"
            git add "$file"
            log_success "已解决: $file (使用上游版本)"
            ;;
        *)
            log_error "未知策略: $strategy"
            return 1
            ;;
    esac
}

# 智能解决冲突
smart_resolve() {
    log_info "========== 智能冲突解决 =========="
    log_info "根据文件类型自动选择解决策略"
    echo ""
    
    # 获取所有冲突文件
    conflicts=$(git diff --name-only --diff-filter=U)
    
    if [ -z "$conflicts" ]; then
        log_success "没有冲突需要解决"
        return 0
    fi
    
    for file in $conflicts; do
        case $file in
            # 保留本地版本的文件
            console/src/App.tsx|\
            console/src/pages/Login/index.tsx|\
            console/src/contexts/AuthContext.tsx|\
            console/src/lib/supabase.ts|\
            website/src/contexts/AuthContext.tsx|\
            website/src/pages/Login.tsx|\
            website/src/pages/AuthCallback.tsx|\
            website/src/pages/Docs.tsx|\
            website/src/pages/ReleaseNotes.tsx|\
            website/src/lib/supabase.ts|\
            src/copaw/agents/tools/claude_code_control.py|\
            src/copaw/app/routers/supabase_auth.py|\
            src/copaw/app/routers/supabase_client.py|\
            src/copaw/app/supabase_client.py|\
            scripts/dev-start.sh|\
            scripts/dev-stop.sh|\
            scripts/backend-dev.sh|\
            scripts/setup-supabase-auth.sh|\
            nginx/nginx.conf|\
            nginx/Dockerfile|\
            DEPLOYMENT.md|\
            docs/*)
                log_info "📝 $file - 自定义文件，保留本地版本"
                auto_resolve_file "$file" "ours"
                ;;
            
            # 需要手动合并的文件
            docker-compose.yml|\
            console/package.json|\
            website/package.json|\
            pyproject.toml)
                log_warning "⚠️  $file - 需要手动合并"
                log_info "   建议: 打开文件手动解决冲突"
                log_info "   解决后运行: git add $file"
                ;;
            
            # package-lock.json 特殊处理
            console/package-lock.json|\
            website/package-lock.json)
                log_info "📦 $file - 锁文件，将在 package.json 解决后重新生成"
                # 先保留上游版本，稍后重新生成
                auto_resolve_file "$file" "theirs"
                ;;
            
            # 配置文件
            console/vite.config.ts|\
            website/vite.config.ts)
                log_warning "⚙️  $file - 配置文件，建议手动检查"
                ;;
            
            # 默认保留上游版本
            *)
                log_info "🔄 $file - 默认保留上游版本"
                auto_resolve_file "$file" "theirs"
                ;;
        esac
        echo ""
    done
    
    # 检查剩余冲突
    remaining=$(git diff --name-only --diff-filter=U | wc -l)
    if [ "$remaining" -eq 0 ]; then
        log_success "所有冲突已自动解决！"
        log_info "运行以下命令继续:"
        log_info "  git rebase --continue"
    else
        log_warning "还有 $remaining 个文件需要手动解决"
        log_info "手动解决后运行:"
        log_info "  git add <file>"
        log_info "  git rebase --continue"
    fi
}

# 手动合并关键文件的辅助函数
merge_docker_compose() {
    log_info "========== docker-compose.yml 合并指南 =========="
    cat << 'DOCKER_GUIDE'
合并策略:
1. 保留上游的 copaw 服务定义（可能有更新）
2. 添加本地的服务: nginx, console, website
3. 合并 volumes 和 networks 配置

建议步骤:
1. 打开文件查看冲突: vim docker-compose.yml
2. 保留上游的 copaw 服务基础配置
3. 添加本地的微服务架构:
   - nginx (端口 80)
   - console (端口 5173)
   - website (端口 5174)
4. 确保 networks 和 volumes 包含所有服务需要的配置
5. 保存后运行: git add docker-compose.yml
DOCKER_GUIDE
}

merge_package_json() {
    local dir=$1
    log_info "========== $dir/package.json 合并指南 =========="
    cat << 'PACKAGE_GUIDE'
合并策略:
1. 合并 dependencies: 保留两边的依赖
2. 合并 devDependencies: 保留两边的依赖
3. 如果版本冲突，优先使用上游版本（除非本地有特殊需求）
4. scripts 部分: 保留本地自定义脚本

解决后:
1. git add package.json
2. cd <dir> && npm install  # 重新生成 package-lock.json
3. git add package-lock.json
PACKAGE_GUIDE
}

merge_pyproject_toml() {
    log_info "========== pyproject.toml 合并指南 =========="
    cat << 'PYPROJECT_GUIDE'
合并策略:
1. dependencies: 合并两边的依赖
2. optional-dependencies: 确保保留 supabase 组
3. 其他配置: 优先使用上游版本

关键点:
- 确保 supabase 可选依赖组存在:
  [project.optional-dependencies]
  supabase = [
      "supabase>=2.0.0",
  ]

解决后:
1. git add pyproject.toml
PYPROJECT_GUIDE
}

# 交互式菜单
interactive_menu() {
    while true; do
        echo ""
        log_info "========== 冲突解决菜单 =========="
        echo "1. 列出所有冲突文件"
        echo "2. 智能自动解决冲突"
        echo "3. 查看特定文件冲突详情"
        echo "4. 手动解决文件 (保留本地版本)"
        echo "5. 手动解决文件 (保留上游版本)"
        echo "6. docker-compose.yml 合并指南"
        echo "7. package.json 合并指南"
        echo "8. pyproject.toml 合并指南"
        echo "9. 继续 rebase"
        echo "0. 退出"
        echo ""
        read -p "请选择操作 [0-9]: " choice
        
        case $choice in
            1)
                list_conflicts
                ;;
            2)
                smart_resolve
                ;;
            3)
                read -p "输入文件路径: " file
                if [ -f "$file" ]; then
                    show_conflict_details "$file"
                else
                    log_error "文件不存在: $file"
                fi
                ;;
            4)
                read -p "输入文件路径: " file
                auto_resolve_file "$file" "ours"
                ;;
            5)
                read -p "输入文件路径: " file
                auto_resolve_file "$file" "theirs"
                ;;
            6)
                merge_docker_compose
                ;;
            7)
                read -p "输入目录 (console/website): " dir
                merge_package_json "$dir"
                ;;
            8)
                merge_pyproject_toml
                ;;
            9)
                log_info "继续 rebase..."
                git rebase --continue
                exit $?
                ;;
            0)
                log_info "退出"
                exit 0
                ;;
            *)
                log_error "无效选择"
                ;;
        esac
    done
}

# 主函数
main() {
    log_info "CoPaw 冲突解决辅助脚本"
    log_info "=============================="
    echo ""
    
    # 检查冲突状态
    check_conflict_state
    
    # 解析参数
    case "${1:-}" in
        --auto)
            smart_resolve
            ;;
        --list)
            list_conflicts
            ;;
        --help)
            cat << 'HELP'
用法: ./resolve-conflicts.sh [选项]

选项:
  --auto    自动智能解决冲突
  --list    列出所有冲突文件
  --help    显示此帮助信息
  (无参数)  进入交互式菜单

示例:
  ./resolve-conflicts.sh           # 交互式菜单
  ./resolve-conflicts.sh --auto    # 自动解决
  ./resolve-conflicts.sh --list    # 列出冲突
HELP
            exit 0
            ;;
        "")
            interactive_menu
            ;;
        *)
            log_error "未知选项: $1"
            log_info "使用 --help 查看帮助"
            exit 1
            ;;
    esac
}

main "$@"
