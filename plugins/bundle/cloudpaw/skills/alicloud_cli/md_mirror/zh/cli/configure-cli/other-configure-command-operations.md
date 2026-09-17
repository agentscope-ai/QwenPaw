阿里云CLI支持保存多套凭证配置，您可以通过`configure`及其子命令便捷地管理这些配置。本文为您介绍相关命令语法及其使用示例。  

## **交互式创建**配置
您可以使用`aliyun configure`命令，以交互式方式创建配置。

### 命令语法

```
HELPCODEESCAPE-shell
aliyun configure [--mode <AUTHENTICATE_MODE>] [--profile <PROFILE_NAME>]
```

* `AUTHENTICATE_MODE`：指定要设置的凭证类型。若参数为空，则默认创建**AK**类型凭证配置。

* `PROFILE_NAME`：指定配置名称。若不使用该选项，将优先修改当前配置。若指定配置不存在则新建配置。

### 调用示例

1. 执行如下命令，使用交互式方式创建**AK** 类型凭证配置*AkProfile*。

   ```
   HELPCODEESCAPE-shell
   aliyun configure --mode AK --profile AkProfile
   ```

2. 交互过程如下所示。

   ```
   HELPCODEESCAPE-shell
   Configuring profile 'AkProfile' in 'AK' authenticate mode...
   Access Key Id []: "0wNEpMMlzy7s****"
   Access Key Secret []: <YOUR_ACCESS_KEY_SECRET>
   Default Region Id []: cn-hangzhou
   Default Output Format [json]: json (Only support json)
   Default Language [zh|en] en: en
   Saving profile[profile] ...Done.
   ```

## 非交互式创建或修改配置
您可以使用`aliyun configure set`命令，以非交互式方式创建或修改配置。  
**说明**

成功修改配置后，阿里云CLI会将被修改配置切换为当前配置。

### 命令语法

```
HELPCODEESCAPE-shell
aliyun configure set [--mode <AUTHENTICATE_MODE>] [--profile <PROFILE_NAME>] [--settingName <settingValue>...]
```

* `AUTHENTICATE_MODE`：指定凭证类型。若参数为空，则默认创建**AK**类型凭证配置。

* `PROFILE_NAME`：指定配置名称。若参数为空且未配置环境变量`ALIBABA_CLOUD_PROFILE`，则优先修改当前配置。若指定配置不存在则创建新配置。

* `settingName`：指定配置参数。创建配置时需参考[身份凭证类型](https://help.aliyun.com/document_detail/121193.html#30ab0f9c3eovm)，设置对应类型中所有必填项，否则将创建失败。

  可修改设置项列表  
  <table> <thead> <tr> <td><p><b>选项</b></p></td> <td><p><b>说明</b></p></td> <td><p><b>示例值</b></p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p>--region</p></td> <td><p>默认地域ID。</p></td> <td><p>cn-hangzhou</p></td> </tr> <tr> <td><p>--language</p></td> <td><p>帮助信息语言。</p> <ul> <li><p>中文：<code>zh</code></p></li> <li><p>英文：<code>en</code></p></li> </ul></td> <td><p>zh</p></td> </tr> <tr> <td><p>--read-timeout</p></td> <td><p>I/O超时时间（单位：秒）。</p></td> <td><p>10</p></td> </tr> <tr> <td><p>--connect-timeout</p></td> <td><p>连接超时时间（单位：秒）。</p></td> <td><p>10</p></td> </tr> <tr> <td><p>--retry-count</p></td> <td><p>重试次数。</p></td> <td><p>5</p></td> </tr> <tr> <td><p>--expired-seconds </p></td> <td><p>凭证过期时间。</p></td> <td><p>900</p></td> </tr> <tr> <td><p>--access-key-id</p></td> <td><p>阿里云账号或 RAM 用户的AccessKey ID。</p></td> <td><p>yourAccessKeyID</p></td> </tr> <tr> <td><p>--access-key-secret</p></td> <td><p>阿里云账号或 RAM 用户的AccessKey Secret。</p></td> <td><p>yourAccessKeySecret</p></td> </tr> <tr> <td><p>--sts-token</p></td> <td><p>安全令牌。</p></td> <td><p>yourSecurityToken</p></td> </tr> <tr> <td><p>--sts-region</p></td> <td><p>获取STS Token令牌时发起调用的地域。</p></td> <td><p>cn-hangzhou</p></td> </tr> <tr> <td><p>--ram-role-name</p></td> <td><p>RAM角色名称。</p></td> <td><p>ECSAdmin</p></td> </tr> <tr> <td><p>--ram-role-arn</p></td> <td><p>RAM角色ARN。</p></td> <td><p>acs:ram::012345678910\*\*\*\*:role/Alice</p></td> </tr> <tr> <td><p>--role-session-name</p></td> <td><p>角色会话名称。</p></td> <td><p>alice</p></td> </tr> <tr> <td><p>--source-profile</p></td> <td><p>源配置名称。</p></td> <td><p>RamRoleArnProfile</p></td> </tr> <tr> <td><p>--process-command</p></td> <td><p>外部程序运行命令。</p></td> <td><p>acs-sso login --profile sso</p></td> </tr> <tr> <td><p>--oidc-provider-arn</p></td> <td><p>OIDC提供商ARN。</p></td> <td><p>acs:ram::012345678910\*\*\*\*:oidc-provider/TestOidcIdp</p></td> </tr> <tr> <td><p>--oidc-token-file</p></td> <td><p>OIDC Token文件路径。</p></td> <td><p>/path/to/oidctoken</p></td> </tr> <tr> <td><p>--cloud-sso-sign-in-url</p></td> <td><p>云SSO用户登录地址。</p></td> <td><p>https://signin-\*\*\*\*\*\*.alibabacloudsso.com/device/login</p></td> </tr> <tr> <td><p>--cloud-sso-access-config</p></td> <td><p>云SSO访问配置ID。</p></td> <td><p>ac-012345678910abcde\*\*\*\*</p></td> </tr> <tr> <td><p>--cloud-sso-account-id</p></td> <td><p>云SSO登录云账号UID。</p></td> <td><p>012345678910\*\*\*\*</p></td> </tr> <tr> <td><p>--oauth-site-type</p></td> <td><p>OAuth登录站点类型。</p> <ul> <li><p>中国站：<code>CN</code></p></li> <li><p>国际站：<code>INTL</code></p></li> </ul></td> <td><p>CN</p></td> </tr> </tbody> </table>

### 示例一：非交互式创建配置

1. 执行如下命令，使用非交互式方式创建**AK** 类型凭证配置*AkProfile**。*

   ```
   HELPCODEESCAPE-shell
   aliyun configure set \
     --access-key-id <yourAccessKeyID> \
     --access-key-secret <yourAccessKeySecret> \
     --region cn-hangzhou \
     --profile AkProfile \
     --mode AK \
     --language en
   ```

2. 执行`aliyun configure list`命令，终端输出如下信息。则配置*AkProfile*已成功创建。

   ```
   HELPCODEESCAPE-shell
   Profile           | Credential            | Valid   | Region           | Language
   ---------         | ------------------    | ------- | ---------------- | --------
   default           | AK:******             | Valid   | cn-beijing       | zh
   AkProfile *       | AK:******             | Valid   | cn-hangzhou      | en
   ```

### 示例二：修改指定配置

1. 执行`aliyun configure get region`命令，终端返回当前配置中的地域ID。

   ![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/8496603471/p927026.png)
2. 执行如下命令，将当前配置的地域ID修改至`cn-shanghai`。

   ```
   HELPCODEESCAPE-shell
   aliyun configure set --region cn-shanghai
   ```

3. 再次执行`aliyun configure get region`命令，验证修改结果。

   ![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/8496603471/p927028.png)

## 获取配置列表
您可以使用`aliyun configure list`命令获取配置列表，在列表中查看全部配置的概要信息。

### 调用示例

1. 执行如下命令，获取凭证配置列表。

   ```
   HELPCODEESCAPE-shell
   aliyun configure list
   ```

2. 终端返回如下配置列表。

   配置列表包含以下概要信息：配置名称、当前配置标记（阿里云CLI使用星形标示号`*`标记当前配置，该记号位于配置名称右侧）、部分凭证信息、凭据有效性、默认地域ID以及帮助信息语言。

   ```
   HELPCODEESCAPE-shell
   Profile           | Credential            | Valid   | Region           | Language
   ---------         | ------------------    | ------- | ---------------- | --------
   AkProfile *       | AK:******             | Valid   | cn-beijing       | en
   StsTokenProfile   | StsToken:******       | Valid   | cn-hangzhou      | en
   RamRoleArnProfile | RamRoleArn:******     | Valid   | cn-shanghai      | en
   EcsRamRoleProfile | EcsRamRole:ECSAdmin   | Valid   | cn-qingdao       | zh
   ```

## 查看指定配置信息
您可以使用`aliyun configure get`命令查看指定配置的详细信息。

### 命令语法

```
HELPCODEESCAPE-shell
aliyun configure get [--profile <PROFILE_NAME>] [<SETTING_NAME>...]
```

* `PROFILE_NAME`：指定配置名称。若该参数为空且未配置环境变量`ALIBABA_CLOUD_PROFILE`，则优先查看当前配置信息。若指定配置不存在，则提示`profile <PROFILE_NAME> not found!`。

* `SETTING_NAME`：指定要查看的设置项，可同时指定多项设置，未指定时显示全部设置项。若指定的设置项不存在，命令执行后终端不返回信息。

  可查看设置项列表  
  <table> <thead> <tr> <td><p><b>命令参数</b></p></td> <td><p><b>说明</b></p></td> <td><p><b>关联设置字段</b></p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p>profile</p></td> <td><p>配置名称。</p></td> <td><p>name</p></td> </tr> <tr> <td><p>mode</p></td> <td><p>凭证类型。</p></td> <td><p>mode</p></td> </tr> <tr> <td><p>region</p></td> <td><p>默认地域ID。</p></td> <td><p>region_id</p></td> </tr> <tr> <td><p>language</p></td> <td><p>帮助信息语言。</p></td> <td><p>language</p></td> </tr> <tr> <td><p>access-key-id</p></td> <td><p>阿里云账号或 RAM 用户的AccessKey ID。</p></td> <td><p>access_key_id</p></td> </tr> <tr> <td><p>access-key-secret</p></td> <td><p>阿里云账号或 RAM 用户的AccessKey Secret。</p></td> <td><p>access_key_secret</p></td> </tr> <tr> <td><p>sts-token</p></td> <td><p>RAM用户或角色的临时身份凭证STS Token。</p></td> <td><p>sts_token</p></td> </tr> <tr> <td><p>sts-region</p></td> <td><p>RAM用户或角色获取临时身份凭证时发起调用的地域ID。</p></td> <td><p>sts_region</p></td> </tr> <tr> <td><p>ram-role-name</p></td> <td><p>RAM角色名称。</p></td> <td><p>ram_role_name</p></td> </tr> <tr> <td><p>ram-role-arn</p></td> <td><p>RAM角色ARN。</p></td> <td><p>ram_role_arn</p></td> </tr> <tr> <td><p>external-id</p></td> <td><p>角色外部ID。</p></td> <td><p>external_id</p></td> </tr> <tr> <td><p>role-session-name</p></td> <td><p>角色会话名称。</p></td> <td><p>ram_session_name</p></td> </tr> <tr> <td><p>cloud-sso-sign-in-url</p></td> <td><p>云SSO用户登录地址。</p></td> <td><p>cloud-sso-sign-in-url</p></td> </tr> <tr> <td><p>cloud-sso-access-config</p></td> <td><p>云SSO访问配置ID。</p></td> <td><p>cloud-sso-access-config</p></td> </tr> <tr> <td><p>cloud-sso-account-id</p></td> <td><p>云SSO登录云账号UID。</p></td> <td><p>cloud-sso-account-id</p></td> </tr> <tr> <td><p>oauth-site-type</p></td> <td><p>OAuth登录站点类型。</p></td> <td><p>oauth-site-type</p></td> </tr> </tbody> </table>

### 示例一：查看指定配置全部设置信息

1. 执行如下命令，查看**AK** 类型凭证配置*AkProfile*的全部设置项。

   ```
   HELPCODEESCAPE-shell
   aliyun configure get --profile AkProfile
   ```

2. 返回结果。

   ```
   HELPCODEESCAPE-json
   {
     "name": "AkProfile",
     "mode": "AK",
     "access_key_id": "<yourAccessKeyID>",
     "access_key_secret": "<yourAccessKeySecret>",
     "region_id": "cn-hangzhou",
     "output_format": "json",
     "language": "en"
   }
   ```

### 示例二：查看指定配置部分设置信息

1. 执行如下命令，查看**External** 类型凭证配置*ExternalProfile*的配置名称、凭证类型及默认语言。

   ```
   HELPCODEESCAPE-shell
   aliyun configure get profile mode language --profile ExternalProfile
   ```

2. 终端以`key=value`格式返回设置详情。

   ```
   HELPCODEESCAPE-shell
   profile=ExternalProfile
   mode=External
   language=en
   ```

## 切换当前配置
阿里云CLI自`v3.0.214`版本起，支持执行`aliyun configure switch`命令，可将指定配置切换为当前生效配置。切换成功后，阿里云CLI发起的所有请求在未指定凭证时，均会自动使用此配置。

### 命令语法

```
HELPCODEESCAPE-shell
aliyun configure switch --profile <PROFILE_NAME>
```

`PROFILE_NAME`：指定配置名称，该选项为必填项。若参数为空或配置不存在，命令执行失败。

### 调用示例

1. 执行`aliyun configure list`命令[获取配置列表](#4addcad7ec44w)，可知当前配置为`default`（阿里云CLI使用星形标示号`*`标记当前配置，该记号位于配置名称右侧）。

   ```
   HELPCODEESCAPE-shell
   Profile           | Credential            | Valid   | Region           | Language
   ---------         | ------------------    | ------- | ---------------- | --------
   default *         | AK:******             | Valid   | cn-hangzhou      | en
   ExampleProfile    | AK:******             | Valid   | cn-beijing       | zh
   ```

2. 执行如下命令，将当前配置切换为*ExampleProfile**。* 设置成功后终端返回信息``The default profile is `ExampleProfile` now.``。

   ```
   HELPCODEESCAPE-shell
   aliyun configure switch --profile exampleProfile
   ```

3. 再次执行`aliyun configure list`命令，确认当前配置已更新。

   ```
   HELPCODEESCAPE-shell
   Profile           | Credential            | Valid   | Region           | Language
   ---------         | ------------------    | ------- | ---------------- | --------
   default           | AK:******             | Valid   | cn-hangzhou      | en
   ExampleProfile *  | AK:******             | Valid   | cn-beijing       | zh
   ```

## 删除指定配置
您可以使用`aliyun configure delete`命令删除指定配置。

### 命令语法

```
HELPCODEESCAPE-shell
aliyun configure delete --profile <PROFILE_NAME>
```

* `PROFILE_NAME`：指定待删除的配置名称，该选项为必填项。若传入参数为空或配置不存在，命令执行失败。

* 若要删除的配置为当前配置，则删除完成后自动将配置列表最顶端配置切换为当前配置，详情请参见调用示例。

* 建议保留至少一项配置。如果您误操作导致清空凭证配置，则阿里云CLI将无法正常工作。您需要手动删除`config.json`文件以解决此问题，该文件位于您个人用户目录下的`.aliyun`文件夹中，个人用户目录位置因操作系统而异。

  * Windows：`C:\Users\`**<** ***USER_NAME>***`\.aliyun`

  * Linux/macOS：`/home/`***<USER_NAME>***`/.aliyun`

### 调用示例

1. 执行`aliyun configure list`命令，查看配置列表。

   ```
   HELPCODEESCAPE-shell
   Profile           | Credential            | Valid   | Region           | Language
   ---------         | ------------------    | ------- | ---------------- | --------
   default           | AK:******             | Valid   | cn-hangzhou      | en
   AkProfile         | AK:******             | Valid   | cn-hangzhou      | en
   ExampleProfile *  | AK:******             | Valid   | cn-hangzhou      | en
   ```

2. 执行如下命令，删除配置*ExampleProfile*。

   ```
   HELPCODEESCAPE-shell
   aliyun configure delete --profile ExampleProfile
   ```

3. 再次执行`aliyun configure list`命令，配置*ExampleProfile*成功删除，当前配置已切换为*default*。

   ```
   HELPCODEESCAPE-shell
   Profile           | Credential            | Valid   | Region           | Language
   ---------         | ------------------    | ------- | ---------------- | --------
   default *         | AK:******             | Valid   | cn-hangzhou      | en
   AkProfile         | AK:******             | Valid   | cn-hangzhou      | en
   ```

<br />