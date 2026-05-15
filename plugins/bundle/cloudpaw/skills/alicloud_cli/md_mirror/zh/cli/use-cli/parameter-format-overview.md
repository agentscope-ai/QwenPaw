本文介绍使用阿里云CLI时不同数据类型参数需要遵循的格式要求。  

## **参数格式要求**
**说明**

阿里云CLI支持在OpenAPI门户中自动生成CLI示例。具体操作，请参见[生成并调用命令](https://help.aliyun.com/document_detail/110848.html)。

在OpenAPI门户中自动生成的CLI示例默认采用Linux适用参数格式，若您需要在其他环境下执行CLI命令，请根据实际情况修正参数格式。

对于OpenAPI中不同数据类型的字段，阿里云CLI遵循如下格式要求：

### 参数名大小写

由于OpenAPI参数名严格区分大小写，因此阿里云CLI的参数名输入同样严格区分大小写。

### 参数值大小写

部分参数值不区分大小写。但为确保书写规范的一致性，建议您严格区分参数值的大小写。

### Integer类型

在OpenAPI文档中标注为`Integer`类型的参数，可以直接传入。

```
HELPCODEESCAPE-shell
aliyun ecs DescribeImages --ImageName Example_Image --Pagesize 10
```

### String类型

在OpenAPI文档中标注为`String`类型的参数，如果参数值中没有包含特殊字符（如`$`、`````、`\`、空格等），可直接传入。否则需要用单引号`''`或双引号`""`包含后再传入。

* 通常情况

  阿里云CLI在接收字符串作为参数时，通常需要将字符串中的特殊字符转换为一般字符。在Linux、macOS或Windows PowerShell中，需要使用单引号`''`包含参数，在Windows命令提示符中，使用双引号`""`。
  * 无特殊字符：

    ```
    HELPCODEESCAPE-shell
    aliyun ecs DescribeImages --ImageName Example_Image
    ```

  <!-- -->

  * 有特殊字符：

    * Windows命令提示符：

      ```
      HELPCODEESCAPE-shell
      aliyun ecs DescribeImages --ImageName "Example Image"
      ```

    * Linux/macOS/Windows PowerShell：

      ```
      HELPCODEESCAPE-shell
      aliyun ecs DescribeImages --ImageName 'Example Image'
      ```

* 特殊情况

  调用ROA风格OpenAPI时，如需使用`--body`选项指定字符串（字符串中包含转义字符）或变量作为请求主体，引号的使用方式与通常情况存在差异。在Linux、macOS或Windows命令提示符中需要使用双引号`""`包含请求参数，在Windows PowerShell中，使用单引号`''`。
  * Windows命令提示符/Linux/macOS：

    ```
    HELPCODEESCAPE-shell
    aliyun cs PUT /clusters/<ClusterId>/nodepools/<NodepoolId> --body "{\"nodepool_info\":{\"name\":\"default-nodepool\",\"resource_group_id\":\"rg-acfmyvw****\"}}"
    ```

  * Windows PowerShell：

    ```
    HELPCODEESCAPE-shell
    aliyun cs PUT /clusters/<ClusterId>/nodepools/<NodepoolId> --body '{\"nodepool_info\":{\"name\":\"default-nodepool\",\"resource_group_id\":\"rg-acfmyvw****\"}}'
    ```

### String类型字符串列表

在OpenAPI文档中标注为`String`类型的参数，如果支持传入多个值的列表（如`ImageId`列表），则参数格式如下所示。

* Windows命令提示符：

  在Windows命令提示符中，应将相应的参数值串用逗号`,`分隔后，再使用双引号`""`包含后传入。

  ```
  HELPCODEESCAPE-shell
  aliyun ecs DescribeImages --ImageId "m-23e0o****,m-23wae****"
  ```

* Linux/macOS/Windows PowerShell：

  在Linux、macOS或Windows PowerShell中，应将相应的参数值串用逗号`,`分隔后，再使用单引号`''`包含后传入。

  ```
  HELPCODEESCAPE-shell
  aliyun ecs DescribeImages --ImageId 'm-23e0o****,m-23wae****'
  ```

### String类型JSON数组

在OpenAPI文档中标注为`String`类型的参数，如果要求参数值是一个带有格式的JSON数组，则参数格式如下所示。

* Windows：

  在Windows命令提示符及Windows PowerShell中，应将所有值置于最外层的双引号`""`内，双引号内使用中括号`[]`包含、单引号`''`引用，使用逗号`,`进行分隔。

  ```
  HELPCODEESCAPE-shell
  aliyun ecs DescribeDisks --DiskIds "['d-23rss****','d-23vsi****','d-23sfq****']"
  ```

* Linux/macOS：

  在Linux或macOS中，应将所有值置于最外层的单引号`''`内，单引号内使用中括号`[]`包含、双引号`""`引用，使用逗号`,`进行分隔。

  ```
  HELPCODEESCAPE-shell
  aliyun ecs DescribeDisks --DiskIds '["d-23rss****","d-23vsi****","d-23sfq****"]'
  ```

### String类型JSON数组列表

在OpenAPI文档中标注为`String`类型的参数，如需将参数值设定为一个JSON数组，则参数格式如下所示。

* Windows：

  在Windows命令提示符及Windows PowerShell中，应将所有值置于最外层的双引号`""`内，双引号内使用中括号`[]`包含。JSON数组中的各个值需用大括号`{}`包含，单引号`''`引用，使用逗号`,`进行分隔。JSON数组内的键与值之间使用冒号`:`进行分隔。

  ```
  HELPCODEESCAPE-shell
  aliyun slb AddBackendServers --LoadBalancerId 15157b19f18-cn-hangzhou-dg**** --BackendServers "[{'ServerId':'i-23g8a****'},{'ServerId':'i-23bb0****'}]"
  ```

* Linux/macOS：

  在Linux及macOS中，应将所有值置于最外层的单引号`''`内，单引号内使用中括号`[]`包含。JSON数组中的各个值需用大括号`{}`包含，双引号`""`引用，使用逗号`,`进行分隔。JSON数组内的键与值之间使用冒号`:`进行分隔。

  ```
  HELPCODEESCAPE-shell
  aliyun slb AddBackendServers --LoadBalancerId 15157b19f18-cn-hangzhou-dg**** --BackendServers '[{"ServerId":"i-23g8a****"},{"ServerId":"i-23bb0****"}]'
  ```

### String类型日期

OpenAPI文档中标注为`String`类型的参数，如果要求参数值是一个按照ISO8601标准表示的UTC时间，需要将时间按`YYYY-MM-DDThh:mm:ssZ`格式传入。

```
HELPCODEESCAPE-shell
aliyun ecs DescribeInstanceMonitorData --InstanceId i-94ola4btx**** --StartTime 2015-11-28T15:00:00Z --EndTime 2015-11-28T18:00:00Z
```

### 特殊字符

若您输入的参数值在使用引号包含之后，参数中的特殊字符在命令执行过程中仍出现解析错误。您可尝试将参数格式调整为`key=value`的格式，以确保命令正确执行。

#### **示例**

在执行如下命令时，阿里云CLI无法将`-1/-1`识别为`PortRange`对应参数。

```
HELPCODEESCAPE-shell
aliyun ecs AuthorizeSecurityGroup --SecurityGroupId 'sg-bp67acfmxazb4p****' --Permissions.1.PortRange "-1/-1" --method POST --force
```

如下所示，将`--PortRange -1/-1`修改为`--PortRange=-1/-1`，命令可以正确执行。

```
HELPCODEESCAPE-shell
aliyun ecs AuthorizeSecurityGroup --SecurityGroupId 'sg-bp67acfmxazb4p****' --Permissions.1.PortRange=-1/-1 --method POST --force
```