declare module "*.png" {
  const url: string;
  export default url;
}

declare module "*.png?url" {
  const url: string;
  export default url;
}
