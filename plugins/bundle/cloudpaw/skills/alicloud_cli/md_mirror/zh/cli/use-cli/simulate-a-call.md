当您需要检查向服务器发送的请求是否正确，且不希望对云资源有任何实际操作时，您可以使用阿里云CLI的模拟调用功能。  

## --dryrun选项字段说明
为方便用户检查请求参数是否正确，阿里云CLI提供了`--dryrun`选项，您可以使用该选项打印并检查请求。`--dryrun`选项与部分命令行选项互斥，使用以下命令行选项时，无法使用模拟调用功能。

* `--pager`：分页类接口结果聚合。

* `--waiter`：结果轮询。

## 命令示例
1. 执行如下命令，检查调用云服务器ECS的API`DescribeInstances`时产生的请求信息。关于此API的更多信息，请参见[DescribeInstances - 查询一台或多台ECS实例的详细信息](https://help.aliyun.com/document_detail/2679689.html)。

   ```
   HELPCODEESCAPE-shell
   aliyun ecs DescribeInstances --dryrun
   ```

2. 系统显示如下输出，输出内容包含身份凭证、使用地域、API版本等信息。

   ```
   HELPCODEESCAPE-shell
   Skip invoke in dry-run mode, request is:
   ------------------------------------
   POST /?AccessKeyId=AccesskeyId&Action=DescribeInstances&Format=JSON&RegionId=cn-hangzhou&Signature=ni5DWOuI9G0OnKKKB5gTNg%2BS0UU%3D&SignatureMethod=HMAC-SHA1&SignatureNonce=27373c2fcad641b28e355931f408f2ce&SignatureType=&SignatureVersion=1.0&Timestamp=2024-06-27T09%3A35%3A31Z&Version=2014-05-26 HTTPS/1.1
   Host: ecs.cn-hangzhou.aliyuncs.com
   Accept-Encoding: identity
   Content-Type: application/x-www-form-urlencoded
   x-acs-action: DescribeInstances
   x-acs-version: 2014-05-26
   x-sdk-client: golang/1.0.0
   x-sdk-core-version: 0.0.1
   x-sdk-invoke-type: common
   ```