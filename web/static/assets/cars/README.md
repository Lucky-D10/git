# 赛车素材 v3

2026-10-02 使用内置 `image_gen` 工具生成，未使用 CLI/API fallback。素材已保存在项目中，运行时不访问外网。

- `blue-v3.png`：1773×887，RGBA，蓝色玩家。
- `orange-v3.png`：1774×887，RGBA，橙色玩家。
- 两车使用同一俯视视角和车身构型，车头朝右。原始生成文件直接复制，保留透明通道；没有用代码改色或裁切。
- 测试读取像素确认背景角点 alpha 为 0、车身中心 alpha 至少为 250；生成文件的车身存在轻微半透明抗锯齿，不宣称所有车身像素都完全不透明。
- 场景缩放由 CSS 控制；位置、停止、奖励尾迹仍由后台快照决定。素材本身没有绘入尾迹、文字、车道或比赛结果。
- `web/static/js/race.js` 统一引用两张素材，首页、实时竞速和竞速成果页共用。

## 蓝车：完整生成提示词

参考输入：`docs/design/youth-ui-v2/03-play.png`，作为风格与车型参考；`transparent_background: true`。

```text
Use case: stylized-concept. Asset type: production transparent PNG sprite for the existing FOCUS children's racing game. Reference image is the design board at C:/Users/17801/Desktop/git/docs/design/youth-ui-v2/03-play.png: use ONLY the blue race car in the lower-left C03 panel as visual reference, do not recreate the page. Generate ONE blue small sports car, strict straight overhead camera, nose pointing to the RIGHT, long axis perfectly horizontal. Match that car's chunky rounded body, rich bright cobalt/cyan glossy paint, curved front hood, dark navy windshield and rear window, bright blue roof panel, narrow white racing stripes on hood and rear, four small black rubber tires, wheel arches and dark underbody. Rounded premium toy/game 3D rendering with clear sculpted volumes, dark outline, soft white highlights from upper left. Narrow compact silhouette about 2.1 times longer than wide, entire car visible and tightly framed with only 4% transparent padding, wide landscape canvas. Car must be highly legible at 110 by 55 pixels. Truly transparent background, only a subtle contact shadow beneath the car. No road, ground, text, labels, badges, smoke, speed streaks, or other objects. Do not generate a vector schematic or flat rectangle; match the original reference car's modeled 3D appearance.
```

## 橙车：完整编辑提示词

编辑输入：上一张蓝车生成图；`transparent_background: true`。

```text
Use case: precise-object-edit. Edit target: the provided transparent blue sports-car sprite. Create its orange player-two variant. Change ONLY the blue painted body panels, blue mirrors and blue trim to vivid warm racing orange (#ff8b16) with golden-orange highlights and deeper burnt-orange shading. Preserve the exact overhead right-facing camera, identical silhouette and proportions, identical wheels, windows, all white racing stripes, crisp 3D modeled highlights, canvas size and placement, and transparent alpha background. No additional object, lettering, smoke or road. Must register exactly with the blue sprite so both players have the same car model.
```

原始生成来源文件名（无需在目标机器上保留这些路径）：

```text
blue:   exec-5ba8948a-cff1-4817-a4be-0e2e13ea80b0.png
orange: exec-d4abd8b7-a46a-49ea-8449-ebad3531e2d5.png
```
