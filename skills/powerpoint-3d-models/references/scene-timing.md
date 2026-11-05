# Scene timing in the slide XML

How PowerPoint stores an embedded 3D animation and how to control it. Edit the saved `.pptx` (a ZIP) after inserting the model by COM; COM has no interface for this.

## Where the scene lives

Inside the 3D model shape, PowerPoint writes:

```xml
<a3danim:embedAnim xmlns:a3danim="http://schemas.microsoft.com/office/drawing/2018/animation/model3d" animId="0">
  <a3danim:animPr length="7000" count="indefinite"/>
</a3danim:embedAnim>
<a3danim:posterFrame animId="0"/>
```

- `animId`: the scene, counted from 0 (one glTF animation is one scene)
- `length`: scene length in ms
- `count`: `indefinite` loops in edit view, `1` plays once

## How it plays

In `p:timing`, "Play 3D" is an emphasis effect with `presetID="100"`. Its `p:anim` drives the attribute `embedded<n>` from 0 to 1 over `dur` ms, where `<n>` is `animId + 1`:

```xml
<p:cTn presetID="100" presetClass="emph" presetSubtype="1" repeatCount="indefinite" fill="hold" nodeType="withEffect">
  ...
  <p:anim calcmode="lin" valueType="num">
    <p:cBhvr>
      <p:cTn dur="7000" fill="hold"/>
      <p:tgtEl><p:spTgt spid="2"/></p:tgtEl>
      <p:attrNameLst><p:attrName>embedded1</p:attrName></p:attrNameLst>
    </p:cBhvr>
    <p:tavLst>
      <p:tav tm="0"><p:val><p:fltVal val="0"/></p:val></p:tav>
      <p:tav tm="100000"><p:val><p:fltVal val="1"/></p:val></p:tav>
    </p:tavLst>
  </p:anim>
</p:cTn>
```

## Recipes

- **Stop the loop:** drop `repeatCount`; `fill="hold"` keeps the end pose. By hand: Animation Pane, Timing, Repeat.
- **One piece per click:** several effects with `nodeType="clickEffect"` and a start condition `<p:cond delay="indefinite"/>`; each sets the values from `start` to `end` (fractions of the scene) and `dur` = (end minus start) times the scene length.
- **Start with the slide:** start conditions `<p:cond delay="indefinite"/><p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond>` and `nodeType="withEffect"`.
- **Pick another scene on a slide:** change three things together, or it fails quietly:
  1. `animId` in `embedAnim` and `posterFrame`
  2. `embedded<n>` in the effect (with only `animId` changed, the Scenes menu shows the right scene but scene 1 plays)
  3. `length` in `animPr` and `dur` in the effect (PowerPoint writes the length of the first scene on every slide)
- **Replace the timing in place.** The order of elements in a slide is fixed (transition before timing); inserting the timing elsewhere makes the file invalid.

## Cutting scenes for one scene per slide

- Scene k must start exactly with the end pose of scene k minus 1. An overlap shows the tail of the previous motion at the start and leaves a rest pose that was never played.
- Hold the end pose for about 0.2 s at the end of each scene. Like video, PowerPoint stops slightly before the last frame; without the hold, the next slide visibly jumps.

## Values that break a file

- `posterFrame/@frame` must be a whole number; fractions and values far beyond the scene length make PowerPoint refuse the file. The attribute had no visible effect in tests.
