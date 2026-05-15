本文介绍阿里云CLI使用过程中的常见错误及其排查步骤。  

## **一般错误排查方式**
在使用阿里云CLI的过程中，如您遇到问题或收到错误信息，请优先检查以下内容，以协助您进行错误排查。

### 检查网络状态

客户端与服务器之间如存在网络异常，可能导致请求无法到达服务器。请检查您的网络状态，以确保您能够访问阿里云的API。

### 检查是否缺失选项

部分命令存在必需选项，若您在命令中未使用必需选项或传入了异常选项值，则命令无法正常执行。您可通过以下方式查看命令详解或接口详情。

* 配置凭证时参考[配置凭证](https://help.aliyun.com/document_detail/121193.html)及[多凭证管理](https://help.aliyun.com/document_detail/121198.html#title-5a4-n9g-ncu)，检查是否携带配置命令必需选项。

* 调用OpenAPI时，可在对应接口文档中查看必需选项信息。

* 使用`--force`选项强制调用接口时必须配合`--version`选项指定需要调用的OpenAPI版本。

### 检查命令及参数格式

如果阿里云CLI提示您某个命令不存在或无法识别可用参数，则说明您当前执行的命令或参数格式可能存在错误。您可以通过以下方式进行命令自检：

* 参考[命令结构](https://help.aliyun.com/document_detail/110344.html)及对应OpenAPI文档，检查命令是否存在拼写或格式错误。

* 检查传入参数是否正确。

* 检查传入参数是否包含需要处理的特殊字符。更多信息，请参见[参数格式](https://help.aliyun.com/document_detail/110340.html)。

### 检查地域及接入点

如果阿里云服务不支持以您指定的接入点或地域发起调用，或者待访问资源位于其他地域，则调用时有可能出现错误，阿里云CLI服务接入点与地域优先级如下所示：

1. `--endpoint`选项指定的接入点信息。

2. `--region`选项指定的地域ID。

3. 凭证配置`profile`中保存的地域ID。

4. 环境变量`ALIBABA_CLOUD_REGION_ID`中保存的地域ID。

### 检查请求详情

在使用阿里云CLI的过程中，如果执行命令后的结果与预期不符，您可以通过以下方式确认请求参数是否按预期方式拼接。

#### **使用模拟调用功能查看请求详情**

使用`--dryrun`选项开启模拟调用，此次操作不会对您的云资源产生任何实际影响。使用模拟调用功能后输出身份凭证、使用地域、API版本等信息。更多信息，请参见[模拟调用功能](https://help.aliyun.com/document_detail/122115.html)。

#### **启用并检查阿里云CLI日志**

启用日志输出功能后，阿里云CLI将在命令执行时为您打印更加详细的调用信息。具体操作，请参见[模拟调用功能](https://help.aliyun.com/document_detail/122115.html)。

### 确认凭证有效性

如果您未能正确配置身份凭证信息，则有可能在发起调用时产生各种错误。您可以检查以下内容以确保身份凭证的有效性：

#### **检查当前使用的配置**

如果使用非预期的凭证配置发起调用，执行命令后的结果可能与预期不符。阿里云CLI凭证配置优先级如下所示：

1. `--profile`选项指定的配置。

2. 环境变量`ALIBABA_CLOUD_PROFILE`指定的配置。

3. 使用`aliyun configure switch`命令指定的当前配置。更多信息，请参见[设定当前凭证配置](https://help.aliyun.com/document_detail/121198.html#0bdad0014c27a)。

#### **检查配置中保存的凭证信息**

如果配置中保存的凭证信息有误，阿里云CLI无法使用此配置调用OpenAPI。您可以通过以下方式检查凭证信息：

* 执行`aliyun configure list`命令查看全部凭证配置的概要信息。

* 执行`aliyun configure get`命令查看单个凭证配置的详细信息。

若凭证信息存在错误，您可尝试重新配置身份凭证，或使用`aliyun configure set`命令修改已保存的凭证信息。具体操作，请参见[修改指定身份凭证配置](https://help.aliyun.com/document_detail/121198.html#a24b211140br6)。

#### **检查凭证模式**

在使用**RamRoleArn** 、**EcsRamRole**等凭证模式时，您需要检查凭证Provider是否可以正常工作。若阿里云CLI无法获取有效的身份凭证则会引起接口调用失败。

* **RamRoleArn、ChainableRamRoleArn** ：使用此凭证模式需确保已为RAM用户或RAM角色授予STS的管理权限（AliyunSTSAssumeRoleAccess）。更多信息，请参见[AssumeRole - 获取扮演角色的临时身份凭证](https://help.aliyun.com/document_detail/371864.html)。

* **EcsRamRole** ：使用此凭证模式需参考[权限示例](https://help.aliyun.com/document_detail/61175.html#5f7bede1ebnwb)为当前用户身份授予相应权限。

* **External、CredentialsURI**：使用此凭证模式需检查外部程序命令能否正常获取凭证。

#### **凭证对应的身份是否具备访问权限**

如果您使用的凭证信息正确，则有可能您当前的身份并不具备执行当前操作所需的权限。请您为当前身份授予所需权限后重新尝试执行命令。

### 更新或重新安装阿里云CLI版本

阿里云CLI通常会随着版本更新引入新的支持内容，可能包括阿里云服务、功能及参数等。新的支持内容仅可在首次引入该内容后发布的阿里云CLI版本中使用。如果您已确认命令及参数格式均无错误，但阿里云CLI仍提示您命令不存在或无法识别可用参数，建议您尝试重新安装或更新到最新版本的阿里云CLI。

## 常见问题
### 找不到aliyun命令

#### **安装完成后未重新启动终端**

修改`PATH`环境变量后，需重新启动终端会话才能生效。请尝试重新启动所有终端会话以解决此问题。

#### **环境变量PATH未更新或配置了错误的安装路径**

执行以下命令查看当前环境变量`PATH`，检查环境变量中是否包含正确的安装目录路径。

## Linux/macOS
```
HELPCODEESCAPE-bash
echo $PATH
```

## Windows PowerShell
```
HELPCODEESCAPE-powershell
echo $Env:PATH
```

## Windows命令提示符CMD
```
HELPCODEESCAPE-shell
echo %PATH%
```

#### **可执行文件丢失**

请检查可执行文件是否位于阿里云CLI安装目录下。若该文件被删除或移动至其他目录，则阿里云CLI无法正常运行。您可能需要重新安装阿里云CLI。

Windows系统中可执行文件：`aliyun.exe`

Linux/macOS系统中可执行文件：`aliyun`

#### **可执行文件损坏**

若以上均无异常，阿里云CLI仍无法正常运行。建议您卸载阿里云CLI之后重新执行安装操作。  

### 执行aliyun version命令时返回的版本与安装的版本不同

#### **更新阿里云CLI时使用了与初始安装方式不匹配的更新方式**

例如，在macOS系统中通过`Homebrew`安装阿里云CLI后，使用PKG安装包进行更新。此时可能会导致系统命令在软件更新后仍指向旧版本。该现象通常由 PATH 环境变量优先级或残留软链接引起。

建议您卸载所有版本的阿里云CLI后，根据操作系统重新执行安装操作。

#### **更新阿里云CLI时未使用旧安装路径，但PATH变量仍指向旧路径**

建议您卸载旧版本阿里云CLI并删除环境变量后，重新配置环境变量。  

### 卸载阿里云CLI后仍能使用aliyun命令

#### **卸载阿里云CLI时使用了与初始安装方式不匹配的卸载方式**

建议您根据安装方式，完整执行相应的卸载操作。例如，在macOS系统中通过`Homebrew`安装阿里云CLI后，需要使用`Homebrew`执行卸载操作。

若您不确定阿里云CLI的安装方式，可根据操作系统尝试执行所有卸载操作，直至`aliyun version`不再返回任何版本信息。

#### **安装了其他版本的阿里云CLI**

若您已执行卸载操作，则可能在系统中的其他位置仍安装有阿里云CLI。建议您根据操作系统卸载所有版本的阿里云CLI，直至`aliyun version`不再返回任何版本信息。  

### 无法识别命令

#### **命令未区分大小写**

由于OpenAPI参数名严格区分大小写，因此阿里云CLI的参数名输入同样严格区分大小写。部分参数值不区分大小写。但为确保书写规范的一致性，建议您同样严格区分参数值的大小写。

建议您参考OpenAPI文档，检查并修正命令可能存在的拼写或格式错误。

#### **命令格式错误**

若命令格式存在错误，可能导致阿里云CLI在解析命令时发生错误。例如：使用ROA风格命令格式调用RPC风格API。

参考[命令结构](https://help.aliyun.com/document_detail/110344.html)及对应OpenAPI文档，检查并修正命令可能存在的拼写或格式错误。

#### **命令构建异常**

阿里云CLI支持以变量形式构建命令，若变量为空值或仅包含空格，则可能导致阿里云CLI在解析命令时发生错误。

您需要检查变量值是否存在，以及变量值是否与预期一致。

#### **阿里云CLI当前版本过低**

若阿里云CLI版本过低，则可能无法提供您所需要的功能或产品支持。例如：阿里云CLI自`v3.0.271`版本起引入CloudSSO类型凭证，若小于该版本则无法识别配置命令。

建议您及时更新到最新版本的阿里云CLI。  

### 字符串解析异常

#### **不同的Shell终端在引用规则上可能存在差异**

在构建命令时，您需要根据终端类型修正引用格式，开启调用日志或使用模拟调用功能可检查传入参数的详细信息。更多信息，请参见[参数格式](https://help.aliyun.com/document_detail/110340.html)。

调用ROA风格OpenAPI时，可使用`--body-file`选项直接传入JSON文件，从而绕过终端的引用规则。

#### **部分特殊符号在Shell终端中无法正确解析**

在参数部分直接传入部分特殊符号可能导致命令解析失败，请将符号转义后再传入。若仍无法解析，您可尝试使用`--key=value`的格式传入参数。具体操作，请参见[特殊字符](https://help.aliyun.com/document_detail/110340.html#677f70cf67xic)。  

### 调用API时发生"required parameters not assigned"类型错误

阿里云CLI调用API之前会对参数进行校验，如果缺少必要参数，您将收到类似`required parameters not assigned`的错误提示。例如，如果实例ID缺失，会报错：`ERROR: required parameters not assigned: --InstanceId`。

建议您检查以下内容：

* 参考API文档确认必填项。确保必填参数值正确。

* 确保填写的必填参数值正确无误，例如手机号格式等是否符合要求。

您也可在OpenAPI门户中使用自动生成的命令示例。更多信息，请参见[生成并调用命令](https://help.aliyun.com/document_detail/110848.html)。  

### 配置身份凭证时发生"fail to set configuration"类型错误

使用`aliyun configure set`命令配置凭证时会对参数进行校验，如果缺少必要参数，您将收到类似`fail to set configuration`的错误提示。例如，如果未指定地域ID，会报错：`fail to set configuration: region can't be empty`。

建议您参考[配置凭证](https://help.aliyun.com/document_detail/121193.html)及[多凭证管理](https://help.aliyun.com/document_detail/121198.html)，检查凭证必要参数是否完整。如始终配置失败，请尝试使用`aliyun configure`采用交互式方式配置身份凭证。  

### 网络连接超时

#### **客户端无法连接网络或连接不稳定**

使用`ping`或`curl`命令测试本地主机与云产品Endpoint之间连通性，例如调用ECS`DescribeInstances`接口超时，使用ping ecs.cn-qingdao.aliyuncs.com或curl -v ecs.cn-qingdao.aliyuncs.com测试连通性。

* 若命令执行超时或无响应，请检查防火墙或路由器中是否设置阻断策略。

* 对于网络不稳定的情况，建议更换网络环境。

#### **接口处理时间过长**

接口处理时间可能过长，超过预设的超时时间。您可通过以下方式修改超时时间：

* 使用`aliyun configure set`命令和`--read-timeout`、`--connect-timeout`选项修改配置中的超时时间，通过增加超时时间适应较长的接口响应时间。

* 在命令行中使用`--read-timeout`和`--connect-timeout`选项，仅修改当前命令的超时时间。

### 凭证无效

**使用了非预期的凭证配置**

阿里云CLI支持保存多套配置，如果在调用API时如果使用了非预期的配置，则有可能导致调用失败。您可以在执行命令前[检查当前使用的配置](#774aefa03fa04)并切换到正确的配置以解决此问题。
**凭证信息错误**

在阿里云CLI中使用交互式方式配置身份凭证，在完成配置流程时会进行有效性校验。但在使用非交互式方式配置身份凭证时，阿里云CLI仅校验必需参数是否为空，无法验证凭证有效性。

您可以尝试[检查配置中保存的凭证信息](#078262d960fmy)并修正错误的凭证信息以解决此问题。
**临时凭证过期**

阿里云CLI提供多种凭证类型，部分凭证类型可能出现凭证失效的问题。例如：

* StsToken：StsToken类型使用静态临时凭证，凭证过期即失效。

* External：External类型凭证通过外部程序获取凭证，如使用此类型凭证需确保外部程序实现定期刷新机制。

* CredentialsURI：CredentialsURI类型凭证通过访问用户输入的URI地址获取凭证，如使用此类型凭证需定期刷新URI中保存凭证信息。

您需要[检查凭证模式](#9604d20242cbi)以确保阿里云CLI可以获取有效的身份凭证。

## 错误信息列表
以下表格为您展示阿里云CLI常见错误码及相关信息。调用OpenAPI时返回的错误码，您可在[OpenAPI问题诊断](https://api.aliyun.com/troubleshoot)中获取诊断方案与日志信息。  
错误详情  
<table> <thead> <tr> <td><p><b>错误描述</b></p></td> <td><p><b>可能的原因</b></p></td> <td><p><b>处理方式</b></p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p>unknown profile \&lt;PROFILE_NAME\&gt;, run configure to check</p></td> <td><p>配置文件中不存在指定凭证配置。</p></td> <td> <ul> <li><p>执行<code>aliyun configure list/get</code>命令检查配置名称。</p></li> <li><p>执行<code>aliyun configure</code>/<code>aliyun configure set</code>命令创建凭证配置</p></li> </ul></td> </tr> <tr> <td><p>unexpected authenticate mode: \&lt;CREMODE\&gt;</p></td> <td><p>执行<code>aliyun configure</code>命令时指定了错误的凭证类型。</p></td> <td><p>执行<code>aliyun configure</code>命令时指定正确的凭证类型。</p></td> </tr> <tr> <td><p>the --profile \&lt;profileName\&gt; is required</p></td> <td><p>执行<code>aliyun configure switch</code>命令时未指定凭证配置。</p></td> <td><p>执行命令时使用<code>--profile</code>选项指定凭证配置。</p></td> </tr> <tr> <td><p>the profile \`\&lt;profileName\&gt;\` is inexist</p></td> <td><p>执行<code>aliyun configure switch</code>命令时指定的凭证配置不存在。</p></td> <td><p>执行<code>aliyun configure list/get</code>命令检查配置详情。</p></td> </tr> <tr> <td><p>fail to set configuration: \&lt;Error Message\&gt;</p></td> <td><p>使用<code>aliyun configure set</code>命令配置凭证时，未正确传入必要参数。</p></td> <td><p><a href="#6a96e33800sci">配置身份凭证时发生"fail to set configuration"类型错误</a></p></td> </tr> <tr> <td><p>AccessKeyId/AccessKeySecret is empty! run \`aliyun configure\` first</p></td> <td><p>指定凭证配置中的AccessKey ID或AccessKey Secret为空。</p></td> <td> <ul> <li><p>执行<code>aliyun configure get</code>命令检查配置详情。</p></li> <li><p>执行<code>aliyun configure</code>/<code>aliyun configure set</code>命令修改凭证配置。</p></li> </ul></td> </tr> <tr> <td><p>default RegionId is empty! run \`aliyun configure\` first</p></td> <td><p>指定凭证配置中的地域ID为空。</p></td> </tr> <tr> <td><p>can not load the source profile: \&lt;profileName\&gt;</p></td> <td><p>使用<b>ChainableRamRoleArn</b>类型凭证配置时，配置中的前置凭证配置名称有误。</p></td> </tr> <tr> <td><p>invalid credentials uri</p></td> <td><p>使用<b>CredentialsURI</b>类型凭证配置时，配置中的凭证URI为空。</p></td> </tr> <tr> <td><p>unexpected certificate mode: \&lt;Mode\&gt;</p></td> <td><p>指定凭证配置类型存在错误。</p></td> </tr> <tr> <td><p>get credentials from \&lt;Credentials URI\&gt; failed, status code \&lt;StatusCode\&gt;</p></td> <td><p>使用<b>CredentialsURI</b>类型凭证配置时，配置中的凭证URI无法访问。</p></td> <td> <ul> <li><p>执行<code>aliyun configure get</code>命令检查配置详情。</p></li> <li><p>检查凭证URI有效性。</p></li> <li><p>检查当前设备网络状态是否正常。</p></li> <li><p>执行<code>aliyun configure</code>/<code>aliyun configure set</code>命令修改凭证配置。</p></li> </ul></td> </tr> <tr> <td><p>unmarshal credentials failed, the body \&lt;Credentials Body\&gt;</p></td> <td><p>使用<b>CredentialsURI</b>类型凭证配置时，无法反序列化从凭证URI中获取的凭证数据<code>Credentials Body</code>。</p></td> </tr> <tr> <td><p>get sts token err, Code is not Success</p></td> <td><p>使用<b>CredentialsURI</b>类型凭证配置时，无法从凭证URI中获取凭证信息。</p></td> </tr> <tr> <td><p>required parameters not assigned</p></td> <td><p>调用OpenAPI时，未指定必填参数。</p></td> <td> <ul> <li><p><a href="#3d0e5a15f4z1q">检查命令及参数格式</a>。</p></li> <li><p><a href="#c7c17eaaa6utu">更新或重新安装阿里云CLI版本</a>。</p></li> </ul></td> </tr> <tr> <td><p>unchecked version \&lt;OpenAPI Version\&gt;</p></td> <td><p>调用OpenAPI时，指定了错误的版本信息。</p></td> </tr> <tr> <td><p>too many arguments</p></td> <td><p>调用OpenAPI时，命令格式与要求不符。</p></td> </tr> <tr> <td><p>invalid argument</p></td> <td><p>调用RPC风格OpenAPI时，命令格式与要求不符。</p></td> </tr> <tr> <td><p>product '\&lt;ProductCode\&gt;' need restful call</p></td> <td><p>调用ROA风格OpenAPI时，未指定请求方式。</p></td> </tr> <tr> <td><p>bad restful path \&lt;PathPattern\&gt;</p></td> <td><p>调用ROA风格OpenAPI时，指定了无效的请求路径<code>PathPattern</code>。</p></td> </tr> <tr> <td><p>--method value \&lt;Method\&gt; is not supported, please set method in {GET\|POST}</p></td> <td><p>调用RPC风格OpenAPI时，指定了不支持的请求方式。</p></td> <td><p><code>--method</code>选项仅支持指定<code>GET</code>/<code>POST</code>请求方式。</p></td> </tr> <tr> <td><p>invalid flag --header \`\&lt;RequestHeader\&gt;\` use \`--header HeaderName=Value</p></td> <td><p>使用<code>--header</code>选项时，传参格式与要求不符。</p></td> <td><p><code>--header</code>选项仅支持使用<code>key=value</code>形式指定请求头。</p></td> </tr> <tr> <td><p>missing version for product \&lt;ProductCode\&gt;</p></td> <td><p>使用<code>--force</code>选项时，未使用<code>--version</code>选项指定OpenAPI版本信息。</p></td> <td><p>使用<code>--version</code>选项指定OpenAPI版本。</p></td> </tr> <tr> <td><p>missing region for product \&lt;ProductCode\&gt;</p></td> <td><p>使用<code>--force</code>选项时，未使用<code>--region</code>选项指定地域ID。</p></td> <td><p>使用<code>--region</code>选项指定地域ID。</p></td> </tr> <tr> <td><p>unknown endpoint for \&lt;ProductCode\&gt;/\&lt;RegionID\&gt;!</p></td> <td><p>使用<code>--force</code>选项时，指定了无效的接入点地址。</p></td> <td> <ul> <li><p>检查产品代码及地域ID是否正确。</p></li> <li><p>使用<code>--endpoint</code>选项指定正确的接入点。</p></li> </ul></td> </tr> <tr> <td><p>you need to assign col=col1,col2,... with --output</p></td> <td><p>使用<code>--output</code>选项时，未指定过滤字段值。</p></td> <td><p>参考文档<a href="https://help.aliyun.com/document_detail/122111.html">过滤且表格化输出结果</a>，根据响应结果指定字段名。</p></td> </tr> <tr> <td><p>jmespath: '\&lt;rows\&gt;' failed</p></td> <td><p>使用<code>--output</code>选项时，指定的过滤字段路径<code>rows</code>格式与JMESPath规范不符。</p></td> <td><p>参考<a href="http://jmespath.org/tutorial.html">JMESPath官方文档</a>，根据JMESPath格式规范修正过滤字段路径<code>rows</code>。</p></td> </tr> <tr> <td><p>jmespath: '\&lt;rows\&gt;' failed Need Array Expr</p></td> <td><p>使用<code>--output</code>选项时，指定的过滤字段路径<code>rows</code>无法匹配到目标数据。</p></td> <td><p>参考OpenAPI文档，修正过滤字段路径<code>rows</code>。</p></td> </tr> <tr> <td><p>colNames: \&lt;cols\&gt; must be string:number format, like 'name:0', 0 is the array index</p></td> <td><p>使用<code>--output</code>选项处理JSON数组时，过滤字段值<code>cols</code>格式错误。</p></td> <td><p>使用<code>--output</code>选项处理JSON数组时，需以<code>string:number</code>的格式指定过滤字段值<code>cols</code>。</p></td> </tr> <tr> <td><p>read json from \&lt;MetadatasPath\&gt; failed</p></td> <td><p>无法获取OpenAPI元数据。</p></td> <td><p><a href="#c7c17eaaa6utu">更新或重新安装阿里云CLI版本</a>。</p></td> </tr> <tr> <td><p>unmarshal json \&lt;MetadatasPath\&gt; failed</p></td> <td><p>无法反序列化OpenAPI元数据JSON文件。</p></td> </tr> <tr> <td><p>jmespath: '\&lt;Field\&gt;' failed</p></td> <td><p>使用<code>--pager</code>选项时，指定的字段格式不符合JMESPath规范。</p></td> <td><p>参考OpenAPI文档及<a href="http://jmespath.org/tutorial.html">JMESPath官方文档</a>，根据JMESPath格式规范修正字段参数。</p></td> </tr> <tr> <td><p>jmespath search failed</p></td> <td><p>使用<code>--pager</code>选项时，指定的路径字段<code>path</code>格式不符合JMESPath规范。</p></td> </tr> <tr> <td><p>jmespath result empty: \&lt;path\&gt;</p></td> <td><p>使用<code>--pager</code>选项时，指定的路径字段<code>path</code>无效。</p></td> </tr> <tr> <td><p>can't auto recognize collections path: you need add \`--pager path=\[jmespath\]\` to assign manually</p></td> <td><p>使用<code>--pager</code>选项时，无法自动识别数据集合路径。</p></td> <td><p>参考OpenAPI文档及<a href="http://jmespath.org/tutorial.html">JMESPath官方文档</a>，使用<code>path</code>字段指定数据集合路径。</p></td> </tr> <tr> <td><p>unmarshal failed</p></td> <td><p>无法反序列化响应数据。</p></td> <td> <ul> <li><p><a href="#3d0e5a15f4z1q">检查命令及参数格式</a>。</p></li> <li><p>检查当前设备网络状态是否正常。</p></li> <li><p><a href="#c7c17eaaa6utu">更新或重新安装阿里云CLI版本</a>。</p></li> </ul></td> </tr> <tr> <td><p>jmes search failed</p></td> <td><p>JMESPath无法解析响应数据。</p></td> </tr> <tr> <td><p>object \&lt;Response\&gt; isn't string</p></td> <td><p>无法将接口响应数据转化为string格式字符串。</p></td> </tr> <tr> <td><p>'--\&lt;Param\&gt;' is not a valid parameter or flag</p></td> <td><p>调用OpenAPI时，使用了无效的参数或选项<code>Param</code>。</p></td> <td><p>参考OpenAPI文档或帮助信息，修正所用参数或选项。</p></td> </tr> <tr> <td><p>invaild flag --header \`\&lt;value\&gt;\` use \`--header HeaderName=Value\`</p></td> <td><p>设置请求头时，使用了错误的命令格式。</p></td> <td><p>使用<code>--header HeaderName=Value</code>格式设置请求头。</p></td> </tr> <tr> <td><p>unknown parameter position; \&lt;PARAM_NAME\&gt; is \&lt;PARAM_POSITION\&gt;</p></td> <td><p>元数据错误。</p></td> <td><p>在命令后添加<code>--method POST --force</code>选项发起强制调用。</p></td> </tr> </tbody> </table>

## 技术支持
以上问题的解决方案旨在帮助您更友好地使用阿里云CLI。如果您在使用过程中遇到其他问题，可以通过[GitHub Issues](https://github.com/aliyun/aliyun-cli/issues/new)或工单提交反馈，帮助我们共同改进阿里云CLI体验。

## 相关文档
如您在使用`aliyun oss`命令时出现问题，可参考[ossutil常见问题](https://help.aliyun.com/document_detail/101135.html)尝试解决。