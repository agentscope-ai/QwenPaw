阿里云CLI集成了对象存储 OSS（Object Storage Service）的命令行工具`ossutil`，您可以在统一的CLI环境中执行OSS资源管理操作。本文为您介绍基于阿里云CLI使用ossutil的相关操作。  

## **使用准备**
* `ossutil`是阿里云官方提供的OSS命令行工具，支持通过Windows、Linux和macOS系统以命令行方式管理OSS数据。目前，`ossutil`以插件形式深度集成至阿里云CLI，您可以通过阿里云CLI直接调用`ossutil`完成对存储空间（Bucket）、文件（Object）等核心资源的管理操作。

* 自阿里云CLI`v3.0.304`版本起，深度集成[ossutil 2.0](https://help.aliyun.com/document_detail/2786110.html)，向您提供更稳定、更高效的使用体验。当前阿里云CLI同时兼容`ossutil 1.0`与`ossutil 2.0`两个版本，[旧版本命令](#8770f3b81e5xp)仍可正常使用。建议您将阿里云CLI升级至最新版本，以获得 `ossutil 2.0` 的全部新特性与性能提升。

* 阿里云CLI中`ossutil 1.0`和`ossutil 2.0`主要差异如下：

  **命令调用差异**  
  新版本命令由 `oss` 升级为 `ossutil`，便于区分功能模块并支持更多高级特性。
  <table> <thead> <tr> <td><p><b>版本</b></p></td> <td><p><b>命令格式</b></p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p>ossutil 1.0（旧版本）</p></td> <td><p><code>aliyun oss</code></p></td> </tr> <tr> <td><p>ossutil 2.0（新版本）</p></td> <td><p><code>aliyun ossutil</code></p></td> </tr> </tbody> </table>  
  **说明**

  新版本命令由`oss` 变更为 `ossutil`，如需使用`ossutil 2.0`，请在脚本或自动化任务中注意更新命令。  
  **命令差异**  
  <table> <thead> <tr> <td><p>差异项</p></td> <td><p>ossutil 1.0（旧版本）</p></td> <td><p>ossutil 2.0（新版本）</p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p>bucket类配置</p></td> <td><p>按照功能进行分类，放在根命令下，例如logging、lifecycle。</p></td> <td> <ul> <li><p>一个接口对应一个命令，放在ossutil api子命令下。</p></li> <li><p>配置参数同时支持XML和JSON格式。</p></li> <li><p>支持对输出内容的格式转换，例如转换成JSON。</p></li> </ul></td> </tr> <tr> <td><p>rm命令</p></td> <td> <ul> <li><p>支持删除存储空间。</p></li> <li><p>一次操作，支持删除多种类型的数据，例如同时删除对象和分片。</p></li> </ul><p>示例：<code>rm oss://bucket/prefix -r -f -m\&nbsp;</code></p></td> <td> <ul> <li><p>不支持删除存储空间，如果需要删除存储空间，请使用新增命令rb。</p></li> <li><p>一次操作，只能删除一种类型的数据，例如删除对象和分片时，需要分别调用。</p></li> </ul><p>示例：<code>rm oss://bucket/prefix -r -f</code>和</p><p><code>rm oss://bucket/prefix -m -r -f</code></p></td> </tr> <tr> <td><p>追加命令</p></td> <td> <ul> <li><p>命令为appendfromfile。</p></li> <li><p>数据源仅支持本地路径。</p></li> </ul></td> <td> <ul> <li><p>命令为append。</p></li> <li><p>数据源支持本地路径、OSS资源地址和标准输入。</p></li> </ul></td> </tr> <tr> <td><p>cat命令</p></td> <td><p>仅支持输出整个文件内容。</p></td> <td><p>支持输出部分文件内容，例如前10个字节或者最后10个字节。</p></td> </tr> <tr> <td><p>cp命令</p></td> <td><p>对象间的拷贝只拷贝数据，不拷贝元数据和标签。</p></td> <td><p>进行对象间的拷贝时，可通过--copy-props来控制元数据和标签的复制规则：不拷贝、拷贝元数据、拷贝元数据和标签。</p><p>默认拷贝元数据和标签。</p></td> </tr> <tr> <td><p>修改对象属性（</p><p>权限、存储类型、元数据和标签）</p></td> <td> <ul> <li><p>通过set-acl修改对象权限。</p></li> <li><p>通过set-meta修改对象元信息。</p></li> <li><p>通过cp命令，修改对象存储类型和标签。</p></li> <li><p>通过object-tagging命令修改对象标签。</p></li> </ul></td> <td> <ul> <li><p>对象属性修改合并成一个命令set-props，根据需要修改的属性参数选择合适的接口，让属性修改更有效率。</p></li> <li><p>通过别名方式支持set-acl和set-meta，但是命令行参数和原命令参数不一致。</p></li> <li><p>支持丰富的元数据和标签修改指令，包括 replace、update、purge和delete。</p></li> </ul></td> </tr> <tr> <td><p>预签名</p></td> <td> <ul> <li><p>命令名为sign。</p></li> <li><p>签名的过期时间。仅支持时间间隔，例如120秒。</p></li> </ul></td> <td> <ul> <li><p>命令名为presign。</p></li> <li><p>支持sign别名，但是命令行参数和原命令参数不一致。</p></li> <li><p>签名的过期时间。既支持时间间隔，例如 120秒，也只支持绝对时间设置。</p></li> <li><p>v4签名下，限制生成操作7天的预签名地址。</p></li> </ul><p></p></td> </tr> <tr> <td><p>版本恢复</p></td> <td><p>仅支持通过删除"删除标记"恢复最新版本。</p></td> <td> <ul> <li><p>支持通过删除"删除标记"恢复最新版本。</p></li> <li><p>支持通过版本索引，采用复制方式恢复到指定版本。</p></li> <li><p>支持通过时间索引，采用复制方式恢复到指定版本。</p></li> </ul></td> </tr> <tr> <td><p>hash</p></td> <td><p>仅支持计算本地文件哈希值。</p></td> <td> <ul> <li><p>支持本地文件。</p></li> <li><p>支持对象路径。</p></li> <li><p>支持批量操作。</p></li> </ul></td> </tr> <tr> <td><p>sync</p></td> <td> <ul> <li><p>不使用--delete参数时，与cp命令效果相同，边扫描源边拷贝，没有最大数量限制。</p></li> <li><p>使用--delete参数时，数据复制阶段也采用边扫描源边拷贝模式。</p></li> </ul></td> <td> <ul> <li><p>无论是否设置--delete参数，都有最大数量限制，默认值是100W，最大可以配置到500W。</p></li> <li><p>先扫描源端和目的端列表，然后同步数据，最后根据--delete选项删除目的端文件的工作模式，所以当结合--update/--size-only选项时，有更好的同步性能。</p></li> </ul></td> </tr> </tbody> </table>  
  **选项差异**  
  <table> <thead> <tr> <td><p>差异项</p></td> <td><p>ossutil 1.0（旧版本）</p></td> <td><p>ossutil 2.0（新版本）</p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p>--include</p><p>--exclude</p></td> <td> <ul> <li><p>仅支持对象/文件名匹配。</p></li> <li><p>当包含多个include（包含）和exclude（排除）条件时，从左到右逐一运用每个规则，直至最后才能最终确定匹配的结果。</p></li> </ul></td> <td> <ul> <li><p>支持对象/文件名匹配。</p></li> <li><p>支持对象/文件路径匹配。</p></li> <li><p>当包含多个include（包含）和exclude（排除）条件时，从左到右按照顺序运用规则，如果匹配到规则（包含或者排除），马上停止后面的检查。</p></li> </ul></td> </tr> <tr> <td><p>--snapshot-path</p></td> <td><p>支持</p></td> <td><p>不支持</p></td> </tr> <tr> <td><p>--encoding-type</p></td> <td><p>同时对输入参数和输出参数生效。</p></td> <td> <ul> <li><p>高级命令中，该参数只对输入参数生效，不对输出结果生效。</p></li> <li><p>API级命令中，该参数与接口的对应参数含义一致。</p></li> </ul></td> </tr> <tr> <td><p>目的端的排除选项</p></td> <td><p>仅支持--update。</p></td> <td><p>支持--update、-size-only、--checksum和--ignore-existing。</p></td> </tr> <tr> <td><p>速度限制</p></td> <td><p>仅支持上传的限速，使用--max-speed设置选项。</p></td> <td><p>支持上传和下载限速，使用--bandwidth-limit设置选项。</p></td> </tr> <tr> <td><p>默认配置</p></td> </tr> <tr> <td><p>签名版本</p></td> <td><p>签名版本1。</p></td> <td><p>签名版本4。当使用v4预签名时，最长有效期为1周。</p></td> </tr> <tr> <td><p>HTTPS协议</p></td> <td><p>当不指定时，默认是HTTP协议。</p></td> <td><p>默认使用HTTPS协议。</p></td> </tr> <tr> <td><p>对象列举接口</p></td> <td><p>使用ListObjects接口。</p></td> <td><p>默认使用ListObjectsV2接口，可以通过--list-objects切换到ListObjects接口。</p></td> </tr> <tr> <td><p>read-timeout</p></td> <td><p>客户端读写超时，默认值为1200秒。</p></td> <td><p>默认值20秒。</p></td> </tr> <tr> <td><p>connect-timeout</p></td> <td><p>客户端连接超时的时间，单位为秒，默认值为120秒。</p></td> <td><p>默认值10秒。</p></td> </tr> <tr> <td><p>断点续传</p></td> <td><p>支持，默认开启。</p></td> <td><p>支持，默认关闭。</p></td> </tr> </tbody> </table>

  <br />

## 新版本
**说明**

* 在新版本的阿里云CLI中，ossutil 2.0支持自动检查并升级至最新版本，您无需手动执行`update`命令。

* ossutil 2.0版本与阿里云CLI主程序版本相互独立，更新不受CLI版本绑定限制。

### 命令结构

阿里云CLI中ossutil 2.0命令格式如下：

```
HELPCODEESCAPE-plaintext
aliyun ossutil command [argument] [flags]

aliyun ossutil command subcommond [argument] [flags]  

aliyun ossutil topic
```

* `argument`：参数，为字符串。

* `flags`：选项，支持短名字风格`-o[=value]/ -o [value]`和长名字风格`--options[=value]/--options[value]`。如果多次指定某个排它参数，则仅最后一个值生效。

命令示例如下：

* 命令：`aliyun ossutil cat oss://bucket/object`

* 多级命令：`aliyun ossutil api get-bucket-cors --bucket bucketexample`

* 帮助主题：`aliyun ossutil filter`

### 命令列表

ossutil 2.0提供了高级命令、API级命令、辅助命令等三类命令。

* 高级命令：用于常用的对对象或者存储空间的操作场景，例如存储空间创建、删除、数据拷贝、对象属性修改等。

  <table> <thead> <tr> <td><p><b>命令名</b></p></td> <td><p><b>含义</b></p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2786748.html">mb</a></p></td> <td><p>创建存储空间</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2787417.html">rb</a></p></td> <td><p>删除存储空间</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2786654.html">du</a></p></td> <td><p>获取存储或者指定前缀所占的存储空间大小</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2788324.html">stat</a></p></td> <td><p>显示存储空间或者对象的描述信息</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2786861.html">mkdir</a></p></td> <td><p>创建一个名字有后缀字符<code>/</code>的对象</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2786483.html">append</a></p></td> <td><p>将内容上传到追加类型的对象末尾</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2786494.html">cat</a></p></td> <td><p>将对象内容连接到标准输出</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2786726.html">ls</a></p></td> <td><p>列举存储空间或者对象</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2786505.html">cp</a></p></td> <td><p>上传、下载或拷贝对象</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2788299.html">rm</a></p></td> <td><p>删除存储空间里的对象</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2788303.html">set-props</a></p></td> <td><p>设置对象的属性</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2786863.html">presign</a></p></td> <td><p>生成对象的预签名URL</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2787122.html">restore</a></p></td> <td><p>恢复冷冻状态的对象为可读状态</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2787228.html">revert</a></p></td> <td><p>将对象恢复成指定的版本</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2788836.html">sync</a></p></td> <td><p>将本地文件目录或者对象从源端同步到目的端</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2786683.html">hash</a></p></td> <td><p>计算文件/对象的哈希值</p></td> </tr> </tbody> </table>
* API级命令：提供了API操作的直接访问，支持该接口的配置参数。

  <table> <thead> <tr> <td><p>命令名</p></td> <td><p>含义</p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2789737.html">put-bucket-acl</a></p></td> <td><p>设置、修改Bucket的访问权限</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2796987.html">get-bucket-acl</a></p></td> <td><p>获取访问权限</p></td> </tr> <tr> <td><p>....</p></td> <td><p></p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2797069.html">put-bucket-cors</a></p></td> <td><p>设置跨域资源共享规则</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2797073.html">get-bucket-cors</a></p></td> <td><p>获取跨域资源共享规则</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2789739.html">delete-bucket-cors</a></p></td> <td><p>删除跨域资源共享规则</p></td> </tr> <tr> <td><p>...</p></td> <td><p></p></td> </tr> </tbody> </table>
* 辅助命令：例如配置文件的配置、额外的帮助主题等。

  <table> <thead> <tr> <td><p>命令名</p></td> <td><p>含义</p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2786302.html">help</a></p></td> <td><p>获取帮助信息</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2793512.html">config</a></p></td> <td><p>创建配置文件用以存储配置项和访问凭证</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2793515.html">version</a></p></td> <td><p>显示版本信息</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2793586.html">probe</a></p></td> <td><p>探测命令</p></td> </tr> </tbody> </table>

### 命令行选项

ossutil 2.0中的命令行选项分为全局命令行选项和局部命令行选项。全局命令行选项适用于所有命令，局部命令行选项仅适用于特定的命令。命令行选项的优先级最高，可以覆盖配置文件设置或环境变量设置的参数。  

#### **查询命令行选项**

执行以下命令查询命令行选项：

```
HELPCODEESCAPE-bash
ossutil cp -h
```

输出内容如下：

```
HELPCODEESCAPE-bash
Flags:
      --acl string                         The access control list (ACL) of the object, valid value(s): "private","public-read","public-read-write","default"
      --bandwidth-limit SizeSuffix         Bandwidth limit in B/s, or use suffix B|K|M|G|T|P
      --bigfile-threshold SizeSuffix       The threshold of file size, the file size larger than the threshold will use multipart upload, download or copy, or use suffix B|K|M|G|T|P (default 100Mi)
      --cache-control string               The caching behavior of the web page when the object is downloaded
      --checkers int                       Number of checkers to run in parallel (default 16)
      --checkpoint-dir string              The specified directory for breakpoint continuation information
      --checksum                           Only copy the source file with different size and checksum(if available)
      --content-disposition string         The method that is used to access the object
      --content-encoding string            The method that is used to encode the object
      --content-type string                The mime type of object
      --copy-props string                  Determines which properties are copied from the source object, valid value(s): "none","metadata","default"
  -d, --dirs                               Return matching subdirectory names instead of contents of the subdirectory
      --encoding-type string               The encoding type of object name or file name that user inputs, valid value(s): "url"
      --end-with string                    The name of the object from which the list operation ends, include
      --exclude stringArray                Exclude files matching pattern
      --exclude-from stringArray           Read exclude patterns from file
      --expires string                     The expiration time of the cache in UTC
      --files-from stringArray             Read list of source-file names from file, ignores blank and comment line
      --files-from-raw stringArray         Read list of source-file names from file without any processing of lines
      --filter stringArray                 A file-filtering rule
      --filter-from stringArray            Read file filtering rules from a file
  -f, --force                              Operate silently without asking user to confirm the operation
      --ignore-existing                    Skip all files that already exist on destination
      --include stringArray                Don't exclude files matching pattern
      --include-from stringArray           Read include patterns from file
  -j, --job int                            Amount of concurrency tasks between multi-files (default 3)
      --list-objects                       Use ListObjects instead of ListObjectsV2 to list objects
      --max-age Duration                   Don't transfer any file older than this, in s or suffix ms|s|m|h|d|w|M|y (default off)
      --max-mtime Time                     Don't transfer any file younger than this, UTC time format (default off)
      --max-size SizeSuffix                Don't transfer any file larger than size, in B or suffix B|K|M|G|T|P, 1K(KiB)=1024B
      --metadata strings                   Specifies the object's user metadata, in key=value foramt
      --metadata-directive string          The method that is used to configure the metadata of the destination object, valid value(s): "COPY","REPLACE"
      --metadata-exclude stringArray       Exclude metadata matching pattern
      --metadata-filter stringArray        A metadata-filtering rule
      --metadata-filter-from stringArray   Read metadata filtering rules from a file
      --metadata-include stringArray       Don't exclude metadata matching pattern
      --min-age Duration                   Don't transfer any file younger than this, in s or suffix ms|s|m|h|d|w|M|y (default off)
      --min-mtime Time                     Don't transfer any file older than this, UTC time format (default off)
      --min-size SizeSuffix                Don't transfer any file smaller than size, in B or suffix B|K|M|G|T|P, 1K(KiB)=1024B
      --no-error-report                    Don't generate error report file during batch operation
      --no-progress                        The progress is not displayed
      --output-dir string                  Specifies the directory to place output file in, output file contains: error report file generated during batch operation (default "ossutil_output")
      --page-size int                      The number of results to return in each response to a list operation (default 1000), in the range 1 - 1000
      --parallel int                       Amount of concurrency tasks when work with a file
      --part-size SizeSuffix               The part size, calculated the suitable size according to file size by default, or use suffix B|K|M|G|T|P, in the range 100Ki - 5Gi
  -r, --recursive                          Operate recursively, if the option is specified, the command will operate on all match objects under the bucket, else operate on the single object.
      --request-payer string               The payer of the request. set this value if you want pay for requester, valid value(s): "requester"
      --size-only                          Only copy the source file with different size
      --start-after string                 The name of the object from which the list operation starts, not include
      --storage-class string               The storage class of the object, valid value(s): "Standard","IA","Archive","ColdArchive","DeepColdArchive"
      --tagging strings                    Specifies the tag of the destination object, in key=value foramt
      --tagging-directive string           The method that is used to configure tags for the destination object, valid value(s): "COPY","REPLACE"
  -u, --update                             Only copy when the source file is newer than the destination file

Global Flags:
  -i, --access-key-id string        AccessKeyID while access oss
  -k, --access-key-secret string    AccessKeySecret while access oss
      --addressing-style string     The style in which to address endpoints (default "virtual"), valid value(s): "virtual","path","cname"
      --cloudbox-id string          The Id of the cloud box. It is applicable to cloud box scenarios
  -c, --config-file string          The path of the configuration file (default "~/.ossutilconfig")
      --connect-timeout int         The client connection timed out, the unit is: s (default 10)
  -n, --dry-run                     Do a trial run with no permanent changes
  -e, --endpoint string             The domain names that other services can use to access OSS.
  -h, --help                        help for the command
      --language string             The display text language
      --log-file string             Specifies the log output file. When -, outputs to Stdout
      --loglevel string             The debug message level (default "off"), valid value(s): "off","info","debug"
      --mode string                 Specifies the authentication mode, valid value(s): "AK","StsToken","EcsRamRole","Anonymous"
      --output-format string        The formatting style for command output (default "raw")
      --output-properties strings   The properties of output format
      --output-query string         A JMESPath query to use in filtering the response data
      --profile string              Specific profile from your config file.
      --proxy string                Specifies the proxy server. When 'env', use HTTP_PROXY and HTTPS_PROXY environment variables
  -q, --quiet                       Quiet mode, print as little stuff as possible
      --read-timeout int            The client read timed out, the unit is: s (default 20)
      --region string               The region in which the bucket is located.
      --retry-times int             Retry times when fail (default 10)
      --role-arn string             Specifies the ARN of role
      --role-session-name string    Specifies the session name
      --sign-version string         The version of the signature algorithm (default "v4"), valid value(s): "v1","v4"
      --skip-verify-cert            Specifies that the oss server's digital certificate file will not be verified
  -t, --sts-token string            STSToken while access oss
```

#### **使用命令行选项**

在命令行操作中，部分命令需要附加参数以指定操作对象或设置选项，而其他命令则不需要参数。对于带参数的命令，您可以根据具体要求提供适当的参数值，以实现预期的功能，例如，带参数的命令如：

```
HELPCODEESCAPE-plaintext
ossutil ls --profile dev
```

`ossutil ls --profile dev`允许用户通过参数值`dev`指定特定的配置文件。带参数的选项通常需要通过空格或等号（=）将选项名称与参数值分隔，例如`--profile dev`或`--profile=dev`。当参数值包含空格时，必须使用双引号将整个参数值括起来，以确保命令正确解析，例如 `--description "OSS bucket list"`。  

#### **支持的全局命令行选项**

<table> <thead> <tr> <td><p>参数</p></td> <td><p>类型</p></td> <td><p>说明</p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p>-i, --access-key-id</p></td> <td><p>string</p></td> <td><p>访问OSS使用的AccessKey ID。</p></td> </tr> <tr> <td><p>-k, --access-key-secret</p></td> <td><p>string</p></td> <td><p>访问OSS使用的AccessKey Secret。</p></td> </tr> <tr> <td><p>--addressing-style</p></td> <td><p>string</p></td> <td><p>请求地址的格式。取值范围如下：</p> <ul> <li><p>virtual（默认值），表示虚拟托管模式。</p></li> <li><p>path，表示路径模式。</p></li> <li><p>cname，表示自定义域名模式。</p></li> </ul></td> </tr> <tr> <td><p>-c, --config-file</p></td> <td><p>string</p></td> <td><p>配置文件的路径。 默认值为<code>\~\\\\.ossutilconfig</code>。</p></td> </tr> <tr> <td><p>--connect-timeout</p></td> <td><p>int</p></td> <td><p>客户端连接超时的时间。单位为秒，默认值为10。</p></td> </tr> <tr> <td><p>-n, --dry-run</p></td> <td><p>/</p></td> <td><p>在不进行任何更改的情况下执行试运行。</p></td> </tr> <tr> <td><p>-e, --endpoint</p></td> <td><p>string</p></td> <td><p>对外服务的访问域名。</p></td> </tr> <tr> <td><p>-h, --help</p></td> <td><p>/</p></td> <td><p>显示帮助信息。</p></td> </tr> <tr> <td><p>--language</p></td> <td><p>string</p></td> <td><p>显示的语言。</p></td> </tr> <tr> <td><p>--loglevel</p></td> <td><p>string</p></td> <td><p>日志级别。取值范围如下：</p> <ul> <li><p>off（默认值）</p></li> <li><p>info</p></li> <li><p>debug</p></li> </ul></td> </tr> <tr> <td><p>--mode</p></td> <td><p>string</p></td> <td><p>鉴权模式。取值：</p> <ul> <li><p>AK，表示访问密钥。</p></li> <li><p>StsToken，表示临时安全凭证。</p></li> <li><p>EcsRamRole，表示使用ECS实例角色（RAM Role）进行鉴权。</p></li> <li><p>Anonymous，表示匿名访问。</p></li> </ul></td> </tr> <tr> <td><p>--output-format</p></td> <td><p>string</p></td> <td><p>输出格式，默认值为raw。</p></td> </tr> <tr> <td><p>--output-query</p></td> <td><p>string</p></td> <td><p>JMESPath查询条件。</p></td> </tr> <tr> <td><p>--profile</p></td> <td><p>string</p></td> <td><p>指定配置文件里的profile。</p></td> </tr> <tr> <td><p>-q,\&nbsp;--quiet</p></td> <td><p>/</p></td> <td><p>安静模式，打印尽可能少的信息。</p></td> </tr> <tr> <td><p>--read-timeout</p></td> <td><p>int</p></td> <td><p>客户端读写请求超时时间。单位为秒，默认值为20。</p></td> </tr> <tr> <td><p>--region</p></td> <td><p>string</p></td> <td><p>数据中心所在的地域，配置值可设置为cn-hangzhou。</p></td> </tr> <tr> <td><p>--retry-times</p></td> <td><p>int</p></td> <td><p>当错误发生时的重试次数。默认值为10。</p></td> </tr> <tr> <td><p>--sign-version</p></td> <td><p>string</p></td> <td><p>请求使用的签名算法版本。取值：</p> <ul> <li><p>v1</p></li> <li><p>v4（默认值）</p></li> </ul></td> </tr> <tr> <td><p>--skip-verify-cert</p></td> <td><p>/</p></td> <td><p>表示不校验服务端的数字证书。</p></td> </tr> <tr> <td><p>-t, --sts-token</p></td> <td><p>string</p></td> <td><p>访问OSS使用的STS Token。</p></td> </tr> <tr> <td><p>--proxy</p></td> <td><p>string</p></td> <td><p>指定代理服务器，</p><p>配置值可以为以下几种：</p> <ul> <li><p>直接配置：可以直接指定代理服务器的详细信息，例如：</p> <ul> <li><p><code>http://proxy.example.com:8080</code></p></li> <li><p><code>https://proxy.example.com:8443</code></p></li> </ul></li> <li><p><code>env</code>：表示使用环境变量\&nbsp;<code>HTTP_PROXY</code>\&nbsp;和\&nbsp;<code>HTTPS_PROXY</code>\&nbsp;来获取代理服务器信息。用户需要在操作系统中配置这两个环境变量，例如：</p> <ul> <li><p><code>HTTP_PROXY=http://proxy.example.com:8080</code></p></li> <li><p><code>HTTPS_PROXY=https://proxy.example.com:8443</code></p></li> </ul><p>配置这些环境变量后，将代理服务器选项的值设置为\&nbsp;<code>env</code>，系统将自动使用这些环境变量中的代理设置。</p></li> </ul></td> </tr> <tr> <td><p>--log-file</p></td> <td><p>string</p></td> <td><p>指定日志输出文件，配置值为：</p> <ul> <li><p><code>-</code>：表示将日志输出到标准输出（Stdout）。</p></li> <li><p><code>文件路径</code>：指定一个具体的文件路径，将日志输出到该文件。</p></li> </ul><p>如果未指定日志输出文件，输出到默认配置文件上。</p></td> </tr> <tr> <td><p>--cloudbox-id\&nbsp;</p></td> <td><p>string</p></td> <td><p>云盒ID，应用于云盒场景</p></td> </tr> </tbody> </table>

### 命令选项类型

<table> <thead> <tr> <td><p>选项类型</p></td> <td><p>选项</p></td> <td><p>说明</p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p>字符串</p></td> <td><p>--option string</p></td> <td> <ul> <li><p>字符串参数可以包含ASCII字符集中的字母及数字字符、符号和空格。</p></li> <li><p>如果字符串中包含空格，需要使用引号包括。</p></li> </ul><p>例如：--acl private。</p></td> </tr> <tr> <td><p>布尔值</p></td> <td><p>--option</p></td> <td><p>打开或关闭某一选项。</p><p>例如：--dry-run。</p></td> </tr> <tr> <td><p>整数</p></td> <td><p>--option Int</p></td> <td><p>无符号整数。</p><p>例如：--read-timeout 10。</p></td> </tr> <tr> <td><p>时间戳</p></td> <td><p>--option Time</p></td> <td><p>ISO 8601格式，即DateTime或Date。</p><p>例如：--max-mtime 2006-01-02T15:04:05。</p></td> </tr> <tr> <td><p>字节单位后缀</p></td> <td><p>--option SizeSuffix</p></td> <td><p>默认单位是字节（B），也可以使用单位后缀形式，支持的单位后缀为：K（KiB）=1024字节、M（MiB）、G（GiB）、G（GiB）、T（TiB）、P（PiB）、E（EiB）</p><p>例如：最小size为1024字节</p><p>--min-size 1024</p><p>--min-size 1K</p></td> </tr> <tr> <td><p>时间单位后缀</p></td> <td><p>--option Duration</p></td> <td><p>时间单位，默认单位是秒。支持的单位后缀为：ms 毫秒，s 秒，m 分钟，h 小时，d 天，w 星期，M 月，y 年。</p><p>支持小数。例如：1.5天</p><p>--min-age 1.5d</p></td> </tr> <tr> <td><p>字符串列表</p></td> <td><p>--option strings</p></td> <td><p>支持单个或者多个同名选项，支持以逗号（,）分隔的多个值。</p><p>支持多选项输入的单值。</p><p>例如：--metadata user=jack,email=ja\*\*@test.com --metadata\&nbsp;address=china</p></td> </tr> <tr> <td><p>字符串数组</p></td> <td><p>--option stringArray</p></td> <td><p>支持单个或者多个同名选项，只支持多选项输入的单值。</p><p>例如 ：--include \*.jpg --include \*.txt。</p></td> </tr> </tbody> </table>

### 从非命令行中加载数据

一般情况下，参数的值都放在命令行里，当参数值比较复杂时，需要从文件加载参数值；当需要串联多个命令操作时，需要标准输中加载参数值。所以，对需要支持多种加载参数值的参数，做了如下约定：

* 以`file://`开始的，表示从文件路径中加载。

* 当参数值为`-`时，表示从标准输入中加载。

例如， 设置存储空间的跨域设置，以JSON参数格式为例，通过文件方式加载跨域参数。cors-configuration.json文件如下：

```
HELPCODEESCAPE-json
{
  "CORSRule": {
    "AllowedOrigin": ["www.aliyun.com"],
    "AllowedMethod": ["PUT","GET"],
    "MaxAgeSeconds": 10000
  }
}
```

```
HELPCODEESCAPE-plaintext
aliyun ossutil api put-bucket-cors --bucket examplebucket --cors-configuration file://cors-configuration.json
```

通过选项参数值加载跨域参数，cors-configuration.json的紧凑形式如下：

```
HELPCODEESCAPE-json
{"CORSRule":{"AllowedOrigin":["www.aliyun.com"],"AllowedMethod":["PUT","GET"],"MaxAgeSeconds":10000}}
```

```
HELPCODEESCAPE-plaintext
aliyun ossutil api put-bucket-cors --bucket examplebucket --cors-configuration  "{\"CORSRule\":{\"AllowedOrigin\":[\"www.aliyun.com\"],\"AllowedMethod\":[\"PUT\",\"GET\"],\"MaxAgeSeconds\":10000}}"
```

从标准输入加载参数的示例如下：

```
HELPCODEESCAPE-bash
cat cors-configuration.json | aliyun ossutil api put-bucket-cors --bucket examplebucket --cors-configuration -
```

### 控制命令输出

#### **输出格式**

对ossutil api下的子命令，以及du、stat、ls命令，支持通过`--output-format`参数调整其输出格式，当前支持的格式如下：
<table> <thead> <tr> <td><p><b>格式名称</b></p></td> <td><p><b>说明</b></p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p>raw</p></td> <td><p>以原始方式输出，即服务端返回什么内容，则输出什么内容。</p></td> </tr> <tr> <td><p>json</p></td> <td><p>输出采用JSON字符串的格式。</p></td> </tr> <tr> <td><p>yaml</p></td> <td><p>输出采用YAML字符串的格式。</p></td> </tr> </tbody> </table>

例如：以`get-bucket-cors`为例，原始内容如下：

```
HELPCODEESCAPE-plaintext
aliyun ossutil api get-bucket-cors --bucket bucketexample
<?xml version="1.0" encoding="UTF-8"?>
<CORSConfiguration>
  <CORSRule>
    <AllowedOrigin>www.aliyun.com</AllowedOrigin>
    <AllowedMethod>PUT</AllowedMethod>
    <AllowedMethod>GET</AllowedMethod>
    <MaxAgeSeconds>10000</MaxAgeSeconds>
  </CORSRule>
  <ResponseVary>false</ResponseVary>
</CORSConfiguration>
```

转成JSON如下：

```
HELPCODEESCAPE-json
aliyun ossutil api get-bucket-cors --bucket bucketexample --output-format json
{
  "CORSRule": {
    "AllowedMethod": [
      "PUT",
      "GET"
    ],
    "AllowedOrigin": "www.aliyun.com",
    "MaxAgeSeconds": "10000"
  },
  "ResponseVary": "false"
}
```

#### **筛选输出**

ossutil提供了基于JSON的内置客户端筛选功能，通过`--output-query value`选项使用。  
**说明**

该选项仅支持ossutil api下的子命令。

该功能基于JMESPath语法，当使用该功能时，会把返回的内容转成JSON，然后再使用JMESPath进行筛查，最后按照指定的输出格式输出。有关JMESPath 语法的说明，请参见[JMESPath Specification](https://jmespath.org/specification.html#)。

例如：以get-bucket-cors为例，只输出AllowedMethod内容，示例如下：

```
HELPCODEESCAPE-plaintext
aliyun ossutil api get-bucket-cors --bucket bucketexample --output-query CORSRule.AllowedMethod --output-format json
[
  "PUT",
  "GET"
]
```

#### **友好显示**

对于高级命令（du、stat），提供了`--human-readable`选项，对字节、数量数据，提供了以人类可读方式输出信息。即字节数据转成Ki\|Mi\|Gi\|Ti\|Pi后缀格式（1024 base），数量数据转成k\|m\|g\|t\|p后缀格式(1000 base)。

例如：原始模式

```
HELPCODEESCAPE-plaintext
aliyun ossutil stat oss://bucketexample
ACL                         : private
AccessMonitor               : Disabled
ArchiveObjectCount          : 2
ArchiveRealStorage          : 10
ArchiveStorage              : 131072
...
StandardObjectCount         : 119212
StandardStorage             : 66756852803
Storage                     : 66756852813
StorageClass                : Standard
TransferAcceleration        : Disabled
```

友好模式

```
HELPCODEESCAPE-plaintext
aliyun ossutil stat oss://bucketexample --human-readable
ACL                         : private
AccessMonitor               : Disabled
ArchiveObjectCount          : 2
ArchiveRealStorage          : 10
ArchiveStorage              : 131.072k
...
StandardObjectCount         : 119.212k
StandardStorage             : 66.757G
Storage                     : 66.757G
StorageClass                : Standard
TransferAcceleration        : Disabled
```

### 命令返回码

通过进程等方式调用ossutil时，无法实时查看回显信息。ossutil支持在进程运行结束后，根据不同的运行结果生成不同的返回码，具体的返回码及其含如下。您可以通过以下方式获取最近一次运行结果的返回码，然后根据返回码分析并处理问题。

## Linux
执行命令获取返回码：`echo $?`。

## Windows
执行命令获取返回码：`echo %errorlevel%`。

## macOS
执行命令获取返回码：`echo $?`。
<table> <thead> <tr> <td><p><b>返回码</b></p></td> <td><p><b>含义</b></p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p>0</p></td> <td><p>命令操作成功，发送到服务端的请求执行正常，服务端返回200响应。</p></td> </tr> <tr> <td><p>1</p></td> <td><p>参数错误，例如缺少必需的子命令或参数，或使用了未知的命令或参数。</p></td> </tr> <tr> <td><p>2</p></td> <td><p>该命令已成功解析，并已对指定服务发出了请求，但该服务返回了错误（非2xx响应）。</p></td> </tr> <tr> <td><p>3</p></td> <td><p>调用OSS GO SDK时，遇到的非服务端错误。</p></td> </tr> <tr> <td><p>4</p></td> <td><p>批量操作时，例如cp、rm部分请求发生了错误。</p></td> </tr> <tr> <td><p>5</p></td> <td><p>中断错误。命令执行过程中，您通过<code>ctrl</code>+<code>c</code>取消了某个命令。</p></td> </tr> </tbody> </table>

### 操作示例

* 示例1：上传本地文件upload.rar到bucket存储空间中，上传速度为20 MB/s，默认单位为字节每秒（B/s）。

  ```
  HELPCODEESCAPE-sh
  aliyun ossutil cp D:\\upload.rar oss://bucket/ --bandwidth-limit 20971520
  ```

* 示例2：上传本地文件file.rar到bucket存储空间中，上传速度为50 MB/s，指定单位为兆字节每秒（MB/s）。

  ```
  HELPCODEESCAPE-sh
  aliyun ossutil cp D:\\file.rar oss://bucket/dir -r --bandwidth-limit 50M
  ```

* 示例3：将bucket存储空间中的download.rar文件下载到当前目录，并将下载速度限制为20 MB/s。

  ```
  HELPCODEESCAPE-bash
  aliyun ossutil cp oss://bucket/download.rar . --bandwidth-limit 20971520
  ```

## 旧版本
### 命令结构

```
HELPCODEESCAPE-shell
aliyun oss [command] [args...] [options...]
```

### 命令列表

<table> <thead> <tr> <td><p>名称</p></td> <td><p>描述</p></td> </tr> </thead> <colgroup></colgroup> <colgroup></colgroup> <tbody> <tr> <td><p><a href="https://help.aliyun.com/document_detail/600527.html#concept-2295157">access-monitor</a></p></td> <td><p>配置存储空间（Bucket）的访问跟踪状态。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120069.html#concept-303823">appendfromfile</a></p></td> <td><p>用于在已上传的追加类型文件（Appendable Object）末尾直接追加内容。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/304440.html#concept-2107853">bucket-cname</a></p></td> <td><p>查看Bucket的CNAME配置。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120307.html#concept-354612">bucket-encryption</a></p></td> <td><p>添加、修改、查询、删除Bucket的加密配置。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/129733.html#concept-1614438">bucket-policy</a></p></td> <td><p>添加、修改、查询、删除Bucket的Bucket policy配置。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120305.html#concept-354610">bucket-tagging</a></p></td> <td><p>添加、修改、查询、删除Bucket的标签配置。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/121686.html#concept-610185">bucket-versioning</a></p></td> <td><p>添加或查询Bucket的版本控制配置。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120070.html#concept-303824">cat</a></p></td> <td><p>将文件内容输出到ossutil。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120072.html#concept-303826">config</a></p></td> <td><p>创建配置文件来存储OSS访问信息。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120063.html#concept-303816">cors</a></p></td> <td><p>添加、修改、查询、删除Bucket的CORS配置。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/122573.html#concept-744986">cors-options</a></p></td> <td><p>用于测试Bucket是否允许指定的跨域访问请求。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/179376.html#concept-303810">cp</a></p></td> <td><p>用于上传、下载、拷贝文件。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120059.html#concept-303812">create-symlink</a></p></td> <td><p>创建符号链接（软链接）。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/129732.html#concept-1614437">du</a></p></td> <td><p>用于获取指定Bucket、指定Object或文件目录所占的存储空间大小。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120068.html#concept-303821">getallpartsize</a></p></td> <td><p>获取Bucket内所有未完成上传的Multipart任务的每个分片大小以及分片总大小。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120073.html#concept-303827">hash</a></p></td> <td><p>用于计算本地文件的CRC64或MD5。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120071.html#concept-303825">help</a></p></td> <td><p>获取命令的帮助信息。当您不清楚某个命令的用法时，建议您使用<span><b>help</b></span>命令获取该命令的帮助信息。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/163935.html#concept-2483196">inventory</a></p></td> <td><p>命令用于添加、查询、列举、删除Bucket的清单规则。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/122574.html#concept-744987">lifecycle</a></p></td> <td><p>命令用于添加、修改、查询、删除生命周期规则配置。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120067.html#concept-303820">listpart</a></p></td> <td><p>列出没有完成分片上传的Object的分片信息。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120065.html#concept-303818">logging</a></p></td> <td><p>添加、修改、查询、删除Bucket的日志管理配置。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/274438.html#concept-2094023">lrb</a></p></td> <td><p>列举单个或多个地域（Region）下Bucket的基本信息。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120052.html#concept-303804">ls</a></p></td> <td><p>列举Bucket、Object和Part。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120051.html#concept-303803">mb</a></p></td> <td><p>创建Bucket。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120062.html#concept-303815">mkdir</a></p></td> <td><p>在Bucket内创建文件目录。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/129735.html#concept-1614441">object-tagging</a></p></td> <td><p>添加、修改、查询或删除Object的标签配置。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120061.html#concept-303814">probe</a></p></td> <td><p>针对OSS访问的检测命令，可用于排查上传、下载过程中因网络故障或基本参数设置错误导致的问题。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120060.html#concept-303813">read-symlink</a></p></td> <td><p>读取符号链接（软链接）文件的描述信息。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120066.html#concept-303819">referer</a></p></td> <td><p>添加、修改、查询、删除Bucket的防盗链配置。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/295410.html#concept-2102726">replication</a></p></td> <td><p>管理Bucket的跨区域复制规则配置。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/129734.html#concept-1614439">request-payment</a></p></td> <td><p>设置或查询Bucket的请求者付费模式配置。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2357390.html#concept-2348486">resource-group</a></p></td> <td><p>为存储空间（Bucket）配置所属资源组以及获取资源组信息。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120058.html#concept-303811">restore</a></p></td> <td><p>恢复冷冻状态的Object为可读状态。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/171787.html#concept-2541372">revert-versioning</a></p></td> <td><p>将已删除的Object恢复至最近的版本。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120053.html#concept-303805">rm</a></p></td> <td><p>删除Bucket、Object和Part。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120055.html#concept-303807">set-acl</a></p></td> <td><p>设置Bucket或Object的访问权限（ACL）。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120056.html#concept-303809">set-meta</a></p></td> <td><p>设置已上传Object的元数据。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120064.html#concept-303817">sign</a></p></td> <td><p>用于生成经过签名的文件URL，并将签名URL分享给第三方供其下载或预览。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120054.html#concept-303806">stat</a></p></td> <td><p>获取指定Bucket或Object的描述信息。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/2357563.html#concept-2348661">style</a></p></td> <td><p>设置图片样式。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/256351.html#concept-2105804">sync</a></p></td> <td><p>用于同步本地文件到OSS、同步OSS文件到本地、在OSS之间同步文件。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/120074.html#concept-303828">update</a></p></td> <td><p>用于更新ossutil版本。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/122575.html#concept-744988">website</a></p></td> <td><p>用于添加、修改、查询、删除Bucket的静态网站托管配置、重定向配置、镜像回源配置。</p></td> </tr> <tr> <td><p><a href="https://help.aliyun.com/document_detail/202134.html#concept-2036215">worm</a></p></td> <td><p>管理Bucket的合规保留策略。</p></td> </tr> </tbody> </table>

### 命令示例

* 示例1：创建一个命名为`vmeixme`的存储空间（Bucket），并设定Bucket的存储类型为`Standard`。

  ```
  HELPCODEESCAPE-shell
  aliyun oss mb oss://vmeixme --storage-class Standard
  ```

* 示例2：在Bucket内创建一个命名为`horse`的文件目录。

  ```
  HELPCODEESCAPE-shell
  aliyun oss mkdir oss://vmeixme/horse/
  ```

* 示例3：列举您账号下的OSS资源，包括存储空间（Bucket）、对象（Object）和碎片（Part）信息，并设定返回结果的最大个数为20。

  ```
  HELPCODEESCAPE-shell
  aliyun oss ls --limited-num 20
  ```

## 常见问题
如您在使用`ossutil`时发现异常，可参考以下文档进行错误排查。

* [ossutil 1.0常见问题](https://help.aliyun.com/document_detail/101135.html)

* [ossutil 2.0常见问题](https://help.aliyun.com/document_detail/2862160.html)