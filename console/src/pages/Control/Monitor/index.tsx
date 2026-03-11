import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Spin, Button, Tag, Empty, message } from "antd";
import {
  AlertTriangle,
  CalendarClock,
  Cpu,
  GitBranch,
  Newspaper,
  RefreshCw,
  TrendingUp,
  Zap,
} from "lucide-react";
import api from "../../../api";
import styles from "./index.module.less";

interface MonitorData {
  startupHistory: Array<{ time: string; status: string }>;
  errorLogs: Array<{ time: string; message: string; level: string }>;
  cronJobs: Array<{
    id: string;
    name: string;
    schedule: string;
    status: string;
    lastRun?: string;
  }>;
  runningScripts: Array<{ name: string; pid: number; status: string }>;
  tokenUsage: { today: number; total: number };
  gitProjects: Array<{ name: string; url: string; deployUrl?: string }>;
  hotSkills: Array<{ name: string; description: string; installs: number }>;
  aiNews: Array<{ title: string; source: string; url: string; time: string }>;
}

function MonitorPage() {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<MonitorData | null>(null);

  const fetchMonitorData = async () => {
    setLoading(true);
    try {
      // 获取定时任务
      const cronJobsRes = await api.listCronJobs();
      
      // 模拟其他数据 - 实际需要从后端 API 获取
      const mockData: MonitorData = {
        startupHistory: [
          { time: "2025-03-08 00:00:01", status: "success" },
          { time: "2025-03-07 00:00:02", status: "success" },
          { time: "2025-03-06 00:00:01", status: "success" },
        ],
        errorLogs: [],
        cronJobs: cronJobsRes.map((job: any) => ({
          id: job.id,
          name: job.name || job.id,
          schedule: job.schedule,
          status: job.paused ? "paused" : "active",
          lastRun: job.last_run,
        })),
        runningScripts: [
          { name: "copaw-app", pid: 12345, status: "running" },
          { name: "copaw-heartbeat", pid: 12346, status: "running" },
        ],
        tokenUsage: { today: 15234, total: 1250000 },
        gitProjects: [
          {
            name: "copaw-main",
            url: "https://github.com/agentscope-ai/CoPaw",
            deployUrl: "https://copaw.agentscope.io",
          },
        ],
        hotSkills: [
          {
            name: "search",
            description: "Search for latest news and information",
            installs: 1250,
          },
          {
            name: "browser_use",
            description: "Control browser with Playwright",
            installs: 980,
          },
          {
            name: "xlsx",
            description: "Work with Excel spreadsheets",
            installs: 856,
          },
        ],
        aiNews: [
          {
            title: "AI Agent 技术最新进展",
            source: "机器之心",
            url: "https://example.com/news1",
            time: "2 小时前",
          },
          {
            title: "大模型应用开发最佳实践",
            source: "量子位",
            url: "https://example.com/news2",
            time: "5 小时前",
          },
        ],
      };

      setData(mockData);
    } catch (error) {
      console.error("Failed to fetch monitor data:", error);
      message.error("获取监控数据失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMonitorData();
  }, []);

  if (loading) {
    return (
      <div className={styles.monitorPage}>
        <div className={styles.loadingState}>
          <Spin size="large" />
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className={styles.monitorPage}>
        <Empty description={t("monitor.noSkillsData", "暂无监控数据")} />
      </div>
    );
  }

  return (
    <div className={styles.monitorPage}>
      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.title}>{t("monitor.title", "监控中心")}</h1>
          <p className={styles.description}>
            {t("monitor.description", "查看小超的运行状态、资源消耗和系统信息")}
          </p>
        </div>
        <Button
          icon={<RefreshCw size={16} />}
          onClick={fetchMonitorData}
          className={styles.refreshBtn}
        >
          {t("monitor.refresh", "刷新")}
        </Button>
      </div>

      {/* Token 使用统计 */}
      <div className={styles.tokenSection}>
        <div className={styles.tokenCard}>
          <div className={styles.tokenLabel}>
            {t("monitor.tokenToday", "今日消耗 Token")}
          </div>
          <div className={styles.tokenValue}>
            {data.tokenUsage.today.toLocaleString()}
          </div>
          <div className={styles.tokenLabel}>
            {t("monitor.tokenDaily", "今日累计")}
          </div>
        </div>
        <div className={styles.tokenCardSecondary}>
          <div className={styles.tokenLabel}>
            {t("monitor.tokenTotal", "历史总消耗 Token")}
          </div>
          <div className={styles.tokenValue}>
            {data.tokenUsage.total.toLocaleString()}
          </div>
          <div className={styles.tokenLabel}>
            {t("monitor.tokenCumulative", "累计总量")}
          </div>
        </div>
      </div>

      {/* 启动历史 */}
      <div className={styles.section}>
        <div className={styles.listContainer}>
          <div className={styles.listTitle}>
            <span>
              <CalendarClock size={18} style={{ marginRight: 8 }} />
              {t("monitor.startupHistory", "历史启动时间")}
            </span>
          </div>
          {data.startupHistory.length > 0 ? (
            <div>
              {data.startupHistory.map((startup, index) => (
                <div key={index} className={styles.listItem}>
                  <div>
                    <div className={styles.listItemName}>{startup.time}</div>
                  </div>
                  <Tag color={startup.status === "success" ? "green" : "red"}>
                    {startup.status === "success"
                      ? t("monitor.normalStartup", "正常启动")
                      : t("monitor.startupFailed", "启动失败")}
                  </Tag>
                </div>
              ))}
            </div>
          ) : (
            <div className={styles.emptyState}>
              {t("monitor.noStartupRecords", "暂无启动记录")}
            </div>
          )}
        </div>
      </div>

      {/* 异常日志 */}
      <div className={styles.section}>
        <div className={styles.listContainer}>
          <div className={styles.listTitle}>
            <span>
              <AlertTriangle size={18} style={{ marginRight: 8 }} />
              {t("monitor.errorLogs", "异常日志报告")}
            </span>
          </div>
          {data.errorLogs.length > 0 ? (
            <div>
              {data.errorLogs.map((log, index) => (
                <div key={index} className={styles.listItem}>
                  <div>
                    <div className={styles.listItemName}>{log.message}</div>
                    <div className={styles.listItemInfo}>{log.time}</div>
                  </div>
                  <Tag color={log.level === "error" ? "red" : "orange"}>
                    {log.level.toUpperCase()}
                  </Tag>
                </div>
              ))}
            </div>
          ) : (
            <div className={styles.emptyState}>
              {t("monitor.noErrorLogs", "🎉 无异常日志，系统运行正常")}
            </div>
          )}
        </div>
      </div>

      {/* 定时任务 */}
      <div className={styles.section}>
        <div className={styles.listContainer}>
          <div className={styles.listTitle}>
            <span>
              <CalendarClock size={18} style={{ marginRight: 8 }} />
              {t("monitor.cronJobs", "定时任务")}
            </span>
          </div>
          {data.cronJobs.length > 0 ? (
            <div>
              {data.cronJobs.map((job) => (
                <div key={job.id} className={styles.listItem}>
                  <div>
                    <div className={styles.listItemName}>{job.name}</div>
                    <div className={styles.listItemInfo}>
                      {t("monitor.schedule", "调度")}：{job.schedule}
                      {job.lastRun &&
                        ` · ${t("monitor.lastRun", "上次运行")}：${job.lastRun}`}
                    </div>
                  </div>
                  <span
                    className={`${styles.statusBadge} ${
                      job.status === "active"
                        ? styles.statusRunning
                        : job.status === "paused"
                        ? styles.statusPaused
                        : styles.statusStopped
                    }`}
                  >
                    <span className={styles.dot} />
                    {job.status === "active"
                      ? t("monitor.running", "运行中")
                      : job.status === "paused"
                      ? t("monitor.paused", "已暂停")
                      : t("monitor.stopped", "已停止")}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className={styles.emptyState}>
              {t("monitor.noCronJobs", "暂无定时任务")}
            </div>
          )}
        </div>
      </div>

      {/* 运行中的脚本 */}
      <div className={styles.section}>
        <div className={styles.listContainer}>
          <div className={styles.listTitle}>
            <span>
              <Cpu size={18} style={{ marginRight: 8 }} />
              {t("monitor.runningScripts", "Mac 运行脚本")}
            </span>
          </div>
          {data.runningScripts.length > 0 ? (
            <div>
              {data.runningScripts.map((script, index) => (
                <div key={index} className={styles.scriptItem}>
                  <div className={styles.scriptName}>{script.name}</div>
                  <div className={styles.scriptPid}>
                    PID: {script.pid} · 状态：{script.status}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className={styles.emptyState}>
              {t("monitor.noRunningScripts", "暂无运行中的脚本")}
            </div>
          )}
        </div>
      </div>

      {/* Git 项目 */}
      <div className={styles.section}>
        <div className={styles.listContainer}>
          <div className={styles.listTitle}>
            <span>
              <GitBranch size={18} style={{ marginRight: 8 }} />
              {t("monitor.gitProjects", "管理的 Git 项目")}
            </span>
          </div>
          {data.gitProjects.length > 0 ? (
            <div>
              {data.gitProjects.map((project, index) => (
                <div key={index} className={styles.gitProjectItem}>
                  <div className={styles.gitProjectName}>{project.name}</div>
                  <div className={styles.gitProjectUrl}>
                    <a href={project.url} target="_blank" rel="noopener noreferrer">
                      {project.url}
                    </a>
                  </div>
                  {project.deployUrl && (
                    <div className={styles.gitProjectStatus}>
                      部署地址：
                      <a
                        href={project.deployUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {project.deployUrl}
                      </a>
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className={styles.emptyState}>
              {t("monitor.noGitProjects", "暂无 Git 项目")}
            </div>
          )}
        </div>
      </div>

      {/* 热门 Skills */}
      <div className={styles.section}>
        <div className={styles.listContainer}>
          <div className={styles.listTitle}>
            <span>
              <Zap size={18} style={{ marginRight: 8 }} />
              {t("monitor.hotSkills", "全球热门 Skills")}
            </span>
            <Tag color="blue">Top 3</Tag>
          </div>
          {data.hotSkills.length > 0 ? (
            <div>
              {data.hotSkills.map((skill, index) => (
                <div key={index} className={styles.listItem}>
                  <div>
                    <div className={styles.listItemName}>
                      <TrendingUp size={14} style={{ marginRight: 6 }} />
                      {skill.name}
                    </div>
                    <div className={styles.listItemInfo}>
                      {skill.description}
                    </div>
                  </div>
                  <Tag color="green">
                    {skill.installs} {t("monitor.installs", "安装")}
                  </Tag>
                </div>
              ))}
            </div>
          ) : (
            <div className={styles.emptyState}>
              {t("monitor.noSkillsData", "暂无 Skills 数据")}
            </div>
          )}
        </div>
      </div>

      {/* AI 新闻 */}
      <div className={styles.section}>
        <div className={styles.listContainer}>
          <div className={styles.listTitle}>
            <span>
              <Newspaper size={18} style={{ marginRight: 8 }} />
              {t("monitor.aiNews", "热门 AI 新闻")}
            </span>
            <Tag color="orange">实时更新</Tag>
          </div>
          {data.aiNews.length > 0 ? (
            <div>
              {data.aiNews.map((news, index) => (
                <div key={index} className={styles.newsItem}>
                  <div className={styles.newsTitle}>{news.title}</div>
                  <div className={styles.newsSource}>
                    {news.source} · {news.time}
                  </div>
                  <a
                    href={news.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={styles.newsLink}
                  >
                    阅读原文 →
                  </a>
                </div>
              ))}
            </div>
          ) : (
            <div className={styles.emptyState}>
              {t("monitor.noAiNews", "暂无 AI 新闻")}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default MonitorPage;
