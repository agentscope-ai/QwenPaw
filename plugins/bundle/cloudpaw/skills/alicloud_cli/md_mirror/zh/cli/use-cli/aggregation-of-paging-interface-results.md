调用分页类接口时，默认情况下仅返回单页查询结果。使用`--pager`选项可聚合分页数据，实现全量数据的一次性获取。  

## 字段说明
在阿里云CLI中，您可以使用`--pager`选项开启分页聚合功能，对分页类接口的数组类结果进行聚合。该选项包含以下字段：  
**说明**

若接口返回字段与默认值不一致，可能导致解析异常。建议您根据实际返回数据结构，手动映射字段参数，以确保数据提取的准确性和稳定性。
<table> <thead> <tr> <td><p><b>字段</b></p></td> <td><p><b>描述</b></p></td> <td><p><b>默认值</b></p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p><span>PageNumber</span></p></td> <td><p>列表当前页码。</p></td> <td><p><code>PageNumber</code></p></td> </tr> <tr> <td><p><span>PageSize</span></p></td> <td><p>每页最大结果数量。</p></td> <td><p><code>PageSize</code></p></td> </tr> <tr> <td><p><span>TotalCount</span></p></td> <td><p>列表总行数。</p></td> <td><p><code>TotalCount</code></p></td> </tr> <tr> <td><p><span>NextToken</span></p></td> <td><p>查询凭证。</p></td> <td><p><code>NextToken</code></p></td> </tr> <tr> <td><p><span>path</span></p></td> <td><p>目标数据的<a href="http://jmespath.org/">JMESPath</a>路径。</p></td> <td><p>自动识别数组类型数据路径。如调用ECS <code>DescribeInstances</code>接口时，<code>path</code>默认值为<code>Instances.Instance</code>。</p></td> </tr> </tbody> </table>

## 示例场景
**说明**

部分接口支持通过`maxResult`参数设置单次查询的最大结果数量。若设置值过小，可能导致请求频率及数据处理耗时显著增加。建议您在使用`--pager`选项时合理设置`maxResult`参数以优化查询效率。

1. ECS产品的`DescribeInstances`接口是分页类接口。默认情况下，执行如下命令仅返回实例信息列表的第一页数据。

   ```
   HELPCODEESCAPE-shell
   aliyun ecs DescribeInstances
   ```

2. 系统显示如下结果（部分截取）。

   ```
   HELPCODEESCAPE-json
   {
       "PageNumber": 1,
       "TotalCount": 4,
       "PageSize": 10,
       "RequestId": "6EA82E70-9750-4A97-A738-E021D8A57F07",
       "Instances": {
           "Instance": [
               {    
                   "InstanceId": "i-m5edv0cqkr9hawls****",
                   "ImageId": "win2012r2_64_dtc_9600_zh-cn_40G_alibase_20190318.vhd",
                   "SerialNumber": "f06857e8-7f3c-443a-9f88-8e84eb51****",
                   "Cpu": 1,
                   "Memory": 2048,
                   "DeviceAvailable": true,
                   "SecurityGroupIds": {
                       "SecurityGroupId": [
                           "sg-bp1fgviwol82z8ap****"
                       ]
                   }
               }
           ]
       }
   }
   ```

3. 开启分页聚合功能后，可一次性获取所有分页中的实例信息。

   ```
   HELPCODEESCAPE-shell
   aliyun ecs DescribeInstances --pager PageNumber=PageNumber PageSize=PageSize TotalCount=TotalCount path=Instances.Instance
   ```

   若某个字段参数值与默认值一致，无需显式指定该字段。例如，上述命令可简化为：

   ```
   HELPCODEESCAPE-bash
   aliyun ecs DescribeInstances --pager
   ```

4. 命令执行后，系统显示如下聚合结果（部分截取）。

   **说明**

   聚合后仅输出聚合字段。若需通过过滤功能查看特定字段，请注意过滤路径应为聚合后的[JMESPath](http://jmespath.org/)路径。更多信息，请参见[过滤且表格化输出结果](https://help.aliyun.com/document_detail/122111.html#concept-661998)。

   ```
   HELPCODEESCAPE-json
   {
       "Instances": {
           "Instance": [
               {    
                   "InstanceId": "i-m5edv0cqkr9hawls****",
                   "ImageId": "win2012r2_64_dtc_9600_zh-cn_40G_alibase_20190318.vhd",
                   "SerialNumber": "f06857e8-7f3c-443a-9f88-8e84eb51****",
                   "Cpu": 1,
                   "Memory": 2048,
                   "DeviceAvailable": true,
                   "SecurityGroupIds": {
                       "SecurityGroupId": [
                           "sg-bp1fgviwol82z8ap****"
                       ]
                   }
               }
           ]
       }
   }
   ```