阿里云CLI支持导出命令元数据与OpenAPI元数据，本文为您介绍导出元数据的操作步骤。  

## **注意事项**
* 云产品的OpenAPI元数据是指与API相关的所有描述性信息的集合，详情请参见[OpenAPI元数据](https://help.aliyun.com/document_detail/2859170.html)。

* 元数据导出功能仅用于调试或开发用途，建议在导出完成后关闭该功能。

* 元数据文件默认保存在Shell的工作目录下，如需更改保存路径，请切换工作目录至目标路径。

* 如果未看到`cli-metadata`目录生成，请确认是否成功执行了阿里云CLI命令，并检查当前用户对Shell工作目录是否有写入权限。

* 元数据会随阿里云CLI版本更新产生变更，建议您升级阿里云CLI至最新版本后执行导出操作。

## 操作步骤
### 步骤一：启用导出功能

在Shell环境中设置临时环境变量`GENERATE_METADATA`，环境变量值为`YES`。通过设置此环境变量以启用元数据导出功能。

不同操作系统设置方式：

* Linux/macOS

  ```
  HELPCODEESCAPE-bash
  export GENERATE_METADATA=YES
  ```

* Windows PowerShell

  ```
  HELPCODEESCAPE-powershell
  $env:GENERATE_METADATA = "YES"
  ```

* Windows CMD

  ```
  HELPCODEESCAPE-shell
  set GENERATE_METADATA=YES
  ```

### 步骤二：导出元数据

设置环境变量后执行任意阿里云CLI命令，命令执行后阿里云CLI将开始导出元数据。例如：

```
HELPCODEESCAPE-bash
aliyun
```

所有生成的元数据文件都将保存在当前工作目录下的`cli-metadata`目录中，例如

* 在`C:\Users\User`目录下运行命令，则元数据保存位置为`C:\Users\User\cli-metadata`

* 在`/home/user/`目录下运行命令，则元数据保存位置为`/home/user/cli-metadata`

生成元数据文件包含主要子目录和文件，分别用于存储不同类型的元数据信息：

```
HELPCODEESCAPE-plaintext
cli-metadata/
├── metadatas/                   # 阿里云CLI支持OpenAPI元数据汇总目录
│   ├── products.json            # 产品列表及基本信息，包含产品名、接入点、默认集成API版本、API风格及产品API列表等信息
│   └── <product-name>/          # 每个产品对应一个子目录（如vpc、ecs等）
│       └── <api-name>.json      # 每个API接口的详细定义文件
│
├── en-US/                       # 阿里云CLI支持产品与接口元数据（英文版，部分产品无英文描述不在此目录中）
│   ├── products.json            # 产品列表及基本信息
│   └── <product-name>/          # 每个产品对应一个子目录（如vpc、ecs等）
│       ├── <api-name>.json      # 每个API接口的详细定义文件
│       └── version.json         # 该产品支持的OpenAPI版本及版本包含接口列表
│
├── zh-CN/                       # 阿里云CLI支持产品与接口元数据（中文版，结构同en-US，部分产品无中文描述不在此目录中）
│   ├── products.json
│   └── <product-name>/
│       ├── <api-name>.json
│       └── version.json
│   
├── commands.json                # 阿里云CLI命令结构定义文件，包含所有命令、子命令、选项及其参数说明
└── version                      # 当前使用的阿里云CLI版本号（纯文本文件）
```

### 步骤三：关闭元数据导出功能

元数据导出完成后，请关闭该功能以避免执行后续命令时仍然生成元数据文件。

#### **方法一：重启Shell会话**

关闭当前终端窗口并重新打开一个新的Shell会话，即可自动清除环境变量。

#### **方法二：手动清除临时环境变量**

* Linux/macOS

  ```
  HELPCODEESCAPE-bash
  unset GENERATE_METADATA
  ```

* Windows PowerShell

  ```
  HELPCODEESCAPE-powershell
  $env:GENERATE_METADATA = ""
  ```

* Windows CMD

  ```
  HELPCODEESCAPE-shell
  set GENERATE_METADATA=
  ```

<br />