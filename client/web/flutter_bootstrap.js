{{flutter_js}}
{{flutter_build_config}}

// CanvasKit 从同源加载（构建时 --no-web-resources-cdn），校园网与国内网络下不依赖 gstatic CDN。
_flutter.loader.load({
  config: { canvasKitBaseUrl: "canvaskit/" },
  onEntrypointLoaded: async function (engineInitializer) {
    const appRunner = await engineInitializer.initializeEngine();
    const s = document.getElementById("splash");
    if (s) s.remove();
    await appRunner.runApp();
  },
});
