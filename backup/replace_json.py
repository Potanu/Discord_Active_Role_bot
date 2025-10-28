# replace_json.py
import json
from pathlib import Path

# 置換設定
TARGET = "アクティブなメンバー"
REPLACE = "未参加"

folder = Path(__file__).parent

for file_path in folder.glob("*.json"):
    print(f"処理中: {file_path.name}")

    # UTF-8 BOM付き読み込み
    with open(file_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    # 再帰的に文字列値を置換
    def replace_in_obj(obj):
        if isinstance(obj, dict):
            return {k: replace_in_obj(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [replace_in_obj(x) for x in obj]
        elif isinstance(obj, str):
            return obj.replace(TARGET, REPLACE)
        else:
            return obj

    new_data = replace_in_obj(data)

    # JSONに戻してBOM付きUTF-8で上書き保存
    with open(file_path, "w", encoding="utf-8-sig") as f:
        json.dump(new_data, f, ensure_ascii=False, indent=4)

    print(f"  → 保存完了: {file_path.name}")

print("\n✅ 完了しました")
