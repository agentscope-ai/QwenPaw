---
name: bi-clustering
description: 对用户、产品等业务对象做分群：用波士顿矩阵法做象限分群，或用分层聚类、K-means、DBSCAN 等聚类技术分群。当需要做客群/产品分群、象限策略、画像或密度型子结构发现时调用。触发条件：当对话中出现“分群”、“分类”、“聚类”、“不同类型”、“不同场景”等体现分群分析词语时触发。
---

# bi-clustering

将特征相似或策略上需区分的业务对象（用户、产品、门店等）划为若干群组。根据分群分析的目的。

## 执行流程

### 1. 分群方法的选择

分析数据分析的目的和两种方法的适用场景，明确是使用波士顿矩阵法对分析对象进行分群还是应该使用聚类技术对分析对象完成分群。

| 路径 | 更合适_when | 说明 |
|------|-------------|------|
| **波士顿矩阵法** | 策略上需要 **2×2 象限**（如「增长×份额」「客流×客单」）、维度含义清晰、便于与经典业务框架对齐 | 每条轴上把对象划为「高/低」两档，得到四象限；解释成本低，适合汇报与策略分派 |
| **聚类** | 需要 **多特征综合**、簇数/形状事先不明确、或簇非球形/需标出噪声点 | 用距离与密度在特征空间划分；可选 K-means、分层聚类、DBSCAN（参见下文） |

若仅能在「简单四象限」与「多簇细划」之间二选一：**优先波士顿**当业务叙事依赖两个主轴；**优先聚类**当维度多、需数据驱动定簇结构。

### 2. 特征维度的确定

确定分群所依据的维度：若采用波士顿矩阵法，则确定两个象限用以分群；若采用聚类方法，则按需选择合适的分群特征。

实务上，波士顿路径需选定横轴、纵轴各一个指标且与目标一致；聚类路径需注意缺失、异常、量纲与类别编码（高基数类别慎用无约束 one-hot）。

### 3. 分群数据准备

查看数据，确认数据中包含在步骤 2 中确定的特征维度；然后，整理数据为 CSV 格式，数据包含一个分析对象列，和分群所需的特征维度，每个特征应该对应一个数据列。

补充：对象为行粒度，按需完成对象级汇总（如事件级先聚合到用户/产品）、缺失与异常处理；聚类路径下数值特征由脚本的 `--scale` 处理缩放。

### 4. 数据分群

#### a) 波士顿矩阵法

若象限对应数据是离散的，根据离散值将其分成两个区间；若象限对应数据是连续的，在连续轴上选定**分界统计量**（**平均数**或**中位数**），按该值将数据分成「≤ 分界 / \> 分界」两个区间。完成象限划分后，将分析对象划分至各个象限。

说明：**平均数**对极端值敏感、**中位数**更稳健；横轴与纵轴可分别指定（脚本参数 `--x-continuous-split` / `--y-continuous-split`，值为 `mean` 或 `median`，默认均为 `mean`）。离散轴仍按有序取值前半/后半分为两档；`auto` 模式下由列类型与去重个数判定连续/离散（见脚本 `--discrete-max-uniques`）。结果中 stderr 的 `axes:` 一行在连续轴上会附带 `:mean` 或 `:median`。可向业务侧标注象限名称（如 Q1–Q4）并统计规模与指标概要。

分群结果保存为 json 文件。

使用 `<skill-dir>/scripts/boston_quadrant.py` 脚本完成数据的划分，如

```bash
python scripts/boston_quadrant.py \
  --input-file data.csv \
  --id-col user_id \
  --x-col 市场份额 \
  --y-col 增长率 \
  --x-continuous-split mean \
  --y-continuous-split median \
  --output-json result.json
```

参数说明：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--input-file` | 输入 CSV 路径 | （必填） |
| `--id-col` | 分析对象唯一标识列 | （必填） |
| `--x-col` / `--y-col` | 横轴、纵轴特征列各一列 | （必填） |
| `--x-mode` / `--y-mode` | 该轴划分方式：`auto` \| `continuous` \| `discrete` | `auto` |
| `--discrete-max-uniques` | `auto` 时：数值列去重个数 ≤ 此阈值则按离散轴处理 | `12` |
| `--x-continuous-split` | 横轴为连续时：用 `mean`（均值）或 `median`（中位数）作分界，低为 ≤、高为 \> | `mean` |
| `--y-continuous-split` | 纵轴为连续时：同上 | `mean` |
| `--output-json` | 象限分群结果 JSON（格式见「输出结果」） | （必填） |

#### b) 聚类分析

**聚类方法选择**：

| 方法 | 适用场景 | 适合的数据类型 / 形态 |
|------|----------|------------------------|
| **K-means** | K 可预估或可试算；簇大致球形、规模相近；样本量大、需快速迭代 | 主要为连续数值（脚本内会按 `--scale` 处理）；对离群点敏感 |
| **分层聚类** | 需要树状结构或 K 不固定、多层解读；样本量中等 | 数值矩阵 + 选定距离/连接法（脚本中欧氏 + linkage） |
| **DBSCAN** | 簇数未知；形状任意、密度不均；需显式噪声/未分类 | 调节 eps、min_samples；高维时距离区分度可能下降 |

**使用聚类脚本**：

使用 `<skill-dir>/scripts/clustering.py`执行聚类，分群结果保存为 json 文件。脚本调用示例如下，

```bash
python scripts/clustering.py \
  --input-file data.csv \
  --id-col user_id \
  --feature-cols 年龄 消费金额 访问次数 \
  --method kmeans \
  --n-clusters 5 \
  --output-json result.json
```

调优示例（K-means 按轮廓系数选 K；**`--output-json` 仍必填**，写出最终簇划分）：

```bash
python scripts/clustering.py \
  --input-file data.csv \
  --id-col user_id \
  --feature-cols 年龄 消费金额 访问次数 \
  --method kmeans \
  --tune \
  --k-min 2 \
  --k-max 10 \
  --output-json result.json \
  --tuning-report-file ./out/tune.json
```

DBSCAN 调优示例（**`--tune` 时必须同时提供** `--tune-eps` 与 `--tune-min-samples`）：

```bash
python scripts/clustering.py \
  --input-file data.csv \
  --id-col user_id \
  --feature-cols f1 f2 \
  --method dbscan \
  --tune \
  --tune-eps 0.3,0.5,0.8,1.2 \
  --tune-min-samples 3,5,10 \
  --max-noise-ratio 0.35 \
  --output-json result.json \
  --tuning-report-file ./out/tune.json
```

**聚类脚本参数说明**

| 参数 | 含义 | 默认 |
|------|------|------|
| `--input-file` | 输入 CSV 路径 | （必填） |
| `--id-col` | 分析对象唯一标识列名 | （必填） |
| `--feature-cols` | 参与聚类的**数值**特征列名，多个列名以空格分隔（脚本内 `pd.to_numeric`） | （必填） |
| `--method` | `kmeans` \| `hierarchical` \| `dbscan` | （必填） |
| `--output-json` | 聚类分群结果 JSON 路径 | （必填） |
| `--scale` | 聚类前特征缩放：`standard` \| `minmax` \| `none` | `standard` |
| `--random-state` | K-means 随机种子 | `42` |
| `--n-init` | K-means `n_init` | `10` |
| `--n-clusters` | K-means / 分层聚类的簇数 K；**未**使用 `--tune` 时与上述方法搭配为必填 | 无 |
| `--linkage` | 分层聚类连接法：`ward`、`complete`、`average`、`single` | `ward` |
| `--eps` | DBSCAN 邻域半径；**未**使用 `--tune` 时与 `--min-samples` 同时必填 | 无 |
| `--min-samples` | DBSCAN `min_samples`；**未**使用 `--tune` 时与 `--eps` 同时必填 | 无 |
| `--skip-drop-na` | 含 NaN 的特征行**不**丢弃（需 `--fill-mean` 或数据已无 NaN） | 默认会丢弃含 NaN 行 |
| `--fill-mean` | 用列均值填补特征中的 NaN | 关闭 |
| `--centroids-file` | 若指定且为 K-means：另写出质心 CSV（列为 `--feature-cols`，**与聚类一致的缩放后空间**；并带 `cluster_label`） | 无 |
| `--tune` | 开启超参搜索：K-means/分层按轮廓系数选 K（分层可同时试多种 `--tune-linkages`）；DBSCAN 在非噪声点上算轮廓且受 `--max-noise-ratio` 约束 | 关闭 |
| `--k-min` / `--k-max` | K-means / 分层在 `--tune` 时的 K 搜索范围 | `2` / `10` |
| `--tune-linkages` | 分层 `--tune` 时要尝试的连接法列表（每项为 `ward` 等） | 仅用当前 `--linkage` |
| `--tune-eps` | DBSCAN `--tune` 必填：逗号分隔的 eps 候选，如 `0.3,0.5,0.8` | 无 |
| `--tune-min-samples` | DBSCAN `--tune` 必填：逗号分隔的 `min_samples` 候选，如 `3,5,10` | 无 |
| `--max-noise-ratio` | DBSCAN `--tune` 时：噪声占比超过该值的参数组合被淘汰 | `0.35` |
| `--tuning-report-file` | 可选：写出调优过程与最终选中超参数的 JSON（**不是**分群 ID 列表文件） | 无 |

拟合后结合写出的 JSON 汇报各簇（及噪声）规模、方法与全部关键超参数，并做业务解读。

### 5. 报道结果（两类路径共用）

**必备内容**：

- **输出物**：主结果 **`--output-json`** 文件路径（及调优 JSON 若使用）；可得自脚本的 stderr 相对路径与 stdout 中的 JSON 内容
- **数据与特征**：对象粒度、样本量、特征列表、预处理（缺失、标准化、编码）
- **方法与参数**：波士顿两轴定义与分割规则（连续轴的 mean/median 与离散分档）；或聚类方法理由与全部关键超参数
- **群组规模**：各象限或各簇的样本量、占比；DBSCAN 单独汇报噪声数量与占比
- **群组画像**：相对总体或跨组的业务指标/特征对比；避免仅有算法指标而无业务解释
- **稳定性与局限**（视情况）：参数微扰或随机种子对标签的影响；高维、小样本对结论的影响

**质量检查**

- [ ] 行粒度与「一个待分群对象」一致
- [ ] 波士顿：两维分割规则在文档中一致且可复现
- [ ] 聚类：连续特征缩放策略明确；方法与数据形态匹配
- [ ] 各象限/簇规模可解释，结论能指向可执行动作

## 输出结果

分群/聚类结果以 JSON 格式呈现，包含以下字段和对应的聚类结果：

- **聚类**（`clustering.py`）：键为 **`"cluster 1"`、`"cluster 2"`、…**（对应 `sklearn` 簇标签 `0`、`1`、…）；**DBSCAN** 中标签 `-1` 的样本归入 **`"noise"`**（仅当存在噪声点时才有此键）。**仅当簇内至少有一个对象时**才出现对应键，**不会出现空数组的簇键**。
- **波士顿象限**（`boston_quadrant.py`）：恒包含 **`"cluster 1"`～`"cluster 4"`** 四键（象限含义见该脚本文件头注释），某象限无对象时值为 `[]`。连续轴分界可为 **均值（`mean`）** 或 **中位数（`median`）**；运行结束后 stderr 中 `axes:` 一行对连续轴会附带 `:mean` 或 `:median`，便于核对所用规则。

聚类另可选用 **`--tuning-report-file`** 写出调优网格与选中超参数的 JSON，**与**上述「ID 分组」主结果文件**相互独立**。

## 注意事项

1. **可解释性**：无监督分群的组是否业务上有意义，需结合画像与验证；不宜单凭轮廓系数定成败。
2. **高维**：维度过高时距离趋于均匀；可考虑特征选择或领域驱动子集。
3. **公平与合规**：分群若用于差异化策略，需遵守隐私与反歧视相关规范。
