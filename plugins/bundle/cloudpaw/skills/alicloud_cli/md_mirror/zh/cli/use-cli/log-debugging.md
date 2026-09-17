当您通过阿里云CLI访问API时，可以打开日志输出功能以打印请求日志。日志可帮助您分析请求及响应内容是否正确。  
**说明**

OSS命令日志功能的开启方式与阿里云CLI不同。如需为OSS命令开启日志功能，请参见[OSS命令日志功能](#section-of8-ixh-0d6)。

## 阿里云CLI日志功能
在终端中，可以通过设置环境变量开启阿里云CLI的日志功能。新增环境变量示例如下：
<table> <thead> <tr> <td><p><b>变量</b></p></td> <td><p><b>示例</b></p></td> <td><p><b>说明</b></p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p><b><i>DEBUG</i></b></p></td> <td> <ul> <li><p>变量名：<code>DEBUG</code></p></li> <li><p>变量值：<code>sdk</code></p></li> </ul></td> <td> <ul> <li><p>当变量<code>DEBUG</code>的值为<code>sdk</code>时，表示开启阿里云CLI的日志功能。</p></li> <li><p>如需禁用日志输出，请删除该环境变量。</p></li> </ul></td> </tr> </tbody> </table>

配置环境变量的具体操作，请参见[在Linux、macOS和Windows系统配置环境变量](https://help.aliyun.com/document_detail/2766629.html)。

### 使用示例

开启日志功能后，以如下命令为例：

```
HELPCODEESCAPE-shell
aliyun ecs DescribeRegions
```

阿里云CLI将在命令执行后显示类似如下信息：

```
HELPCODEESCAPE-plaintext
> POST /?AccessKeyId=<yourAccesskeyId>&Action=DescribeRegions&Format=JSON&RegionId=cn-hangzhou&Signature=u9lPKI5Nyw0dIKV5ytJAx6****&SignatureMethod=HMAC-SHA1&SignatureNonce=29f426485b2720f6ae0****&SignatureType=&SignatureVersion=1.0&Timestamp=2020-05-18T09%3A52%3A42Z&Version=2014-05-26 HTTP/1.1
> Host: ecs-cn-hangzhou.aliyuncs.com
> x-acs-action: DescribeEndpoints
> x-acs-credentials-provider: static_sts
> x-sdk-client: golang/1.0.0
> x-sdk-invoke-type: common
> Accept-Encoding: identity
> x-acs-version: 2014-05-26
> User-Agent: AlibabaCloud (darwin; amd64) Golang/1.13.9 Core/0.0.1 Aliyun-CLI/3.0.43
> x-sdk-core-version: 1.63.22
> Content-Type: application/x-www-form-urlencoded
>
 Retry Times: 0.
< HTTP/1.1 200 OK
< Access-Control-Expose-Headers: *
< X-Acs-Trace-Id: 99176a2d8de06237945913f8e9f66adb
< Content-Type: application/json;charset=utf-8
< Connection: keep-alive
< Access-Control-Allow-Origin: *
< X-Acs-Request-Id: 4C92B935-4698-5EF5-BB0E-EAF1C3F4CE34
< Date: Tue, 17 Jun 2025 02:14:09 GMT
< Keep-Alive: timeout=25
< Vary: Accept-EncodingAccept-Encoding
<
# omitted output
```

## OSS命令日志功能
OSS命令可以使用`--loglevel`选项开启命令日志，并对日志输出级别进行定义。

可选值：

* 默认为空，不进行输出

* `info`：输出提示信息日志

* `debug`：输出详细日志信息

日志将会输出到文件，文件路径将在终端显示，例如以下命令：

```
HELPCODEESCAPE-plaintext
aliyun oss ls --loglevel info
log file is /Users/user/Documents/ossutil.log
# omitted output
```