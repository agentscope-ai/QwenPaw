本文将为您介绍在阿里云CLI中使用代理服务器访问和管理云服务的操作步骤。  

## **操作步骤**
**说明**

若您需要使用代理调用OSS命令，请参考[OSS命令配置代理](#section-5yf-ejl-jwf)。

阿里云CLI支持通过配置环境变量，使用代理服务器访问和管理云服务。具体配置信息如下表所示。具体配置方式，请参见[在Linux、macOS和Windows系统配置环境变量](https://help.aliyun.com/document_detail/2766629.html)。

## 使用HTTP代理
<table> <thead> <tr> <td><p><b>变量名</b></p></td> <td><p><b>变量值</b></p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p><code>http_proxy</code></p></td> <td> <ul> <li><p>格式：<code>http://proxy_server_address:port</code></p></li> <li><p>示例：</p> <ul> <li><p><code>http://192.168.1.2:1234</code></p></li> <li><p><code>http://proxy.example.com:1234</code></p></li> </ul></li> </ul></td> </tr> </tbody> </table>

## 使用HTTPS代理
<table> <thead> <tr> <td><p><b>变量名</b></p></td> <td><p><b>变量值</b></p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p><code>https_proxy</code></p></td> <td> <ul> <li><p>格式：<code>https://proxy_server_address:port</code></p></li> <li><p>示例：</p> <ul> <li><p><code>https://192.168.1.2:5678</code></p></li> <li><p><code>https://proxy.example.com:5678</code></p></li> </ul></li> </ul></td> </tr> </tbody> </table>

## OSS命令配置代理
针对于OSS命令，无法通过环境变量配置代理，可以使用以下选项进行代理配置：

```
HELPCODEESCAPE-shell
# 网络代理服务器的url地址,支持http/https/socks5,比如 https://120.79.XX.XX:3128, socks5://120.79.XX.XX:1080
--proxy-host

# 网络代理服务器的用户名,默认为空
--proxy-user

# 网络代理服务器的密码,默认为空
--proxy-pwd
```

使用示例：

```
HELPCODEESCAPE-shell
aliyun oss ls oss://<Bucket> --proxy-host <YourProxyHost> --proxy-user <UserName> --proxy-pwd <Password>
```