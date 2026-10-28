# 真实手册通道

合成手册跑通的是**管线**；这个目录用来放**厂商公开的真实手册**，让评测数字有真实分母。

## 为什么单独放一层

- 合成手册由 `scripts/gen_manuals.py` 生成，可随时重跑，用来压测边界（跨页表格、表头页脚、多型号同参数名）。
- 真实手册来自厂商，**不重分发**，只在本机使用；放这里不影响仓库里合成数据的可复现性。
- 两者合并进同一个索引：`MANUAL_META`（合成）+ `real/_meta.json`（真实）。

## 放什么、怎么命名

1. 把 PDF 重命名为 `<型号>_manual.pdf`，例如 `ATV320_manual.pdf`
2. 放到本目录
3. 在 `_meta.json` 里登记一行（没有就新建）：

```json
{
  "ATV320_manual": {
    "doc_title": "ATV320 变频器 安装与编程手册",
    "model_id": "ATV320"
  }
}
```

4. 在 `data/equipment/registry/devices.json` 里加一台该型号的设备，型号过滤才有东西可锁：

```json
{
  "device_id": "VFD-320-01",
  "model_id": "ATV320",
  "name": "8 号线变频器",
  "line": "8 号线包装段",
  "location": "包装段电控柜",
  "manual": "ATV320_manual",
  "thresholds": {"motor_temp_c": 80, "output_freq_hz": 50}
}
```

5. 重启服务，`[boot]` 那行会打印新的段数。

## 施耐德 ATV320 手册在哪下（免费公开）

厂商文档页（需要浏览器点击下载，直接 curl 会被防盗链挡 403）：

- 安装手册（中文）：https://www.se.com/tw/zh/download/document/ATV320-Installation-Manual-V1/
- 编程手册（中文，2025 版）：https://www.schneider-electric.cn/zh/download/document/NVE41300/

下载后是一个 2 MB 左右的中文 PDF。**只放本机，不要提交到仓库**（`.gitignore` 已排除本目录的 PDF）。

## 版权与边界

厂商手册受版权保护，公开发布的用户文档可以自由下载阅读，但**重分发需要授权**。
所以本目录的 PDF：

- ✅ 本机使用、跑评测、面试演示
- ❌ 不提交到公开仓库、不放进 release、不二次分发

仓库里提交的是**生成脚本 + 合成数据**，任何人都能一键复现 —— 这比塞一本 PDF 更有价值。
