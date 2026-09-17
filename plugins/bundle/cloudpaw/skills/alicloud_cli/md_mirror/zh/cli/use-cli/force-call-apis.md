阿里云CLI在调用云产品API时会检查参数的合法性。由于API具有不同的版本，导致内置的产品和接口信息并不能满足所有的需求。您可以强制调用元数据列表以外的接口，并自行检查该接口相关信息的准确性。  

## --force选项说明
在阿里云CLI中，如果调用了一个元数据中未包含的API或参数，会导致`unknown api`或`unknown parameter`错误。您可以通过使用`--force`选项，强制调用元数据列表以外的API和参数。调用时，您需要确保以下信息的准确性。

* 云产品code：可使用`--help`选项[获取支持产品列表及可用命令行选项](https://help.aliyun.com/document_detail/122046.html#c9e132a571okf)。

* API名称及参数：可使用`--help`选项获取API名称和参数，详情请参见[获取产品可用API列表](https://help.aliyun.com/document_detail/122046.html#bba9bfc3bb6n4)及[获取API参数详情](https://help.aliyun.com/document_detail/122046.html#6f830ae763a38)。

* API版本：使用`--force`选项强制调用接口时必须配合`--version`选项，指定需要调用的API版本。

* 接入地址信息：使用`--endpoint`选项指定产品的接入地址。若不指定，则从阿里云CLI内置数据中获取。

## 示例
### 示例场景

在CMS产品中，有一个接口用于描述`MetricList`。在CMS API的`2019-01-01`版本中，该接口名称为`DescribeMetricList`。但在`2017-03-01`版本中，该接口名称为`QueryMetricList`，直接调用此接口会导致阿里云CLI报错。

![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/2160749171/p814602.png)

### 示例命令

1. 执行如下命令，强制调用`2017-03-01`版本的`QueryMetricList`接口。

   ```
   HELPCODEESCAPE-shell
   aliyun cms QueryMetricList --Project acs_ecs_dashboard --Metric cpu_idle --version 2017-03-01 --force
   ```

2. 返回结果

   ![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/2160749171/p814622.png)