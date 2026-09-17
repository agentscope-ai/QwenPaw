本文提供一个基于阿里云CLI的操作示例，为您演示如何通过阿里云CLI创建和复制自定义镜像，实现ECS实例的跨地域迁移。该示例仅供参考使用，实际业务场景中可能需要结合多个API灵活组合，具体方案请根据实际需求设计。  

## 方案概览
使用阿里云CLI通过自定义镜像跨地域迁移ECS实例数据，大致可分为以下五个步骤：

1. 创建镜像：为源ECS实例创建自定义镜像，使用该镜像创建的新实例，会包含您已配置的自定义项，省去您重复自定义实例的时间。

2. 复制镜像：复制镜像后，您可以在目标地域获得不同ID的新镜像，其标签、资源组、加密属性等配置以复制镜像时的输入参数为准。

3. 新建实例：使用自定义镜像在目标地域中新建目标ECS实例。

4. 检查实例：检查新创建的目标ECS实例的相关数据情况，确保实例数据迁移后，业务功能仍可流畅运行。

5. 释放资源：迁移完成后，结合自身的实际需求，可以选择释放或删除源ECS实例的相关资源，避免资源持续产生费用。

   ![image](https://help-static-aliyun-doc.aliyuncs.com/assets/img/zh-CN/5946382571/CAEQTxiBgICgsObJjBkiIDViYTQ2M2MwZmUwNTQwMjRiMzlmZWFlYmNhMTFlMjFi4556547_20240730162624.870.svg)

## 注意事项
数据迁移前，请您仔细阅读以下注意事项。

1. 在创建自定义镜像期间，系统会对ECS实例的各个云盘自动创建快照，快照将产生一定的费用。有关快照费用的详细信息，请参见[快照计费](https://help.aliyun.com/document_detail/56159.html#concept-rq2-pcx-ydb)。

2. 部分包含本地盘的实例无法创建快照，此类实例不支持通过本文的操作完成实例的数据迁移。

3. 源ECS实例的网络类型可以是经典网络或专有网络VPC。

4. 新建目标ECS实例时，仅支持创建VPC网络类型的ECS实例。

5. 新建目标ECS实例时，仅支持选择当前可用区下有库存的实例规格。建议您提前自行做好资源所属地域和可用区的规划工作。

6. 由于是通过自定义镜像完成的实例数据迁移操作，因此数据迁移后，新创建的目标ECS实例中云盘数据与源ECS实例中的云盘数据保持一致，但新创建的目标ECS实例的实例元数据会重新生成，与源ECS实例中的实例元数据相比较会发生变化。关于实例元数据的更多信息，请参见[实例元数据](https://help.aliyun.com/document_detail/108460.html)。

   由于实例元数据会发生变化，在实例数据迁移之前，建议您手动排查资源关联关系，并在数据迁移后及时更新资源的关联关系。例如：
   * 集群内部通过私网IP地址互联互通，在进行实例数据迁移后，您需要替换为最新的私网IP地址。

   * 某些应用的许可证（License）与ECS实例的MAC地址绑定，在进行实例数据迁移后，这些许可证将因为ECS实例的MAC地址改变而失效，您需要重新绑定最新的MAC地址。

7. 如果您要保持公网IP地址不变，且源ECS实例使用的是固定公网IP，可以先将公网IP转换为弹性公网IP（EIP）以保留该公网IP，然后解绑EIP，最后绑定到迁移后的ECS实例上。具体操作，请参见[固定公网IP转为弹性公网IP](https://help.aliyun.com/document_detail/61290.html)和[弹性公网IP](https://help.aliyun.com/document_detail/417420.html)。

   **说明**

   如果源ECS实例使用的是弹性公网IP（EIP），迁移后，源ECS实例先解绑EIP，然后绑定到迁移后的ECS实例上。具体操作，请参见[弹性公网IP](https://help.aliyun.com/document_detail/417420.html)。
8. 本地SSD型实例规格不支持创建包含系统盘和数据盘的镜像。更多信息，请参见[本地SSD型实例规格族介绍](https://help.aliyun.com/document_detail/108494.html#section-pd1-127-5jp)。

## 操作步骤
### 步骤一：为源ECS实例创建自定义镜像

通过实例创建自定义镜像前，您需要了解相关注意事项。更多信息，请参见[使用实例创建自定义镜像](https://help.aliyun.com/document_detail/35109.html#section-3wg-n7r-23g)。  
**说明**

为保证数据完整性，建议您停止实例后再进行创建镜像的操作。

1. 执行以下命令，调用[CreateImage](https://help.aliyun.com/document_detail/2679792.html)接口创建源ECS实例的自定义镜像。

   ```
   HELPCODEESCAPE-shell
   aliyun ecs CreateImage \
     --RegionId 'cn-hangzhou' \
     --ImageName Created_from_hangzhouECS \
     --InstanceId 'i-bp1g6zv0ce8oghu7****' \
   ```

2. 系统返回类似如下结果示例。

   ```
   HELPCODEESCAPE-json
   {
     "ImageId": "m-bp146shijn7hujku****",
     "RequestId": "C8B26B44-0189-443E-9816-*******"
   }
   ```

3. 执行以下命令，调用[DescribeImages](https://help.aliyun.com/document_detail/2679797.html)接口查询自定义镜像创建状态。确认镜像状态变更为`Available`后执行下一步骤。

   ```
   HELPCODEESCAPE-shell
   aliyun ecs DescribeImages \
     --RegionId 'cn-hangzhou' \
     --ImageId 'm-bp146shijn7hujku****' \
     --Status 'Creating,Available' \
     --output cols='ImageId,Status' rows='Images.Image[]' \
     --waiter expr='Images.Image[0].Status' to='Available'
   ```

### 步骤二：跨地域复制镜像

将源ECS实例的数据跨地域迁移至新创建的目标ECS实例，需要先通过复制镜像功能将自定义镜像复制到其他地域。

1. 执行以下命令，调用[CopyImage](https://help.aliyun.com/document_detail/2679795.html)接口从`cn-hangzhou`复制源ECS实例的自定义镜像到`cn-beijing`。

   ```
   HELPCODEESCAPE-shell
   aliyun ecs CopyImage \
     --RegionId 'cn-hangzhou' \
     --DestinationImageName Copy_from_hangzhouImage \
     --ImageId 'm-bp146shijn7hujku****' \
     --DestinationRegionId 'cn-beijing' \
   ```

2. 返回结果示例。

   ```
   HELPCODEESCAPE-json
   {
     "ImageId": "m-bp1h46wfpjsjastd****",
     "RequestId": "473469C7-AA6F-4DC5-B3DB-A3DC0DE3C83E"
   }
   ```

3. 执行以下命令，调用[DescribeImages](https://help.aliyun.com/document_detail/2679797.html)接口查询复制镜像创建状态。确认镜像状态变更为`Available`后执行下一步骤。

   ```
   HELPCODEESCAPE-shell
   aliyun ecs DescribeImages \
     --RegionId 'cn-beijing' \
     --ImageId 'm-bp1h46wfpjsjastd****' \
     --Status 'Creating,Available' \
     --output cols='ImageId,Status' rows='Images.Image[]' \
     --waiter expr='Images.Image[0].Status' to='Available'
   ```

### 步骤三：使用自定义镜像新建目标ECS实例

1. 执行以下命令，调用[RunInstances](https://help.aliyun.com/document_detail/2679677.html)接口根据自定义镜像在目标地域创建ECS实例。

   **说明**
   * 示例命令中`PasswordInherit`选项设置为`true`，执行命令创建实例时将使用镜像预设的密码。使用镜像预设密码后，新创建的目标ECS实例登录密码与源ECS实例的登录密码一致。

   * 您可根据需求自行选择符合的实例规格，更多参数信息，请参见[自定义购买实例](https://help.aliyun.com/document_detail/87190.html)。

   ```
   HELPCODEESCAPE-shell
   aliyun ecs RunInstances \
     --RegionId 'cn-beijing' \
     --SecurityGroupId 'sg-2zea9dbddva****' \
     --VSwitchId 'vsw-2zep7vc25mjc1****' \
     --ImageId 'm-bp1h46wfpjsjastd****' \
     --InstanceType 'ecs.e-c1m1.large' \
     --InstanceName Copy_from_hangzhouECS \
     --PasswordInherit true \
     --InternetChargeType PayByTraffic \
     --SystemDisk.Size 40 \
     --SystemDisk.Category cloud_essd \
     --InstanceChargeType PostPaid \
     --InternetMaxBandwidthOut 10
   ```

2. 返回结果示例：

   ```
   HELPCODEESCAPE-json
   {
     "RequestId": "473469C7-AA6F-4DC5-B3DB-A3DC0DE3****",
     "InstanceIdSets": {
       "InstanceIdSet": [
         "i-bp67acfmxazb4pd2****"
       ]
     }
   }
   ```

### 步骤四：检查目标ECS实例内数据

目标ECS实例创建后，您需要检查实例内部相关数据情况，以确保实例数据迁移后，业务功能仍可流畅运行。例如：

* 检查云盘数据：远程连接新创建的目标ECS实例，检查系统盘数据是否与源ECS实例一致，例如比较文件和目录结构是否一致。如果源ECS实例存在数据盘并在目标ECS实例上挂载了相应的云盘，您可以检查数据盘上的数据是否与源ECS实例一致。

* 运行应用程序或服务：如果您的源ECS实例上运行了特定的应用程序或服务，您可以尝试在目标ECS实例上运行相同的应用程序或服务，并验证其功能和数据操作是否与源ECS实例一致。

* 对比资源信息变化：

  * 您可以执行以下命令，调用[DescribeInstances](https://help.aliyun.com/document_detail/2679689.html)，对比源ECS实例与新创建的目标ECS实例相关的资源信息变化，例如镜像信息、网络配置等。

    ```
    HELPCODEESCAPE-shell
    aliyun ecs DescribeInstances --RegionId 'cn-beijing' --InstanceIds '["i-bp67acfmxazb4pd2****"]'
    ```

* 更新资源的关联关系：新创建的目标ECS实例的实例元数据会重新生成，与源ECS实例中的实例元数据相比会发生变化。您需要在数据迁移后及时更新资源的关联关系。更多信息，请参见[实例元数据](https://help.aliyun.com/document_detail/108460.html#concept-dwj-y1x-wgb)。

### 步骤五：释放或删除源ECS实例及相关资源

在您仔细检查新创建的目标ECS实例与源ECS实例数据没有差异，且完成了资源关联关系的更新，确保新创建的目标ECS实例内业务可以流畅运行后，结合自身的实际需求，可以选择释放或删除源ECS实例的相关资源，避免资源持续产生费用。相关操作说明如下：  
**警告**

释放实例、删除镜像以及删除快照的操作为单向操作，一旦操作完成，资源内的数据不可恢复。请确保您已完成所有业务数据的迁移再执行释放或删除资源的操作。

* 您可执行以下命令，调用[DeleteInstance](https://help.aliyun.com/document_detail/2679709.html)接口释放源ECS实例。更多信息，请参见[释放实例](https://help.aliyun.com/document_detail/25442.html#concept-jfp-wbf-5db)。

  ```
  HELPCODEESCAPE-shell
  aliyun ecs DeleteInstance --InstanceId i-bp67acfmxazb4pd2****
  ```

* 您可执行以下命令，调用[DeleteImage](https://help.aliyun.com/document_detail/2679804.html)接口删除创建的自定义镜像。更多信息，请参见[删除自定义镜像](https://help.aliyun.com/document_detail/25466.html#concept-azs-5bt-xdb)。

  **重要**

  删除自定义镜像后，使用该镜像创建的ECS实例将无法初始化系统盘。如果您的自定义镜像为免费镜像，且您需要保留该镜像以供后续使用，建议无需删除该自定义镜像。有关镜像计费的详细信息，请参见[镜像计费](https://help.aliyun.com/document_detail/179021.html#concept-1937441)。

  ```
  HELPCODEESCAPE-shell
  aliyun ecs DeleteImage --RegionId 'cn-hangzhou' --ImageId 'm-bp146shijn7hujku****'
  ```

* 您可执行以下命令，调用[DeleteInstance](https://help.aliyun.com/document_detail/2679709.html)接口删除指定的快照。更多信息，请参见[删除快照](https://help.aliyun.com/document_detail/128131.html#task-1478465)。

  ```
  HELPCODEESCAPE-shell
  aliyun ecs DeleteSnapshot --SnapshotId 's-bp1c0doj0taqyzzl****'
  ```

## 脚本示例
阿里云CLI可在命令行脚本中使用，以下简单示例供您参考，您可以在此基础上自行实现异常处理、资源清理等高级功能。  
**说明**

运行Bash脚本示例需自行安装jq工具。  
**示例**  
Bash  

```
HELPCODEESCAPE-bash
#!/usr/bin/env bash

# 源实例ID
SRC_INSTANCE_ID="i-bp1g6zv0ce8oghu7****"
# 源实例所属地域ID
SRC_REGION_ID="cn-hangzhou"
# 迁移目标地域ID
DST_REGION_ID="cn-beijing"
# 目标实例所属可用区ID
DST_ZONE_ID="cn-beijing-h"
# 源实例规格
SRC_INSTANCE_TYPE="ecs.e-c1m1.large"
# 源实例系统盘类型
SRC_SYSTEM_DISK_CATEGORY="cloud_auto"
# 源实例系统盘大小
SRC_SYSTEM_DISK_SIZE=40

# 输出日志
function log {
  local level="$1"
  local message="$2"
  echo "$(date +'%Y-%m-%d %H:%M:%S') [$level] $message"
}

# 封装阿里云CLI
function invoke_aliyun_command() {
  local service="$1"
  local action="$2"
  shift 2
  local -a params=("$@")
  response=$(aliyun "$service" "$action" "${params[@]}")
  exit_code=$?
  if [ $exit_code -eq 0 ]; then return 0; fi
  log "ERROR" "Failed to invoke aliyun command: aliyun $service $action ${params[*]}"
  exit 1
}

# 等待资源可用
function wait_resource_available() {
  local service="$1"
  local action="$2"
  local region_id="$3"
  local resource_type="$4"
  local resource_id="$5"

  local -a params=(
    "--region" "$region_id"
    "--RegionId" "$region_id"
    "--${resource_type}Id" "$resource_id"
  )

  if [ "$resource_type" == "Image" ]; then
    params+=("--Status" "Creating,Waiting,Available")
  fi

  local current_status
  local current_progress

  local timeout=1200
  local interval=20
  local end_time=$(( $(date +%s) + timeout ))

  while (( $(date +%s) < end_time )); do
    invoke_aliyun_command "$service" "$action" "${params[@]}"
    current_status=$(echo "$response" | jq -r '.. | .Status? // empty' | head -n1)
    current_progress=$(echo "$response" | jq -r '.. | .Progress? // empty' | head -n1)

    log "INFO" "${resource_type} status: $current_status"
    if [[ -n "$current_progress" ]]; then
        log "INFO" "Creation progress: $current_progress"
    fi
    if [[ "$current_status" == "Available" ]]; then return 0; fi
    sleep "$interval"
  done
}

# 创建镜像
log "INFO" "Creating source image from instance '$SRC_INSTANCE_ID'"
src_img_params=(
  "--region" "$SRC_REGION_ID"
  "--RegionId" "$SRC_REGION_ID"
  "--InstanceId" "$SRC_INSTANCE_ID"
  "--ImageName" "cli-src-img"
)
invoke_aliyun_command ecs CreateImage "${src_img_params[@]}"
src_img_id=$(echo "$response" | jq -r .ImageId)
wait_resource_available ecs DescribeImages "$SRC_REGION_ID" "Image" "$src_img_id"
log "INFO" "Source image created: '$src_img_id'"

# 复制镜像到目标区域
log "INFO" "Copying image to region: '$DST_REGION_ID'"
dst_img_params=(
  "--region" "$SRC_REGION_ID"
  "--RegionId" "$SRC_REGION_ID"
  "--DestinationRegionId" "$DST_REGION_ID"
  "--ImageId" "$src_img_id"
  "--DestinationImageName" "cli-dst-img"
)
invoke_aliyun_command ecs CopyImage "${dst_img_params[@]}"
dst_img_id=$(echo "$response" | jq -r .ImageId)
wait_resource_available ecs DescribeImages "$DST_REGION_ID" "Image" "$dst_img_id"
log "INFO" "Destination image copied: '$dst_img_id'"

# 创建 VPC
log "INFO" "Creating VPC"
dst_vpc_params=(
  "--region" "$DST_REGION_ID"
  "--RegionId" "$DST_REGION_ID"
  "--CidrBlock" "10.0.0.0/8"
  "--VpcName" "cli-dst-vpc"
)
invoke_aliyun_command ecs CreateVpc "${dst_vpc_params[@]}"
dst_vpc_id=$(echo "$response" | jq -r .VpcId)
wait_resource_available "Vpc" "DescribeVpcAttribute" "$DST_REGION_ID" "Vpc" "$dst_vpc_id"
log "INFO" "VPC created: '$dst_vpc_id'"

# 创建交换机
log "INFO" "Creating VSwitch"
dst_vsw_params=(
  "--region" "$DST_REGION_ID"
  "--RegionId" "$DST_REGION_ID"
  "--ZoneId" "$DST_ZONE_ID"
  "--VpcId" "$dst_vpc_id"
  "--CidrBlock" "10.1.1.0/24"
)
invoke_aliyun_command vpc CreateVSwitch "${dst_vsw_params[@]}"
dst_vsw_id=$(echo "$response" | jq -r .VSwitchId)
wait_resource_available "vpc" "DescribeVSwitchAttributes" "$DST_REGION_ID" "VSwitch" "$dst_vsw_id"
log "INFO" "VSwitch created: '$dst_vsw_id'"

# 创建安全组
log "INFO" "Creating security group"
dst_sg_params=(
  "--region" "$DST_REGION_ID"
  "--RegionId" "$DST_REGION_ID"
  "--SecurityGroupName" "cli-dst-sg"
  "--VpcId" "$dst_vpc_id"
  "--SecurityGroupType" "normal"
)
invoke_aliyun_command ecs CreateSecurityGroup "${dst_sg_params[@]}"
dst_sg_id=$(echo "$response" | jq -r .SecurityGroupId)
log "INFO" "Security group created: '$dst_sg_id'"

# 在目标地域创建一个按量付费ECS实例
log "INFO" "Creating ECS instance in zone: '$DST_ZONE_ID'"
dst_instance_params=(
  "--region" "$DST_REGION_ID"
  "--RegionId" "$DST_REGION_ID"
  "--ImageId" "$dst_img_id"
  "--SecurityGroupId" "$dst_sg_id"
  "--VSwitchId" "$dst_vsw_id"
  "--InstanceType" "$SRC_INSTANCE_TYPE"
  "--InstanceName" "cli-dst-ecs"
  "--PasswordInherit" "true"
  "--SystemDisk.Category" "$SRC_SYSTEM_DISK_CATEGORY"
  "--SystemDisk.Size" "$SRC_SYSTEM_DISK_SIZE"
  "--InstanceChargeType" "PostPaid"
)
invoke_aliyun_command ecs RunInstances "${dst_instance_params[@]}"
dst_instance_id=$(echo "$response" | jq -r '.InstanceIdSets.InstanceIdSet[0]')
log "INFO" "ECS instance created: '$dst_instance_id'"
```

PowerShell  

```
HELPCODEESCAPE-powershell
# 设置错误退出策略
$ErrorActionPreference = "Stop"

# 设置字符编码
chcp 65001 | Out-Null
[System.Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 源实例ID
$SRC_INSTANCE_ID = "i-bp1g6zv0ce8oghu7****"
# 源实例所属地域ID
$SRC_REGION_ID = "cn-hangzhou"
# 迁移目标地域ID
$DST_REGION_ID = "cn-beijing"
# 目标实例所属可用区ID
$DST_ZONE_ID = "cn-beijing-h"
# 源实例规格
$SRC_INSTANCE_TYPE = "ecs.e-c1m1.large"
# 源实例系统盘类型
$SRC_SYSTEM_DISK_CATEGORY = "cloud_auto"
# 源实例系统盘大小
$SRC_SYSTEM_DISK_SIZE = 40

# 输出日志
function Log {
    param ([string]$Level, [string]$Message)
    Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [$Level] $Message"
}

# 封装阿里云CLI
function Invoke-AliyunCommand {
    param ([string]$Service, [string]$Action, [array]$Params)
    $response = aliyun $Service $Action $Params
    if ($LASTEXITCODE -eq 0) { return $response | ConvertFrom-Json }
    Log "ERROR" "Failed to call aliyun command: aliyun $Service $Action $Params"
    exit 1
}

# 获取嵌套属性值
function Get-NestedPropertyValue {
    param (
        [object]$Object,
        [string]$PropertyPath
    )
    $parts = $PropertyPath -split '\.'
    $value = $Object

    foreach ($part in $parts) {
        $value = $value.$part
    }
    return $value
}

# 等待资源可用
function Wait-ResourceAvailable {
    param (
        [string]$Service,
        [string]$Action,
        [object]$Params,
        [string]$StatusPath,
        [string]$ProgressPath
    )
    $timeout = 1200
    $interval = 20
    $endTime = (Get-Date).AddSeconds($timeout)
    while ((Get-Date) -lt $endTime) {
        $response = Invoke-AliyunCommand $Service $Action $Params
        $currentStatus = Get-NestedPropertyValue $response $StatusPath
        Log "INFO" "Resource status: $currentStatus"
        if ($ProgressPath) {
            $currentProgress = Get-NestedPropertyValue $response $ProgressPath
            Log "INFO" "Creation progress: $currentProgress"
        }
        if ("Available" -eq $currentStatus) { return }
        Start-Sleep -Seconds $interval
    }
}

# 创建镜像
Log "INFO" "Creating source image from instance '$SRC_INSTANCE_ID'"
$srcImgId = (Invoke-AliyunCommand -Service "ecs" -Action "CreateImage" -Params @(
    "--region", $SRC_REGION_ID,
    "--RegionId", $SRC_REGION_ID,
    "--InstanceId", $SRC_INSTANCE_ID,
    "--ImageName", "cli-src-img"
)).ImageId
Wait-ResourceAvailable -Service "ecs" -Action "DescribeImages" -Params @(
    "--region", $SRC_REGION_ID,
    "--RegionId", $SRC_REGION_ID,
    "--ImageId", $srcImgId,
    "--Status", "Creating,Waiting,Available"
) -StatusPath "Images.Image.Status" -ProgressPath "Images.Image.Progress"
Log "INFO" "Source image created: '$srcImgId'"

# 复制镜像到目标区域
Log "INFO" "Copying image to region: '$DST_REGION_ID'"
$dstImgId = (Invoke-AliyunCommand -Service "ecs" -Action "CopyImage" -Params @(
    "--region", $SRC_REGION_ID,
    "--RegionId", $SRC_REGION_ID,
    "--DestinationRegionId", $DST_REGION_ID,
    "--ImageId", $srcImgId,
    "--DestinationImageName", "cli-dst-img"
)).ImageId
Wait-ResourceAvailable -Service "ecs" -Action "DescribeImages" -Params @(
    "--region", $DST_REGION_ID,
    "--RegionId", $DST_REGION_ID,
    "--ImageId", $dstImgId,
    "--Status", "Creating,Waiting,Available"
) -StatusPath "Images.Image.Status" -ProgressPath "Images.Image.Progress"
Log "INFO" "Destination image copied: '$dstImgId'"

# 创建 VPC
Log "INFO" "Creating VPC"
$dstVpcId = (Invoke-AliyunCommand -Service "vpc" -Action "CreateVpc" -Params @(
    "--region", $DST_REGION_ID,
    "--RegionId", $DST_REGION_ID,
    "--CidrBlock", "10.0.0.0/8",
    "--VpcName", "cli-dst-vpc"
)).VpcId
Wait-ResourceAvailable -Service "Vpc" -Action "DescribeVpcAttribute" -Params @(
    "--region", $DST_REGION_ID,
    "--RegionId", $DST_REGION_ID,
    "--VpcId", $dstVpcId
) -StatusPath "Status"
Log "INFO" "VPC created: '$dstVpcId'"

# 创建交换机
Log "INFO" "Creating VSwitch"
$dstVSwitchId = (Invoke-AliyunCommand vpc CreateVSwitch @(
    "--region", $DST_REGION_ID,
    "--RegionId", $DST_REGION_ID,
    "--ZoneId", $DST_ZONE_ID,
    "--VpcId", $dstVpcId,
    "--CidrBlock", "10.1.1.0/24"
)).VSwitchId
Wait-ResourceAvailable -Service "Vpc" -Action "DescribeVSwitchAttributes" -Parameters @(
    "--region", $DST_REGION_ID,
    "--RegionId", $DST_REGION_ID,
    "--VSwitch", $dstVSwitchId
) -StatusPath "Status"
Log "INFO" "VSwitch created: '$dstVSwitchId'"

# 创建安全组
Log "INFO" "Creating security group"
$dstSecurityGroupId = (Invoke-AliyunCommand ecs CreateSecurityGroup @(
    "--region", $DST_REGION_ID,
    "--RegionId", $DST_REGION_ID,
    "--SecurityGroupName", "cli-dst-sg",
    "--VpcId", $dstVpcId,
    "--SecurityGroupType", "normal"
)).SecurityGroupId
Log "INFO" "Security group created: '$dstSecurityGroupId'"

# 在目标地域创建一个按量付费ECS实例
Log "INFO" "Creating ECS instance in zone: '$DST_ZONE_ID'"
$dstInstanceId = (Invoke-AliyunCommand ecs RunInstances @(
    "--region", $DST_REGION_ID,
    "--RegionId", $DST_REGION_ID,
    "--ImageId", $dstImgId,
    "--SecurityGroupId", $dstSecurityGroupId,
    "--VSwitchId", $dstVSwitchId,
    "--InstanceType", $SRC_INSTANCE_TYPE,
    "--InstanceName", "cli-dst-ecs",
    "--PasswordInherit", "true",
    "--SystemDisk.Category", $SRC_SYSTEM_DISK_CATEGORY,
    "--SystemDisk.Size", $SRC_SYSTEM_DISK_SIZE,
    "--InstanceChargeType", "PostPaid"
)).InstanceIdSets.InstanceIdSet[0]
Log "INFO" "ECS instance created: '$dstInstanceId'"
Log "INFO" "Script execution completed successfully."
```

## 相关文档
您可在控制台中实现同地域或者跨地域下的ECS实例间的迁移。具体操作，请参见[通过自定义镜像跨地域复制ECS实例](https://help.aliyun.com/document_detail/312097.html)。