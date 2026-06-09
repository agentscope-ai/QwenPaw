import styles from './TaskNodeDrawer.module.less';

/**
 * LoadingDots 组件
 * 渲染三个跳动的圆点，表示内容正在加载或流式传输中
 */
export default function LoadingDots() {
  return (
    <div className={styles.loadingDots}>
      <div className={styles.loadingDot} />
      <div className={styles.loadingDot} />
      <div className={styles.loadingDot} />
    </div>
  );
}
