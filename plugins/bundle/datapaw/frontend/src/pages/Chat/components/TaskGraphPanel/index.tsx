import { useCallback, useMemo } from 'react';
import { Dropdown } from 'antd';
import type { MenuProps } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { EllipsisOutlined } from '@ant-design/icons';
import { Button, Table } from '@agentscope-ai/design';
import { SparkModifyLine } from '@agentscope-ai/icons';
import { useTranslation } from 'react-i18next';
import type { PlanSnapshot, TaskNode } from './types';
import { getStatusConfig, isClickable } from './constants';
import PlanCorrectionPopover from './PlanCorrectionPopover';
import styles from './index.module.less';

interface TaskGraphPanelProps {
  /** 计划快照数据 */
  plan: PlanSnapshot;
  /** 点击节点的回调 */
  onNodeClick: (nodeId: string) => void;
  /** 计划纠偏确认回调 */
  onPlanCorrection?: (yaml: string) => void;
  /** 更多操作菜单点击 */
  onMoreMenuClick?: (key: string) => void;
  /** 是否展示头部操作区 */
  showActions?: boolean;
}

type TaskRow = TaskNode & {
  rowIndex: number;
};

const STATUS_COL_WIDTH = 108;
const ACTIONS_COL_WIDTH = 156;

/**
 * TaskGraphPanel 组件
 * 渲染任务计划列表卡片，展示每个节点的名称和状态
 * 已完成和进行中的节点可点击打开详情抽屉
 */
export default function TaskGraphPanel({
  plan,
  onNodeClick,
  onPlanCorrection,
  onMoreMenuClick,
  showActions = true,
}: TaskGraphPanelProps) {
  const { t } = useTranslation();

  const dataSource = useMemo(
    () =>
      Object.values(plan.nodes).map((node, index) => ({
        ...node,
        rowIndex: index + 1,
      })),
    [plan.nodes],
  );

  const moreMenuItems: MenuProps['items'] = useMemo(
    () => [
      {
        key: 'view-plan',
        label: t('taskGraph.viewPlanDetail'),
      },
      {
        key: 'download-sop',
        label: t('taskGraph.downloadSop'),
      },
      {
        key: 'download-dag',
        label: t('taskGraph.downloadDag'),
      },
      {
        key: 'artifact-manage',
        label: t('taskGraph.artifactManage'),
      },
    ],
    [t],
  );

  const handleMoreMenuClick: MenuProps['onClick'] = useCallback(
    ({ key }) => {
      onMoreMenuClick?.(String(key));
    },
    [onMoreMenuClick],
  );

  const columns: ColumnsType<TaskRow> = useMemo(() => {
    const baseColumns: ColumnsType<TaskRow> = [
      {
        title: t('taskGraph.taskContent'),
        key: 'content',
        render: (_, record) => (
          <span className={styles.taskContent}>
            {record.rowIndex}. {record.name || record.node_id}
          </span>
        ),
      },
      {
        title: t('taskGraph.taskStatus'),
        key: 'state',
        width: STATUS_COL_WIDTH,
        align: 'center',
        onHeaderCell: () => ({ className: styles.statusHeaderCell }),
        onCell: () => ({ className: styles.statusBodyCell }),
        render: (_, record) => {
          const config = getStatusConfig(record.state);
          return (
            <span className={`${styles.statusTag} ${styles[config.className] || ''}`}>
              {t(config.label)}
            </span>
          );
        },
      },
    ];

    if (showActions) {
      baseColumns.push({
        title: (
          <div className={styles.headerActions}>
            <PlanCorrectionPopover plan={plan} onConfirm={onPlanCorrection}>
              <Button
                className={styles.correctionBtn}
                icon={<SparkModifyLine size={14} />}
              >
                {t('taskGraph.planCorrection')}
              </Button>
            </PlanCorrectionPopover>
            <Dropdown menu={{ items: moreMenuItems, onClick: handleMoreMenuClick }} trigger={['click']}>
              <button
                type="button"
                className={styles.moreBtn}
                aria-label={t('taskGraph.moreActions')}
              >
                <EllipsisOutlined />
              </button>
            </Dropdown>
          </div>
        ),
        key: 'actions',
        width: ACTIONS_COL_WIDTH,
        align: 'right',
        onHeaderCell: () => ({ className: styles.actionsHeaderCell }),
        onCell: () => ({ colSpan: 0 }),
        render: () => null,
      });
    }

    return baseColumns;
  }, [handleMoreMenuClick, moreMenuItems, onPlanCorrection, plan, showActions, t]);

  return (
    <div className={styles.taskPlan}>
      <Table<TaskRow>
        className={styles.taskTable}
        columns={columns}
        dataSource={dataSource}
        rowKey="node_id"
        pagination={false}
        tableLayout="fixed"
        onRow={(record) => ({
          onClick: () => {
            if (isClickable(record.state)) {
              onNodeClick(record.node_id);
            }
          },
          className: isClickable(record.state) ? styles.clickableRow : undefined,
        })}
      />
    </div>
  );
}
