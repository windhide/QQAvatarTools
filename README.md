# QQAvatarTools — NTQQ 高清 / 透明头像工具

为新版 QQ（NTQQ）设计的本地头像上传工具：**无损 PNG 直传**（不经客户端二次压缩）、**透明头像**、内置图片编辑器，零安装、纯本地运行。

## 功能特性

- **无损直传**：原始像素封装为 PNG，经 NapCat 的 OneBot 11 `set_qq_avatar` 接口直达 QQ 内核 `NodeIKernelProfileService.setHeader`，跳过官方客户端的裁剪与 JPEG 重压缩
- **透明头像**：完整保留 PNG Alpha 通道，透明区域原样上传
- **图片编辑器**（浏览器 Canvas，所见即所得）：
  - 方形裁剪 + 拖拽平移
  - 任意角度旋转（90° 步进 + ±45° 微调，双击归零）
  - 水平 / 垂直翻转
  - 1/8 ～ 8× 连续缩放，画布留白自动作为透明区域上传
  - 圆形参考线（QQ 头像显示为圆形）+ 实时方形预览
- **零安装**：内置 [NapCat](https://github.com/NapNeko/NapCatQQ) Shell，复用本机已安装的 QQ 桌面版，扫码即用，不需要另外部署任何服务
- **自动合规**：自动遵守 3 MiB / 4096px 上限（超限才逐步降采样，保精度优先）
- **每次打开都需重新扫码**：绝不沿用、也绝不保存上一次的登录
- **干净退出**：关闭工具自动结束它拉起的隐藏 QQ；即使被强杀，看门狗进程也会完成清理，不留后台残留
- **纯本地**：全部数据只在本机，上传临时文件用后即删，不保存任何票据

## 使用方法

1. 安装 [新版 QQ 桌面版（NTQQ）](https://im.qq.com/pcqq/index.shtml)
2. 双击 `QQAvatarTools.exe`（自动请求管理员权限 —— 注入 QQ 需要）
3. 点击「启动并登录」，用手机 QQ 扫码（或点快速登录按钮）
4. 拖入图片 → 编辑 → 「上传到 QQ 头像」

## 要求与注意

- 目标机器需已安装**新版 QQ 桌面版**，工具通过注册表自动定位 QQ 路径
- 上传期间会以隐藏方式拉起一个 QQ 实例：若桌面 QQ 正登着同一账号，建议先退出，传完再登回，避免互踢
- 注入 QQ 的组件可能被杀毒软件误报，需自行加白名单
- **假阴性**：NapCat 对 `set_qq_avatar` 偶发「报错但头像实际已更新」，报错时先刷新 / 重启 QQ 核对，不要反复重试（频繁换头像有风控风险）
- 动态头像（小世界图层）、群头像、名片背景不在支持范围内
- 高级面板可填外置 NapCat HTTP 地址作为回退通道

## 工作原理

```
浏览器 Canvas 编辑（裁剪 / 旋转 / 翻转坐标）
        │  坐标 + 角度
        ▼
本工具服务端 Pillow 渲染（与预览逐像素一致，含透明留白填充）
        │  无损 PNG（≤3MiB / ≤4096px 自动约束）
        ▼
NapCat Shell（注入本机 QQ）→ OneBot 11 set_qq_avatar
        ▼
QQ 内核 NodeIKernelProfileService.setHeader —— 头像更新，无客户端压缩
```

## 从源码构建

环境：Python 3.10+（仅依赖 [Pillow](https://python-pillow.github.io/)、[qrcode](https://github.com/lincolnloop/python-qrcode)、[PyInstaller](https://pyinstaller.org/)）

```bash
pip install pillow qrcode pyinstaller

# 下载 NapCat Shell 载荷（约 34MB，不入库）
# 国内网络可先设置代理：export HTTPS_PROXY=http://127.0.0.1:7890
python tools/download_payload.py

# 打包单文件 exe（自动嵌入管理员清单，双击即弹 UAC）
pyinstaller --onefile --uac-admin --name QQAvatarTools ^
  --add-data "static;static" --add-data "payload/napcat_shell.zip;." ^
  --clean --noconfirm app.py
```

产物在 `dist/QQAvatarTools.exe`。Windows 下也可直接运行 `build.bat`。

开发调试（免打包）：`python app.py`，浏览器打开 `http://127.0.0.1:17860`；
本地无 QQ 时可用 `test/mock_napcat.py` 起一个模拟 OneBot 服务做端到端联调。

## 第三方组件引用（重要）

本项目运行时依赖并内置 **NapCat**：

- 项目地址：<https://github.com/NapNeko/NapCatQQ>（作者 MliiKowa 及 NapNeko 团队）
- 使用版本：v4.18.42（Shell 模式，未修改其任何代码，仅调用其公开接口）
- 许可证：NapCat 采用其自定义 **Limited Redistribution License**（[全文见 NAPCAT_LICENSE.txt](NAPCAT_LICENSE.txt)）。
  该许可允许在附带完整许可文本并明确标注出处的前提下再分发，且**仅限非商业用途**。
- Release 附件中的可执行文件内嵌了 NapCat Shell 组件，该部分一切权利归原作者所有；如对 NapCat 有任何许可疑问，请联系其作者。

本项目自身代码以 [MIT License](LICENSE) 发布；转载或二次开发请同时保留对 NapCat 的上述引用说明。

## 隐私与免责声明

- 全部数据与计算只在本机：不联网上报、不保存任何登录票据、上传的临时文件用后即删
- 本工具通过 NapCat 调用 QQ 内部接口，**仅供学习交流使用**，与腾讯 / QQ 官方无关，限非商业用途
- 使用本工具产生的一切后果由使用者自行承担
