"""
AI 视频 → 透明 PNG 序列帧 工具
=================================
将 AI 生成的纯色背景怪物动画视频 (MP4) 转为透明背景的 PNG 序列帧。

用法:
    python video_to_frames.py <视频路径> --name <怪物名> --action <walk/attack> [选项]

示例:
    python video_to_frames.py slime_walk.mp4 --name slime --action walk --frames 6
    python video_to_frames.py goblin_attack.mp4 --name goblin --action attack --frames 4 --smart
"""

import argparse
import json
import os
import sys
from pathlib import Path

# 终端 UTF-8 支持（防止 GBK 编码报错）
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import cv2
import numpy as np
from PIL import Image


def parse_args():
    parser = argparse.ArgumentParser(
        description="将 AI 生成的纯色背景怪物动画视频转为透明 PNG 序列帧"
    )
    parser.add_argument("video", type=str, help="输入视频路径 (.mp4 / .mov / .avi)")
    parser.add_argument("--name", type=str, required=True, help="怪物名称 (如 slime)")
    parser.add_argument(
        "--action", type=str, required=True, choices=["walk", "attack", "idle", "hurt", "death"],
        help="动画类型",
    )
    parser.add_argument(
        "--frames", type=int, default=None,
        help="输出帧数 (walk 默认 6, attack 默认 4)",
    )
    parser.add_argument(
        "--smart", action="store_true",
        help="启用智能关键帧提取 (适合 attack 等非均匀节奏的动画)",
    )
    parser.add_argument(
        "--bg-color", type=int, nargs=3, default=[0, 255, 0],
        metavar=("R", "G", "B"),
        help="背景色 RGB (默认: 0 255 0 绿色)",
    )
    parser.add_argument(
        "--tolerance", type=int, default=40,
        help="色彩容差 (默认: 40, 越大扣得越激进)",
    )
    parser.add_argument(
        "--size", type=int, default=256,
        help="输出画布尺寸 (正方形, 默认: 256)",
    )
    parser.add_argument(
        "--output", type=str, default="./output",
        help="输出目录 (默认: ./output)",
    )
    parser.add_argument(
        "--preview", action="store_true",
        help="生成一张预览拼贴图方便查看效果",
    )
    parser.add_argument(
        "--gif", action="store_true",
        help="生成一张预览 GIF 动图直接查看动画效果",
    )
    parser.add_argument(
        "--gif-fps", type=float, default=None,
        help="GIF 的播放帧率 (默认与视频 fps 相同或 8fps)",
    )
    return parser.parse_args()


def get_default_frames(action: str) -> int:
    """根据动画类型返回默认帧数。"""
    defaults = {"walk": 6, "attack": 4, "idle": 4, "hurt": 3, "death": 5}
    return defaults.get(action, 6)


# ─────────────────────────────────────────────
# 帧提取
# ─────────────────────────────────────────────

def extract_frames_uniform(video_path: str, num_frames: int):
    """
    均匀采样：从视频中均匀取出 N 帧。
    返回 list of (frame_index, BGR_frame)。
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"无法打开视频: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    duration = total_frames / fps if fps > 0 else 0

    print(f"  视频总帧数: {total_frames}, FPS: {fps:.1f}, 时长: {duration:.2f}s")

    if total_frames < num_frames:
        print(f"  [WARN] 视频帧数 ({total_frames}) 少于请求的帧数 ({num_frames})，将输出全部帧")
        num_frames = total_frames

    # 计算均匀间隔（取中间区域，避免首尾过渡帧）
    if num_frames == 1:
        indices = [total_frames // 2]
    else:
        # 从 10%~90% 范围均匀采样，避开开头和结尾的过渡帧
        start = int(total_frames * 0.08)
        end = int(total_frames * 0.92)
        if end - start < num_frames:
            start = 0
            end = total_frames
        indices = np.linspace(start, end - 1, num_frames, dtype=int)

    frames = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if ret:
            frames.append((int(idx), frame))
        else:
            print(f"  [WARN] 无法读取第 {idx} 帧，跳过")

    cap.release()
    return frames, fps


def extract_frames_smart(video_path: str, num_frames: int):
    """
    智能关键帧提取：基于帧间差异检测动作峰值，在动作变化最大的时刻取帧。
    适合 attack 等预备→出招→收招的非均匀节奏。
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"无法打开视频: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    print(f"  视频总帧数: {total_frames}, FPS: {fps:.1f}")

    if total_frames < num_frames:
        print(f"  ⚠ 视频帧数不足，回退到均匀采样")
        cap.release()
        return extract_frames_uniform(video_path, num_frames)

    # 读取所有帧
    all_frames = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        all_frames.append(frame)
    cap.release()

    if len(all_frames) < 2:
        return [(0, all_frames[0])], fps

    # 计算帧间差异（灰度图的绝对差之和）
    diffs = []
    for i in range(1, len(all_frames)):
        gray_prev = cv2.cvtColor(all_frames[i - 1], cv2.COLOR_BGR2GRAY)
        gray_curr = cv2.cvtColor(all_frames[i], cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(gray_prev, gray_curr).sum()
        diffs.append(diff)

    # 对差异值做平滑
    diffs = np.array(diffs, dtype=float)
    kernel_size = max(3, len(diffs) // 20)
    if kernel_size % 2 == 0:
        kernel_size += 1
    diffs_smooth = cv2.GaussianBlur(diffs, (1, kernel_size), 0).flatten()

    # 找峰值：在动作变化最大的位置取帧
    # 排除开头和结尾 8%
    start_idx = int(len(diffs_smooth) * 0.08)
    end_idx = int(len(diffs_smooth) * 0.92)
    if end_idx - start_idx < num_frames:
        start_idx = 0
        end_idx = len(diffs_smooth)

    # 找 top-N 峰值（带最小间隔约束）
    peak_indices = []
    min_gap = max(1, (end_idx - start_idx) // (num_frames * 2))

    scored = [(i, diffs_smooth[i]) for i in range(start_idx, end_idx)]
    scored.sort(key=lambda x: -x[1])

    for idx, _ in scored:
        if len(peak_indices) >= num_frames:
            break
        # 检查是否离已选的峰太近
        too_close = any(abs(idx - p) < min_gap for p in peak_indices)
        if not too_close:
            peak_indices.append(idx)

    peak_indices.sort()

    # 如果找到的峰值不够，补充均匀采样
    if len(peak_indices) < num_frames:
        needed = num_frames - len(peak_indices)
        existing = set(peak_indices)
        uniform = np.linspace(start_idx, end_idx - 1, needed + 2, dtype=int)[1:-1]
        extra = [i for i in uniform if i not in existing][:needed]
        peak_indices.extend(extra)
        peak_indices.sort()

    frames = [(i, all_frames[i]) for i in peak_indices]
    return frames, fps


# ─────────────────────────────────────────────
# 背景抠图
# ─────────────────────────────────────────────

def chroma_key(frame, bg_rgb, tolerance):
    """
    背景抠图：将指定背景色变为透明。
    对于白色/浅色背景，使用 AI 抠图 (rembg) 获得更干净的边缘。
    对于彩色背景，使用 HSV 色度抠图。
    返回 RGBA numpy array (H, W, 4)。
    """
    frame_bgr = frame.copy()
    bgr = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)

    # 判断背景色是白色还是彩色
    is_white_bg = all(c > 200 for c in bg_rgb)

    if is_white_bg:
        rgba = _remove_background_ai(frame_bgr)
    else:
        mask = _remove_colored_background(frame_bgr, bg_rgb, tolerance)
        mask = cv2.medianBlur(mask, 5)
        mask = cv2.GaussianBlur(mask, (3, 3), 0)
        bgr[:, :, 3] = mask
        rgba = bgr

    return rgba


def _remove_colored_background(frame_bgr, bg_rgb, tolerance):
    """
    彩色背景去除：HSV 色度抠图。
    """
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    bg_hsv = cv2.cvtColor(np.uint8([[list(reversed(bg_rgb))]]), cv2.COLOR_BGR2HSV)[0][0]
    bg_h = int(bg_hsv[0])
    bg_s = int(bg_hsv[1])
    bg_v = int(bg_hsv[2])

    # 对于高饱和度的彩色背景，H 通道可能绕回，需要双向范围
    # 但这里简化处理
    lower = np.array([max(0, bg_h - tolerance // 2),
                      max(0, bg_s - tolerance),
                      max(0, bg_v - tolerance)], dtype=np.uint8)
    upper = np.array([min(179, bg_h + tolerance // 2),
                      min(255, bg_s + tolerance),
                      min(255, bg_v + tolerance)], dtype=np.uint8)
    mask = cv2.inRange(hsv, lower, upper)
    return cv2.bitwise_not(mask)


def _remove_background_ai(frame_bgr):
    """
    AI 抠图：使用 rembg 去除背景。
    适合白色/浅色背景，边缘干净。
    """
    try:
        from rembg import remove
        from PIL import Image

        pil_img = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
        result = remove(pil_img)
        rgba = cv2.cvtColor(np.array(result), cv2.COLOR_RGBA2BGRA)
        return rgba
    except Exception as e:
        print(f"    [WARN] AI 抠图失败: {e}，回退到阈值法")
        # 回退到灰度阈值
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY)
        mask = cv2.bitwise_not(mask)
        mask = cv2.medianBlur(mask, 5)
        bgr = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2BGRA)
        bgr[:, :, 3] = mask
        return bgr


def try_rembg_fallback(rgba, frame_bgr):
    """
    当色度抠图效果不佳时，尝试用 rembg 做 AI 抠图作为备用。
    需要安装 rembg 包。
    """
    try:
        from rembg import remove
        from PIL import Image

        pil_img = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
        result = remove(pil_img)
        return cv2.cvtColor(np.array(result), cv2.COLOR_RGBA2BGRA)
    except ImportError:
        print("  ⚠ rembg 未安装，跳过 AI 抠图备用方案")
        return rgba
    except Exception as e:
        print(f"  ⚠ rembg 抠图失败: {e}，使用色度抠图结果")
        return rgba


# ─────────────────────────────────────────────
# 裁切 & 居中
# ─────────────────────────────────────────────

def crop_and_center(rgba, canvas_size, padding_ratio=0.08):
    """
    自动检测主体边界框，裁切后居中放置到正方形画布上。
    所有帧保持一致的输出尺寸。
    """
    alpha = rgba[:, :, 3]

    # 找到非透明像素的边界
    rows = np.any(alpha > 30, axis=1)
    cols = np.any(alpha > 30, axis=0)

    if not rows.any() or not cols.any():
        # 全透明帧 → 返回空白画布
        canvas = np.zeros((canvas_size, canvas_size, 4), dtype=np.uint8)
        return canvas

    y_min, y_max = np.where(rows)[0][[0, -1]]
    x_min, x_max = np.where(cols)[0][[0, -1]]

    # 裁切
    cropped = rgba[y_min:y_max + 1, x_min:x_max + 1]

    # 四周加边距
    h, w = cropped.shape[:2]
    pad = int(max(h, w) * padding_ratio)
    padded = cv2.copyMakeBorder(cropped, pad, pad, pad, pad,
                                cv2.BORDER_CONSTANT, value=(0, 0, 0, 0))

    # 缩放至适合画布大小（保持宽高比）
    ph, pw = padded.shape[:2]
    scale = min(canvas_size / pw, canvas_size / ph)
    new_w = int(pw * scale)
    new_h = int(ph * scale)
    resized = cv2.resize(padded, (new_w, new_h), interpolation=cv2.INTER_AREA)

    # 居中放置到画布
    canvas = np.zeros((canvas_size, canvas_size, 4), dtype=np.uint8)
    x_offset = (canvas_size - new_w) // 2
    y_offset = (canvas_size - new_h) // 2
    canvas[y_offset:y_offset + new_h, x_offset:x_offset + new_w] = resized

    return canvas


# ─────────────────────────────────────────────
# 输出
# ─────────────────────────────────────────────

def save_frames(frames, output_dir, base_name, canvas_size, metadata, preview=False, gif=False, gif_fps=None):
    """保存帧为 PNG 并更新 metadata。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    file_list = []
    for i, (idx, rgba) in enumerate(frames):
        filename = f"{base_name}_{i + 1:03d}.png"
        filepath = output_dir / filename

        # BGRA → RGBA for Pillow
        rgb = cv2.cvtColor(rgba, cv2.COLOR_BGRA2RGBA)
        pil_img = Image.fromarray(rgb, "RGBA")
        pil_img.save(filepath, "PNG")

        file_list.append({
            "frame": i + 1,
            "file": filename,
            "source_frame": int(idx),
            "asset_id": None,
        })
        print(f"  ✅ {filename}")

    metadata["files"] = file_list

    # 保存 metadata.json
    meta_path = output_dir / "metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    print(f"  📄 metadata.json 已保存")

    # 生成预览拼贴图
    if preview and len(frames) > 1:
        create_preview(frames, output_dir, base_name, canvas_size)

    # 生成 GIF 动图
    if gif and len(frames) > 1:
        create_gif(frames, output_dir, base_name, canvas_size, gif_fps)

    return file_list


def create_preview(frames, output_dir, base_name, canvas_size):
    """将多帧拼成一张横向预览图。"""
    n = len(frames)
    preview_w = canvas_size * n
    preview = Image.new("RGBA", (preview_w, canvas_size), (0, 0, 0, 0))

    for i, (_, rgba) in enumerate(frames):
        rgb = cv2.cvtColor(rgba, cv2.COLOR_BGRA2RGBA)
        pil_img = Image.fromarray(rgb, "RGBA")
        preview.paste(pil_img, (i * canvas_size, 0), pil_img)

    preview_path = output_dir / f"{base_name}_preview.png"
    preview.save(preview_path, "PNG")
    print(f"  🖼 预览图: {preview_path}")


def create_gif(frames, output_dir, base_name, canvas_size, fps=None):
    """将多帧合成一张预览 GIF 动图。"""
    n = len(frames)
    if fps is None:
        fps = 8  # 默认 8fps
    duration = int(1000 / fps)  # 每帧显示毫秒数

    pil_frames = []
    for _, rgba in frames:
        rgb = cv2.cvtColor(rgba, cv2.COLOR_BGRA2RGBA)
        pil_img = Image.fromarray(rgb, "RGBA")

        # GIF 不支持半透明，合成到棋盘格背景上便于观察透明效果
        checker = Image.new("RGBA", (canvas_size, canvas_size), (200, 200, 200))
        checker.paste(pil_img, (0, 0), pil_img)
        pil_frames.append(checker.convert("P", palette=Image.Palette.ADAPTIVE))

    gif_path = output_dir / f"{base_name}_preview.gif"
    pil_frames[0].save(
        gif_path,
        save_all=True,
        append_images=pil_frames[1:],
        duration=duration,
        loop=0,  # 无限循环
        optimize=True,
    )
    print(f"  🎬 预览 GIF: {gif_path} (fps={fps}, {n}帧, 无限循环)")


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────

def process_video(video_path: str, name: str, action: str,
                  num_frames: int = None, smart: bool = False,
                  bg_color=None, tolerance: int = 40,
                  canvas_size: int = 256, output_dir: str = "./output",
                  preview: bool = False, gif: bool = False, gif_fps: float = None):
    """完整处理流程：视频 → PNG 序列帧。"""
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    if bg_color is None:
        bg_color = [0, 255, 0]

    if num_frames is None:
        num_frames = get_default_frames(action)

    base_name = f"{name}_{action}"
    out_dir = Path(output_dir) / base_name

    print(f"\n🎬 处理: {video_path.name}")
    print(f"   怪物: {name}, 动作: {action}, 帧数: {num_frames}")
    print(f"   输出: {out_dir}")

    # 1. 提取帧
    if smart:
        print(f"\n📽 智能关键帧提取...")
        frames_list, fps = extract_frames_smart(str(video_path), num_frames)
    else:
        print(f"\n📽 均匀采样帧提取...")
        frames_list, fps = extract_frames_uniform(str(video_path), num_frames)

    if not frames_list:
        print("  ❌ 未提取到任何帧")
        return None

    print(f"   提取了 {len(frames_list)} 帧")

    # 2. 抠图 + 裁切
    print(f"\n🎨 抠图 & 裁切...")
    processed = []
    for idx, frame in frames_list:
        rgba = chroma_key(frame, bg_color, tolerance)

        # 检查是否大部分是空的（色度抠图可能失败）
        alpha_ratio = np.mean(rgba[:, :, 3] > 30)
        if alpha_ratio < 0.02:
            print(f"   ⚠ 第 {idx} 帧抠图后几乎全透明，尝试 rembg 备用")
            rgba = try_rembg_fallback(rgba, frame)

        centered = crop_and_center(rgba, canvas_size)
        processed.append((idx, centered))

    # 3. 输出
    print(f"\n💾 保存帧...")
    metadata = {
        "name": name,
        "action": action,
        "total_frames": len(processed),
        "fps": fps,
        "canvas_size": canvas_size,
        "source_video": video_path.name,
        "files": [],
    }
    result = save_frames(processed, out_dir, base_name, canvas_size, metadata, preview, gif, gif_fps)

    print(f"\n✅ 完成！共输出 {len(processed)} 帧到: {out_dir}")
    return out_dir


def main():
    args = parse_args()
    process_video(
        video_path=args.video,
        name=args.name,
        action=args.action,
        num_frames=args.frames,
        smart=args.smart,
        bg_color=args.bg_color,
        tolerance=args.tolerance,
        canvas_size=args.size,
        output_dir=args.output,
        preview=args.preview,
        gif=args.gif,
        gif_fps=args.gif_fps,
    )


if __name__ == "__main__":
    main()
