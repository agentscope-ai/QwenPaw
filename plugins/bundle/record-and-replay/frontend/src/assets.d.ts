declare module "*.module.less" {
  const classes: Record<string, string>;
  export default classes;
}
declare module "*.less?inline" {
  const css: string;
  export default css;
}
