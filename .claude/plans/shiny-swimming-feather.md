# AI 视频转序列帧工具 — 实现方案

## 背景

将 AI 生成的怪物动画视频（MP4，纯绿背景）自动转成透明背景的 PNG 序列帧，按规范命名并上传至 Roblox Studio，用于制作帧动画。

**输入**：AI 工具生成的 MP4 视频（如 Runway/Pika/Kling），**纯绿色背景**，走路和攻击各一个视频
**输出**：透明 PNG 序列帧 + JSON 元数据文件 + 可选自动上传到 Roblox

## 整体流程

```
AI视频 (MP4, 纯绿背景)  
  → 帧提取 (均匀采样 / 智能关键帧)  
  → 色度抠图 (绿幕去除)  
  → 主体裁切 + 居中 + 统一尺寸  
  → 按规范命名输出 PNG  
  → (可选) 批量上传到 Roblox
```

## 技术栈

| 组件 | 用途 |
|------|------|
| **Python 3.10+** | 主语言 |
| **OpenCV (cv2)** | 视频读取、帧提取、绿幕抠图 |
| **rembg** | 备选：色度抠图效果不好时做 AI 边缘精修 |
| **Pillow (PIL)** | 图片裁剪、缩放、居中、输出 PNG |
| **NumPy** | 数组运算 |

## 文件结构

```
tools/video_to_frames/
├── video_to_frames.py       # 主程序：单视频 → PNG序列帧
├── batch_process.py         # 批量处理整个文件夹
├── upload_to_roblox.py      # 批量上传 PNG 到 Roblox + 回填 asset ID
├── requirements.txt         # 依赖清单
└── output/                  # 输出目录 (自动创建)
    └── {name}_{action}/
        ├── {name}_{action}_001.png
        ├── {name}_{action}_002.png
        ├── ...
        └── metadata.json    # 元数据（含上传后的 asset ID）
```

## CLI 命令设计

### 1. 单条处理

```bash
python video_to_frames.py slime_walk.mp4 \
  --name slime \            # 怪物名称
  --action walk \            # 动画类型 (walk / attack)
  --frames 6 \              # 输出帧数（walk建议6帧，attack建议4帧）
  --bg-color 0 255 0 \      # 绿色背景 RGB
  --tolerance 30            # 色彩容差
  --size 256                # 输出画布尺寸（正方形）
  --output ./output         # 输出目录
```

### 2. 批量处理

```bash
python batch_process.py ./videos/ --output ./output
```

自动识别文件名规则：`{name}_{action}.mp4`（如 `slime_walk.mp4`、`slime_attack.mp4`）

### 3. 上传到 Roblox

```bash
python upload_to_roblox.py ./output/slime_walk/metadata.json
```

使用 upload_decal 工具上传每帧图片，将返回的 asset ID 回填到 metadata.json。

## 核心处理逻辑

### 帧提取

**简单模式（均匀采样）**：
- 计算视频总帧数，均匀取出 N 帧
- 适用于行走动画（周期性重复）
- 额外：自动检测一个完整步态周期，只取一个周期的帧，避免取到重复周期

**智能模式（动作峰值检测）**：
- 计算相邻帧的差异度（像素变化绝对值之和）
- 在差异度峰值附近取帧
- 适用于攻击动画（预备→出招→收招节奏不均匀）

### 绿幕抠图

```python
# OpenCV 色度抠图核心逻辑
hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
lower_green = np.array([40, 40, 40])   # 绿色范围下限
upper_green = np.array([80, 255, 255]) # 绿色范围上限
mask = cv2.inRange(hsv, lower_green, upper_green)
mask_inv = cv2.bitwise_not(mask)
rgba = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
rgba[:, :, 3] = mask_inv  # Alpha 通道
```

- 支持 `--tolerance` 参数调节色彩容差
- 支持手动指定 `--bg-color` 适应非绿色背景
- 结果不理想时自动 fallback 到 rembg AI 抠图

### 裁切居中

1. 检测非透明像素的边界框
2. 四周留 10% 边距
3. 缩放到 `--size` 指定尺寸（默认 256×256）
4. 所有帧保持一致的画布大小

### 输出命名规则

```
{name}_{action}_{frame:03d}.png
```

示例：
```
slime_walk_001.png
slime_walk_002.png
...
slime_walk_006.png
```

### metadata.json 格式

```json
{
  "name": "slime",
  "action": "walk",
  "total_frames": 6,
  "fps": 8,
  "canvas_size": 256,
  "source_video": "slime_walk.mp4",
  "files": [
    {"file": "slime_walk_001.png", "asset_id": null},
    {"file": "slime_walk_002.png", "asset_id": null},
    ...
  ]
}
```

## 推荐的默认参数

| 动画类型 | 帧数 | 说明 |
|---------|:----:|:-----|
| 行走 (walk) | **6 帧** | 左右腿交替 + 中间过渡，足够流畅 |
| 攻击 (attack) | **4 帧** | 预备1帧 + 出招1帧 + 收招2帧 |

同一怪物的行走和攻击保持相同的画布尺寸，方便在代码里切换动画时位置对齐。

## 实施步骤

1. **创建目录结构** `tools/video_to_frames/`
2. **写 `requirements.txt`** — opencv-python, rembg, pillow, numpy
3. **写 `video_to_frames.py`** — 核心逻辑
   - 视频读取 + 帧提取
   - 绿幕抠图（+ rembg fallback）
   - 裁切居中 + 统一尺寸
   - 输出 PNG + metadata.json
4. **写 `batch_process.py`** — 遍历目录批量处理
5. **写 `upload_to_roblox.py`** — 用 `upload_decal` 上传 + 回填 asset ID
6. **测试** — 找一条测试视频跑通全流程
7. **清理** — 把临时测试文件移除，只保留工具代码

## 验证方法

1. **本地验证**：用测试视频运行 `video_to_frames.py`，检查输出 PNG 的透明度和对齐
2. **动画预览**：用 `python -c "from PIL import Image; ..."` 按顺序打开 PNG 查看动画是否流畅
3. **Roblox 验证**：上传后导入 Studio，用 ImageLabel/Decal 逐帧切换确认效果
4. **批量验证**：准备 2-3 个不同怪物的视频，跑 `batch_process.py` 确认全部正常
