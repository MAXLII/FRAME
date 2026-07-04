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

交互式终端的 J-Link 命令按 GUI 页面动作拆分：

```text
jlink elf <elf-or-axf>
jlink map <map|->
jlink device <target> [speed_khz]
jlink load
jlink list [filter] [limit]
jlink search <keyword> [limit]
jlink funcs [filter] [limit]
jlink read <expression> [depth]
jlink write <expression> <value>
jlink source <expression|symbol|address> [context_lines]
jlink connect <target> [speed_khz]
```

### 3.1 装载符号文件

```text
jlink elf D:\OneDrive\LWX\GD32\base\gd32g553c\build\demo.elf
jlink map D:\OneDrive\LWX\GD32\base\gd32g553c\build\demo.map
jlink load
```

`jlink elf` 和 `jlink map` 会把路径保存到本地 JSON 配置。下次启动 GUI 或终端时会复用这些路径。`jlink map -` 表示清空 MAP 路径，只使用 ELF/AXF。

`jlink load` 只重新读取 ELF/MAP 并解析变量、类型、结构体、数组、指针和内存范围，不通过 J-Link 读取目标板内存。

### 3.2 保存 Target / Device

```text
jlink device GD32G553RET6 10000
jlink connect GD32G553RET6 10000
```

`jlink device` 会把 target 和 speed 保存到 JSON 配置。`jlink connect` 只测试当前 J-Link 连接。

### 3.3 列出未展开变量

```text
jlink list
jlink list p_init 20
jlink search p_init 20
```

`jlink list` 只显示未展开的顶层变量列表，不读取目标板内存。`filter` 只过滤变量名，`limit` 控制最多显示多少行。

`jlink search` 是明确的搜索命令，只搜索未展开的顶层变量名，不搜索结构体内部成员，也不通过 J-Link 读取目标板内存。

### 3.4 展示函数列表

```text
jlink funcs
jlink funcs main
jlink funcs task 20
```

`jlink funcs` 从 ELF 函数符号表和 DWARF 子程序信息展示函数名、地址和源码位置，不通过 J-Link 读取目标板内存。可以先用它查函数名，再用 `jlink source <function>` 展示源码。

如果某个函数只有 DWARF 源码位置，没有可用代码地址，`address` 会显示为 `-`，这种函数仍然可以用 `jlink source <function>` 展示源码。

### 3.5 读取变量并展开

```text
jlink read p_init_first 1
jlink read p_init_first.p_next 1
jlink read p_init_first.p_next.p_next 1
```

`jlink read <expression> [depth]` 会通过 J-Link 读取指定表达式。表达式对应结构体、数组或指针时，会按 `depth` 展开成员。结构体和指针字段使用 `.` 分隔。

读取指针时，FRAME 会先读取指针变量自身的值，再把该值作为目标结构体地址继续读取。目标地址必须落在 ELF/MAP 解析出的内存范围内。

### 3.6 写入 RAM 变量

```text
jlink write p_init_first.p_next.priority 0
jlink write my_float 3.14
jlink write my_ptr 0x20000000
```

`jlink write` 使用和 GUI Value 单元格相同的写入逻辑。只允许写入 RAM 地址，Flash/code 区域会被拒绝。整数不带 `0x` 时按十进制写入，带 `0x` 时按十六进制写入，浮点变量支持浮点文本。

### 3.7 显示函数源码

```text
jlink source p_init_first.p_next.p_func 6
jlink source bsp_gpio_init 6
jlink source 0x08001B09 6
```

`jlink source` 会根据 ELF 里的 DWARF 调试信息，把函数地址定位到源码文件和行号。不带 `context_lines` 时显示完整函数源码；带数字时显示目标行前后若干行源码。

输入可以是函数符号名、裸地址，或者明确的函数指针字段。`jlink source` 不会从结构体里自动猜测 `p_func`，需要把要展示的函数或函数指针字段写清楚。

交互式终端会记住最近一次显式执行的命令前缀。带子命令的命令会记住前两个词，例如 `jlink source`、`jlink funcs`、`perf dict`；普通带参数命令会记住第一个词，例如 `connect`。后续如果直接输入一个不是 FRAME 顶层命令的名字，会自动补上最近记住的前缀。

例如执行过一次 `jlink source <function>` 后，后续可以直接输入函数名：

```text
jlink source main
section_init
```

第二行等价于：

```text
jlink source section_init
```

再例如执行过 `jlink funcs task 20` 后，直接输入 `main 5` 等价于：

```text
jlink funcs main 5
```

该功能需要满足两个条件：

- ELF/AXF 包含 DWARF 调试信息。
- DWARF 中记录的源码路径在当前电脑上仍然存在。

## 4. 一次性 CLI 使用

普通命令行入口用于一次性读取并输出变量表。

```powershell
.\frame jlink --elf <elf> --map <map> --device <device> --speed 4000 --filter <keyword> --limit 50
```

如果 GUI 已经保存过 J-Link 配置，可以省略已保存的参数：

```powershell
.\frame jlink --filter p_init --limit 5
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
