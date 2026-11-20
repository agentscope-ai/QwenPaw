/*
 * 占位实现：vendor/markdown（开源库 @lidary/markdown v3.0.0，见该目录 LICENSE/README）
 * 的 LaTeX 公式渲染依赖外部包 @cangjie-tpc/formula_hybrid。本工程不引入该外部依赖，
 * 故提供同名最小占位——同时该库的 latex 扩展不再注册，公式令牌不会产生，这些成员不会被调用。
 */

export enum LatexMathColorFormat {
  COLOR_FORMAT_BGRA_8888 = 0
}

export async function latexStringToImage(latexText: string, textSize: number, textColor: number,
  backGroupColor: number, colorFormat: LatexMathColorFormat): Promise<ArrayBuffer> {
  throw new Error('LaTeX rendering is not enabled.');
}
