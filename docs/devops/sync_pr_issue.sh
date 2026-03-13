# 获取 upstream PR
curl -s https://api.github.com/repos/agentscope-ai/CoPaw/pulls > docs/devops/upstream_prs.json

# 获取 upstream issues
curl -s https://api.github.com/repos/agentscope-ai/CoPaw/issues > docs/devops/upstream_issues.json

# 获取 fork PR
curl -s https://api.github.com/repos/futuremeng/CoPaw/pulls > docs/devops/fork_prs.json

# 获取 fork issues
curl -s https://api.github.com/repos/futuremeng/CoPaw/issues > docs/devops/fork_issues.json

# 可用 jq/awk 等工具筛选、格式化输出
