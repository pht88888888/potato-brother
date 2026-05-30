"""
批量处理脚本：遍历目录中的所有动画视频，自动识别名称和动作类型。

文件名命名规则: {怪物名}_{动作}.mp4
    例如: slime_walk.mp4, slime_attack.mp4, goblin_walk.mp4

用法:
    python batch_process.py ./videos/ --output ./output
    python batch_process.py ./videos/ --frames walk:6 attack:4 --smart attack
"""

import argparse
import re
import sys
from pathlib import Path

from video_to_frames import process_video, get_default_frames


# 常见的动作关键词 → 标准 action 名称
ACTION_KEYWORDS = {
    "walk": "walk",
    "行走": "walk",
    "run": "run",
    "跑步": "run",
    "attack": "attack",
    "atk": "attack",
    "攻击": "attack",
    "idle": "idle",
    "待机": "idle",
    "hurt": "hurt",
    "受伤": "hurt",
    "death": "death",
    "die": "death",
    "死亡": "death",
}


def parse_filename(filename: str):
    """
    从文件名解析怪物名称和动作类型。
    支持格式:
        slime_walk.mp4 → ("slime", "walk")
        slime-walk.mp4 → ("slime", "walk")
        史莱姆_行走.mp4 → ("史莱姆", "walk")
        GoblinAttack.mp4 → ("Goblin", "attack")    [首字母大写分隔]
    """
    stem = Path(filename).stem

    # 尝试下划线/连字符分隔
    for sep in ["_", "-"]:
        if sep in stem:
            parts = stem.rsplit(sep, 1)
            if len(parts) == 2:
                name, action_str = parts
                # 尝试匹配动作关键词
                for key, action in ACTION_KEYWORDS.items():
                    if action_str.lower() == key:
                        return name, action
                # 如果没有匹配到关键词，就用原字符串作为 action
                print(f"  ⚠ 未识别的动作 '{action_str}'，将直接使用")
                return name, action_str

    # 尝试驼峰分隔 (如 GoblinAttack)
    split_points = re.findall(r'[A-Z][a-z]*', stem)
    if len(split_points) >= 2:
        name = split_points[0]
        action_str = split_points[1].lower()
        for key, action in ACTION_KEYWORDS.items():
            if action_str == key:
                return name, action
        return name, action_str

    # 都解析失败
    return None, None


def scan_videos(input_dir: str):
    """扫描目录中的视频文件。"""
    input_path = Path(input_dir)
    if not input_path.exists():
        print(f"❌ 目录不存在: {input_dir}")
        return []

    video_exts = {".mp4", ".mov", ".avi", ".webm", ".gif"}
    videos = []
    for f in sorted(input_path.iterdir()):
        if f.suffix.lower() in video_exts:
            name, action = parse_filename(f.name)
            if name and action:
                videos.append((f, name, action))
            else:
                print(f"⚠ 无法解析文件名: {f.name} (跳过)")
    return videos


def main():
    parser = argparse.ArgumentParser(description="批量处理怪物动画视频 → PNG 序列帧")
    parser.add_argument("input_dir", type=str, help="视频文件夹路径")
    parser.add_argument("--output", type=str, default="./output", help="输出目录")
    parser.add_argument("--frames", type=str, nargs="*", default=[],
                        help="自定义帧数, 如 walk:6 attack:4")
    parser.add_argument("--smart", type=str, nargs="*", default=[],
                        help="对指定动作启用智能关键帧, 如 --smart attack walk")
    parser.add_argument("--bg-color", type=int, nargs=3, default=[0, 255, 0],
                        metavar=("R", "G", "B"), help="背景色 RGB")
    parser.add_argument("--tolerance", type=int, default=40, help="色彩容差")
    parser.add_argument("--size", type=int, default=256, help="画布尺寸")
    parser.add_argument("--preview", action="store_true", help="生成预览图")
    parser.add_argument("--gif", action="store_true", help="生成预览 GIF 动图")
    parser.add_argument("--gif-fps", type=float, default=None, help="GIF 的播放帧率")
    args = parser.parse_args()

    # 解析自定义帧数
    frame_overrides = {}
    if args.frames:
        for fspec in args.frames:
            if ":" in fspec:
                action, count = fspec.split(":", 1)
                frame_overrides[action.strip()] = int(count)

    smart_actions = set(a.strip() for a in args.smart)

    videos = scan_videos(args.input_dir)
    if not videos:
        print("没有找到可处理的视频。")
        print("文件名格式: {怪物名}_{动作}.mp4 (如 slime_walk.mp4)")
        return

    print(f"\n📋 找到 {len(videos)} 个视频:\n")
    for vid_path, name, action in videos:
        print(f"  {vid_path.name}  →  {name}_{action}")

    print("\n" + "=" * 50)
    success = 0
    fail = 0

    for vid_path, name, action in videos:
        num_frames = frame_overrides.get(action, get_default_frames(action))
        use_smart = action in smart_actions

        try:
            result = process_video(
                video_path=str(vid_path),
                name=name,
                action=action,
                num_frames=num_frames,
                smart=use_smart,
                bg_color=args.bg_color,
                tolerance=args.tolerance,
                canvas_size=args.size,
                output_dir=args.output,
                preview=args.preview,
                gif=args.gif,
                gif_fps=args.gif_fps,
            )
            if result:
                success += 1
            else:
                fail += 1
        except Exception as e:
            print(f"\n  ❌ 处理失败: {e}")
            fail += 1

    print("\n" + "=" * 50)
    print(f"\n📊 处理完成: {success} 成功, {fail} 失败")
    if fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
