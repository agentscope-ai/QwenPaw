本文以在VS Code编辑器中调用云服务器 ECS的`DescribeInstances`接口为例，为您介绍在VS Code编辑器中使用阿里云CLI Visual Studio Code插件的操作步骤。  

## **前置准备**
1. 在VS Code编辑器中使用阿里云CLI插件，需要您先安装阿里云CLI并配置身份凭证。安装及配置的具体操作，请参见[使用阿里云CLI调用OpenAPI](https://help.aliyun.com/document_detail/2808429.html)。

2. 本文示例需授予RAM用户只读访问ECS的权限策略*AliyunECSReadOnlyAccess*。

## 方案概览
在VS Code编辑器中使用阿里云CLI插件调用ECS的`DescribeInstances`接口，大致分为以下几个步骤：

1. 安装插件：在VS Code编辑器中安装`Alibaba Cloud CLI Tools`插件。

2. 编辑命令：在VS Code编辑器中创建一个`.aliyun`为后缀的文件，在文件中编辑`DescribeInstances`命令。

3. 执行命令：选中需要执行的命令，在编辑器或终端中执行。

## 步骤一：安装阿里云CLI插件
## 在插件市场下载安装
1. 在VS Code编辑器左侧（Activity Bar）导航栏中，单击![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/5829538271/p850262.png)图标。

2. 在搜索框中输入`Alibaba Cloud CLI Tools`，单击**Install**。

## 通过浏览器跳转下载
1. 通过浏览器访问官网[Marketplace](https://marketplace.visualstudio.com/items?itemName=alibabacloud-openapi.aliyuncli)，单击**Install**，可自动跳转至VS Code编辑器扩展页面。

2. 在扩展页面中，单击**Install**。

安装完成后，会在底部状态栏显示阿里云CLI插件图标及当前使用配置。单击图标可切换身份凭证配置。

## 步骤二：编辑命令
1. 在VS Code编辑器中单击**File** \> **New File...** ，输入文件名`example.aliyun`，创建一个后缀名为`.aliyun`的新文件。

   **说明**

   在`.aliyun`文件中编码时，阿里云CLI Visual Studio Code插件会提供命令补全提示，可大幅提升命令行的编写效率。

   ## 命令级自动补全提示
   ------------

   ![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/5829538271/p850349.png)

   ## 方法级自动补全提示
   ------------

   ![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/5829538271/p850383.png)

   ## 参数级自动补全提示
   ------------

   ![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/5829538271/p850393.png)
2. 根据补全提示输入以下命令，并按需设置命令参数。

   ```
   HELPCODEESCAPE-shell
   aliyun ecs DescribeInstances --InstanceIds "['i-bp118piqciobxjkb****']"
   ```

## 步骤三：执行命令
命令编写完成后，您可以选择在终端或者编辑器中执行CLI命令。

## 在终端中执行完整命令
单击待执行命令左上方**run**，唤出终端并执行完整命令。

![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/5829538271/p850574.png)

## 在终端中执行选中命令
1. 长按鼠标左键，选中待执行部分命令。在选中命令处右击唤出右键菜单。

2. 单击**Alibaba Cloud CLI** \>**Run Line in Terminal**，唤出终端并执行选中部分命令。

   ![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/5829538271/p850690.png)

## 在编辑器中执行选中命令
1. 长按鼠标左键，选中待执行部分命令。在选中命令处右击唤出右键菜单。

2. 单击**Alibaba Cloud CLI** \>**Run Line in Editor**，在VS Code编辑器中执行选中部分命令。

![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/5829538271/p850716.png)

<br />