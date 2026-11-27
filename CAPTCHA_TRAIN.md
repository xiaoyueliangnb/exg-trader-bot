# 本站验证码专训任务（Windows + RTX 4080）

把本说明和同目录的压缩包 `captcha_data_train.zip` 一起交给执行方。目标：训练可被 `ddddocr` 加载的自定义模型。

---

## 1. 背景

线上系统用通用 `ddddocr` 识别 4 位彩色扭曲英文字母验证码，错误率偏高。已收集标注样本约 **736** 张，需在本机用 **dddd_trainer** 专训。

云主机无 NVIDIA GPU，请在 **Windows 原生环境 + RTX 4080** 上训练（**不要用 WSL**，除非你更熟 WSL；本任务按纯 Windows 写）。

---

## 2. 数据说明

### 压缩包

- 文件：`captcha_data_train.zip`（约 3.5MB）
- 解压后得到目录：`captcha_data/`
- 内含 **736** 张 PNG

### 命名格式（dddd_trainer「从文件名导入」）

```text
{label}_{hash}.png
例如：qecm_f8cd3b08626bd338.png
```

- `label`：正确答案，**4 位小写英文字母**
- `hash`：内容指纹，可忽略

### 数据构成（已合并进压缩包，不必再单独拷 captcha_wrong）

| 来源 | 数量 | 说明 |
|------|------|------|
| 识别成功样本 | 607 | 常规正例 |
| 人工标注错例 | 129 | 难例，含易混字母，**必须保留** |
| 合计 | 736 | |

错例尤其重要，常见混淆包括：`u/v`、`p/f`、`a/d`、`c/e`、`b/h`、`r/f` 等。不要只拿成功样本训练。

### 验证码外观

- 约 `100×40`，彩色、扭曲、带干扰线
- 固定 4 个英文字母（标签已统一小写）

---

## 3. 环境准备（Windows）

1. 安装较新的 **NVIDIA 显卡驱动**（能驱动 4080）
2. 安装 **Python 3.10/3.11**（建议）
3. 按 https://pytorch.org 安装 **CUDA 版 PyTorch**（CUDA 12.x 即可）
4. PowerShell 中验证：

```powershell
nvidia-smi
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

应显示 `True` 和类似 `NVIDIA GeForce RTX 4080`。

5. 克隆训练工具并装依赖：

```powershell
git clone https://github.com/sml2h3/dddd_trainer.git
cd dddd_trainer
pip install -r requirements.txt
# 若 torch 被装成 CPU 版，请按 pytorch.org 命令重装 CUDA 版覆盖
```

6. 解压数据，例如：

```powershell
Expand-Archive captcha_data_train.zip -DestinationPath .
# 得到 .\captcha_data\*.png
```

---

## 4. 训练步骤

```powershell
cd dddd_trainer

# 创建 CRNN 序列识别项目（不要加 --single，那是单字 CNN）
python app.py create jifen_captcha

# 缓存数据（文件名导入模式）
python app.py cache jifen_captcha .\captcha_data

# 编辑 projects\jifen_captcha\config.yaml
#   System.GPU: true
#   System.GPU_ID: 0
# 可按显存调大 Train.BATCH_SIZE（如 32/64）
# ImageHeight 建议保持 16 的倍数；宽度可按工具默认或 -1 自适应

python app.py train jifen_captcha
```

训练达标后，模型在：

```text
dddd_trainer\projects\jifen_captcha\models\
  ├── *.onnx
  └── charsets.json
```

---

## 5. 交付物

请交付这两个文件（可重命名）：

1. `model.onnx`（把生成的 `.onnx` 改名或复制为此名）
2. `charsets.json`

放到云主机项目目录：

```text
/home/ubuntu/server/exg/jifen/captcha_model/model.onnx
/home/ubuntu/server/exg/jifen/captcha_model/charsets.json
```

云主机侧 `ocr_captcha.py` 已支持：若上述两文件存在，则**优先使用专训模型**；否则回退通用 ddddocr。

---

## 6. 验收建议

用难例抽测（原错例对应标签）：随机抽 `captcha_data` 中来自错例的标签，或对照线上 `captcha_wrong/*__正解.png`。

关注是否改善：

- `u↔v`、`p↔f`、`a↔d`、`c↔e`、`b↔h`

报告建议包含：训练集大小、验证准确率、若干难例识别前后对比。

---

## 7. 注意

- 使用 **Windows + 4080**，不要在无 GPU 的云主机上硬训
- **必须包含错例样本**（压缩包里已含，勿删）
- 标签保持小写 4 字母，与数据一致
- 不要使用 `python app.py create ... --single`（不适合 4 字验证码）
- 样本后续还会增加；本次先用 736 张出一版可用模型即可

---

## 8. 一句话需求

在 Windows RTX 4080 上，用附件 `captcha_data_train.zip`（含成功样本 + 标注错例共 736 张）经 dddd_trainer 训练 4 位字母验证码模型，交付可被 ddddocr 加载的 `model.onnx` + `charsets.json`。
