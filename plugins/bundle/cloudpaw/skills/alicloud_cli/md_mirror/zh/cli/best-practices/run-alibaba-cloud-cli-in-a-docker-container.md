使用Docker可以快速创建一个用于运行阿里云CLI的隔离环境，提高运行环境的安全性。本教程将为您介绍如何在Docker容器中运行阿里云CLI。  

## 前提条件
* 请确保您已经安装Docker 18.09或更高版本。详细安装说明，请参见[Docker官方文档](https://docs.docker.com/get-started/get-docker/)。

* 安装完成后，您可以执行`docker --version`命令验证Docker的安装信息。

* 由于运营商网络原因，会导致您拉取Docker Hub镜像变慢，甚至下载失败。为此，阿里云容器镜像服务ACR提供了官方的镜像加速器，从而加速官方镜像的下载。具体操作，请参见[官方镜像加速](https://help.aliyun.com/document_detail/60750.html)。

## 方案概览
在Docker容器中运行阿里云CLI，可大致分为以下四个步骤：

1. 创建`Dockerfile`文件：`Dockerfile`是一个用于指导自动构建镜像的文本文件，该文件通常由一系列命令和参数构成。

2. 构建自定义镜像：执行`docker build`命令，使用`Dockerfile`文件创建自定义Docker镜像。

3. 启动容器：执行`docker run`命令，加载自定义镜像并运行Docker容器。

4. 连接容器：执行`docker exec`命令进入已启动的容器，在容器内部即可使用阿里云CLI。

## 步骤一：创建Dockerfile文件
### 操作步骤

在桌面上（或其他任何位置）创建一个新目录，并将下列代码保存到名为 Dockerfile 的纯文本文件中。

```
HELPCODEESCAPE-dockerfile
FROM centos:latest

# 获取并安装阿里云CLI工具，此处以最新版本举例
# 下载阿里云CLI安装包
RUN curl -SLO "https://aliyuncli.alicdn.com/aliyun-cli-linux-latest-amd64.tgz"
# 解压安装包
RUN tar -xvzf aliyun-cli-linux-latest-amd64.tgz
# 删除安装包
RUN rm aliyun-cli-linux-latest-amd64.tgz
# 移动可执行文件aliyun至/usr/local/bin目录下
RUN mv aliyun /usr/local/bin/
```

### 注意事项

* Docker文件应始终命名为`Dockerfile`（带有大写字母D且没有文件扩展名），每个目录下只能保存一个`Dockerfile`文件。

* 若您使用ARM架构系统（例如苹果M1芯片），则下载地址需要改为<https://aliyuncli.alicdn.com/aliyun-cli-linux-latest-arm64.tgz>。

* 示例中以CentOS系统举例，假如您使用Alpine Linux，则`Dockerfile`文件可参考如下示例进行配置：

  Alpine Linux Dockerfile参考  

  ```
  HELPCODEESCAPE-dockerfile
  FROM alpine:latest

  # 添加 jq，以 JSON 的格式输出
  RUN apk add --no-cache jq

  # 获取并安装阿里云 CLI 工具
  # 下载阿里云CLI安装包
  RUN wget https://aliyuncli.alicdn.com/aliyun-cli-linux-latest-amd64.tgz
  # 解压安装包
  RUN tar -xvzf aliyun-cli-linux-latest-amd64.tgz
  # 删除安装包
  RUN rm aliyun-cli-linux-latest-amd64.tgz
  # 移动可执行文件aliyun至/usr/local/bin目录下
  RUN mv aliyun /usr/local/bin/

  # 注意：alpine需要额外创建 lib64 的动态链接库软连接
  RUN mkdir /lib64 && ln -s /lib/libc.musl-x86_64.so.1 /lib64/ld-linux-x86-64.so.2
  ```

## 步骤二：构建自定义镜像
1. 在`Dockerfile`文件所在目录下执行以下命令，构建一个名为`aliyuncli`的自定义Docker镜像。

   ```
   HELPCODEESCAPE-shell
   docker build --tag aliyuncli .
   ```

2. 执行命令后，预期输出如下信息。

   ![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/7086252371/p871095.png)

## 步骤三：启动容器
1. 创建自定义Docker镜像之后，您可以运行以下命令启动一个Docker容器。

   ```
   HELPCODEESCAPE-shell
   docker run -it -d --name mycli aliyuncli
   ```

   * `mycli`：容器名。您可以自定义容器名称。

   * `aliyuncli`：自定义镜像名。此处镜像名需与[步骤二：构建自定义镜像](#8cdfbf54d6m4t)中名称保持一致。

2. 执行命令后，预期输出容器ID。

   ![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/7086252371/p871118.png)

## 步骤四：连接容器
1. 容器启动成功后，您可以运行以下命令连接至Docker容器内部。

   ```
   HELPCODEESCAPE-shell
   docker exec -it mycli /bin/sh
   ```

2. 在容器内部执行`aliyun version`命令，查看阿里云CLI版本信息。

   ![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/2249531571/p871124.png)

## 后续操作
成功启动并进入Docker容器后，您需要为阿里云CLI配置身份凭证，您可以借助阿里云CLI实现与阿里云产品的交互，在Shell工具中管理阿里云产品。更多信息，请参见[配置凭证](https://help.aliyun.com/document_detail/121193.html)及[生成并调用命令](https://help.aliyun.com/document_detail/110848.html)。

## 相关文档
* [什么是阿里云CLI](https://help.aliyun.com/document_detail/110244.html#concept-rc3-qrc-bhb)

* [使用阿里云CLI调用OpenAPI](https://help.aliyun.com/document_detail/2808429.html)