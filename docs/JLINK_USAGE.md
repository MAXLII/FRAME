# J-Link 使用方法

本文档说明 FRAME 中 J-Link 变量读取、结构体展开、RAM 写入和命令行读取的使用方法。

## 1. 使用前准备

### 1.1 硬件连接

1. 将 J-Link 连接到目标板 SWD/JTAG 调试口。
2. 确认目标板已经供电。
3. 如需要同时使用串口功能，继续在顶部串口区选择串口并打开。

### 1.2 软件依赖

FRAME 会自动从以下位置查找 `JLink.exe` 或 `JLinkExe.exe`：

- 系统 `PATH`
- SEGGER 默认安装目录，例如 `C:\Program Files\SEGGER\JLink`
- SEGGER 版本目录，例如 `C:\Program Files\SEGGER\JLink_V936`

GUI 页面不需要手动选择 `JLink.exe`。

### 1.3 符号文件

J-Link 变量页需要 ELF/AXF 或 MAP 文件。

- ELF/AXF：用于读取变量符号、DWARF 类型、结构体、数组、指针类型和内存范围。
- MAP：用于补充变量符号和内存范围。
- 推荐同时选择 ELF/AXF 和 MAP。

如果 ELF 带 DWARF 调试信息，结构体、数组、指针和函数内静态变量的类型信息更完整。

## 2. GUI 页面使用

### 2.1 打开 J-Link 页面

1. 启动 FRAME GUI。
2. 进入 `J-Link` 页。
3. 在左侧 `配置` 区填写或确认以下内容：
   - `Target / Device`
   - `Interface`
   - `Speed kHz`
   - `ELF / AXF`
   - `MAP`

配置会保存到本地 JSON 配置文件，下次启动会自动恢复。

### 2.2 Target / Device

`Target / Device` 是 SEGGER J-Link 使用的芯片型号名称，例如：

```text
GD32G553RET6
GD32G553RCT6
HC32F334K8TA
STM32F407VE
```

使用方式：

1. 如果 ELF/MAP 中能识别出芯片型号，FRAME 会自动填入。
2. 如果输入框为空，点击 `Connect` 会弹出 SEGGER 自带的 target 选择界面。
3. 点击输入框可以选择历史使用过的 target。

### 2.3 Load

点击 `Load` 会重新从磁盘读取 ELF/AXF 和 MAP。

Load 阶段只做符号和类型解析，不通过 J-Link 读取变量值。此时表格中会显示：

- `Expression`
- `Type`
- `Address`
- 初始 `Status`

未展开的结构体和数组不会在 Load 阶段读取内部成员数据。

### 2.4 Connect

点击 `Connect` 用当前 `Target / Device`、`Interface` 和 `Speed kHz` 测试 J-Link 连接。

连接成功后会保存 target 历史。

### 2.5 读取变量

双击变量行可以读取该变量当前值。

读取后表格会更新：

- `Value`：按类型格式化后的值
- `Raw`：原始字节
- `Status`：读取状态

显示规则：

- `void *` 和普通指针默认显示为 16 进制地址。
- 整型显示为十进制。
- 浮点显示为浮点数。
- 字符串指针和字符数组会尽量显示 ASCII 字符串。
- 指针如果能匹配到符号，会显示为 `symbol_name (0x地址)`。

### 2.6 展开结构体

结构体默认不展开。

点击结构体左侧展开符号后，FRAME 会根据结构体类型和该变量地址读取内存，并显示结构体成员。

结构体成员显示规则：

- 成员按结构体字段顺序显示。
- 成员地址按结构体基地址加字段偏移计算。
- 成员值按成员类型显示。
- 结构体下的内容重新进行灰白背景交替。

### 2.7 展开数组

数组默认不展开。

展开数组后按索引显示：

```text
[0]
[1]
[2]
```

多维数组按层级继续展开：

```text
[0]
  [0]
  [1]
[1]
  [0]
  [1]
```

数组元素读取规则与普通变量相同。

### 2.8 展开指针和链表

指针变量如果具备以下信息，可以展开：

- 指针变量地址
- 指针变量类型
- 指针当前保存的目标地址

展开指针时，FRAME 先通过 J-Link 读取指针变量自身的内存值，再把该内存值作为目标结构体地址读取成员。

链表字段如 `p_next` 可以继续展开。每次展开都会按当前指针值重新读取目标结构体。

如果指针为 `NULL`，展开后不会读取子项。

如果指针指向 ELF/MAP 内存范围之外，FRAME 会阻止展开并提示原因。

### 2.9 Refresh

点击 `Refresh` 只刷新当前可见变量行。

未展开的结构体、数组和指针不会读取隐藏成员。

### 2.10 Search

搜索框用于过滤顶层变量和当前可见行。

未展开结构体和数组的内部成员不参与搜索。

### 2.11 复制内容

在变量表中点击需要复制的位置：

- `Ctrl+C` 复制当前单元格
- 右键菜单可以复制单元格、整行、Expression 或 Value

### 2.12 写入 RAM 变量

双击 `Value` 单元格会进入编辑状态。

写入规则：

1. 修改 `Value` 文本。
2. 按 Enter 提交写入。
3. 未按 Enter 时不会写入，编辑状态用红色提示。

支持的输入：

```text
123
-20
3.14
0x20000000
hex: 01 02 03 04
```

说明：

- 不带 `0x` 的整数按十进制写入。
- 带 `0x` 的整数按 16 进制写入。
- 浮点变量支持浮点文本。
- `hex:` 或 `raw:` 可写入原始字节。
- 只能写 RAM 地址范围。
- Flash 和代码区域不能通过该入口写入。

## 3. 交互式终端使用

启动终端：

```powershell
.\frame shell
```

进入后可执行：

```text
jlink connect <device> [speed_khz]
jlink read <elf> [map|-] [device] [filter] [limit]
```

示例：

```text
jlink connect GD32G553RET6 4000
jlink read D:\OneDrive\LWX\GD32\base\gd32g553c\build\demo.elf D:\OneDrive\LWX\GD32\base\gd32g553c\build\demo.map GD32G553RET6 p_init 50
```

参数说明：

- `<elf>`：ELF/AXF 文件路径。
- `[map|-]`：MAP 文件路径；填 `-` 表示不使用 MAP。
- `[device]`：J-Link target/device；省略时会尝试从 ELF/MAP 中识别。
- `[filter]`：变量名过滤关键字。
- `[limit]`：最多显示多少行。

## 4. 一次性 CLI 使用

普通命令行入口用于一次性读取并输出变量表。

```powershell
.\frame jlink --elf <elf> --map <map> --device <device> --speed 4000 --filter <keyword> --limit 50
```

只解析变量列表，不读取目标板内存：

```powershell
.\frame jlink --elf D:\xxx\firmware.elf --map D:\xxx\firmware.map --no-read
```

读取并输出 JSON：

```powershell
.\frame jlink --elf D:\xxx\firmware.elf --map D:\xxx\firmware.map --device GD32G553RET6 --format json
```

保存到文件：

```powershell
.\frame jlink --elf D:\xxx\firmware.elf --map D:\xxx\firmware.map --device GD32G553RET6 --output D:\xxx\jlink_vars.csv --format csv
```

## 5. 常见问题

### 5.1 找不到 J-Link

确认已经安装 SEGGER J-Link，并且 `JLink.exe` 存在于默认安装目录或 PATH。

### 5.2 读不到变量

检查：

- ELF/AXF 是否带符号信息。
- MAP 文件是否与当前固件匹配。
- 目标板是否供电。
- `Target / Device` 是否正确。
- J-Link 是否被其他软件占用。

### 5.3 结构体不能展开

检查 ELF 是否包含 DWARF 调试信息。

只有知道结构体类型、变量地址和成员偏移，FRAME 才能展开结构体。

### 5.4 指针不能展开

检查：

- 指针变量是否已经被读取。
- 指针值是否为 `0x00000000`。
- 指针目标地址是否在 ELF/MAP 解析出的内存范围内。
- 指针类型是否带有目标结构体类型。

### 5.5 写入失败

检查：

- 选择的变量地址是否在 RAM。
- 输入格式是否符合变量类型。
- 目标板是否允许调试器写 RAM。
- J-Link 连接是否稳定。
