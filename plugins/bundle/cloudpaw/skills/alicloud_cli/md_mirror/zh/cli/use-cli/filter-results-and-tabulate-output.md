阿里云产品的查询接口会返回JSON结构化数据，不方便阅读。您可以通过使用阿里云CLI的高级过滤功能，获取您感兴趣的字段，且默认表格化输出。  

## --output选项字段说明
为了使命令输出结果更直观，阿里云CLI提供了`--output`选项，您可以使用该选项提取返回结果中感兴趣的字段，且默认以表格形式输出。

`--output`选项包含以下字段：
<table> <thead> <tr> <td><p><b>字段名</b></p></td> <td><p><b>描述</b></p></td> <td><p><b>示例值</b></p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p>cols</p></td> <td><p>表格列名。</p><p>使用<code>--output</code>选项时需要以<code>cols="\&lt;column1\&gt;,\&lt;column2\&gt;"</code>形式确定表格与数据的映射关系。多个列名之间使用逗号<code>,</code>隔开。</p> <ul> <li><p>若JSON数据为<code>object</code>键值对类型，该字段需要与数据对应键名保持一致。</p></li> <li><p>若JSON数据为<code>array</code>数组类型，该字段可自定义显示名称，同时您需要手动添加数组元素索引。列名与索引之间使用冒号<code>:</code>隔开。</p></li> </ul></td> <td> <ul> <li><p><code>object</code>类型：cols="InstanceId,Status"</p></li> <li><p><code>array</code>类型：cols="name:0,type:1"</p></li> </ul></td> </tr> <tr> <td><p>rows</p></td> <td><p>待过滤数据所在的<a href="http://jmespath.org/">JMESPath</a>路径。</p><p>阿里云CLI将通过<a href="http://jmespath.org/">JMESPath</a>查询语句来指定表格行在JSON结果中的数据来源。 </p></td> <td><p>rows="Instances.Instance\[\]"</p></td> </tr> <tr> <td><p>num</p></td> <td><p>开启行号显示。</p><p>指定该字段为<code>true</code>可开启行号显示，开启后阿里云CLI将在表格左侧新增行号列并输出行号，起始行号为<code>0</code>。该字段默认值为<code>false</code>。</p></td> <td><p>num="true"</p></td> </tr> </tbody> </table>

## 过滤示例
### 示例场景

阿里云产品的查询接口会返回JSON结构化数据，不方便阅读。

1. 以查询所有ECS实例信息为例，执行如下命令。

   ```
   HELPCODEESCAPE-shell
   aliyun ecs DescribeInstances
   ```

2. 系统显示类似如下输出结果（部分省略）。

   ```
   HELPCODEESCAPE-json
   {
     "PageNumber": 1,
     "TotalCount": 2,
     "PageSize": 10,
     "RequestId": "2B76ECBD-A296-407E-BE17-7E668A609DDA",
     "Instances": {
       "Instance": [
         {
           "ImageId": "ubuntu_16_0402_64_20G_alibase_20171227.vhd",
           "InstanceTypeFamily": "ecs.xn4",
           "VlanId": "",
           "InstanceId": "i-1234567891234567****",
           "Status": "Stopped",
           "SecurityGroupIds": {
             "SecurityGroupId": [
               "sg-bp12345678912345****",
               "sg-bp98765432198765****"
             ]
           }
         },
         {
           "ImageId": "ubuntu_16_0402_64_20G_alibase_20171227.vhd",
           "InstanceTypeFamily": "ecs.xn4",
           "VlanId": "",
           "InstanceId": "i-abcdefghijklmnop****",
           "Status": "Running",
           "SecurityGroupIds": {
             "SecurityGroupId": [
               "sg-bp1abcdefghijklm****",
               "sg-bp1zyxwvutsrqpon****"
             ]
           }
         }
       ]
     }
   }
   ```

### 示例一

1. 执行如下命令，过滤示例场景返回结果中的字段`RequestId`。该字段作为根元素，无需指定`rows`字段。

   ```
   HELPCODEESCAPE-shell
   aliyun ecs DescribeInstances --output cols=RequestId
   ```

2. 系统显示类似如下输出结果。

   ```
   HELPCODEESCAPE-plaintext
   RequestId
   ---------
   2B76ECBD-A296-407E-BE17-7E668A609DDA
   ```

### 示例二

1. 执行如下命令，过滤示例场景返回结果中的字段`InstanceId`以及`Status`。这两个字段所在的JMESPath路径为`Instances.Instance[]`，则`rows="Instances.Instance[]"`。具体JMESPath书写方法，请参见[JMESPath Tutorial](http://jmespath.org/tutorial.html)。

   ```
   HELPCODEESCAPE-shell
   aliyun ecs DescribeInstances --output cols="InstanceId,Status" rows="Instances.Instance[]"
   ```

2. 系统显示类似如下输出结果。

   ```
   HELPCODEESCAPE-plaintext
   InstanceId             | Status
   ----------             | ------
   i-12345678912345678123 | Stopped
   i-abcdefghijklmnopqrst | Running
   ```

3. 如果需要输出行号，则指定`num=true`，系统显示类似如下输出结果。

   ```
   HELPCODEESCAPE-plaintext
   Num | InstanceId             | Status
   --- | ----------             | ------
   0   | i-12345678912345678123 | Stopped
   1   | i-abcdefghijklmnopqrst | Running
   ```

### 示例三

1. 执行如下命令，过滤示例场景返回结果中的数组类型字段`SecurityGroupId`的具体元素。数组所在的JMESPath路径为`Instances.Instance[].SecurityGroupIds.SecurityGroupId`。

   ```
   HELPCODEESCAPE-shell
   aliyun ecs DescribeInstances --output cols="sg1:0,sg2:1" rows="Instances.Instance[].SecurityGroupIds.SecurityGroupId"
   ```

2. 系统显示类似如下输出结果。

   ```
   HELPCODEESCAPE-plaintext
   sg1                     | sg2
   ---                     | ---
   sg-bp11234567891234**** | sg-bp19876543219876****
   sg-bp1abcdefghijklm**** | sg-bp1zyxwvutsrqpon****
   ```