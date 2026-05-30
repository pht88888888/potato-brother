"""
Roblox 批量上传脚本：将 PNG 序列帧上传到 Roblox 并回填 asset ID。

用法:
    # 上传单个怪物的序列帧
    python upload_to_roblox.py ./output/slime_walk/metadata.json

    # 批量上传 output 目录下的所有怪物
    python upload_to_roblox.py ./output/ --batch

需求:
    配置环境变量:
        ROBLOX_OPEN_CLOUD_API_KEY  (必需)
        ROBLOX_CREATOR_USER_ID     (必需)
    或者从 .claude/settings.local.json 读取。
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# 终端 UTF-8 支持（防止 GBK 编码报错）
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import requests


def load_env_from_settings():
    """尝试从 .claude/settings.local.json 读取环境变量。"""
    settings_paths = [
        Path(".claude/settings.local.json"),
        Path.home() / ".claude" / "settings.json",
        Path(__file__).parent.parent.parent / ".claude" / "settings.local.json",
        Path(__file__).parent.parent.parent / ".claude" / "settings.json",
    ]
    for sp in settings_paths:
        if sp.exists():
            try:
                with open(sp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                env = data.get("env", {})
                if "ROBLOX_OPEN_CLOUD_API_KEY" in env:
                    os.environ.setdefault("ROBLOX_OPEN_CLOUD_API_KEY",
                                          env["ROBLOX_OPEN_CLOUD_API_KEY"])
                if "ROBLOX_CREATOR_USER_ID" in env:
                    os.environ.setdefault("ROBLOX_CREATOR_USER_ID",
                                          str(env["ROBLOX_CREATOR_USER_ID"]))
                if env:
                    return True
            except Exception:
                continue
    return False


# ─────────────────────────────────────────────
# Roblox Open Cloud API 上传
# ─────────────────────────────────────────────

def upload_decal_to_roblox(image_path: str, display_name: str, description: str = ""):
    """
    通过 Roblox Open Cloud API 上传贴图。
    返回 asset_id (int) 或抛出异常。

    API 文档:
        POST https://apis.roblox.com/cloud/v2/users/{userId}/decals
        Headers: x-api-key {API_KEY}
    """
    api_key = os.environ.get("ROBLOX_OPEN_CLOUD_API_KEY")
    user_id = os.environ.get("ROBLOX_CREATOR_USER_ID")
    group_id = os.environ.get("ROBLOX_CREATOR_GROUP_ID")

    if not api_key:
        raise ValueError(
            "缺少 ROBLOX_OPEN_CLOUD_API_KEY\n"
            "请设置环境变量或在 .claude/settings.local.json 中配置"
        )

    if not user_id and not group_id:
        raise ValueError(
            "缺少 ROBLOX_CREATOR_USER_ID 或 ROBLOX_CREATOR_GROUP_ID\n"
            "请设置环境变量或在 .claude/settings.local.json 中配置"
        )

    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"图片文件不存在: {image_path}")

    # 构建请求 URL
    if group_id:
        url = f"https://apis.roblox.com/cloud/v2/groups/{group_id}/decals"
    else:
        url = f"https://apis.roblox.com/cloud/v2/users/{user_id}/decals"

    headers = {
        "x-api-key": api_key,
    }

    # 准备 multipart 数据
    with open(image_path, "rb") as f:
        files = {
            "request": (None, json.dumps({
                "displayName": display_name,
                "description": description,
            }), "application/json"),
            "file": (image_path.name, f, "image/png"),
        }

        print(f"  📤 上传中: {display_name} ...", end=" ", flush=True)
        resp = requests.post(url, headers=headers, files=files, timeout=60)

    if resp.status_code == 200:
        data = resp.json()
        asset_id = None
        if "path" in data:
            # path 格式: "users/{userId}/decals/{assetId}"
            asset_id = int(data["path"].rsplit("/", 1)[-1])
        elif "id" in data:
            asset_id = int(data["id"])

        if asset_id:
            print(f"✅ Asset ID: {asset_id}")
            return asset_id
        else:
            print(f"⚠ 响应中未找到 asset ID: {data}")
            return None
    elif resp.status_code == 429:
        print(f"⏳ 触发限流，等待 5 秒后重试...")
        time.sleep(5)
        return upload_decal_to_roblox(image_path, display_name, description)
    else:
        error_msg = resp.text[:500] if resp.text else f"HTTP {resp.status_code}"
        raise RuntimeError(f"上传失败: {error_msg}")


# ─────────────────────────────────────────────
# 处理单个 metadata.json
# ─────────────────────────────────────────────

def process_metadata(meta_path: str, dry_run: bool = False):
    """处理一个 metadata.json：上传未上传的帧并回填 asset ID。"""
    meta_path = Path(meta_path)
    if not meta_path.exists():
        raise FileNotFoundError(f"metadata.json 不存在: {meta_path}")

    with open(meta_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    name = metadata.get("name", "unknown")
    action = metadata.get("action", "unknown")
    base_dir = meta_path.parent

    files = metadata.get("files", [])
    if not files:
        print("  ⚠ metadata 中没有文件列表")
        return

    total = len(files)
    uploaded = 0
    skipped = 0

    print(f"\n🎯 {name}_{action}: 共 {total} 帧")

    for i, file_info in enumerate(files):
        # 跳过已上传的
        if file_info.get("asset_id") is not None:
            print(f"  ⏭ {file_info['file']}: 已上传 (Asset ID: {file_info['asset_id']})")
            skipped += 1
            continue

        file_path = base_dir / file_info["file"]
        display_name = f"{name}_{action}_{file_info['frame']:03d}"
        description = f"{name} {action} animation frame {file_info['frame']}/{total}"

        if dry_run:
            print(f"  📋 [DRY RUN] 将上传: {file_path.name} → {display_name}")
            uploaded += 1
            continue

        try:
            asset_id = upload_decal_to_roblox(str(file_path), display_name, description)
            if asset_id:
                file_info["asset_id"] = asset_id
                uploaded += 1
            # 上传间隔，避免触发限流
            time.sleep(1.5)
        except Exception as e:
            print(f"  ❌ 上传失败: {e}")
            # 保存已上传的进度
            break

    # 保存更新后的 metadata
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"\n📊 结果: 上传 {uploaded}, 跳过 {skipped}, 总计 {total}")
    return uploaded, skipped


# ─────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="将 PNG 序列帧上传到 Roblox")
    parser.add_argument("target", type=str,
                        help="metadata.json 路径 或 包含 metadata.json 的目录")
    parser.add_argument("--batch", action="store_true",
                        help="批量模式：递归搜索 target 目录下所有 metadata.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="只列出待上传文件，不实际上传")
    args = parser.parse_args()

    # 加载环境变量
    load_env_from_settings()

    # 校验环境
    if not args.dry_run:
        api_key = os.environ.get("ROBLOX_OPEN_CLOUD_API_KEY")
        if not api_key:
            print("❌ 缺少 ROBLOX_OPEN_CLOUD_API_KEY")
            print("   请在 .claude/settings.local.json 中配置 env.ROBLOX_OPEN_CLOUD_API_KEY")
            sys.exit(1)

    target = Path(args.target)

    if args.batch and target.is_dir():
        # 递归查找所有 metadata.json
        meta_files = sorted(target.rglob("metadata.json"))
        if not meta_files:
            print(f"在 {target} 下未找到 metadata.json")
            return

        print(f"📦 批量模式: 找到 {len(meta_files)} 个 metadata.json\n")
        total_uploaded = 0
        total_skipped = 0
        for mf in meta_files:
            up, skip = process_metadata(str(mf), args.dry_run)
            total_uploaded += up
            total_skipped += skip
        print(f"\n{'=' * 40}")
        print(f"📊 全部完成: 上传 {total_uploaded}, 跳过 {total_skipped}")
    else:
        if target.is_dir():
            # 可能是输出目录，查找其下的 metadata.json
            meta_path = target / "metadata.json"
            if meta_path.exists():
                process_metadata(str(meta_path), args.dry_run)
            else:
                print(f"{target} 下未找到 metadata.json")
                sys.exit(1)
        else:
            process_metadata(str(target), args.dry_run)


if __name__ == "__main__":
    main()
