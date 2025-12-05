# 画像パラメータ仕様書 / Image Parameter Specification

## 概要 / Overview

プロンプトテンプレートに画像を含めるための2つの新しいパラメータ型を追加します。

- **FILE型**: ブラウザから画像をアップロード（単発実行・バッチ実行両方対応）
- **FILEPATH型**: サーバーからアクセス可能なファイルパスを指定（主にバッチ実行用）

## パラメータ型の定義

### 1. FILE型

#### 構文
```
{{param_name:FILE}}
```

#### 動作
- **単発実行**: ファイルアップロードボタンが表示される
- **バッチ実行**: CSVに Base64 エンコードされた画像データを記載

#### 使用例
```
以下の画像を分析してください。

画像: {{screenshot:FILE}}

分析内容:
- 画面に表示されているUI要素をリストアップ
- 改善点を3つ提案
```

#### データフォーマット
- **単発実行時**: ブラウザでBase64エンコード → JSON送信
- **バッチ実行時**: CSVセルに Base64 文字列を記載
- **サーバー側**: Base64 → LLM API送信

#### 制約
- 対応形式: JPEG, PNG, GIF, WebP
- 最大サイズ: 20MB (Base64エンコード前)
- 自動リサイズ: 長辺が2048pxを超える場合は自動縮小

### 2. FILEPATH型

#### 構文
```
{{param_name:FILEPATH}}
```

#### 動作
- **単発実行**: テキストボックスが表示され、ファイルパスを入力
- **バッチ実行**: CSVにファイルパスを記載

#### 使用例
```
以下のスクリーンショットを分析してください。

スクリーンショット: {{screenshot_path:FILEPATH}}

画像から読み取れるエラーメッセージを抽出してください。
```

#### データフォーマット
- **単発実行時**: ファイルパス文字列 → JSON送信
- **バッチ実行時**: CSVセルにファイルパスを記載
- **サーバー側**: ファイル読み込み → Base64変換 → LLM API送信

#### ファイルパスの制約

##### セキュリティ
サーバー側で以下のディレクトリのみアクセス可能：
```python
ALLOWED_IMAGE_DIRS = [
    "/var/data/images",
    "/home/{username}/images",
    "./uploads",
    os.path.expanduser("~/images")
]
```

環境変数での設定:
```bash
ALLOWED_IMAGE_DIRS="/var/data/images,/home/user/images"
```

##### パス指定方法
- 絶対パス: `/var/data/images/screenshot.jpg`
- 相対パス: `./uploads/image001.png`
- Windowsパス: `C:\data\images\test.jpg` (Windowsサーバーのみ)

##### 使用条件
✅ **動作する環境**:
- localhost開発環境 (ブラウザとサーバーが同じマシン)
- サーバー上の共有ストレージ
- サーバーがマウントしているネットワークドライブ

❌ **動作しない環境**:
- リモートサーバー環境で、クライアントのローカルファイルを指定
- サーバーからアクセスできないパス

## LLM APIへの送信形式

### Vision API対応モデル

以下のモデルが画像入力をサポート：
- Azure GPT-4.1
- Azure GPT-5-mini
- Azure GPT-5-nano
- OpenAI GPT-4-nano
- OpenAI GPT-5-nano

### API送信フォーマット

```python
messages = [
    {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": "画像を分析してください"
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/jpeg;base64,/9j/4AAQSkZJRg..."
                }
            }
        ]
    }
]
```

### 複数画像の対応

プロンプトに複数の画像パラメータがある場合：
```
{{image1:FILE}}
{{image2:FILE}}
{{screenshot:FILEPATH}}
```

送信順序: プロンプト内の出現順に配列化
```python
images = [
    "base64_data_of_image1",
    "base64_data_of_image2",
    "base64_data_of_screenshot"
]
```

## データベーススキーマ

### 既存スキーマへの影響
画像データは `job_items.input_params` に JSON 形式で保存されます。
スキーマ変更は不要です。

```json
{
    "question": "この画像の内容は？",
    "screenshot": "data:image/jpeg;base64,/9j/4AAQSkZJRg...",
    "image_path": "/var/data/images/test.jpg"
}
```

## フロントエンド UI

### FILE型の表示

```html
<div class="input-group">
    <label>screenshot (FILE):</label>
    <input type="file" accept="image/*" id="param-screenshot">
    <div class="image-preview">
        <img id="preview-screenshot" style="max-width: 300px; display: none;">
    </div>
    <div class="file-info">
        <span id="filesize-screenshot"></span>
    </div>
</div>
```

### FILEPATH型の表示

```html
<div class="input-group">
    <label>screenshot_path (FILEPATH):</label>
    <input type="text"
           id="param-screenshot_path"
           placeholder="/path/to/image.jpg">
    <small class="help-text">
        ⚠️ サーバーからアクセス可能なパスを指定してください
    </small>
</div>
```

## バッチ実行でのCSVフォーマット

### FILE型を使用する場合

```csv
question,screenshot
"画像1の内容は？","data:image/jpeg;base64,/9j/4AAQ..."
"画像2の内容は？","data:image/png;base64,iVBORw0KGgo..."
```

**注意**: Base64データは非常に長いため、Excelでの編集は推奨しません。
専用のインポートツールの使用を推奨します。

### FILEPATH型を使用する場合

```csv
question,screenshot_path
"画像1の内容は？","/var/data/images/screenshot001.jpg"
"画像2の内容は？","/var/data/images/screenshot002.jpg"
"画像3の内容は？","./uploads/test_image.png"
```

## エラーハンドリング

### FILE型のエラー

| エラー | 原因 | 対処 |
|--------|------|------|
| "Invalid image format" | 非対応の画像形式 | JPEG/PNG/GIF/WebPを使用 |
| "Image too large" | ファイルサイズ超過 | 20MB以下に縮小 |
| "Failed to encode image" | Base64変換エラー | 画像ファイルの破損を確認 |

### FILEPATH型のエラー

| エラー | 原因 | 対処 |
|--------|------|------|
| "File not found" | ファイルが存在しない | パスを確認 |
| "Access denied" | 許可されていないディレクトリ | 許可ディレクトリを確認 |
| "Invalid file path" | パストラバーサル検出 | 正しいパスを指定 |
| "Not an image file" | 画像ファイルではない | 画像ファイルを指定 |

## セキュリティ考慮事項

### 1. ファイルパスのサニタイゼーション
```python
def _validate_file_path(self, file_path: str) -> str:
    """Validate and sanitize file path."""
    # パストラバーサル対策
    real_path = os.path.realpath(file_path)

    # 許可ディレクトリチェック
    allowed = any(
        real_path.startswith(os.path.realpath(d))
        for d in ALLOWED_IMAGE_DIRS
    )

    if not allowed:
        raise ValueError(f"Access denied: {file_path}")

    return real_path
```

### 2. ファイルサイズ制限
```python
MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20MB
MAX_IMAGE_DIMENSION = 2048  # pixels
```

### 3. MIMEタイプ検証
```python
ALLOWED_MIME_TYPES = [
    'image/jpeg',
    'image/png',
    'image/gif',
    'image/webp'
]
```

## パフォーマンス最適化

### 1. 画像の自動リサイズ
```python
def _resize_image_if_needed(self, img: Image.Image) -> Image.Image:
    """Resize image if dimensions exceed maximum."""
    max_dim = 2048

    if max(img.size) > max_dim:
        ratio = max_dim / max(img.size)
        new_size = tuple(int(dim * ratio) for dim in img.size)
        return img.resize(new_size, Image.LANCZOS)

    return img
```

### 2. ファイルキャッシュ（バッチ実行）
```python
# 同じファイルパスの画像は一度だけ読み込む
image_cache: Dict[str, str] = {}

def _load_image_cached(self, file_path: str) -> str:
    """Load image with caching."""
    if file_path in image_cache:
        return image_cache[file_path]

    base64_data = self._load_image_from_path(file_path)
    image_cache[file_path] = base64_data
    return base64_data
```

## 既存機能への影響

### プロンプトリビルド
FILE/FILEPATH型を含むプロンプトにリビルドする場合、警告を表示：
```
⚠️ 警告: 新しいプロンプトには画像パラメータが含まれています。

既存のジョブ履歴は画像データを含んでいないため、
リビルドするとエラーになる可能性があります。

続行しますか？ [はい] [いいえ]
```

### CSV/Excelインポート
- FILE型: Base64データを含むCSVのインポートをサポート
- FILEPATH型: 通常のテキストとして扱う（特別な処理不要）

## 使用例

### 例1: スクリーンショット分析（単発実行）

**プロンプト**:
```
以下のスクリーンショットを分析してください。

スクリーンショット: {{screenshot:FILE}}

以下の観点で分析結果をJSONで出力してください：
- UI要素のリスト
- ユーザビリティの問題点
- 改善提案
```

**実行手順**:
1. ファイルアップロードボタンから画像を選択
2. プレビューで画像を確認
3. 送信ボタンをクリック

### 例2: バッチスクリーンショット分析

**プロンプト**:
```
以下のスクリーンショットに含まれるエラーメッセージを抽出してください。

スクリーンショット: {{screenshot_path:FILEPATH}}

JSON形式で以下を出力：
{
  "error_message": "抽出されたエラーメッセージ",
  "severity": "高/中/低",
  "suggested_fix": "修正方法の提案"
}
```

**CSV**:
```csv
screenshot_path
/var/data/screenshots/error001.jpg
/var/data/screenshots/error002.jpg
/var/data/screenshots/error003.jpg
```

## テスト計画

### 単体テスト
- [ ] FILE型パラメータの解析
- [ ] FILEPATH型パラメータの解析
- [ ] Base64エンコード/デコード
- [ ] ファイルパスのバリデーション
- [ ] 画像リサイズ
- [ ] MIMEタイプ検証

### 結合テスト
- [ ] 単発実行でFILE型を使用
- [ ] 単発実行でFILEPATH型を使用
- [ ] バッチ実行でFILE型を使用（Base64 CSV）
- [ ] バッチ実行でFILEPATH型を使用
- [ ] 複数画像パラメータの処理
- [ ] エラーケースの処理

### E2Eテスト
- [ ] 実際のLLM APIで画像分析
- [ ] 大きな画像のリサイズ確認
- [ ] 異なる画像形式のテスト
- [ ] パフォーマンステスト（大量の画像）

## 参考資料

### Azure OpenAI Vision API
- [Azure OpenAI Service REST API reference](https://learn.microsoft.com/en-us/azure/ai-services/openai/reference)
- [GPT-4 Turbo with Vision](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/gpt-with-vision)

### OpenAI Vision API
- [Vision guide](https://platform.openai.com/docs/guides/vision)
- [Image inputs](https://platform.openai.com/docs/guides/vision/image-inputs)

## 変更履歴

| 日付 | バージョン | 変更内容 |
|------|-----------|---------|
| 2025-12-06 | 1.0.0 | 初版作成 |
