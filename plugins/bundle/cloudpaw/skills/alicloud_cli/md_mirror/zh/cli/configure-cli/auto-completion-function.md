阿里云CLI中包含一个与zsh、bash兼容的命令自动补全功能。在使用阿里云CLI时，您可以手动开启自动补全功能以提升您的工作效率。Linux或macOS无需进行额外配置，暂不支持Windows。  

## **开启或关闭** **命令自动补全**
您可以通过如下命令开启或关闭自动补全功能，目前仅支持zsh、bash。

* 启用自动补全功能

  ```
  HELPCODEESCAPE-shell
  aliyun auto-completion
  ```

* 关闭自动补全功能

  ```
  HELPCODEESCAPE-shell
  aliyun auto-completion --uninstall
  ```

## 功能示例
当您输入命令、参数或选项的部分内容时，命令自动补全功能会自动完成您的命令或显示建议的命令列表。以下示例为您展示不同场景下命令自动补全功能的实际应用。

### 示例1：显示建议的命令列表

1. 输入待补全命令的首字母后，按下***Tab***键。

   ```
   HELPCODEESCAPE-shell
   aliyun ecs C
   ```

2. 系统显示`C`开头的可用命令列表。

   ```
   HELPCODEESCAPE-shell
   CancelAutoSnapshotPolicy          CopyImage                         CreateDemand                      
   CreateHpcCluster                  CreateNatGateway                  CreateSimulatedSystemEvents
   CancelCopyImage                   CopySnapshot                      CreateDeploymentSet               
   CreateImage                       CreateNetworkInterface            CreateSnapshot
   ```

### 示例2：显示建议的参数列表

1. 输入待补全参数的首字母后，按下***Tab***键。

   ```
   HELPCODEESCAPE-shell
   aliyun ecs CreateImage --D
   ```

2. 系统显示该命令下`D`开头的可用参数列表。

   ```
   HELPCODEESCAPE-shell
   --Description                     --DiskDeviceMapping.1.SnapshotId
   --DetectionStrategy
   --DiskDeviceMapping.1.Device
   --DiskDeviceMapping.1.Size
   ```

<br />